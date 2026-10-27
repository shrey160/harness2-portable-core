# Session handoff — core reliability

Updated: 28 October 2026 · Asia/Calcutta  
State: offline WSL/Docker reliability pass complete. Frontend is explicitly deferred by the user.

## Session-close checkpoint

The user is closing this session. This closeout updates documentation only; do not start new experiments, background jobs or scheduled work from it.

- Last completed baseline (28 Oct 2026, hackathons copy): 42 passing tests and ten passing crash/recover/retry/stop cycles. The actual scripted Harness² workflow also recovered and resumed without repeating its completed rollout. Evidence: `evidence/validation-20261027T192235771699Z/`, `evidence/reliability-20261027T192335280691Z/`; image `sha256:58f9015f…`.
- CORE-002 vendoring completed after that baseline (28 Oct 2026): pinned engine vendored at `vendor/harness2-cli/` (provenance: [UPSTREAM.md](UPSTREAM.md)), declared as a uv source dependency with `uv.lock`, external-checkout/PYTHONPATH coupling removed, `h2portable optimize` entry point added, wheels-only Docker build from this repo, fresh isolated install (no upstream CLI checkout) passed 51/51 tests + optimize smoke, and the suite re-established at 51 tests + 10/10 crash cycles with new evidence `evidence/validation-20261027T214029922053Z/` + `evidence/reliability-20261027T214140223919Z/`; final image `sha256:f1e6ebcc…`. See [RELIABILITY.md](RELIABILITY.md) CORE-002 section, including one recorded timing flake. CORE-002 is committed in this repository in two commits (vendored engine + provenance, then integration/entry point/evidence/docs).
- Last cleanup check (28 Oct 2026) found no managed task containers. Both upstream checkouts had no tracked modifications. No repository was published or pushed.
- The original lab's eleven documents were unchanged at the last integrity check.
- The Meta key has been entered locally; do not ask the user to paste it again, and never inspect .env. Live authentication/model execution is still unverified.
- Keep the next session on the core. Frontend, multimodal product construction, MCP export and training remain deferred.

## Read first

1. [RELIABILITY.md](RELIABILITY.md): current evidence and limits.
2. [SETUP.md](SETUP.md): launch commands and runtime layout.
3. [Final validation](evidence/validation-20261027T192235771699Z/validation.json), [42-test log](evidence/validation-20261027T192235771699Z/tests.log), and [10-cycle crash report](evidence/reliability-20261027T192335280691Z/reliability.json).

The latest user direction is: “No need frontend now, just want to make sure the core works reliably.” Preserve this scope; do not resume UI/domain/MCP/training construction as the next step.

## Boundaries and credentials

Authoritative source/docs:
C:/Shrey_Projs/hackathons/harness2_portable_core.
(Copied here from C:/Shrey_Projs/Recruitements_comp/layer_x_res/harness2_portable_core on 28 Oct 2026; the old copy is stale — do not run its launcher against the shared WSL execution root.)

Linux execution root:
/home/shrey31/projects/harness2_portable_core in Ubuntu WSL2. project/ is an explicit one-way source mirror guarded by .source-sync.json. Edit Windows source, then sync through the launcher; do not silently edit the mirror.

Do not modify, move, rename or delete anything in harness2_capability_lab or its archive. It remains read-only product context.

The user entered only the Meta key in .env after requesting that the agent not read it. **Do not open, read, search, hash or copy .env or other secret environment files.** .env.example is the only exception. Runtime code may load credentials when needed without printing values. The key has not been read/used/validated by the agent. No Meta calls or credits were spent.

## Current implementation

- Method reference: official google-research/harness2 at 1cfe254e8d25b15f37048c3730134686abe60335, separate environment.
- Application base: independent 3ae3ae/harness2-cli at 0c811344a4edfe34960b2fc8f286369d7e81fb27.
- No tracked upstream patches.
- h2portable supplies local/Docker runners, a persisted foreground run/status/stop CLI, input snapshots, artifact integrity and recovery.
- Custom scripted fixture invokes the real fork core directly. A managed version of that workflow was interrupted mid-probe and successfully resumed.
- Fork built-in project/task UI/background controls and final consolidation are not yet the application interface.

Local workers use a durable identity record plus launch gate. Docker intent/name/CID/labels are recorded before execution. A controller-owned registry tracks nested runners outside task mounts. Recovery stops local workflow parents first, then reconciles their registered workers.

status/start/stop acquire the job lock before reconciling abandoned resources. Pending cleanup blocks retries. Resource records, process-instance handles, boot/start/namespace checks and Docker labels prevent guessing at ownership. Normal completion drains registered nested resources as well.

## Evidence from this session

42 tests passed with real Docker cases and no skips. Coverage includes:

- Normal/failing execution, timeout, stop, Ctrl+C, process groups, paths and pre-cancel.
- Controller SIGKILL, local descendants, exact Docker cleanup, and concurrent nested probes.
- Actual Harness² interruption/resume with unchanged previously completed rollout records.
- Concurrent status observers and safe two-attempt retry histories.
- Pending/failed Docker recovery, stale process identities, foreign labels and malformed state.
- Corrupt outputs/logs, linked directories, FIFOs, protected filenames and pre-launch storage failure.
- Independent checks rejecting plausible incorrect outputs.

The full offline pipeline also passed both upstream demos, local/Docker task refinement, zero-work completed resume, damaged-answer recovery and complete-core container execution.

A separate campaign passed five local and five Docker crash/recover/retry/stop cycles. Compact reports and checksum-protected full-run archives are in the evidence directories linked above. Raw Linux paths remain in exported records.

## Reproduce

From the Windows portable-core folder:

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 test
.\scripts\dev.ps1 demo
.\scripts\dev.ps1 reliability
```

Ubuntu 24.04.3 / WSL2 2.6.3.0 / Python 3.12.3; Docker Desktop 4.91.0 / Linux Engine 29.8.0 / amd64. Ubuntu integration is enabled. uv 0.13.6 is project-scoped. Upstream commits, Python base image and hashed Python build dependencies are pinned.

The final tested image ID is recorded in RELIABILITY.md and the validation report. Tasks have no network, Docker socket or provider credentials passed in; they run non-root with resource limits and a read-only root. This is not a hardened hostile-code boundary.

## Remaining work and limits

Current priority stays on the core. Clean-environment reproduction, broader representative task coverage and executor/improver protocol tests are useful next checks. Do not claim live model-agent reliability from scripted tests.

Recovery is triggered by status/start/stop rather than a background sweeper. It covers runner-registered resources; arbitrary tools that bypass those adapters are not automatically tracked. Unverifiable groups, legacy runs without identities, custom Docker wrappers or engine outages can remain pending and need review. Real VM power loss/daemon restart was not forced; boot/outage cases were simulated or mocked.

Only this Windows + WSL2 + Docker Linux amd64 combination is validated. Native Windows, separate Linux hosts, macOS and ARM64 remain untested. No frontend, multimodal application, real Meta adapter, MCP exporter or training dataset is built.

The broader product vision remains read-only context: task-harness creation, then optional smaller-executor adaptation with weights fixed; later MCP and curated training data. It does not override the current reliability-only direction.

## Suggested continuation

Continue from RELIABILITY.md and the saved evidence; do not restart the broad research survey. Keep frontend deferred, the original lab untouched and .env unread.

Recommended next sequence:

1. Review existing results and current source. Repeat the full suite only if code/environment changes or an unresolved concern warrants it. A clean-environment reproduction remains a useful, distinct validation.
2. Define the executor/improver model protocol and inspect the narrow integration seam in the selected CLI fork. Verify current official Meta API/agent documentation before choosing the transport; do not assume a generic compatible endpoint supports the complete tool loop.
3. Test provider failures with controlled responses: timeout, rate limiting, malformed tool calls, retries, interrupted sessions and incomplete usage/cost reporting. Preserve budget and task identities across recovery.
4. Then perform a small bounded real model/tool-loop pilot through application runtime credential loading, without the agent reading .env or emitting secrets. Set request/time/token/spend limits and record actual usage before scaling.

These are core-only checks. Distinguish tested offline infrastructure from unverified live-model behavior, and do not describe scripted traces as fine-tuning-ready data. The earlier approximately $140 credit amount was user-reported; no live balance was queried and no Meta requests were made by this work.
