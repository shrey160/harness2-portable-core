"""Recover the managed fixture workflow and verify upstream resume integrity."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


@unittest.skipUnless(os.name == "posix" and os.environ.get("H2_TEST_DOCKER_IMAGE"),
                     "set H2_TEST_DOCKER_IMAGE to enable managed workflow recovery")
class TestManagedWorkflowRecovery(unittest.TestCase):
    def test_fixture_recovery_resumes_completed_upstream_runs(self) -> None:
        image = os.environ["H2_TEST_DOCKER_IMAGE"]
        default_upstream = Path.home() / "projects" / "harness2_portable_core" / "upstream" / "cli"
        upstream = Path(os.environ.get("H2_UPSTREAM_CLI", str(default_upstream))).expanduser().resolve()
        if not (upstream / "harness2" / "core" / "runmark.py").is_file():
            self.skipTest("provide the pinned upstream CLI checkout through H2_UPSTREAM_CLI")
        pinned = json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8"))["cli"]["commit"]
        revision = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual(revision.returncode, 0, revision.stderr)
        self.assertEqual(revision.stdout.strip(), pinned, "test must use the pinned upstream CLI checkout")
        sys.path.insert(0, str(upstream))
        from harness2.core import runmark

        fixture = ROOT / "fixtures" / "custom_workflow.py"
        self.assertTrue(fixture.is_file(), f"fixture is missing: {fixture}")
        with tempfile.TemporaryDirectory(prefix="h2 managed workflow ") as directory:
            root = Path(directory)
            store = root / "job store"
            input_workspace = root / "empty input workspace"
            input_workspace.mkdir()
            method_root = root / "persistent method output"
            attempt_logs = store / "jobs" / "managed-fixture" / "attempts" / "0001" / "logs"
            controller_log = root / "first controller.log"
            env = {**os.environ,
                   "PYTHONPATH": str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", ""),
                   "H2_UPSTREAM_CLI": str(upstream)}
            command = [sys.executable, str(fixture), "--backend", "docker", "--image", image,
                       "--output", str(method_root), "--upstream-cli", str(upstream)]
            argv = [sys.executable, "-m", "h2portable", "run", "--id", "managed-fixture", "--store", str(store),
                    "--backend", "local", "--workspace", str(input_workspace), "--timeout", "120", "--", *command]

            def completed_fixture_run() -> tuple[Path, bytes, dict] | None:
                execution_root = method_root / "runs" / "executions"
                if not execution_root.exists():
                    return None
                for path in sorted(execution_root.rglob("execution.json")):
                    try:
                        raw = path.read_bytes()
                        record = json.loads(raw)
                    except (OSError, json.JSONDecodeError):
                        continue
                    if (record.get("task") not in {"records-1", "records-2"}
                            or (record.get("execution") or {}).get("outcome") != "completed"):
                        continue
                    harness_dir = Path(record["harness_dir"]) if record.get("harness_dir") else None
                    marker = path.parent / "fixture_completion"
                    if runmark.read_mark(marker) and runmark.is_complete(marker, harness_dir=harness_dir):
                        return path, raw, record
                return None

            owner = None
            resource_paths: dict[str, Path] = {}
            records: dict[str, dict] = {}
            active_cids: set[str] = set()
            with controller_log.open("wb") as output:
                owner = subprocess.Popen(argv, env=env, stdout=output, stderr=output)
                try:
                    deadline = time.monotonic() + 105
                    completed: tuple[Path, bytes, dict] | None = None
                    while time.monotonic() < deadline:
                        completed = completed_fixture_run()
                        if attempt_logs.exists():
                            for path in attempt_logs.glob("*.resource.json"):
                                try:
                                    record = json.loads(path.read_text(encoding="utf-8"))
                                except (OSError, json.JSONDecodeError):
                                    continue
                                resource_paths[path.name] = path
                                records[path.name] = record
                        active_cids = set()
                        for record in records.values():
                            if record.get("kind") != "docker" or not record.get("cid") or record.get("released"):
                                continue
                            inspected = subprocess.run(
                                ["docker", "inspect", "--format", "{{.State.Running}}", record["cid"]],
                                capture_output=True, text=True, timeout=10,
                            )
                            if inspected.returncode == 0 and inspected.stdout.strip().lower() == "true":
                                active_cids.add(record["cid"])
                        if completed and active_cids and owner.poll() is None:
                            break
                        if owner.poll() is not None:
                            break
                        time.sleep(0.2)
                    self.assertIsNotNone(completed, "fixture did not finish any execution before controller recovery")
                    self.assertTrue(active_cids, "outer job logs did not contain an active managed Docker worker")
                    self.assertIsNone(owner.poll(), "job controller exited before the recovery point")
                    assert completed is not None
                    completed_path, completed_bytes, completed_record = completed
                    old_backend_id = (completed_record.get("execution") or {}).get("backend_id")
                    old_stdout = (completed_record.get("execution") or {}).get("stdout_file")
                    self.assertTrue(old_backend_id and old_stdout, "completed fixture run lacks backend identity or stdout path")

                    owner.kill()  # SIGKILL only the job controller.
                    owner.wait(timeout=5)
                    if attempt_logs.exists():
                        for path in attempt_logs.glob("*.resource.json"):
                            try:
                                records[path.name] = json.loads(path.read_text(encoding="utf-8"))
                                resource_paths[path.name] = path
                            except (OSError, json.JSONDecodeError):
                                continue
                    state_result = subprocess.run(
                        [sys.executable, "-m", "h2portable", "status", "--id", "managed-fixture", "--store", str(store)],
                        env=env, capture_output=True, text=True, timeout=45,
                    )
                    self.assertEqual(state_result.returncode, 0, state_result.stderr)
                    interrupted = json.loads(state_result.stdout)
                    self.assertEqual(interrupted["status"], "interrupted")
                    self.assertEqual(interrupted["attempts"][-1]["recovery"]["status"], "recovered")
                    recovered = {name: json.loads(path.read_text(encoding="utf-8"))
                                 for name, path in resource_paths.items()}
                    self.assertTrue(all(record.get("released") for record in recovered.values()),
                                    "all resources registered by the outer job must be recovered")
                    for cid in {record["cid"] for record in recovered.values()
                                if record.get("kind") == "docker" and record.get("cid")}:
                        inspected = subprocess.run(["docker", "inspect", cid], capture_output=True,
                                                    text=True, timeout=10)
                        self.assertNotEqual(inspected.returncode, 0, "an owned Docker worker survived recovery")

                    retried = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)
                    self.assertEqual(retried.returncode, 0, retried.stderr)
                    report = json.loads((method_root / "custom-workflow.json").read_text(encoding="utf-8"))
                    self.assertEqual((report["done"], report["failed"]), (2, 0))
                    totals = {task: data["selected_output"]["total"]
                              for task, data in report["selected"].items()}
                    self.assertEqual(totals, {"records-1": "-2.00", "records-2": "-1.00"})
                    updated = json.loads(completed_path.read_text(encoding="utf-8"))
                    self.assertEqual(completed_path.read_bytes(), completed_bytes,
                                     "upstream reran or rewrote an intact completed execution")
                    self.assertEqual(updated["execution"]["backend_id"], old_backend_id)
                    self.assertEqual(updated["execution"]["stdout_file"], old_stdout)
                finally:
                    if owner is not None and owner.poll() is None:
                        owner.kill()
                        owner.wait(timeout=5)
                    state_path = store / "jobs" / "managed-fixture" / "state.json"
                    if state_path.exists():
                        from h2portable.jobs import read_job
                        read_job("managed-fixture", store)


if __name__ == "__main__":
    unittest.main()
