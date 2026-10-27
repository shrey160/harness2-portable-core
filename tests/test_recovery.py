"""Durable worker recovery regressions (POSIX integration, Docker gated)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from h2portable.jobs import JobError, read_job, run_job  # noqa: E402
from h2portable.recovery import recover_record  # noqa: E402


@unittest.skipUnless(os.name == "posix" and Path("/proc").is_dir(), "requires POSIX /proc")
class TestLocalRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="h2 recovery ")
        self.root = Path(self.temp.name)
        self.store = self.root / "store"
        self.workspace = self.root / "input ü"
        self.workspace.mkdir()
        self.env = {**os.environ, "PYTHONPATH": str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cli(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-m", "h2portable", *args], env=env or self.env,
                              capture_output=True, text=True, timeout=15, check=False)

    def test_dead_controller_recovers_group_and_allows_new_attempt(self) -> None:
        marker = self.root / "late marker"
        started = self.root / "payload started"
        script = (
            "import os,subprocess,sys,time; "
            "open(sys.argv[1],'w').write('started'); "
            "if_first = os.environ.get('H2_RECOVERY_FIRST') == '1'; "
            "subprocess.Popen([sys.executable,'-c',"
            "'import pathlib,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            "time.sleep(1.5); pathlib.Path(sys.argv[1]).write_text(\"late\")',sys.argv[2]]) "
            "if if_first else None; time.sleep(30) if if_first else None"
        )
        command = [sys.executable, "-c", script, str(started), str(marker)]
        first_env = {**self.env, "H2_RECOVERY_FIRST": "1"}
        owner = subprocess.Popen(
            [sys.executable, "-m", "h2portable", "run", "--id", "recovery", "--store", str(self.store),
             "--backend", "local", "--workspace", str(self.workspace), "--timeout", "60", "--", *command],
            env=first_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        resource: Path | None = None
        try:
            attempt_logs = self.store / "jobs" / "recovery" / "attempts" / "0001" / "logs"
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and not started.exists():
                candidates = list(attempt_logs.glob("*.resource.json")) if attempt_logs.exists() else []
                if candidates:
                    resource = candidates[0]
                time.sleep(0.03)
            self.assertTrue(started.exists(), "worker payload did not start")
            self.assertIsNotNone(resource, "durable worker resource record was not written")
            identity = json.loads(resource.read_text(encoding="utf-8"))
            owner.kill()  # SIGKILL only the controller; recovery owns the worker group.
            owner.wait(timeout=5)

            state = self.cli("status", "--id", "recovery", "--store", str(self.store))
            self.assertEqual(state.returncode, 0, state.stderr)
            recovered = json.loads(state.stdout)
            self.assertEqual(recovered["status"], "interrupted")
            self.assertEqual(recovered["attempts"][-1]["recovery"]["status"], "recovered")
            time.sleep(1.8)
            self.assertFalse(marker.exists(), "a worker descendant ran after recovery")
            self.assertFalse(_active_group_members(identity["pgid"]), "owned process group still has live members")

            retry_env = {**self.env, "H2_RECOVERY_FIRST": "0"}
            retried = self.cli("run", "--id", "recovery", "--store", str(self.store), "--backend", "local",
                               "--workspace", str(self.workspace), "--timeout", "60", "--", *command, env=retry_env)
            self.assertEqual(retried.returncode, 0, retried.stderr)
            self.assertEqual(len(json.loads(retried.stdout)["attempts"]), 2)
            time.sleep(1.8)
            self.assertFalse(marker.exists(), "the orphaned first attempt ran after a retry")
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=5)
            if resource is not None and resource.exists():
                try:
                    recovery = recover_record(resource, grace=0)
                    self.assertIn(recovery["status"], {"recovered", "pending"})
                except Exception:
                    pass


def _active_group_members(pgid: int) -> list[int]:
    """Return non-zombie processes still belonging to an owned process group."""
    members: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="ascii")
            fields = stat[stat.rfind(")") + 2 :].split()
            if fields[0] != "Z" and int(fields[2]) == pgid:  # state, ppid, pgrp
                members.append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return members


class TestRecoveryFailClosed(unittest.TestCase):
    def test_malformed_released_flag_does_not_skip_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / 'worker.resource.json'
            record.write_text(json.dumps({'version': 1, 'kind': 'local', 'released': 'false'}))
            with patch('h2portable.recovery.process_info', side_effect=AssertionError('invalid identity must not be used')):
                result = recover_record(record)
            self.assertEqual(result['status'], 'pending')
            self.assertIn('boolean', result['detail'])

    def test_pending_recovery_blocks_retry_until_read_job_cleans_stale_record(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h2 retry recovery ") as directory:
            root = Path(directory)
            store, workspace = root / "store", root / "workspace"
            workspace.mkdir()
            command = [sys.executable, "-c", "open('retry-launched','w').write('yes')"]
            first = run_job("pending-retry", store, "local", workspace, 5, command)
            self.assertEqual(first["status"], "completed")
            state_path = store / "jobs" / "pending-retry" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["status"] = state["attempts"][-1]["status"] = "interrupted"
            state["attempts"][-1]["owner"] = None
            state["attempts"][-1]["resource_tracking"] = 1
            state_path.write_text(json.dumps(state), encoding="utf-8")
            log_dir = Path(state["attempts"][-1]["log_directory"])
            resource = log_dir / "stale.resource.json"
            resource.write_text(json.dumps({
                "version": 1, "kind": "local", "id": "old-run", "pid": 43210,
                "pgid": 43210, "start_ticks": 1, "boot_id": "previous-boot", "released": False,
            }), encoding="utf-8")

            with patch("h2portable.jobs.recover_records", return_value=[{
                "status": "pending", "detail": "mocked unverified worker",
            }]), patch("h2portable.jobs.LocalRunner") as runner:
                with self.assertRaisesRegex(JobError, "recovery is pending"):
                    run_job("pending-retry", store, "local", workspace, 5, command)
                runner.assert_not_called()
            self.assertEqual(len(json.loads(state_path.read_text(encoding="utf-8"))["attempts"]), 1)

            recovered = read_job("pending-retry", store)
            self.assertEqual(recovered["status"], "interrupted")
            self.assertEqual(recovered["attempts"][-1]["recovery"]["status"], "recovered")
            self.assertTrue(json.loads(resource.read_text(encoding="utf-8"))["released"])

    def test_corrupt_resource_record_stays_pending_without_worker_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h2 corrupt recovery ") as directory:
            record = Path(directory) / "worker.resource.json"
            record.write_text("{truncated", encoding="utf-8")
            with patch("h2portable.recovery.subprocess.run") as docker:
                result = recover_record(record, grace=0)
            self.assertEqual(result["status"], "pending")
            docker.assert_not_called()

    def test_pid_reuse_or_boot_mismatch_never_signals_unverified_worker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h2 recovery record ") as directory:
            record = Path(directory) / "worker.resource.json"
            record.write_text(json.dumps({
                "version": 1, "kind": "local", "id": "owned-run", "pid": 43210,
                "pgid": 43210, "start_ticks": 11, "boot_id": "old-boot", "released": False,
            }), encoding="utf-8")
            with patch("h2portable.recovery.boot_id", return_value="new-boot"), \
                    patch("h2portable.recovery.os.killpg") as killpg:
                result = recover_record(record, grace=0)
            self.assertEqual(result["status"], "recovered")
            killpg.assert_not_called()

            record.write_text(json.dumps({
                "version": 1, "kind": "local", "id": "owned-run", "pid": 43210,
                "pgid": 43210, "start_ticks": 11, "boot_id": "old-boot", "released": False,
            }), encoding="utf-8")
            with patch("h2portable.recovery.boot_id", return_value="old-boot"), \
                    patch("h2portable.recovery.process_info", return_value={
                        "state": "S", "pgid": 43210, "start_ticks": 99,
                    }), \
                    patch("h2portable.recovery.os.killpg") as killpg:
                result = recover_record(record, grace=0)
            self.assertEqual(result["status"], "pending")
            killpg.assert_not_called()

    def test_docker_label_mismatch_refuses_container_removal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h2 docker record ") as directory:
            record = Path(directory) / "worker.resource.json"
            record.write_text(json.dumps({
                "version": 1, "kind": "docker", "id": "owned-run", "name": "h2portable-owned-run",
                "cid": "container-foreign", "docker": "docker", "released": False,
            }), encoding="utf-8")
            inspect = subprocess.CompletedProcess(
                ["docker", "inspect"], 0,
                stdout=json.dumps({"Id": "container-foreign", "Name": "/h2portable-owned-run",
                                   "Config": {"Labels": {"h2portable.managed": "true",
                                                           "h2portable.run": "another-run"}}}),
                stderr="",
            )
            with patch("h2portable.recovery.subprocess.run", return_value=inspect) as run:
                result = recover_record(record, grace=0)
            self.assertEqual(result["status"], "pending")
            self.assertIn("labels differ", result["detail"])
            self.assertEqual(run.call_count, 1, "recovery must not log or remove a foreign container")

    def test_docker_unavailable_then_available_recovers_and_releases_record(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h2 docker retry ") as directory:
            record = Path(directory) / "worker.resource.json"
            value = {"version": 1, "kind": "docker", "id": "owned-run",
                     "name": "h2portable-owned-run", "cid": "container-owned",
                     "docker": "docker", "released": False}
            record.write_text(json.dumps(value), encoding="utf-8")
            unavailable = subprocess.CompletedProcess(["docker", "inspect"], 1, stdout="",
                                                       stderr="Cannot connect to Docker daemon")
            with patch("h2portable.recovery.subprocess.run", return_value=unavailable):
                pending = recover_record(record, grace=0)
            self.assertEqual(pending["status"], "pending")
            self.assertFalse(json.loads(record.read_text(encoding="utf-8"))["released"])

            owned = subprocess.CompletedProcess(
                ["docker", "inspect"], 0,
                stdout=json.dumps({"Id": "container-owned", "Name": "/h2portable-owned-run",
                                   "Config": {"Labels": {"h2portable.managed": "true",
                                                           "h2portable.run": "owned-run"}}}),
                stderr="",
            )
            def docker_available(args, **kwargs):
                if args[1] == "inspect":
                    return owned
                return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

            with patch("h2portable.recovery.subprocess.run", side_effect=docker_available) as run:
                recovered = recover_record(record, grace=0)
            self.assertEqual(recovered["status"], "recovered")
            self.assertEqual([call.args[0][1] for call in run.call_args_list], ["inspect", "logs", "rm"])
            self.assertTrue(json.loads(record.read_text(encoding="utf-8"))["released"])


@unittest.skipUnless(os.name == "posix" and os.environ.get("H2_TEST_DOCKER_IMAGE"),
                     "set H2_TEST_DOCKER_IMAGE to enable Docker recovery integration")
class TestDockerRecovery(unittest.TestCase):
    def test_dead_controller_removes_its_labeled_container(self) -> None:
        image = os.environ["H2_TEST_DOCKER_IMAGE"]
        with tempfile.TemporaryDirectory(prefix="h2 docker recovery ") as directory:
            root = Path(directory)
            store, workspace = root / "store", root / "workspace"
            workspace.mkdir()
            env = {**os.environ, "PYTHONPATH": str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")}
            owner = subprocess.Popen(
                [sys.executable, "-m", "h2portable", "run", "--id", "docker-recovery", "--store", str(store),
                 "--backend", "docker", "--image", image, "--workspace", str(workspace), "--timeout", "60",
                 "--", "python3", "-c", "import time; time.sleep(30)"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                logs = store / "jobs" / "docker-recovery" / "attempts" / "0001" / "logs"
                deadline = time.monotonic() + 25
                records: list[Path] = []
                while time.monotonic() < deadline:
                    records = list(logs.glob("*.resource.json")) if logs.exists() else []
                    if records and json.loads(records[0].read_text(encoding="utf-8")).get("cid"):
                        break
                    time.sleep(0.1)
                self.assertTrue(records, "Docker resource intent record was not written")
                owner.kill()
                owner.wait(timeout=5)
                status = subprocess.run([sys.executable, "-m", "h2portable", "status", "--id", "docker-recovery",
                                         "--store", str(store)], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertEqual(json.loads(status.stdout)["attempts"][-1]["recovery"]["status"], "recovered")
                resource = json.loads(records[0].read_text(encoding="utf-8"))
                inspect = subprocess.run(["docker", "inspect", resource["cid"]], capture_output=True, text=True)
                self.assertNotEqual(inspect.returncode, 0, "the exact owned container still exists")
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
