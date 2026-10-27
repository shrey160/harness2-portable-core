"""POSIX integration tests for the persisted foreground job wrapper."""

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

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from h2portable.jobs import read_job  # noqa: E402


@unittest.skipUnless(os.name == "posix" and Path("/proc").is_dir(), "file-backed jobs require POSIX /proc")
class TestJobs(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="h2 jobs ")
        self.root = Path(self.temp.name)
        self.store = self.root / "store"
        self.workspace = self.root / "input ü"
        self.workspace.mkdir()
        (self.workspace / "seed.txt").write_text("original", encoding="utf-8")
        self.env = {**os.environ, "PYTHONPATH": str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cli(self, *args: str, timeout: float = 10) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-m", "h2portable", *args], env=self.env,
                              capture_output=True, text=True, timeout=timeout, check=False)

    def run_cli(self, job_id: str, command: list[str]) -> subprocess.CompletedProcess[str]:
        return self.cli("run", "--id", job_id, "--store", str(self.store), "--backend", "local",
                        "--workspace", str(self.workspace), "--timeout", "5", "--", *command)

    def test_completed_same_spec_reuses_and_mismatch_is_rejected(self) -> None:
        command = [sys.executable, "-c", "open('new.txt','w').write('working copy')"]
        first = self.run_cli("reuse", command)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["status"], "completed")
        self.assertEqual((self.workspace / "seed.txt").read_text(encoding="utf-8"), "original")
        self.assertFalse((self.workspace / "new.txt").exists())

        second = self.run_cli("reuse", command)
        self.assertEqual(second.returncode, 0, second.stderr)
        reused = json.loads(second.stdout)
        self.assertTrue(reused["reused"])
        self.assertEqual(len(reused["attempts"]), 1)

        mismatch = self.run_cli("reuse", [sys.executable, "-c", "print('different')"])
        self.assertEqual(mismatch.returncode, 2)
        self.assertIn("different", json.loads(mismatch.stderr)["error"])

    def test_failed_job_reruns_as_new_attempt(self) -> None:
        command = [sys.executable, "-c", "raise SystemExit(9)"]
        for expected_count in (1, 2):
            result = self.run_cli("retry", command)
            self.assertEqual(result.returncode, 1)
            state = json.loads(result.stdout)
            self.assertEqual(state["status"], "failed")
            self.assertEqual(len(state["attempts"]), expected_count)

    def test_completed_cache_rejects_missing_log_artifact(self) -> None:
        command = [sys.executable, "-c", "print('cached')"]
        result = self.run_cli("damaged", command)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        Path(state["attempts"][-1]["result"]["stdout_file"]).unlink()
        rejected = self.run_cli("damaged", command)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("artifact", json.loads(rejected.stderr)["error"])
        status = self.cli("status", "--id", "damaged", "--store", str(self.store))
        self.assertEqual(json.loads(status.stdout)["status"], "failed")

    def test_completed_cache_rejects_changed_output_workspace(self) -> None:
        command = [sys.executable, "-c", "open('answer.txt','w').write('original')"]
        result = self.run_cli("changed", command)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        work = Path(state["attempts"][-1]["workspace"])
        (work / "answer.txt").write_text("tampered", encoding="utf-8")
        rejected = self.run_cli("changed", command)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("workspace artifacts failed", json.loads(rejected.stderr)["error"])

    def test_ctrl_c_persists_cancelled_status(self) -> None:
        command = [sys.executable, "-c", "import time; time.sleep(30)"]
        owner = subprocess.Popen(
            [sys.executable, "-m", "h2portable", "run", "--id", "ctrlc", "--store", str(self.store),
             "--backend", "local", "--workspace", str(self.workspace), "--timeout", "60", "--", *command],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            state_path = self.store / "jobs" / "ctrlc" / "state.json"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not state_path.exists():
                time.sleep(0.05)
            self.assertTrue(state_path.exists())
            owner.send_signal(signal.SIGINT)
            stdout, stderr = owner.communicate(timeout=10)
            self.assertEqual(owner.returncode, 130, stderr)
            self.assertEqual(json.loads(stdout)["status"], "cancelled")
        finally:
            if owner.poll() is None:
                owner.send_signal(signal.SIGTERM)
                owner.communicate(timeout=10)

    def test_stop_cli_signals_verified_owner_and_cancels_job(self) -> None:
        command = [sys.executable, "-c", "import time; time.sleep(30)"]
        owner = subprocess.Popen(
            [sys.executable, "-m", "h2portable", "run", "--id", "stopme", "--store", str(self.store),
             "--backend", "local", "--workspace", str(self.workspace), "--timeout", "60", "--", *command],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            state_path = self.store / "jobs" / "stopme" / "state.json"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not state_path.exists():
                time.sleep(0.05)
            self.assertTrue(state_path.exists())
            stopped = self.cli("stop", "--id", "stopme", "--store", str(self.store))
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertTrue(json.loads(stopped.stdout)["stop_requested"])
            stdout, stderr = owner.communicate(timeout=10)
            self.assertEqual(owner.returncode, 130, stderr)
            self.assertEqual(json.loads(stdout)["status"], "cancelled")
        finally:
            if owner.poll() is None:
                owner.send_signal(signal.SIGTERM)
                owner.communicate(timeout=10)

    def test_lock_conflict_is_rejected(self) -> None:
        command = [sys.executable, "-c", "import time; time.sleep(30)"]
        owner = subprocess.Popen(
            [sys.executable, "-m", "h2portable", "run", "--id", "locked", "--store", str(self.store),
             "--backend", "local", "--workspace", str(self.workspace), "--timeout", "60", "--", *command],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            state_path = self.store / "jobs" / "locked" / "state.json"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not state_path.exists():
                time.sleep(0.05)
            self.assertTrue(state_path.exists())
            conflict = self.cli("run", "--id", "locked", "--store", str(self.store), "--backend", "local",
                                "--workspace", str(self.workspace), "--timeout", "60", "--", *command)
            self.assertEqual(conflict.returncode, 2)
            self.assertIn("active owner", json.loads(conflict.stderr)["error"])
        finally:
            owner.send_signal(signal.SIGTERM)
            owner.communicate(timeout=10)

    def test_killed_owner_is_marked_interrupted(self) -> None:
        command = [sys.executable, "-c", "import os,time; open('child.pid','w').write(str(os.getpid())); time.sleep(30)"]
        owner = subprocess.Popen(
            [sys.executable, "-m", "h2portable", "run", "--id", "orphan", "--store", str(self.store),
             "--backend", "local", "--workspace", str(self.workspace), "--timeout", "60", "--", *command],
            env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        pid_file: Path | None = None
        child_pid: int | None = None
        try:
            state_path = self.store / "jobs" / "orphan" / "state.json"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if state_path.exists():
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if state.get("attempts"):
                        pid_file = Path(state["attempts"][0]["workspace"]) / "child.pid"
                        if pid_file.exists():
                            child_pid = int(pid_file.read_text())
                            break
                time.sleep(0.05)
            self.assertIsNotNone(child_pid, "worker command did not start")
            # SIGKILL releases the job lock but bypasses the runner cleanup.
            # Explicitly terminate its child below; recovery is state-only.
            owner.kill()
            owner.wait(timeout=5)
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=5)
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        state = read_job("orphan", self.store)
        self.assertEqual(state["status"], "interrupted")
        self.assertEqual(state["attempts"][-1]["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
