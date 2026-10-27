"""Lifecycle and contract tests for the portable execution backends."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from h2portable.execution import DockerRunner, LocalRunner


class ExecutionCases:
    python = sys.executable
    runner = None

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="h2 portable ü space ")
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace ü space"
        self.output = self.root / "artifacts ü space"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def execute(self, code: str, **kwargs):
        return self.runner.run([self.python, "-c", code], self.workspace, self.output,
                               timeout=kwargs.pop("timeout", 5), **kwargs)

    def test_success_and_stream_files(self) -> None:
        result = self.execute("print('out'); import sys; print('err', file=sys.stderr)")
        self.assertEqual(result.outcome, "completed")
        self.assertEqual(result.returncode, 0)
        self.assertIn("out", Path(result.stdout_file).read_text())
        self.assertIn("err", Path(result.stderr_file).read_text())
        self.assertEqual(result.to_dict()["backend"], result.backend)

    def test_failed_exit_is_normalized(self) -> None:
        result = self.execute("raise SystemExit(7)")
        self.assertEqual((result.outcome, result.returncode), ("failed", 7))

    def test_timeout_kills_child_that_ignores_term(self) -> None:
        marker = Path("late child marker.txt")
        child = (
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(1.2); open(%r,'w').write('orphan')" % str(marker)
        )
        parent = "import subprocess,time,sys; subprocess.Popen([sys.executable,'-c',%r]); time.sleep(20)" % child
        result = self.execute(parent, timeout=0.35)
        self.assertEqual(result.outcome, "timed_out")
        time.sleep(1.3)
        self.assertFalse((self.workspace / marker).exists(), "timed-out child outlived its process group")

    def test_cancellation_kills_process_group(self) -> None:
        cancel = threading.Event()
        timer = threading.Timer(0.2, cancel.set)
        timer.start()
        try:
            result = self.execute("import time; time.sleep(20)", timeout=5, cancel=cancel)
        finally:
            timer.cancel()
        self.assertEqual(result.outcome, "cancelled")

    def test_precancel_does_not_start_command(self) -> None:
        marker = Path("must not exist.txt")
        cancel = threading.Event()
        cancel.set()
        result = self.execute("open(%r,'w').write('started')" % str(marker), cancel=cancel)
        self.assertEqual(result.outcome, "cancelled")
        self.assertFalse((self.workspace / marker).exists())
        self.assertTrue(Path(result.stdout_file).exists())

    def test_rejects_shell_string_and_bad_timeout(self) -> None:
        with self.assertRaises(ValueError):
            self.runner.run("echo unsafe", self.workspace, self.output, 1)  # type: ignore[arg-type]
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.runner.run([self.python, "-c", "pass"], self.workspace, self.output, timeout)


class TestLocalRunner(ExecutionCases, unittest.TestCase):
    runner = LocalRunner(terminate_grace=0.1)

    @unittest.skipUnless(os.name == "posix", "LocalRunner intentionally supports POSIX only")
    def test_timeout_kills_child_that_ignores_term(self) -> None:
        super().test_timeout_kills_child_that_ignores_term()

    @unittest.skipUnless(os.name == "posix", "LocalRunner intentionally supports POSIX only")
    def test_cancellation_kills_process_group(self) -> None:
        super().test_cancellation_kills_process_group()


DOCKER_IMAGE = os.environ.get("H2_TEST_DOCKER_IMAGE")


@unittest.skipUnless(DOCKER_IMAGE, "set H2_TEST_DOCKER_IMAGE to run Docker integration cases")
class TestDockerRunner(ExecutionCases, unittest.TestCase):
    python = "python3"

    def setUp(self) -> None:
        if not shutil.which("docker"):
            self.skipTest("Docker CLI is unavailable")
        self.runner = DockerRunner(DOCKER_IMAGE, terminate_grace=1, cli_timeout=20)  # type: ignore[arg-type]
        super().setUp()

    def test_no_managed_container_remains_after_execution(self) -> None:
        result = self.execute("print('finished')")
        self.assertEqual(result.outcome, "completed")
        run_id = result.backend_id.removeprefix("h2portable-")
        remaining = subprocess.run(
            ["docker", "ps", "-aq", "--filter", f"label=h2portable.run={run_id}"],
            capture_output=True, text=True, check=False, timeout=20,
        )
        self.assertEqual(remaining.returncode, 0, remaining.stderr)
        self.assertEqual(remaining.stdout.strip(), "", "managed worker container was left behind")


if __name__ == "__main__":
    unittest.main()
