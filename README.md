# WSL-first Harness² core

Updated: 28 October 2026 · Current focus: core reliability; frontend deferred.

The offline execution core runs on Windows through Ubuntu WSL2 with constrained Linux Docker task workers. The independent Harness² CLI supplies the actual optimization method; local adapters supply managed execution, persisted jobs and owned-worker recovery.

**Engine (CORE-002):** the pinned `harness2-cli` engine (`0c81134…`) is vendored under [vendor/harness2-cli/](vendor/harness2-cli/) and declared as a local uv source dependency — see [UPSTREAM.md](UPSTREAM.md) and [upstream.lock.json](upstream.lock.json). No external CLI checkout, home path, or `PYTHONPATH` injection is required. One supported entry point, `h2portable optimize`, runs a bounded real Harness² optimization through the managed job lifecycle.

**Verified (28 Oct 2026, after vendoring):** 51 tests passed (42 baseline + 9 new packaging/optimize tests), plus 10 repeated crash/recover/retry/stop cycles. A fresh isolated install with no upstream CLI checkout present passed all 51 tests and an `optimize` smoke run. Managed Harness² interruption/resume reused completed rollouts. Nested concurrent Docker workers were cleaned up without exposing their controller registry to task containers.

| Document | Purpose |
|---|---|
| [RELIABILITY.md](RELIABILITY.md) | Current results, failure cases, evidence and limits |
| [SETUP.md](SETUP.md) | Windows/WSL commands and runtime layout |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Initial implementation and subsequent reliability update |
| [SESSION_HANDOFF.md](SESSION_HANDOFF.md) | Current scope and next-session instructions |
| [UPSTREAM.md](UPSTREAM.md) | Vendored engine provenance, import procedure, patch policy |
| [prototype.md](prototype.md) | Gated roadmap; frontend remains deferred |
| [RESEARCH.md](RESEARCH.md) | Historical upstream/platform research |

[51-test log](evidence/validation-20261027T214029922053Z/tests.log) · [Validation report](evidence/validation-20261027T214029922053Z/validation.json) · [Crash campaign](evidence/reliability-20261027T214140223919Z/reliability.json)

Earlier evidence (pre-vendoring baseline): [validation-20261027T192235771699Z](evidence/validation-20261027T192235771699Z/validation.json) (42 tests, image `sha256:58f9015f…`). Prior evidence dirs retained. Rebuilds are not byte-identical.

Recovery is evidence-based and fails closed when ownership or cleanup cannot be verified. Other platforms and live model/tool-loop reliability are not yet established. No model calls or credits were used.

The user entered a Meta key locally. Never read, copy, hash or expose .env. Keep all work here and leave harness2_capability_lab unchanged.
