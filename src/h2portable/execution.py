"""Synchronous local-process and disposable Docker execution backends.

These adapters execute trusted caller-supplied argv. They do not provide a
hardened boundary for hostile code; Docker isolation depends on the host kernel
and daemon configuration.
"""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from .recovery import _live_group, local_identity, release_record, write_record


Outcome = str
_OUTCOMES = {"completed", "failed", "timed_out", "cancelled"}


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Serializable summary of one execution; streams are stored as files."""

    outcome: Outcome
    returncode: int | None
    stdout_file: str
    stderr_file: str
    elapsed: float
    backend: str
    backend_id: str
    error: str | None = None

    def __post_init__(self) -> None:
        if self.outcome not in _OUTCOMES:
            raise ValueError(f"unsupported execution outcome: {self.outcome}")

    def to_dict(self) -> dict[str, str | int | float | None]:
        """Return JSON-compatible fields without reading potentially large logs."""
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


def _prepare(
    command: Sequence[str], workspace: Path, output_dir: Path, timeout: float
) -> tuple[list[str], Path, Path, float]:
    if isinstance(command, (str, bytes)) or not command:
        raise ValueError("command must be a non-empty argv sequence, not a shell string")
    argv = list(command)
    if any(not isinstance(part, str) or "\0" in part for part in argv):
        raise ValueError("every argv item must be a string without NUL characters")
    try:
        duration = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be a finite positive number of seconds") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("timeout must be a finite positive number of seconds")

    work = Path(workspace).resolve(strict=True)
    if not work.is_dir():
        raise ValueError(f"workspace is not a directory: {work}")
    out = Path(output_dir).resolve()
    if out == work or work in out.parents:
        raise ValueError("output_dir must be outside the task workspace")
    out.mkdir(parents=True, exist_ok=True)
    if not out.is_dir():
        raise ValueError(f"output_dir is not a directory: {out}")
    return argv, work, out, duration


def _result(
    outcome: str,
    returncode: int | None,
    stdout_path: Path,
    stderr_path: Path,
    started: float,
    backend: str,
    backend_id: str,
) -> ExecutionResult:
    return ExecutionResult(
        outcome=outcome,
        returncode=returncode,
        stdout_file=str(stdout_path),
        stderr_file=str(stderr_path),
        elapsed=max(0.0, time.monotonic() - started),
        backend=backend,
        backend_id=backend_id,
    )


def _save_bytes(path: Path, data: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(data)


def _resource_registry(out: Path, work: Path, explicit: Path | None) -> Path:
    selected = explicit or os.environ.get('H2PORTABLE_RESOURCE_ROOT') or out
    registry = Path(selected).resolve()
    if registry == work or work in registry.parents:
        raise ValueError('worker identity registry must be outside the task workspace')
    registry.mkdir(parents=True, exist_ok=True)
    return registry


def resolve_image(image: str, docker: str = "docker") -> str:
    """Resolve a preloaded image to an immutable local ID without pulling."""
    if not image or image.startswith("-") or "\0" in image:
        raise ValueError("supply a preloaded Docker image name or digest")
    try:
        result = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", image],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Docker image lookup timed out; check the engine connection") from exc
    image_id = result.stdout.strip()
    if result.returncode or not image_id.startswith("sha256:"):
        raise ValueError(f"Docker image is unavailable locally: {image}; build or pull it before execution")
    return image_id


class LocalRunner:
    """Run a command locally and terminate its complete POSIX process group."""

    backend = "local-posix"

    def __init__(self, terminate_grace: float = 2.0) -> None:
        if not math.isfinite(terminate_grace) or terminate_grace < 0:
            raise ValueError("terminate_grace must be finite and non-negative")
        self.terminate_grace = terminate_grace

    def run(
        self,
        command: Sequence[str],
        workspace: Path,
        output_dir: Path,
        timeout: float,
        cancel: threading.Event | None = None,
        resource_dir: Path | None = None,
    ) -> ExecutionResult:
        if os.name != "posix":
            raise OSError("LocalRunner requires POSIX process groups; run it inside WSL/Linux")
        argv, work, out, duration = _prepare(command, workspace, output_dir, timeout)
        run_id = uuid.uuid4().hex
        stdout_path, stderr_path = out / f"{run_id}.stdout", out / f"{run_id}.stderr"
        started = time.monotonic()
        registry = _resource_registry(out, work, resource_dir)
        if cancel is not None and cancel.is_set():
            stdout_path.touch()
            stderr_path.touch()
            return _result("cancelled", None, stdout_path, stderr_path, started, self.backend, run_id)
        proc: subprocess.Popen[bytes] | None = None
        resource_path = registry / f"{run_id}.resource.json"
        outcome = "failed"
        returncode: int | None = None
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                proc = subprocess.Popen(
                    [sys.executable, str(Path(__file__).with_name('_launch.py')), *argv],
                    cwd=work,
                    stdin=subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    shell=False,
                    start_new_session=True,
                    env={**os.environ, 'H2PORTABLE_RESOURCE_ROOT': str(registry)},
                )
            except OSError:
                raise
            try:
                # The helper cannot execute payload code until this identity
                # is durable. Parent death before the gate opens yields EOF.
                write_record(resource_path, local_identity(proc.pid, run_id))
                assert proc.stdin is not None
                proc.stdin.write(b"1")
                proc.stdin.close()
                deadline = started + duration
                while True:
                    returncode = proc.poll()
                    if returncode is not None:
                        outcome = "completed" if returncode == 0 else "failed"
                        break
                    if cancel is not None and cancel.is_set():
                        outcome = "cancelled"
                        break
                    if time.monotonic() >= deadline:
                        outcome = "timed_out"
                        break
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            finally:
                # Also reap the complete owned group on KeyboardInterrupt or
                # any unexpected exception after Popen succeeds.
                if proc.stdin is not None and not proc.stdin.closed:
                    proc.stdin.close()
                self._terminate_group(proc)
                returncode = proc.returncode
                if resource_path.exists():
                    release_record(resource_path)
        return _result(outcome, returncode, stdout_path, stderr_path, started, self.backend, run_id)

    def _terminate_group(self, proc: subprocess.Popen[bytes]) -> None:
        # The child is a session leader, so the process group remains ours even
        # if it has spawned grandchildren or its leader has already exited.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            proc.wait()
            return
        end = time.monotonic() + self.terminate_grace
        while time.monotonic() < end:
            if not _live_group(proc.pid):
                proc.wait()
                return
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                proc.wait()
                return
            time.sleep(min(0.05, end - time.monotonic()))
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


class DockerRunner:
    """Run each command in a constrained, disposable Linux Docker container."""

    backend = "docker-cli"

    def __init__(self, image: str, docker: str = "docker", terminate_grace: float = 2.0,
                 cli_timeout: float = 15.0) -> None:
        if not image or image.startswith('-') or "\0" in image:
            raise ValueError("image must be a non-empty Docker image reference")
        if not docker or "\0" in docker:
            raise ValueError("docker must name the Docker CLI executable")
        if not math.isfinite(terminate_grace) or terminate_grace < 0:
            raise ValueError("terminate_grace must be finite and non-negative")
        if not math.isfinite(cli_timeout) or cli_timeout <= 0:
            raise ValueError("cli_timeout must be finite and positive")
        self.image = image
        self.docker = docker
        self.terminate_grace = terminate_grace
        self.cli_timeout = cli_timeout

    def run(
        self,
        command: Sequence[str],
        workspace: Path,
        output_dir: Path,
        timeout: float,
        cancel: threading.Event | None = None,
        resource_dir: Path | None = None,
    ) -> ExecutionResult:
        argv, work, out, duration = _prepare(command, workspace, output_dir, timeout)
        # Docker --mount parses commas as field separators. Reject ambiguous
        # host paths with a concrete explanation instead of invoking the shell.
        if "," in str(work):
            raise ValueError(f"Docker workspace path contains a comma: {work}; choose a comma-free path")
        run_id = uuid.uuid4().hex
        name = f"h2portable-{run_id}"
        stdout_path, stderr_path = out / f"{run_id}.stdout", out / f"{run_id}.stderr"
        started = time.monotonic()
        if cancel is not None and cancel.is_set():
            stdout_path.touch()
            stderr_path.touch()
            return _result("cancelled", None, stdout_path, stderr_path, started, self.backend, name)
        cid: str | None = None
        outcome = "failed"
        returncode: int | None = None
        stdout_data = b""
        stderr_data = b""
        error: str | None = None
        registry = _resource_registry(out, work, resource_dir)
        resource_path = registry / f"{run_id}.resource.json"
        resource = {"version": 1, "kind": "docker", "id": run_id, "name": name,
                    "docker": self.docker, "image": self.image, "released": False,
                    "controller_pid": os.getpid()}
        write_record(resource_path, resource)
        released = False
        try:
            uid, gid = self._container_identity()
            create = [
                self.docker, "create", "--pull", "never", "--name", name,
                "--label", "h2portable.managed=true",
                "--label", f"h2portable.run={run_id}",
                "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                "--memory", "1g", "--cpus", "1", "--pids-limit", "256",
                "--user", f"{uid}:{gid}", "--workdir", "/work",
                "--mount", f"type=bind,src={work},dst=/work",
                self.image, *argv,
            ]
            created = subprocess.run(create, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, check=False, timeout=self.cli_timeout)
            if created.returncode != 0:
                raise RuntimeError("docker create failed: " + created.stderr.decode("utf-8", "replace").strip())
            cid = created.stdout.decode("utf-8", "replace").strip()
            if not cid:
                raise RuntimeError("docker create succeeded without returning a container ID")
            resource['cid'] = cid
            write_record(resource_path, resource)
            started_container = subprocess.run([self.docker, "start", cid], stdin=subprocess.DEVNULL,
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                                               timeout=self.cli_timeout)
            if started_container.returncode != 0:
                raise RuntimeError("docker start failed: " + started_container.stderr.decode("utf-8", "replace").strip())
            deadline = started + duration
            while True:
                if cancel is not None and cancel.is_set():
                    outcome = "cancelled"
                    self._stop_container(cid)
                    break
                if time.monotonic() >= deadline:
                    outcome = "timed_out"
                    self._stop_container(cid)
                    break
                state = subprocess.run(
                    [self.docker, "inspect", "--format", "{{.State.Status}}", cid],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                    timeout=min(self.cli_timeout, max(0.1, deadline - time.monotonic())),
                )
                if state.returncode != 0:
                    raise RuntimeError("docker inspect failed: " + state.stderr.decode("utf-8", "replace").strip())
                if state.stdout.decode("utf-8", "replace").strip() in {"exited", "dead"}:
                    break
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
            waited = subprocess.run([self.docker, "wait", cid], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                                    timeout=self.cli_timeout)
            if waited.returncode != 0:
                raise RuntimeError("docker wait failed: " + waited.stderr.decode("utf-8", "replace").strip())
            try:
                returncode = int(waited.stdout.decode("ascii", "strict").strip())
            except (UnicodeError, ValueError) as exc:
                raise RuntimeError("docker wait returned an invalid exit code") from exc
            if outcome not in {"timed_out", "cancelled"}:
                outcome = "completed" if returncode == 0 else "failed"
            with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
                logs = subprocess.run([self.docker, "logs", cid], stdin=subprocess.DEVNULL,
                                      stdout=stdout_file, stderr=stderr_file, check=False,
                                      timeout=self.cli_timeout)
            if logs.returncode != 0 and outcome not in {"timed_out", "cancelled"}:
                outcome = "failed"
                error = f"docker logs failed (exit {logs.returncode})"
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            outcome = "failed"
            error = str(exc)
        finally:
            if cid is None:
                # A timed-out create can have succeeded in the daemon before
                # stdout returned. Recover only our unique, labelled resource.
                try:
                    probe = subprocess.run(
                        [self.docker, "inspect", "--format", "{{json .}}", name],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        timeout=self.cli_timeout)
                    if probe.returncode == 0:
                        info = json.loads(probe.stdout)
                        labels = info.get("Config", {}).get("Labels", {})
                        if labels.get("h2portable.run") == run_id and labels.get("h2portable.managed") == "true":
                            cid = info["Id"]
                        else:
                            error = "; ".join(filter(None, [error, "cleanup refused: container ownership labels differ"]))
                    elif 'No such' in probe.stderr:
                        released = True
                except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
                    error = "; ".join(filter(None, [error, f"could not verify interrupted container creation: {exc}"]))
            if cid is not None:
                try:
                    removed = subprocess.run([self.docker, "rm", "--force", cid], stdin=subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                                             timeout=self.cli_timeout)
                    if removed.returncode != 0:
                        removal_error = removed.stderr.decode("utf-8", "replace").strip()
                        error = "; ".join(filter(None, [error, "docker container cleanup failed" +
                                                           (f": {removal_error}" if removal_error else "")]))
                        if outcome == "completed":
                            outcome = "failed"
                    else:
                        released = True
                except (OSError, subprocess.SubprocessError) as exc:
                    error = "; ".join(filter(None, [error, f"docker container cleanup failed: {exc}"]))
                    if outcome == "completed":
                        outcome = "failed"
            if not stdout_path.exists():
                _save_bytes(stdout_path, stdout_data)
            if not stderr_path.exists():
                _save_bytes(stderr_path, stderr_data)
            if released:
                release_record(resource_path)
        return ExecutionResult(outcome, returncode, str(stdout_path), str(stderr_path),
                               max(0.0, time.monotonic() - started), self.backend, name, error)

    @staticmethod
    def _container_identity() -> tuple[int, int]:
        # Match the WSL controller's ownership so a writable bind mount remains
        # usable. A root controller falls back to an unprivileged nobody ID.
        uid = os.getuid() if hasattr(os, "getuid") else 65534
        gid = os.getgid() if hasattr(os, "getgid") else 65534
        if uid == 0:
            return 65534, 65534
        return uid, gid

    def _stop_container(self, cid: str) -> None:
        try:
            subprocess.run([self.docker, "stop", "--time", str(int(math.ceil(self.terminate_grace))), cid],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False, timeout=max(self.cli_timeout, self.terminate_grace + 3.0))
        except subprocess.TimeoutExpired:
            # The caller's finally block still force-removes this exact CID.
            subprocess.run([self.docker, "kill", cid], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                           timeout=self.cli_timeout)
