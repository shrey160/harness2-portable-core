# WSL-first Harness² core

Updated: 28 October 2026 · Current focus: core reliability; frontend deferred.

Session closed at the user's request. Resume from [SESSION_HANDOFF.md](SESSION_HANDOFF.md), which records the completed baseline, credential restrictions and next core-only checks.

The offline execution core runs on Windows through Ubuntu WSL2 with constrained Linux Docker task workers. The independent Harness² CLI supplies the actual optimization method; local adapters supply managed execution, persisted jobs and owned-worker recovery.

**Verified:** 42 tests passed, plus 10 repeated crash/recover/retry/stop cycles. Managed Harness² interruption/resume reused completed rollouts. Nested concurrent Docker workers were cleaned up without exposing their controller registry to task containers.

| Document | Purpose |
|---|---|
| [RELIABILITY.md](RELIABILITY.md) | Current results, failure cases, evidence and limits |
| [SETUP.md](SETUP.md) | Windows/WSL commands and runtime layout |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Initial implementation and subsequent reliability update |
| [SESSION_HANDOFF.md](SESSION_HANDOFF.md) | Current scope and next-session instructions |
| [prototype.md](prototype.md) | Gated roadmap; frontend remains deferred |
| [RESEARCH.md](RESEARCH.md) | Historical upstream/platform research |

[42-test log](evidence/validation-20261027T192235771699Z/tests.log) · [Validation report](evidence/validation-20261027T192235771699Z/validation.json) · [Crash campaign](evidence/reliability-20261027T192335280691Z/reliability.json)

Re-validated from the hackathons copy on 28 Oct 2026: same 42-test + 10-cycle results; rebuilt image `sha256:58f9015f…` (rebuilds are not byte-identical). Prior evidence dirs retained.

Recovery is evidence-based and fails closed when ownership or cleanup cannot be verified. Other platforms and live model/tool-loop reliability are not yet established. No model calls or credits were used.

The user entered a Meta key locally. Never read, copy, hash or expose .env. Keep all work here and leave harness2_capability_lab unchanged.
