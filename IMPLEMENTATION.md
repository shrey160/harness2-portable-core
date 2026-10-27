# Offline core implementation and results

Updated: 27 October 2026 · Asia/Calcutta  
State: initial implementation snapshot below; the subsequent [reliability pass](RELIABILITY.md) supersedes its 27-test baseline and hard-crash limitation. Current focus is core reliability, with frontend deferred.

## What now works

The official Harness² reference and the independent CLI fork run unchanged inside Ubuntu WSL2, in separate Python environments. The fork is the selected base for the next integration step. Our custom adapter invokes its actual scheduling, proposal/probe/composition, selection, reflection and lesson-library machinery.

A small h2portable package adds local-process and Docker execution plus a persisted foreground job CLI. A two-task JSON-normalization fixture exercises the real method through either backend. Its deliberately flawed base omits negative amounts; scripted edits repair it. The controller independently checks exact records, counts and totals after selection. This establishes infrastructure integration, not model intelligence or measured capability gains.

The custom fixture calls the fork core directly. It does not yet wire the fork's built-in project-task CLI, background runner, final-project consolidation, or a model-backed main agent into the new application. The new foreground job wrapper is our code; the optimization engine is upstream.

## Saved evidence

- [Final validation report](evidence/validation-20261027T174912734324Z/validation.json)
- [27-test log](evidence/validation-20261027T174912734324Z/tests.log)
- [Compressed full run](evidence/validation-20261027T174912734324Z/full-run.zip)
- [Archive checksum and export record](evidence/validation-20261027T174912734324Z/export.json)

The raw Linux evidence remains under /home/shrey31/projects/harness2_portable_core/evidence/validation-20261027T174912734324Z. Exported raw records retain original absolute Linux references; archive members use relative paths. An earlier successful raw export and failed intermediate runs are historical evidence, not the final result.

| Check | Observed result |
|---|---|
| Official demo, k=1, both recursion modes | 2 tasks; 14 real executions; 16 scripted editor sessions; zero failures |
| Fork demo, same setup | Same counts; zero failures |
| Custom local workflow, sequential k=2 | 2 tasks; 16 executions; 14 proposer and 2 reflection sessions |
| Custom Docker workflow, same task family | Same counts and exact selected JSON outputs |
| Completed custom workflow resumed | 0 executions and 0 editor/reflection calls, for both backends |
| Selected answer deliberately corrupted | Exactly 1 execution reran; expected output restored |
| Entire fork demo in Linux container | Both modes completed with persistent artifacts and no task network |
| Persisted Docker job | Completed, then reused without another attempt |
| Project tests | 27 passed, including real Docker cases; no skipped tests in final run |
| Worker cleanup after final validation | No containers with the project's managed label remained |
| Upstream source | No tracked modifications in either checkout |

The 27 tests cover execution results, streams, timeout, cancellation, process groups, Unicode/space paths, pre-cancel, job ownership, stop, Ctrl+C, interrupted state, artifact corruption, actual Docker restrictions, the independent verifier, workflow resume/recovery, and two cleanup failure races. Five upstream workflow tests also passed separately during base validation.

## Implementation map

| File | Responsibility |
|---|---|
| [execution.py](src/h2portable/execution.py) | Local process groups, constrained Docker workers, normalized results/logs, immutable image lookup |
| [jobs.py](src/h2portable/jobs.py) | Input snapshots, content identities, exclusive ownership, atomic job state, attempt history, artifact-integrity checks |
| [cli.py](src/h2portable/cli.py) | Foreground run/status/stop with JSON responses |
| [custom_workflow.py](fixtures/custom_workflow.py) | Scripted custom adapter and independent controller-side expectations |
| [Dockerfile](Dockerfile) | Python Linux runtime with installed pinned fork and portable package |
| [prepare_wsl.py](scripts/prepare_wsl.py) | Guarded one-way source sync, separate upstream environments and image preparation |
| [dev.ps1](scripts/dev.ps1) | Windows entry point into Ubuntu |
| [validate_core.py](scripts/validate_core.py) | Reproducible offline evidence pipeline |

Source commits are locked in [upstream.lock.json](upstream.lock.json). The base image is pinned in [image.lock.json](image.lock.json). [Build constraints](build-constraints.txt) pin setuptools 84.2.1, wheel 0.48.0 and packaging 26.3 with hashes. Wheel builds enforce those hashes. Runtime packages have no mandatory external Python dependencies. This is not a claim of byte-for-byte identical image builds.

Final tested task image ID: sha256:5d1f6d363c51fc0bebd6d0408f5f2b570cfaf58a63099eadb7a6377b5310b92a. Jobs and custom Docker fixtures resolve the chosen tag to a local immutable ID; execution never pulls a missing image.

## Environment and operational changes

Ubuntu 24.04.3 LTS on WSL2 uses Python 3.12.3. Docker Desktop 4.91.0 provides Linux Engine 29.8.0 on amd64. Enabled Ubuntu's Docker Desktop integration and applied its restart; installed uv 0.13.6 only in the prototype tooling directory; cloned the pinned source revisions and created isolated environments.

The Windows portable-core folder is authoritative source and documentation. An explicit one-way mirror under /home/shrey31/projects/harness2_portable_core/project provides Linux execution. This refines the earlier proposed Linux-authoritative checkout to fit the shared desktop workspace. Dependencies, worktrees/builds and active runs stay in Linux storage. Mirror edits are detected before synchronization.

Nothing was installed into native Windows Python. No Meta requests or credits were used. The user subsequently entered a Meta key locally; the agent must not read .env, and the key has not been used or validated.

## Boundaries and remaining work

**Subsequent reliability update:** durable worker identities, a launch gate, protected nested-worker registration and verified abandoned-worker cleanup are now implemented and tested. Status/start/stop reconcile registered resources and block retries when cleanup is pending. See [RELIABILITY.md](RELIABILITY.md) for the 42-test and ten-cycle evidence plus the remaining limitations.

Local execution is for trusted fixtures and inherits the host environment. Docker workers have no network, provider credentials or Docker socket; they run as non-root with resource limits, a read-only root and task-scoped writable storage. Independent fixture constants/tests are excluded from the image. These settings do not establish a hostile-code security boundary.

Only Windows x64 + Ubuntu WSL2 + Docker Desktop Linux amd64 was tested. Linux hosts, macOS, ARM64, native Windows Python and phone/tablet access remain untested or unimplemented.

There is no real model executor/improver adapter, provider usage accounting, SAM/Transcribe workflow, frontend, MCP exporter or training dataset. A custom command's upstream zero-cost report must never become billing evidence for later model work. Scripted traces are not SFT-ready data.

Current next work stays on core reliability and executor/improver protocol validation. Frontend and multimodal product construction are deferred by the user. Do not infer live model reliability from offline scripted tests; preserve credential privacy and independent evaluation.

## How to run

See [SETUP.md](SETUP.md). From this folder in PowerShell:

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 test
.\scripts\dev.ps1 demo
```

Upstream method and demo patterns originate from Google Research Harness²; the CLI fork is independent. Preserve their Apache 2.0 licenses/notices. No repository has been published or pushed by this work.

