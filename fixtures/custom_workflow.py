"""Run a deterministic, custom-task Harness² workflow through h2portable runners.

From WSL/Linux, with the pinned upstream CLI checkout available, run:

    python /mnt/c/Shrey_Projs/hackathons/harness2_portable_core/fixtures/custom_workflow.py \
      --backend local --output /tmp/h2-custom-local

For Docker, provide an image that is already present on the host:

    python .../custom_workflow.py --backend docker --image python:3.12-slim \
      --output /tmp/h2-custom-docker

The workflow has no model calls. Its proposer edits a deliberately flawed JSON
normalizer, the upstream sequential method probes and composes those edits, the
selector chooses from produced artifacts, and the reflection pass records a lesson.
The controller checks the selected outputs against constants that are independent
of the task files and candidate harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve()
PORTABLE_SRC = HERE.parents[1] / "src"
if str(PORTABLE_SRC) not in sys.path:
    sys.path.insert(0, str(PORTABLE_SRC))

from h2portable.execution import DockerRunner, LocalRunner  # noqa: E402


BASE_SCRIPT = '''import json
import sys
from decimal import Decimal

with open(sys.argv[1], encoding="utf-8") as source:
    records = json.load(source)["records"]
amounts = [Decimal(row["amount"]) for row in records]
total = sum((amount for amount in amounts if amount > 0), Decimal("0"))
normalized = [
    {"id": row["id"], "amount": format(amount, ".2f")}
    for row, amount in zip(records, amounts)
]
print(json.dumps({"records": normalized, "count": len(normalized), "total": format(total, ".2f")},
                 sort_keys=True, separators=(",", ":")))
'''

EXPECTED: dict[str, dict[str, Any]] = {
    "records-1": {
        "records": [
            {"id": "A-1", "amount": "14.25"},
            {"id": "A-2", "amount": "-20.10"},
            {"id": "A-3", "amount": "3.85"},
        ],
        "count": 3,
        "total": "-2.00",
    },
    "records-2": {
        "records": [
            {"id": "B-1", "amount": "-4.50"},
            {"id": "B-2", "amount": "1.25"},
            {"id": "B-3", "amount": "2.25"},
        ],
        "count": 3,
        "total": "-1.00",
    },
}


class CustomJSONAdapter:
    """A two-task benchmark adapter that delegates commands to h2portable."""

    def __init__(self, root: Path, runner: LocalRunner | DockerRunner, backend: str):
        from harness2.core import tree
        from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec
        from harness2.substrate.opencode import OpencodeSubstrate

        self.root = root
        self.runner = runner
        self.backend = backend
        self.substrate = OpencodeSubstrate()
        channel = ChannelSpec("opencode", "local/custom-fixture")
        self.spec = BenchSpec(
            name="custom_json_records",
            runs_root=root / "runs",
            install_mode="workspace_config",
            prompts=BenchPrompts(
                work="normalize signed amount records into canonical JSON",
                domain_word="data-cleaning practice",
                yardstick="Preserve every signed amount and produce a stable canonical JSON artifact.",
                deliverable_word="canonical JSON file",
                domain_guidance="Amounts are decimal strings and may be positive or negative.",
                selection_checks="Confirm the normalized records preserve their signs.",
            ),
            channels={"proposer": channel, "selector": channel},
            leak_globs=("reference_answer.json",),
        )
        self.execution_count = 0
        self.records_by_run: dict[str, dict[str, Any]] = {}
        self._record_lock = threading.Lock()

        base = {name: "" for name in self.substrate.surface().always_on}
        base["systemprompt.md"] = "Run scripts/normalize.py on inputs/records.json.\n"
        base["scripts/normalize.py"] = BASE_SCRIPT
        if self.base_harness().exists():
            actual = tree.read_tree(self.substrate.surface(), self.base_harness())
            if actual != base:
                raise RuntimeError(
                    "the fixture base harness differs from its pinned starting tree; "
                    "preserving it instead of overwriting it"
                )
        else:
            tree.write_tree(self.substrate.surface(), base, self.base_harness(), stubs=False)

        inputs = {
            "records-1": [
                {"id": "A-1", "amount": "14.25"},
                {"id": "A-2", "amount": "-20.10"},
                {"id": "A-3", "amount": "3.85"},
            ],
            "records-2": [
                {"id": "B-1", "amount": "-4.50"},
                {"id": "B-2", "amount": "1.25"},
                {"id": "B-3", "amount": "2.25"},
            ],
        }
        for task_id, records in inputs.items():
            source = self.task_files(task_id)
            source.mkdir(parents=True, exist_ok=True)
            input_file = source / "records.json"
            if not input_file.exists():
                input_file.write_text(
                    json.dumps({"records": records}, indent=2) + "\n", encoding="utf-8"
                )

        execution_root = self.spec.runs_root / "executions"
        for record_path in execution_root.rglob("execution.json"):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("task") in EXPECTED:
                self.records_by_run[
                    record_path.parent.relative_to(execution_root).as_posix()
                ] = record

    def tasks(self, split: str = "all") -> list[str]:
        del split
        return list(EXPECTED)

    def domain_of(self, task_id: str) -> str:
        self._check_task(task_id)
        return "data-cleaning"

    def task_prompt(self, task_id: str) -> str:
        self._check_task(task_id)
        return (
            "Read inputs/records.json. Preserve record ids, normalize each amount to two "
            "decimal places, and write canonical JSON to stdout with records, count, and total."
        )

    def task_files(self, task_id: str) -> Path:
        self._check_task(task_id)
        return self.root / "sources" / task_id

    def base_harness(self) -> Path:
        return self.root / "base"

    def validate_tree(self, harness: dict[str, str]) -> None:
        if "scripts/normalize.py" not in harness:
            raise ValueError("The custom local executor requires scripts/normalize.py")

    def execute(
        self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None
    ) -> Path:
        from harness2.core import runmark

        self._check_task(task_id)
        run_dir = self.spec.runs_root / "executions" / run_id
        duration = float(timeout or 10)
        identity = self._execution_identity(task_id, harness_dir, duration)
        marker_dir = run_dir / "fixture_completion"
        if self._execution_intact(run_dir, run_id, harness_dir, identity):
            record = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
            with self._record_lock:
                self.records_by_run[run_id] = record
            return run_dir

        self.execution_count += 1
        workspace = run_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "scripts").mkdir(exist_ok=True)
        (workspace / "inputs").mkdir(exist_ok=True)
        script = (harness_dir or self.base_harness()) / "scripts" / "normalize.py"
        (run_dir / "answer.json").unlink(missing_ok=True)
        shutil.copy2(script, workspace / "scripts" / "normalize.py")
        shutil.copy2(self.task_files(task_id) / "records.json", workspace / "inputs" / "records.json")

        result = self.runner.run(
            ["python3", "scripts/normalize.py", "inputs/records.json"],
            workspace=workspace,
            output_dir=run_dir / "execution_logs",
            timeout=duration,
        )
        answer: dict[str, Any] | None = None
        if result.outcome == "completed" and result.returncode == 0:
            raw = Path(result.stdout_file).read_text(encoding="utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                answer = parsed
                (run_dir / "answer.json").write_text(raw, encoding="utf-8")

        record = {
            "task": task_id,
            "backend_requested": self.backend,
            "used_base_harness": harness_dir is None,
            "harness_dir": str(harness_dir.resolve()) if harness_dir is not None else None,
            "identity": identity,
            "answer": answer,
            "execution": result.to_dict(),
        }
        (run_dir / "execution.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (run_dir / "trajectory.md").write_text(
            self.trajectory(run_dir, obs_trunc=self.spec.obs_trunc), encoding="utf-8"
        )
        with self._record_lock:
            self.records_by_run[run_id] = record
        if self._successful_record(run_dir, record):
            runmark.mark_complete(
                marker_dir,
                run_id=run_id,
                harness_dir=harness_dir,
                extra={"identity_sha256": identity["sha256"]},
            )
        return run_dir

    def _execution_identity(
        self, task_id: str, harness_dir: Path | None, timeout: float
    ) -> dict[str, Any]:
        from harness2.core import runmark

        script = (harness_dir or self.base_harness()) / "scripts" / "normalize.py"
        input_file = self.task_files(task_id) / "records.json"
        identity: dict[str, Any] = {
            "task": task_id,
            "backend": getattr(self.runner, "backend", self.backend),
            "image": getattr(self.runner, "image", None),
            "command": ["python3", "scripts/normalize.py", "inputs/records.json"],
            "timeout": timeout,
            "harness_fingerprint": runmark.fingerprint(harness_dir),
            "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "input_sha256": hashlib.sha256(input_file.read_bytes()).hexdigest(),
        }
        identity["sha256"] = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return identity

    def _successful_record(self, run_dir: Path, record: dict[str, Any]) -> bool:
        execution = record.get("execution") or {}
        answer_file = run_dir / "answer.json"
        if (
            execution.get("outcome") != "completed"
            or execution.get("returncode") != 0
            or not answer_file.is_file()
            or not (run_dir / "trajectory.md").is_file()
            or not record.get("answer")
        ):
            return False
        try:
            if json.loads(answer_file.read_text(encoding="utf-8")) != record["answer"]:
                return False
            stdout_path = Path(execution["stdout_file"])
            stderr_path = Path(execution["stderr_file"])
            if not stdout_path.is_file() or not stderr_path.is_file():
                return False
            if json.loads(stdout_path.read_text(encoding="utf-8")) != record["answer"]:
                return False
            if (run_dir / "trajectory.md").read_text(encoding="utf-8") != self.trajectory(
                run_dir, obs_trunc=self.spec.obs_trunc
            ):
                return False
        except (OSError, KeyError, json.JSONDecodeError):
            return False
        return True

    def _execution_intact(
        self,
        run_dir: Path,
        run_id: str,
        harness_dir: Path | None,
        identity: dict[str, Any],
    ) -> bool:
        from harness2.core import runmark

        marker_dir = run_dir / "fixture_completion"
        marker = runmark.read_mark(marker_dir)
        if (
            not marker
            or not runmark.is_complete(marker_dir, harness_dir=harness_dir)
            or marker.get("run_id") != run_id
            or marker.get("identity_sha256") != identity["sha256"]
        ):
            return False
        try:
            record = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return record.get("identity") == identity and self._successful_record(run_dir, record)

    def artifacts_intact(self, run_dir: Path) -> bool:
        """Make upstream resume reject damaged outputs or stale backend/input/harness state."""
        try:
            record = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
            task_id = record["task"]
            raw_harness = record.get("harness_dir")
            harness_dir = Path(raw_harness) if raw_harness else None
            timeout = float(record["identity"]["timeout"])
            identity = self._execution_identity(task_id, harness_dir, timeout)
            run_id = run_dir.relative_to(self.spec.runs_root / "executions").as_posix()
            return self._execution_intact(run_dir, run_id, harness_dir, identity)
        except (KeyError, OSError, TypeError, ValueError):
            return False

    def delivered(self, run_dir: Path) -> bool:
        return (run_dir / "answer.json").is_file()

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        del obs_trunc
        info = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
        exec_info = info["execution"]
        stdout = Path(exec_info["stdout_file"]).read_text(encoding="utf-8")
        stderr = Path(exec_info["stderr_file"]).read_text(encoding="utf-8")
        return (
            "[ACTION] Run scripts/normalize.py on inputs/records.json through "
            f"{exec_info['backend']}\n[OBSERVATION]\n{stdout}"
            + (f"\n[ERROR]\n{stderr}" if stderr else "")
        )

    def deliverable_text(self, run_dir: Path) -> str:
        return (run_dir / "answer.json").read_text(encoding="utf-8")

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        return {"answer.json": self.deliverable_text(run_dir)}

    def score(self, run_dir: Path, task_id: str) -> None:
        # The benchmark controller verifies after the upstream method returns; no
        # correctness oracle is exposed to the method or to the selector.
        del run_dir, task_id
        return None

    @staticmethod
    def _check_task(task_id: str) -> None:
        if task_id not in EXPECTED:
            raise KeyError(f"unknown task: {task_id}")


class ScriptedProposer:
    """Deterministic editor/selector for the pinned upstream Proposer protocol."""

    def __init__(self, spec: Any, audit_dir: Path):
        from harness2.core.proposer import Proposer

        self._delegate = Proposer(spec, audit_dir=audit_dir)
        self.spec = self._delegate.spec
        self._calls = self._delegate._calls

    def call(self, *args: Any, **kwargs: Any):
        # Keep the real Proposer.call path (context copy, harvest, audit record),
        # while replacing only the external model subprocess.
        self._delegate._opencode = self._opencode
        return self._delegate.call(*args, **kwargs)

    @staticmethod
    def _opencode(cwd: Path, mission: str, system: str, wall: int):
        del mission, system, wall
        context = cwd / "context"
        harness_script = context / "harness" / "scripts" / "normalize.py"

        adoption = context / "adoption.json"
        if adoption.is_file():
            changed = harness_script.read_text(encoding="utf-8") != (
                context / "base_harness" / "scripts" / "normalize.py"
            ).read_text(encoding="utf-8")
            text = (
                "<edits>\ncomponent: scripts/normalize.py\n"
                "change: removed the positive-only amount filter\n"
                "observed: both signed records were preserved in the probe output\n"
                f"verdict: {'helped' if changed else 'no observed effect'}\n</edits>\n"
                "<experience>\ncue: A JSON amount list can contain credits and debits\n"
                "lesson: Sum every signed Decimal when producing the total.\n"
                "evidence: The selected probe retained the negative records and its total "
                "matched the independent task calculation.\n"
                "confidence: high\n</experience>"
            )
            return text, 0.0, ""

        candidates = context / "candidates"
        if candidates.is_dir():
            source = json.loads((context / "source" / "records.json").read_text(encoding="utf-8"))
            expected = sum(
                (Decimal(row["amount"]) for row in source["records"]), Decimal("0")
            )
            chosen = None
            for path in sorted(candidates.glob("*.md")):
                try:
                    body = path.read_text(encoding="utf-8").split("-->\n", 1)[1]
                    output = json.loads(body)
                except (IndexError, json.JSONDecodeError):
                    continue
                if output.get("total") == format(expected, ".2f"):
                    chosen = path.stem
                    break
            if chosen is None:
                chosen = sorted(candidates.glob("*.md"))[0].stem
            return f"<why>The normalized signed total matches the source records.</why>\n```choice\n{chosen}\n```", 0.0, ""

        pool = context / "pool"
        if pool.is_dir():
            for candidate_script in sorted(pool.glob("*/harness/scripts/normalize.py")):
                text = candidate_script.read_text(encoding="utf-8")
                if "if amount > 0" not in text:
                    harness_script.write_text(text, encoding="utf-8")
                    break

        # First round changes the intentionally defective base. Later rounds retain
        # that repair or copy the same repair from a probed pool candidate.
        current = harness_script.read_text(encoding="utf-8")
        repaired = current.replace(" if amount > 0", "")
        harness_script.write_text(repaired, encoding="utf-8")
        return (
            "<notes>Keep positive and negative Decimal amounts when calculating the total.</notes>",
            0.0,
            "",
        )


def _add_upstream_to_path(path: Path) -> None:
    if not path.is_dir() or not (path / "harness2" / "core" / "schedule.py").is_file():
        raise FileNotFoundError(
            f"pinned Harness² CLI package not found under {path}; pass --upstream-cli"
        )
    sys.path.insert(0, str(path.resolve()))


def _verify_answer(task_id: str, answer: Any) -> None:
    """Compare parsed output to the controller's independent exact answer."""
    expected = EXPECTED[task_id]
    if answer != expected:
        raise AssertionError(
            f"selected output for {task_id} differs from independent expectation: "
            f"expected {expected!r}, got {answer!r}"
        )


def _verify(adapter: CustomJSONAdapter, result: dict[str, Any], backend: str) -> dict[str, Any]:
    if result["failed"] != 0 or result["done"] != len(EXPECTED):
        raise AssertionError(f"upstream workflow did not complete both tasks: {result}")

    selected: dict[str, Any] = {}
    summaries = list(adapter.spec.runs_root.rglob("summary.json"))
    for task_id, expected in EXPECTED.items():
        matching = []
        for summary_path in summaries:
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if summary.get("task_id") == task_id:
                selection = summary.get("selections", {}).get("seq", {})
                if selection.get("chosen_run_id"):
                    matching.append(selection)
        if not matching:
            raise AssertionError(f"no upstream selected run recorded for {task_id}")
        run_id = matching[-1]["chosen_run_id"]
        record = adapter.records_by_run.get(run_id)
        if record is None:
            raise AssertionError(f"selected run {run_id} was not executed by this fixture")
        if record["execution"]["backend"] != ("local-posix" if backend == "local" else "docker-cli"):
            raise AssertionError(f"selected run used an unexpected backend: {record}")
        if record["execution"]["outcome"] != "completed":
            raise AssertionError(f"selected run for {task_id} did not complete: {record}")
        _verify_answer(task_id, record["answer"])

        task_records = [r for r in adapter.records_by_run.values() if r["task"] == task_id]
        if not any(r["used_base_harness"] and r["answer"] != expected for r in task_records):
            raise AssertionError(f"the deliberately flawed base did not fail for {task_id}")
        selected[task_id] = {
            "selected_run_id": run_id,
            "selected_output": record["answer"],
            "backend": record["execution"]["backend"],
            "base_was_wrong": True,
        }
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("local", "docker"), default="local")
    parser.add_argument("--image", default="python:3.12-slim", help="existing image for --backend docker")
    parser.add_argument("--output", type=Path, default=Path("runs/custom-workflow"))
    parser.add_argument(
        "--upstream-cli",
        type=Path,
        default=Path(
            os.environ.get(
                "H2_UPSTREAM_CLI",
                str(Path.home() / "projects" / "harness2_portable_core" / "upstream" / "cli"),
            )
        ),
    )
    args = parser.parse_args(argv)
    _add_upstream_to_path(args.upstream_cli.expanduser())

    from harness2.core.schedule import run_domain
    from harness2.core.spec import ChannelSpec

    root = args.output.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.backend == "local":
        runner = LocalRunner()
    else:
        from h2portable.execution import resolve_image

        runner = DockerRunner(image=resolve_image(args.image))
    adapter = CustomJSONAdapter(root, runner, args.backend)
    proposer = ScriptedProposer(
        ChannelSpec("opencode", "local/custom-fixture"), root / "proposer_audit"
    )
    reflector = ScriptedProposer(
        ChannelSpec("opencode", "local/custom-fixture-reflection"), root / "reflector_audit"
    )
    result = run_domain(
        "data-cleaning",
        adapter.tasks(),
        2,
        adapter=adapter,
        prop=proposer,
        runs_root=adapter.spec.runs_root,
        library_root=root / "library" / "k2",
        modes=("seq",),
        reflector_prop=reflector,
    )
    selected = _verify(adapter, result, args.backend)
    proposer_fresh = sum(not reply.cached for reply in proposer._calls)
    proposer_cached = sum(reply.cached for reply in proposer._calls)
    reflection_fresh = sum(not reply.cached for reply in reflector._calls)
    reflection_cached = sum(reply.cached for reply in reflector._calls)
    report = {
        "workflow": "custom-json-record-normalization",
        "backend": args.backend,
        "pinned_cli_commit": "0c811344a4edfe34960b2fc8f286369d7e81fb27",
        "done": result["done"],
        "failed": result["failed"],
        "execution_count": adapter.execution_count,
        "image": getattr(runner, "image", None),
        "proposer_calls": len(proposer._calls),
        "proposer_fresh_calls": proposer_fresh,
        "proposer_cached_calls": proposer_cached,
        "reflection_calls": len(reflector._calls),
        "reflection_fresh_calls": reflection_fresh,
        "reflection_cached_calls": reflection_cached,
        "selected": selected,
    }
    report_path = root / "custom-workflow.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
