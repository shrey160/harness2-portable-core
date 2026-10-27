"""One supported optimization entry point over the managed job lifecycle.

``optimize`` starts a bounded, real Harness² Propose-Probe-Compose run (the
vendored engine's sequential method, with its lesson library) through the
existing persisted job wrapper: input snapshots, exclusive ownership,
worker recovery, stop handling, and artifact-integrity checks all come from
:mod:`h2portable.jobs`. The first declared task adapter is the deterministic
custom JSON-records fixture; its executor/improver are scripted so
integration tests need no model endpoint. Fixture expectations and held-out
verifier data stay in the fixture/tests, outside task workspaces and images.

The method-output directory is deliberately outside the job's attempt
workspace: it persists across managed retries so the engine reuses
completed rollouts instead of re-executing them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .execution import resolve_image
from .jobs import JobError, run_job

DECLARED_TASK_SET = "custom-json-records"
BASE_HARNESS = "fixtures/custom_workflow.py:base (scripts/normalize.py)"


def _fixture_path() -> Path:
    candidate = Path(__file__).resolve().parents[2] / "fixtures" / "custom_workflow.py"
    if not candidate.is_file():
        raise JobError(
            "the declared task adapter ships with the project checkout at "
            f"{candidate}; run optimize from the project environment"
        )
    return candidate


def _engine_identity() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    lock = root / "upstream.lock.json"
    try:
        pin = json.loads(lock.read_text(encoding="utf-8"))["cli"]
        return {"engine": "harness2-cli (vendored)", "engine_commit": pin["commit"],
                "engine_source": pin.get("vendored_path", "vendor/harness2-cli")}
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    try:
        import importlib.metadata

        return {"engine": "harness2-cli (installed)",
                "engine_version": importlib.metadata.version("harness2-cli")}
    except Exception as exc:  # pragma: no cover - environment dependent
        raise JobError(f"cannot identify the installed harness2-cli engine: {exc}") from exc


def build_optimize_spec(
    *,
    backend: str,
    method_output: Path,
    image: str | None = None,
    timeout: float = 120.0,
    task_set: str = DECLARED_TASK_SET,
    executor_profile: str = "deterministic-scripted",
    improver_profile: str = "deterministic-scripted",
    k: int = 2,
) -> dict[str, Any]:
    """Public, non-secret identity of one optimization run (no credentials)."""
    if task_set != DECLARED_TASK_SET:
        raise JobError(f"unsupported task set {task_set!r}; declared: {DECLARED_TASK_SET!r}")
    if backend not in {"local", "docker"}:
        raise JobError("backend must be local or docker")
    if k < 1:
        raise JobError("k must be positive")
    spec: dict[str, Any] = {
        "task_set": task_set,
        "base_harness": BASE_HARNESS,
        "executor_profile": executor_profile,
        "improver_profile": improver_profile,
        "backend": backend,
        "timeout": float(timeout),
        "probe_k": k,
        "method_output": str(Path(method_output).expanduser().resolve()),
        **_engine_identity(),
    }
    if backend == "docker":
        if not image:
            raise JobError("Docker backend requires --image")
        try:
            spec["image"] = resolve_image(image)
        except (ValueError, OSError) as exc:
            raise JobError(str(exc)) from exc
    return spec


def optimize_command(spec: dict[str, Any]) -> list[str]:
    command = [sys.executable, str(_fixture_path()),
               "--backend", spec["backend"],
               "--output", spec["method_output"],
               "--k", str(spec["probe_k"])]
    if spec["backend"] == "docker":
        command += ["--image", spec["image"]]
    return command


def run_optimize(
    job_id: str,
    store: Path,
    backend: str,
    workspace: Path,
    timeout: float,
    method_output: Path,
    image: str | None = None,
    task_set: str = DECLARED_TASK_SET,
    executor_profile: str = "deterministic-scripted",
    improver_profile: str = "deterministic-scripted",
    k: int = 2,
) -> dict[str, Any]:
    """Run one bounded optimization through the managed job lifecycle."""
    spec = build_optimize_spec(backend=backend, method_output=method_output, image=image,
                               timeout=timeout, task_set=task_set,
                               executor_profile=executor_profile,
                               improver_profile=improver_profile, k=k)
    output = Path(spec["method_output"])
    output.mkdir(parents=True, exist_ok=True)
    # Snapshot the public configuration next to the persistent method output;
    # it contains identities and limits only, never credential contents.
    (output / "optimize-spec.json").write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    state = run_job(job_id, store, backend, workspace, timeout,
                    optimize_command(spec), image)
    return {**state, "optimize": spec}
