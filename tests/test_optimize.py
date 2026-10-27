"""The supported optimize entry point runs a real method loop via jobs."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from h2portable.jobs import JobError
from h2portable.optimize import DECLARED_TASK_SET, build_optimize_spec, run_optimize

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "requires WSL/Linux")
class TestOptimizeEntryPoint(unittest.TestCase):
    def test_unknown_task_set_is_rejected_before_any_job(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h2 optimize reject ") as directory:
            root = Path(directory)
            workspace = root / "input"
            workspace.mkdir()
            with self.assertRaisesRegex(JobError, "unsupported task set"):
                run_optimize("bad-task", root / "store", "local", workspace, 30,
                             root / "method", task_set="not-declared")
            self.assertFalse((root / "store").exists())

    def test_local_optimize_completes_and_reuses_managed_job(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h2 optimize ") as directory:
            root = Path(directory)
            workspace = root / "input"
            workspace.mkdir()
            method = root / "method output"
            store = root / "store"
            pinned = json.loads((ROOT / "upstream.lock.json").read_text())["cli"]["commit"]

            spec = build_optimize_spec(backend="local", method_output=method)
            self.assertEqual(spec["task_set"], DECLARED_TASK_SET)
            self.assertEqual(spec["engine_commit"], pinned)

            state = run_optimize("optimize-local", store, "local", workspace, 180, method)
            self.assertEqual(state["status"], "completed", state)
            self.assertEqual(state["optimize"]["engine_commit"], pinned)
            saved_spec = json.loads((method / "optimize-spec.json").read_text())
            self.assertEqual(saved_spec["task_set"], DECLARED_TASK_SET)
            self.assertNotIn("api_key", json.dumps(saved_spec).lower())
            report = json.loads((method / "custom-workflow.json").read_text())
            self.assertEqual((report["done"], report["failed"]), (2, 0))
            self.assertEqual(report["pinned_cli_commit"], pinned)
            self.assertGreater(report["execution_count"], 0)

            again = run_optimize("optimize-local", store, "local", workspace, 180, method)
            self.assertTrue(again.get("reused"), again)
            self.assertEqual(len(again["attempts"]), 1)


if __name__ == "__main__":
    unittest.main()
