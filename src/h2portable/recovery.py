"""Durable, fail-closed recovery for workers owned by a dead controller."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="."+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()


def process_info(pid: int) -> dict | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        fields = raw[raw.rfind(")") + 2:].split()
        return {"state": fields[0], "pgid": int(fields[2]), "start_ticks": int(fields[19])}
    except FileNotFoundError:
        return None


def _live_group(pgid: int) -> bool:
    # Zombies cannot execute or write artifacts and are reaped by their new parent.
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                info = process_info(int(entry.name))
                if info and info["pgid"] == pgid and info["state"] not in {"Z", "X"}:
                    return True
            except (OSError, ValueError, IndexError):
                continue
    return False


def local_identity(pid: int, run_id: str) -> dict:
    info = process_info(pid)
    if not info or info["pgid"] != pid:
        raise RuntimeError("cannot establish local worker process-group ownership")
    return {"version": 1, "kind": "local", "id": run_id, "pid": pid, "pgid": pid,
            "start_ticks": info["start_ticks"], "boot_id": boot_id(),
            "pid_namespace": os.readlink('/proc/self/ns/pid'), "released": False,
            "controller_pid": os.getpid()}


def release_record(path: Path) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(released=True, released_at=time.time())
    write_record(path, record)


def _recover_local(record: dict, grace: float) -> str:
    if not isinstance(record.get('boot_id'), str) or not record['boot_id']:
        raise ValueError('local boot identity is missing')
    if record.get("boot_id") != boot_id():
        return "previous Linux boot; worker cannot still be running"
    if record.get('pid_namespace') != os.readlink('/proc/self/ns/pid'):
        raise ValueError('local PID namespace differs; refusing to signal')
    pid = record["pid"]
    if not isinstance(pid, int) or pid <= 1 or record.get("pgid") != pid:
        raise ValueError("invalid local worker identity")
    info = process_info(pid)
    if info is None or info["state"] in {"Z", "X"}:
        if _live_group(pid):
            raise ValueError("leader exited with remaining group members; ownership cannot be safely reverified")
        return "worker group is no longer active"
    if info["start_ticks"] != record.get("start_ticks") or info["pgid"] != pid:
        raise ValueError("worker PID or group identity changed; refusing to signal")
    # A pidfd addresses this process instance, even if its numeric PID is reused.
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise ValueError('Linux pidfd support is required for verified local recovery')
    fd = os.pidfd_open(pid)
    stopped = False
    try:
        signal.pidfd_send_signal(fd, signal.SIGSTOP)
        stopped = True
        verified = process_info(pid)
        if not verified or verified["start_ticks"] != record["start_ticks"] or verified["pgid"] != pid:
            raise ValueError("worker identity changed during recovery")
        # Keep the leader stopped and alive until the final group kill, reserving
        # its PGID while children receive TERM and finish.
        os.killpg(pid, signal.SIGTERM)
        time.sleep(grace)
        verified = process_info(pid)
        if verified and verified["start_ticks"] == record["start_ticks"] and verified["state"] not in {"Z", "X"}:
            os.killpg(pid, signal.SIGKILL)
        elif _live_group(pid):
            raise ValueError("group leader disappeared during recovery; remaining group requires review")
    except ProcessLookupError:
        if _live_group(pid):
            raise ValueError("worker disappeared before cleanup could be verified")
    finally:
        if stopped:
            # A failed verification must not leave a process frozen.
            try:
                signal.pidfd_send_signal(fd, signal.SIGCONT)
            except ProcessLookupError:
                pass
        os.close(fd)
    deadline = time.monotonic() + 2
    while _live_group(pid) and time.monotonic() < deadline:
        time.sleep(.025)
    if _live_group(pid):
        raise ValueError("worker group remains active after bounded cleanup")
    return "verified local worker group terminated"


def _recover_docker(record: dict, path: Path) -> str:
    run_id = record["id"]
    name = record["name"]
    if name != "h2portable-" + run_id:
        raise ValueError("container name does not match its ownership token")
    if record.get('docker', 'docker') != 'docker':
        raise ValueError('custom Docker executable needs an explicit recovery configuration')
    docker = 'docker'
    probe = subprocess.run([docker, "inspect", "--format", "{{json .}}", name],
                           capture_output=True, text=True, timeout=5)
    if probe.returncode:
        if "No such" in probe.stderr:
            return "owned container is absent"
        raise ValueError("Docker unavailable or inspect failed; recovery is pending")
    info = json.loads(probe.stdout)
    labels = info.get("Config", {}).get("Labels", {}) or {}
    if labels.get("h2portable.managed") != "true" or labels.get("h2portable.run") != run_id:
        raise ValueError("container ownership labels differ; refusing cleanup")
    if info.get("Name", "").lstrip("/") != name:
        raise ValueError("container name changed; refusing cleanup")
    cid = info["Id"]
    if record.get("cid") and record["cid"] != cid:
        raise ValueError("container ID changed; refusing cleanup")
    # Preserve whatever visible output was produced before the controller died.
    for stream in ("stdout", "stderr"):
        destination = path.with_name(path.stem + ".recovered." + stream)
        if not destination.exists():
            destination.touch()
    with path.with_name(path.stem + ".recovered.stdout").open("wb") as stdout, \
         path.with_name(path.stem + ".recovered.stderr").open("wb") as stderr:
        subprocess.run([docker, "logs", cid], stdout=stdout, stderr=stderr, timeout=5)
    removed = subprocess.run([docker, "rm", "--force", cid], capture_output=True, timeout=5)
    if removed.returncode:
        raise ValueError("owned container could not be removed; recovery is pending")
    return "verified owned container removed"


def recover_record(path: Path, grace: float = .2) -> dict:
    """Called only after the caller holds the abandoned job's exclusive lock."""
    try:
        if not isinstance(grace, (int, float)) or not math.isfinite(grace) or not 0 <= grace <= 5:
            raise ValueError('recovery grace must be between zero and five seconds')
        if path.is_symlink():
            raise ValueError("resource record cannot be a symlink")
        if any(part.lower() == '.env' or part.lower().startswith('.env.') for part in path.parts):
            raise ValueError('protected credential paths cannot be read as resource records')
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError('resource record must be an object')
        if type(record.get("version")) is not int or record['version'] != 1:
            raise ValueError("unsupported resource record version")
        if type(record.get('released')) is not bool:
            raise ValueError('resource released flag must be a boolean')
        if record['released']:
            return {"status": "recovered", "detail": "resource already released", "record": str(path)}
        if record.get("kind") == "local":
            detail = _recover_local(record, grace)
        elif record.get("kind") == "docker":
            detail = _recover_docker(record, path)
        else:
            raise ValueError("unknown worker resource kind")
        record.update(released=True, released_at=time.time(), recovery_detail=detail)
        write_record(path, record)
        return {"status": "recovered", "detail": detail, "record": str(path)}
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError) as exc:
        return {"status": "pending", "detail": str(exc), "record": str(path)}


def recover_records(log_dir: Path) -> list[dict]:
    if log_dir.is_symlink():
        return [{'status': 'pending', 'detail': 'linked worker log directories cannot be recovered'}]
    results = {}
    # Terminate trusted local workflow parents before their workers, then rescan
    # for identities registered just before those parents died. Task containers
    # never receive this registry mount or its environment variable.
    for _ in range(4):
        records = {}
        for path in sorted(log_dir.glob('*.resource.json')):
            if path.is_symlink() or path.name.lower().startswith('.env'):
                results[str(path)] = {'status': 'pending', 'detail': 'invalid resource path', 'record': str(path)}
                continue
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(record, dict):
                    records[path] = record
            except (OSError, ValueError):
                pass
        by_pid = {r.get('pid'): r for r in records.values() if r.get('kind') == 'local' and isinstance(r.get('pid'), int)}
        def depth(record, seen=None):
            seen = set() if seen is None else seen
            parent = record.get('controller_pid')
            if not isinstance(parent, int) or parent not in by_pid or parent in seen or len(seen) >= 128:
                return 0
            return 1 + depth(by_pid[parent], seen | {parent})
        local = sorted((p for p,r in records.items() if r.get('kind') == 'local'), key=lambda p: depth(records[p]))
        fresh = [p for p in local if str(p) not in results]
        for path in fresh:
            results[str(path)] = recover_record(path)
        if not fresh:
            break
    for path in sorted(log_dir.glob('*.resource.json')):
        if str(path) not in results:
            results[str(path)] = recover_record(path)
    return list(results.values())

