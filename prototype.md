# WSL-first Harness² core prototype plan

Updated: 27 October 2026 · Asia/Calcutta  
State: offline implementation validated; see [IMPLEMENTATION.md](IMPLEMENTATION.md) for completed gates and remaining hardening/model work. This document preserves the planned gates.

## Current priority — 28 October 2026

The user explicitly deferred frontend work and prioritized core reliability. See [RELIABILITY.md](RELIABILITY.md) for completed recovery checks, evidence and remaining limits. The later product/UI gates below are historical roadmap items, not the immediate next task.

## What we are building toward

The eventual product accepts a sample-data folder and a recurring goal, clarifies requirements, and builds a reusable task-specific harness through real executions. A later optional run adapts that harness for a supplied smaller executor while keeping model weights fixed. Cloud SAM and Transcribe can remain. A usable frontend follows the core; workflow MCP and curated fine-tuning data follow later.

The immediate milestone is narrower: a reproducible Linux execution core on Windows through WSL2, with an optional Docker Linux worker and inspectable runs. This replaces the old native-Windows-first target. It reduces platform-specific work; it does not establish automatic support for every device.

All new work belongs to this workstream. The sibling harness2_capability_lab, including its archive, is read-only.

## Recommendation and reuse decision

Use Windows as the desktop, Ubuntu on WSL2 as the development/control environment, and Docker Desktop's Linux engine for disposable task workers. Retain a local WSL executor for trusted deterministic fixtures and troubleshooting.

**Provisional application base:** the independent [Harness² CLI](https://github.com/3ae3ae/harness2-cli/tree/0c811344a4edfe34960b2fc8f286369d7e81fb27), revision `0c811344a4edfe34960b2fc8f286369d7e81fb27`. Its custom tasks, command executor, JSON interface, run limits, and stop/resume behavior save implementation work. Those are upstream capabilities to validate, not capabilities already working here.

**Method reference and initial baseline:** [Google Research Harness²](https://github.com/google-research/harness2/tree/1cfe254e8d25b15f37048c3730134686abe60335), revision `1cfe254e8d25b15f37048c3730134686abe60335`. First reproduce its unchanged scripted demo in a separate environment. Its adapter and demo provide a fallback if the fork's integration gate fails.

Keep only one application implementation after the gate. Do not merge both packages into one environment: both import as `harness2`. Keep provenance, Apache 2.0 notices, and a small patch record. The fork is independent of Google.

Timebox base validation to approximately half an engineering day. If the fork fails for a small fixable reason, patch it and retain it. If its task/improver/provider coupling requires a broad rewrite, document the failure and use the official core with one explicit task adapter. Revisit the written decision before implementing a different algorithm.

## What is ready on this machine

Read-only checks established:

| Component | Observed | Implication |
|---|---|---|
| WSL | 2.6.3.0; default Ubuntu uses WSL2 | No new distro is presently needed |
| Ubuntu | 24.04.3 LTS, x86_64, Python 3.12.3, Git found | Suitable starting environment; package readiness still needs checking |
| uv in Ubuntu | Not found on the checked shell PATH | Choose a documented bootstrap; Windows uv is not Linux uv |
| Docker Desktop | 4.91.0; Linux Engine 29.8.0, amd64 responds from Windows | A Linux daemon exists; this is not a container smoke test |
| Docker from Ubuntu | CLI found; /var/run/docker.sock absent | Verify/enable Ubuntu integration before worker tests |
| Windows Python | Discovered at C:/Python314/python.exe | Do not use it for upstream, which requires Python >=3.12,<3.14 |

Initial restricted-session WSL/Docker errors disappeared when the same read-only checks ran with appropriate access. The Ubuntu Docker socket problem remained. Do not infer that Docker is broken globally or install a second daemon to work around it.

## Execution architecture

```text
Windows desktop / future browser frontend
                    |
         controller in Ubuntu WSL2
         - validated job configuration and budgets
         - Harness² propose / probe / compose / lessons
         - executor and improver adapters
         - run manifests, events, candidate versions
                    |
          execution backend contract
             /                  \
 trusted local WSL fixture    Docker Linux task worker
                              input + candidate snapshot
                              task-scoped writable output
                              exit / trace / artifacts
                    |
          independent verifier after freeze
```

The controller owns Docker access and immutable run identities. Workers receive a prepared task directory and candidate harness, not arbitrary host paths. The evaluator and held-out data stay outside actor mounts. Improver sessions also need bounded editable workspaces; sandboxing only the final executor would leave generated helper execution exposed.

The backend contract needs start, poll/wait, cancel, timeout, exit outcome, artifact collection, and backend identity. Wrap existing functions/CLI behavior rather than build a second optimization engine. Normalize completed, failed, timed-out, cancelled, and interrupted outcomes; a zero exit code and artifact existence alone do not prove task correctness.

Keep model/provider transport separate from local/Docker execution. Stage B should change executor profile and create a new harness version, without changing the controller or silently introducing a larger-model fallback.

## Workspace and filesystem policy

Implementation decision: Windows source/docs are authoritative with a guarded one-way execution mirror in WSL; see [SETUP.md](SETUP.md). This replaces the proposed Linux-authoritative source arrangement below. Dependencies and execution still reside on Linux storage.

Keep these planning documents in the current Windows folder. At implementation start establish **one authoritative Linux checkout**, preferably `~/projects/harness2_portable_core`, and record its resolved path here. Create it as a separate project; do not move or copy the original capability-lab folder. Its creation has not happened.

Linux dependencies, Git worktrees, virtual environments, caches, and active run state belong in the WSL filesystem for Linux tools. Avoid developing against /mnt/c as the default. Use a WSL-aware editor or UNC access from Windows. If documents are transferred to the Linux repository, choose an explicit sync/export procedure so two copies cannot silently diverge.

Import explicitly selected Windows samples into a run snapshot; preserve the originals. Represent package paths relative to their root and reject escaping paths/symlinks. Convert Windows paths only at the intake boundary. Test spaces, Unicode, case behavior, line endings, and imported data. Do not share a Windows virtual environment with Linux.

## Ordered implementation gates for the next session

These are proposed work, not executed commands or completed gates.

| Gate | Work | Required evidence |
|---|---|---|
| 0. Establish environment | Verify Ubuntu user, free storage, Python venv/build support, Git, Docker integration and socket access. Bootstrap only the selected Linux tools. Record versions. | Ubuntu can contact the same Linux engine; clean isolated Python 3.12 environment |
| 1. Reproduce method | Check out official pinned revision in an isolated reference environment. Run documented `harness2-demo --output runs/reference --k 1`; inspect both modes and actual output. Then run fork's `harness2 demo` in its own environment, using its help for exact options. | Real subprocess outputs, candidate files, compositions, lessons, demo report; no credentials |
| 2. Commit to base | Run fork custom-task fixture with a deterministic Python command and scripted improver through a narrow test seam. Inspect JSON status and resume behavior. | Custom task reaches the real method, executor and improver; chosen base recorded |
| 3. Reproduce inside Docker | Build a small pinned Python 3.12 Linux image and run the chosen scripted demo with no network at execution time. No Docker daemon inside the image. | Equivalent semantic results in WSL and container; artifacts survive container removal |
| 4. Isolate task execution | Keep controller in WSL; add a Docker executor adapter. Run the same deterministic task via local and container backends. | Comparable outputs, candidate identities, logs, and independent checks; only declared mounts accessible |
| 5. Prove lifecycle | Exercise failure, timeout, cancellation, child processes, restart and conflicting job ownership. | No false success, orphan worker, duplicate completed work, or lost final result |
| 6. Validate provider seam | Mock request/response and tool-call contracts first; then separately authorize/configure a small real Meta experiment and explicit limits. | Real executor and improver tool loops work, usage is captured, limits include retries and in-flight requests |
| 7. Extend product | Add one multimodal template and then the thin frontend using the same job interface. | Folder + goal -> plan -> bounded job -> checked artifact -> fresh-input reuse |

Use the upstream prescribed installation for the official baseline. The reference README includes the render extra; assess whether it is needed before making it a production dependency. Node, an agent CLI, Vertex/gcloud, benchmark datasets, Pandoc, and Poppler are not baseline prerequisites for the scripted demo. Later adapters declare their own dependencies.

The scripted ledger task is an infrastructure fixture, not the hackathon product or evidence of model intelligence. Retain both baseline and changed behavior, and test a plausible incorrect output with an independent verifier. Do not tune against protected final grades.

## Docker sandbox scope

Two distinct things must be proved: the whole deterministic core can execute in a Linux container, and a WSL controller can run task rollouts in disposable Linux containers. The second is the intended development topology. Containerizing everything first would complicate worker launching and host paths.

Use an ordinary OCI Linux container initially; this plan does not require the separate Docker Sandboxes product. Start with non-root execution, explicit CPU/memory/PID limits, a timeout, read-only root where compatible, a temporary writable area, dropped capabilities, no-new-privileges, and only the task mounts. Keep input snapshots read-only and output writable. Pin the built image/digest after validation.

The offline fixture gets no network. Model-backed work later needs explicit endpoint access and a deliberate credential/broker design. Do not assume an ordinary Docker bridge provides hostname-level egress controls. Keep provider keys out of artifacts and evaluation mounts out of workers.

Do not give workers privileged mode, the Docker socket, host PID/network namespaces, or broad host-root mounts. The trusted WSL controller may use the daemon; worker code may not. Containers reduce accidental access but share a kernel and do not establish a hardened boundary for arbitrary hostile code.

WorkBuddy/Harbor is a separate integration: the benchmark runtime needs to create task containers and connect to its bridge. The core demo needs none of that. Defer Harbor adapters, Docker-in-Docker and socket-through-container designs until a chosen task actually requires them.

## Provider and cost gates

A generic custom command is not a complete Meta integration. The fork's improver still selects a supported agent channel. Its command substrate returns zero cost and captures a clipped textual trajectory. Add external normalized usage/cost and raw event capture for any model-backed custom executor.

Verify the actual API format accepted by the chosen agent channel. A provider labeled OpenAI-compatible does not imply both Chat Completions and Responses compatibility or working tool continuation. Prefer the smallest already-supported route that passes a real tool cycle; otherwise add one narrow adapter. No provider choice is considered validated now.

Keep executor and improver model IDs, tool schema, effective configuration, candidate hashes, usage, retries, latency, errors, raw visible events, and truncation markers. This supports later comparison and data research; it is not an SFT-ready export and does not recover hidden reasoning.

No Meta credits are needed for gates 0–5. The reported ~$140 remains unspent by this work. Before gate 6, define a small pilot cap and conservative token/request limits; missing pricing or usage is unknown cost, not free execution.

## Portability and completion criteria

| Target | Initial scope | Current evidence |
|---|---|---|
| Windows x64 + WSL2 Ubuntu | Primary developer and local runtime path | Environment inspected; Harness² untested |
| Linux x64 host | Same Python/contracts and Linux task image | Designed; requires actual host/CI run |
| macOS | Docker-backed route; host-native core assessed separately | Untested |
| ARM64 | Architecture-neutral core where possible, native images where available | Untested; no amd64 parity claim |
| Native Windows Python | Deferred | No compatibility promise |
| Phone/tablet | Later browser client to a reachable service | No native runtime or remote access built |

The core milestone is complete when a clean WSL start, local and Docker execution, preserved method evidence, meaningful failure/lifecycle checks, independent validation, and reproducible setup all pass. Record actual versions and outcomes. Image availability on another OS is not a passing test.

First prove local WSL, then the Docker image, then separate-worker execution. Run targeted tests once they pass; repeat only for a changed behavior or unresolved failure. Add Linux CI when a repository is established, then macOS/ARM checks as resources permit.

## Deliberate deferrals

No frontend build, chosen multimodal domain, smaller-model serving platform, arbitrary workflow generation, universal device support, MCP exporter, training-data pipeline, or fine-tuning is part of this core milestone. Preserve seams for them without adding their infrastructure now.

After the core passes, return to the original product plan: choose one low-dependency SAM and/or Transcribe workflow; expose real jobs and artifacts; run task-harness improvement; then, if a smaller endpoint is supplied, compare original executor + HA, smaller executor + HA, and smaller executor + HB.

See [RESEARCH.md](RESEARCH.md) for source evidence and [SESSION_HANDOFF.md](SESSION_HANDOFF.md) for continuation.

