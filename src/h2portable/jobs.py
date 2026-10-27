"""Small POSIX file-backed foreground job wrapper."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from .execution import DockerRunner, LocalRunner, resolve_image
from .recovery import boot_id, recover_records


class JobError(ValueError):
    """Actionable job-store or request error."""


def _flock_module():
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - exercised on Windows hosts
        raise JobError("persisted jobs require POSIX flock; run the controller in WSL/Linux") from exc
    return fcntl


def _job_dir(store: Path, job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", job_id) or job_id in {".", ".."}:
        raise JobError("job ID must be 1–128 letters, digits, dots, underscores, or hyphens")
    result = Path(store).expanduser().resolve() / "jobs" / job_id
    if result.is_symlink() or result.parent.is_symlink():
        raise JobError('job directories cannot be linked to another location')
    return result


@contextmanager
def _lock(path: Path, *, blocking: bool = False) -> Iterator[bool]:
    fcntl = _flock_module()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(fd, flags)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _read_state(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise JobError(f"cannot read job state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise JobError(f"invalid job state in {path}")
    statuses = {'running', 'completed', 'failed', 'timed_out', 'cancelled', 'interrupted'}
    attempts = value.get('attempts')
    if value.get('status') not in statuses or not isinstance(attempts, list) or not attempts:
        raise JobError(f"invalid job state schema in {path}; preserve the record for review")
    for index, attempt in enumerate(attempts, 1):
        if not isinstance(attempt, dict) or attempt.get('number') != index or attempt.get('status') not in statuses:
            raise JobError(f"invalid attempt history in {path}")
        root = path.parent / 'attempts' / f'{index:04d}'
        if any(p.is_symlink() for p in [root.parent, root, root/'logs', root/'workspace', root/'input_snapshot']):
            raise JobError(f"linked attempt directories are not allowed in {path}")
        for key, leaf in [('workspace','workspace'), ('snapshot','input_snapshot'), ('log_directory','logs')]:
            saved = attempt.get(key)
            if not isinstance(saved, str) or Path(saved).absolute() != root / leaf:
                raise JobError(f"invalid attempt {key} location in {path}")
        result = attempt.get('result')
        if isinstance(result, dict):
            for key, suffix in [('stdout_file','.stdout'), ('stderr_file','.stderr')]:
                saved = result.get(key)
                if not isinstance(saved, str) or Path(saved).parent != root / 'logs' or not saved.endswith(suffix):
                    raise JobError(f"invalid log artifact location in {path}")
    return value


def _tree_manifest(root: Path) -> list[dict[str, Any]]:
    if root.is_symlink() or not root.is_dir():
        raise JobError(f"workspace must be a real directory, not a symlink: {root}")
    manifest: list[dict[str, Any]] = []
    root_stat = root.stat()
    manifest.append({"path": ".", "kind": "directory", "mode": stat.S_IMODE(root_stat.st_mode), "size": 0})
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs.sort()
        files.sort()
        for name in list(dirs):
            if name.lower() == '.env' or name.lower().startswith('.env.'):
                raise JobError('workspace contains a protected environment directory; choose only task data')
            path = current_path / name
            if path.is_symlink():
                raise JobError(f"workspace snapshot rejects symlink: {path}")
            rel = path.relative_to(root).as_posix()
            info = path.stat()
            manifest.append({"path": rel, "kind": "directory", "mode": stat.S_IMODE(info.st_mode), "size": 0})
        for name in files:
            if name.lower() == '.env' or (name.lower().startswith('.env.') and name.lower() != '.env.example'):
                raise JobError('workspace contains a protected credential file; choose task data without secret files')
            path = current_path / name
            if path.is_symlink():
                raise JobError(f"workspace snapshot rejects symlink: {path}")
            rel = path.relative_to(root).as_posix()
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise JobError(f"workspace snapshot rejects non-regular file: {path}")
            file_digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    file_digest.update(chunk)
            manifest.append({"path": rel, "kind": "file", "mode": stat.S_IMODE(info.st_mode),
                             "size": info.st_size, "sha256": file_digest.hexdigest()})
    manifest.sort(key=lambda item: (item["path"], item["kind"]))
    return manifest


def _manifest_hash(manifest: list[dict[str, Any]]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _file_hash(path: Path) -> str:
    if path.is_symlink() or path.name.lower() == '.env' or path.name.lower().startswith('.env.'):
        raise JobError('refusing to hash a protected or linked log artifact')
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_artifact_error(state: dict[str, Any]) -> str | None:
    attempts = state.get("attempts")
    if not isinstance(attempts, list) or not attempts or not isinstance(attempts[-1], dict):
        return "completed job is missing its attempt record"
    attempt = attempts[-1]
    artifacts = attempt.get("artifacts")
    result = attempt.get("result") or {}
    if not isinstance(artifacts, dict) or not isinstance(result, dict):
        return "completed job is missing its artifact integrity record"
    try:
        manifest = _tree_manifest(Path(attempt["workspace"]))
        if manifest != artifacts.get("workspace_manifest") or _manifest_hash(manifest) != artifacts.get("workspace_sha256"):
            return "completed workspace artifacts failed SHA-256 integrity verification"
        for stream in ("stdout_file", "stderr_file"):
            path = Path(result[stream])
            if _file_hash(path) != artifacts.get(stream.replace("_file", "_sha256")):
                return f"completed {stream.removesuffix('_file')} artifact failed SHA-256 integrity verification"
    except (KeyError, OSError, JobError) as exc:
        return f"completed output artifact is missing or unreadable: {exc}"
    return None


def _invalidate_cached(state: dict[str, Any], message: str) -> None:
    attempt = state.get("attempts", [])[-1] if state.get("attempts") else None
    state["status"] = "failed"
    if attempt is not None:
        attempt["status"] = "failed"
        attempt["ended_at"] = time.time()
    state["artifact_integrity_error"] = state["error"] = message
    state["updated_at"] = time.time()


def _proc_start_ticks(pid: int) -> int | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        tail = raw[raw.rfind(")") + 2 :].split()  # begins at proc field 3
        return int(tail[19])  # field 22, starttime
    except (OSError, ValueError, IndexError):
        return None


def _mark_interrupted(state: dict[str, Any]) -> None:
    if state.get("status") != "running" or not state.get("attempts"):
        return
    attempt = state["attempts"][-1]
    attempt["status"] = state["status"] = "interrupted"
    attempt["ended_at"] = state["updated_at"] = time.time()
    attempt["owner"] = None


def _reconcile_workers(state: dict[str, Any], job: Path) -> bool:
    """Caller holds the job lock; never operate on another job's resources."""
    pending = False
    for attempt in state.get('attempts', []):
        if attempt.get('status') not in {'interrupted', 'failed', 'cancelled', 'timed_out', 'completed'}:
            continue
        expected = job / 'attempts' / f"{int(attempt['number']):04d}" / 'logs'
        if Path(attempt.get('log_directory', '')).absolute() != expected or any(
            p.is_symlink() for p in [expected, expected.parent, expected.parent.parent]):
            resources = [{'status': 'pending', 'detail': 'worker log location does not belong to this attempt'}]
        elif attempt.get('resource_tracking') != 1 and attempt.get('status') == 'interrupted':
            resources = [{'status': 'pending', 'detail': 'legacy interrupted run has no durable worker identity; review its workers before retry'}]
        else:
            resources = recover_records(expected)
        status = 'pending' if any(r['status'] == 'pending' for r in resources) else 'recovered'
        attempt['recovery'] = {'status': status, 'resources': resources, 'checked_at': time.time()}
        if status == 'pending' and attempt.get('status') == 'completed':
            attempt['status'] = 'failed'
            state['status'] = 'failed'
            attempt['error'] = 'completed command has unresolved owned workers'
        pending = pending or status == 'pending'
    return not pending


def run_job(
    job_id: str,
    store: Path,
    backend: str,
    workspace: Path,
    timeout: float,
    command: Sequence[str],
    image: str | None = None,
) -> dict[str, Any]:
    """Run one attempt synchronously while holding its exclusive job lock."""
    if backend not in {"local", "docker"}:
        raise JobError("backend must be local or docker")
    if backend == "docker" and not image:
        raise JobError("Docker backend requires --image")
    if backend == "local" and image:
        raise JobError("--image is only valid with the Docker backend")
    if backend == "docker":
        try:
            image = resolve_image(image or "")
        except (ValueError, OSError) as exc:
            raise JobError(str(exc)) from exc
    try:
        duration = float(timeout)
    except (TypeError, ValueError) as exc:
        raise JobError("timeout must be finite and positive") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise JobError("timeout must be finite and positive")
    if isinstance(command, (str, bytes)) or not command or any(not isinstance(x, str) for x in command):
        raise JobError("command must be a non-empty argv list after --")
    source = Path(workspace).expanduser()
    if source.is_symlink():
        raise JobError(f"workspace root cannot be a symlink: {source}")
    source = source.resolve(strict=True)
    store_root = Path(store).expanduser().resolve()
    if source == store_root or source in store_root.parents or store_root in source.parents:
        raise JobError("workspace and job store must be separate directory trees")
    source_hash = _manifest_hash(_tree_manifest(source))
    spec = {"argv": list(command), "backend": backend, "image": image,
            "timeout": duration, "workspace_sha256": source_hash}
    spec_fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    job = _job_dir(store, job_id)
    state_path, lock_path = job / "state.json", job / "lock"
    job.mkdir(parents=True, exist_ok=True)
    with _lock(lock_path) as acquired:
        if not acquired:
            raise JobError(f"job {job_id!r} already has an active owner")
        state = _read_state(state_path) if state_path.exists() else None
        if state is not None:
            _mark_interrupted(state)
            if not _reconcile_workers(state, job):
                _atomic_json(state_path, state)
                raise JobError('owned-worker recovery is pending; retry status after resolving the recorded cleanup issue')
            _atomic_json(state_path, state)
            if state.get("spec_fingerprint") != spec_fingerprint:
                if state.get("status") == "interrupted":
                    _atomic_json(state_path, state)
                raise JobError("job ID already belongs to a different command, backend, timeout, image, or workspace snapshot")
            if state.get("status") == "completed":
                issue = _cache_artifact_error(state)
                if issue:
                    _invalidate_cached(state, issue)
                    _atomic_json(state_path, state)
                    raise JobError(issue + "; use a new job ID or repair the saved artifacts")
                reused = dict(state)
                reused["reused"] = True
                return reused
            if state.get("artifact_integrity_error"):
                issue = _cache_artifact_error(state)
                if issue:
                    raise JobError(state["artifact_integrity_error"] + "; use a new job ID or repair the saved artifacts")
                state["status"] = state["attempts"][-1]["status"] = "completed"
                state.pop("artifact_integrity_error", None)
                state.pop("error", None)
                state["updated_at"] = time.time()
                _atomic_json(state_path, state)
                return {**state, "reused": True}

        attempts = [] if state is None else state.get("attempts", [])
        number = len(attempts) + 1
        attempt_dir = job / "attempts" / f"{number:04d}"
        snapshot = attempt_dir / "input_snapshot"
        working = attempt_dir / "workspace"
        logs = attempt_dir / "logs"
        owner = {"pid": os.getpid(), "start_ticks": _proc_start_ticks(os.getpid()),
                 "boot_id": boot_id(), "pid_namespace": os.readlink('/proc/self/ns/pid')}
        attempt: dict[str, Any] = {"number": number, "status": "running", "started_at": time.time(),
                                   "resource_tracking": 1,
                                   "owner": owner, "snapshot": str(snapshot), "workspace": str(working),
                                   "log_directory": str(logs), "result": None}
        attempts.append(attempt)
        state = {"id": job_id, "status": "running", "spec": spec,
                 "spec_fingerprint": spec_fingerprint, "attempts": attempts,
                 "updated_at": time.time()}
        _atomic_json(state_path, state)
        cancel = threading.Event()
        previous_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, lambda _signum, _frame: cancel.set())
        try:
            attempt_dir.mkdir(parents=True, exist_ok=False)
            shutil.copytree(source, snapshot, symlinks=True)
            if _manifest_hash(_tree_manifest(snapshot)) != source_hash:
                raise JobError("workspace changed while its immutable snapshot was being copied; retry the run")
            shutil.copytree(snapshot, working, symlinks=True)
            logs.mkdir()
        except Exception as exc:
            attempt["error"] = str(exc)
            attempt["status"] = state["status"] = "failed"
            attempt["ended_at"] = state["updated_at"] = time.time()
            attempt["owner"] = None
            _atomic_json(state_path, state)
            signal.signal(signal.SIGTERM, previous_handler)
            if isinstance(exc, JobError):
                raise
            raise JobError(f"could not prepare workspace snapshot: {exc}") from exc
        except KeyboardInterrupt:
            cancel.set()
            attempt["error"] = "cancelled by Ctrl+C during workspace preparation"
            attempt["status"] = state["status"] = "cancelled"
            attempt["ended_at"] = state["updated_at"] = time.time()
            attempt["owner"] = None
            signal.signal(signal.SIGTERM, previous_handler)
            _atomic_json(state_path, state)
            return state
        try:
            runner = LocalRunner() if backend == "local" else DockerRunner(image or "")
            result = runner.run(command, working, logs, duration, cancel=cancel, resource_dir=logs)
            attempt["result"] = result.to_dict()
            attempt["status"] = result.outcome
            state["status"] = result.outcome
            resources = recover_records(logs)
            recovery_status = 'pending' if any(r['status'] == 'pending' for r in resources) else 'recovered'
            attempt['recovery'] = {'status': recovery_status, 'resources': resources, 'checked_at': time.time()}
            if recovery_status == 'pending':
                raise JobError('owned workers remain unresolved after command exit; retry is blocked until recovery completes')
            if result.outcome == "completed":
                manifest = _tree_manifest(working)
                attempt["artifacts"] = {
                    "workspace_manifest": manifest,
                    "workspace_sha256": _manifest_hash(manifest),
                    "stdout_sha256": _file_hash(Path(result.stdout_file)),
                    "stderr_sha256": _file_hash(Path(result.stderr_file)),
                }
        except Exception as exc:
            attempt["error"] = str(exc)
            attempt["status"] = state["status"] = "failed"
        except KeyboardInterrupt:
            cancel.set()
            attempt["error"] = "cancelled by Ctrl+C"
            attempt["status"] = state["status"] = "cancelled"
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
            attempt["ended_at"] = state["updated_at"] = time.time()
            attempt["owner"] = None
            _atomic_json(state_path, state)
        return state


def read_job(job_id: str, store: Path) -> dict[str, Any]:
    job = _job_dir(store, job_id)
    state_path, lock_path = job / "state.json", job / "lock"
    if not state_path.exists():
        raise JobError(f"job {job_id!r} was not found")
    with _lock(lock_path) as acquired:
        state = _read_state(state_path)
        if acquired:
            _mark_interrupted(state)
            _reconcile_workers(state, job)
            if state.get("status") == "interrupted":
                _atomic_json(state_path, state)
            elif state.get("status") == "completed":
                issue = _cache_artifact_error(state)
                if issue:
                    _invalidate_cached(state, issue)
                    _atomic_json(state_path, state)
                else:
                    _atomic_json(state_path, state)
            else:
                _atomic_json(state_path, state)
        return state


def stop_job(job_id: str, store: Path) -> dict[str, Any]:
    job = _job_dir(store, job_id)
    state_path, lock_path = job / "state.json", job / "lock"
    if not state_path.exists():
        raise JobError(f"job {job_id!r} was not found")
    with _lock(lock_path) as acquired:
        state = _read_state(state_path)
        if acquired:
            _mark_interrupted(state)
            _reconcile_workers(state, job)
            _atomic_json(state_path, state)
            return {**state, "stop_requested": False}
        owner = state.get("attempts", [{}])[-1].get("owner") if state.get("attempts") else None
        if state.get("status") != "running" or not owner:
            return {**state, "stop_requested": False}
        pid, ticks = owner.get("pid"), owner.get("start_ticks")
        if owner.get('boot_id') != boot_id() or owner.get('pid_namespace') != os.readlink('/proc/self/ns/pid'):
            raise JobError('job owner boot or PID namespace cannot be verified; refusing to signal')
        if not isinstance(pid, int) or not isinstance(ticks, int) or _proc_start_ticks(pid) != ticks:
            raise JobError("active job owner could not be verified; refusing to signal a possibly reused PID")
        fd = None
        try:
            fd = os.pidfd_open(pid)
            if _proc_start_ticks(pid) != ticks:
                raise JobError("job owner changed during verification; refusing to signal")
            signal.pidfd_send_signal(fd, signal.SIGTERM)
        except OSError as exc:
            raise JobError("job owner exited or its identity could not be verified") from exc
        finally:
            if fd is not None:
                os.close(fd)
        return {**state, "stop_requested": True}
