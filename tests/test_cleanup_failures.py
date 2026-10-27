"""Mocked regressions for cleanup when process/container creation races fail."""

from __future__ import annotations

import json
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from h2portable.execution import DockerRunner, LocalRunner


class TestLocalProcessGroupCleanup(unittest.TestCase):
    @patch("h2portable.execution.os.killpg", side_effect=ProcessLookupError)
    def test_missing_group_never_gets_followup_sigkill(self, killpg: Mock) -> None:
        process = SimpleNamespace(pid=43210, wait=Mock())
        LocalRunner(terminate_grace=0.01)._terminate_group(process)
        self.assertEqual(killpg.call_args_list, [call(43210, signal.SIGTERM)])
        process.wait.assert_called_once_with()


class TestDockerCreateCleanup(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="h2 docker cleanup ")
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.output = self.root / "output"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def inspect_result(run_id: str, *, managed: str = "true", container_id: str = "sha256:owned"):
        payload = {"Id": container_id, "Config": {"Labels": {
            "h2portable.run": run_id, "h2portable.managed": managed,
        }}}
        return subprocess.CompletedProcess(args=["docker", "inspect"], returncode=0,
                                            stdout=json.dumps(payload), stderr="")

    def run_with_create_timeout(self, inspect_response):
        runner = DockerRunner("sha256:image", cli_timeout=0.1)
        created_id: str | None = None
        calls: list[list[str]] = []

        def mocked_run(args, *pargs, **kwargs):
            nonlocal created_id
            argv = list(args)
            calls.append(argv)
            if argv[1] == "create":
                # Save the unique requested name so the test can respond to
                # the inspect-by-name recovery path without a Docker daemon.
                created_id = argv[argv.index("--name") + 1]
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0.1))
            if argv[1] == "inspect":
                return inspect_response(created_id.removeprefix("h2portable-") if created_id else "")
            if argv[1:3] == ["rm", "--force"]:
                return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
            raise AssertionError(f"unexpected Docker operation in mocked test: {argv}")

        with patch("h2portable.execution.subprocess.run", side_effect=mocked_run):
            result = runner.run(["python3", "-c", "pass"], self.workspace, self.output, 1)
        return result, calls

    def test_create_timeout_recovers_and_removes_exact_owned_cid(self) -> None:
        def inspect(name_run_id: str):
            # The inspect target is the unique h2portable-<uuid> name. The
            # ownership label stores the suffix UUID.
            return self.inspect_result(name_run_id)

        result, calls = self.run_with_create_timeout(inspect)
        self.assertEqual(result.outcome, "failed")
        self.assertTrue(any(argv[1:3] == ["rm", "--force"] and argv[-1] == "sha256:owned" for argv in calls))
        self.assertEqual(len([argv for argv in calls if argv[1] == "rm"]), 1)

    def test_create_timeout_with_mismatched_ownership_refuses_removal(self) -> None:
        result, calls = self.run_with_create_timeout(
            lambda _run_id: self.inspect_result("some-other-run", managed="false", container_id="sha256:foreign")
        )
        self.assertEqual(result.outcome, "failed")
        self.assertIn("ownership labels differ", result.error or "")
        self.assertFalse(any(argv[1] == "rm" for argv in calls), "foreign container must not be removed")


if __name__ == "__main__":
    unittest.main()
