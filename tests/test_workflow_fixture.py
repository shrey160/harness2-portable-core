"""Regression checks for the deterministic custom-workflow fixture."""

from __future__ import annotations

import json
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))  # load the fixture module by path; packages come from the installed environment

from custom_workflow import EXPECTED, _verify_answer, main  # noqa: E402


class WorkflowFixtureCases(unittest.TestCase):
    def test_independent_verifier_rejects_valid_json_with_wrong_total(self) -> None:
        wrong = json.loads(
            '{"records":[{"id":"A-1","amount":"14.25"},'
            '{"id":"A-2","amount":"-20.10"},'
            '{"id":"A-3","amount":"3.85"}],"count":3,"total":"18.10"}'
        )
        self.assertEqual(wrong["count"], EXPECTED["records-1"]["count"])
        with self.assertRaisesRegex(AssertionError, "independent expectation"):
            _verify_answer("records-1", wrong)

    @unittest.skipUnless(os.name == "posix", "requires WSL/Linux")
    def test_resume_and_damaged_selected_answer_recompute(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h2-custom-workflow-") as temp:
            output = Path(temp) / "run"

            def invoke() -> dict:
                with contextlib.redirect_stdout(io.StringIO()):
                    main(["--backend", "local", "--output", str(output)])
                return json.loads(
                    (output / "custom-workflow.json").read_text(encoding="utf-8")
                )

            first = invoke()
            self.assertEqual(first["execution_count"], 16)
            self.assertEqual(first["proposer_fresh_calls"], 14)
            self.assertEqual(first["reflection_fresh_calls"], 2)

            second = invoke()
            self.assertEqual(second["execution_count"], 0)
            self.assertEqual(second["proposer_fresh_calls"], 0)
            self.assertEqual(second["proposer_cached_calls"], 0)
            self.assertEqual(second["reflection_fresh_calls"], 0)
            self.assertEqual(second["reflection_cached_calls"], 0)

            selected_id = second["selected"]["records-1"]["selected_run_id"]
            answer_file = output / "runs" / "executions" / selected_id / "answer.json"
            damaged = dict(EXPECTED["records-1"], total="999.99")
            answer_file.write_text(json.dumps(damaged) + "\n", encoding="utf-8")

            repaired = invoke()
            self.assertEqual(repaired["execution_count"], 1)
            self.assertEqual(repaired["selected"]["records-1"]["selected_output"], EXPECTED["records-1"])
            self.assertEqual(json.loads(answer_file.read_text(encoding="utf-8")), EXPECTED["records-1"])
            self.assertEqual(repaired["proposer_fresh_calls"], 0)
            self.assertEqual(repaired["reflection_fresh_calls"], 0)


if __name__ == "__main__":
    unittest.main()
