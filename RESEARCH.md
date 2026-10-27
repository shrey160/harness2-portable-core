# WSL and Docker feasibility research

Reviewed: 27 October 2026 · Asia/Calcutta  
Evidence: pinned public source review, Microsoft/Docker documentation, and read-only local readiness checks. Two GPT-6 Luna subagents handled bounded upstream-runtime and WSL/Docker research; the parent checked the consequential code and local results.

## Current reliability evidence

[RELIABILITY.md](RELIABILITY.md) records the October 28 core reliability pass. Frontend work is currently deferred. Initial research and first implementation counts below remain historical.

## Subsequent implementation evidence

The initial research below is historical. The runtime has since been installed and tested: [IMPLEMENTATION.md](IMPLEMENTATION.md) records passing WSL/Docker execution, corrected integration and current limitations.

## Findings and confidence

**Recommendation:** WSL2 is a sensible first execution environment for this Linux-oriented project. A Linux Docker image is also a plausible runtime for the deterministic core. The current machine has the needed host facilities, but neither Harness² runtime nor a task container has been executed here. Architectural feasibility is not a compatibility test.

The latest user instruction supersedes the old handoff's native-Windows-first priority. Browser access on other devices is a later service/frontend capability, separate from running the core natively.

## Audited revisions

| Repository | Revision reviewed | Role |
|---|---|---|
| [Official Harness²](https://github.com/google-research/harness2/tree/1cfe254e8d25b15f37048c3730134686abe60335) | 1cfe254e8d25b15f37048c3730134686abe60335; commit dated 14 October 2026 | Method reference, baseline, fallback |
| [Independent Harness² CLI](https://github.com/3ae3ae/harness2-cli/tree/0c811344a4edfe34960b2fc8f286369d7e81fb27) | 0c811344a4edfe34960b2fc8f286369d7e81fb27; commit dated 19 October 2026 | Provisional application base |

Commit SHAs were obtained through GitHub's commit endpoint and key files fetched at those revisions. Both use Apache 2.0; preserve third-party notices separately. No repository has been cloned into this workspace.

## Official implementation: what the code establishes

- [README](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/README.md) prescribes Linux, Python 3.12 and uv. The demo uses deterministic editors with real Python executions and needs no model credentials.
- [pyproject.toml](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/pyproject.toml) permits Python >=3.12,<3.14, declares POSIX and no mandatory runtime dependencies. Render and bridge are extras. Windows Python 3.14 is outside that range.
- [DemoAdapter.execute](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/harness2/demo.py) launches the current Python interpreter with an argument list, captures output, and writes answer/trajectory files. It does not invoke Docker or a cloud model. DemoProposer makes scripted changes; it is not a learned improver.
- [Demo entry point](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/harness2/cli/demo.py) runs the actual scheduling/library path, supports both recursion modes, and writes demo.json.
- [BenchmarkAdapter](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/harness2/core/spec.py) separates task execution, trajectory, deliverables, tree validation and external scoring. RunView carries no score; scoring is documented after selection commits.
- [Proposer](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/harness2/core/proposer.py) uses specific CLI channels and Vertex-oriented environment setup. A model-independent method does not mean a provider-independent implementation.
- [Setup guide](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/docs/SETUP.md) adds benchmark-specific dependencies. WorkBuddy requires Docker; LAB has document tooling. These are not all prerequisites of the core demo.

**Inference:** WSL2 Ubuntu and a Python 3.12 Linux container should accommodate the demo's inspected execution path. Neither is claimed as upstream-certified or locally passed. Native Windows support was not disproved by a reproduced failure; upstream documentation and package metadata target POSIX.

## Why consider the independent CLI

The [fork README](https://github.com/3ae3ae/harness2-cli/blob/0c811344a4edfe34960b2fc8f286369d7e81fb27/README.md) adds user-project tasks, custom commands, JSON output, background status/stop, resumable runs, evaluation and a final project harness. These align with the future frontend/controller.

Its [command substrate](https://github.com/3ae3ae/harness2-cli/blob/0c811344a4edfe34960b2fc8f286369d7e81fb27/harness2/substrate/command.py) has important limits:

| Observed implementation | Consequence |
|---|---|
| CommandSubstrate.run uses shell=True and shlex.quote | POSIX shell semantics suit WSL/Linux; this is not native Windows portability |
| Passed env is copied into the child | Broker/controller must construct a limited environment; inheritance alone is not isolation |
| cost_usd returns 0.0 | A model-backed custom command needs independent accounting |
| read_trajectory clips stream.log | Preserve raw visible events separately for later data use |
| subprocess timeout exists | Process-tree cleanup, Docker cancellation and restart correctness still need tests |

The [configuration guide](https://github.com/3ae3ae/harness2-cli/blob/0c811344a4edfe34960b2fc8f286369d7e81fb27/docs/configuration.md) distinguishes executor from improver/selector/reflector channels. A custom executor does not create a custom improver.

[providers.py](https://github.com/3ae3ae/harness2-cli/blob/0c811344a4edfe34960b2fc8f286369d7e81fb27/harness2/providers.py) supports declared provider families, not a dedicated Meta adapter. OpenCode's compatible route and the Codex Responses route differ. Meta integration needs actual wire-format and tool-loop testing; a successful greeting is inadequate. Source inspection is not account access or API validation.

The fork is the provisional application choice because it avoids rebuilding those controls. The official implementation remains the reference and fallback. Test the fork's narrow required path before committing; do not maintain two production engines.

## Local readiness observations

Checks used Windows PowerShell, followed by the same read-only WSL/Docker queries with sufficient access. Nothing was installed, and Docker/WSL settings were not changed. Querying inside Ubuntu started that previously stopped distro; it was not shut down afterward.

| Probe | Result |
|---|---|
| wsl --version | WSL 2.6.3.0; kernel 6.6.87.2-1 |
| wsl --list --verbose | Ubuntu WSL2 default; docker-desktop WSL2 running |
| Ubuntu /etc/os-release | Ubuntu 24.04.3 LTS |
| Ubuntu uname / Python | x86_64; Python 3.12.3 |
| Ubuntu executable lookup | Git and Docker found; uv not found on checked PATH |
| Windows Docker API | Docker Desktop 4.91.0; Engine 29.8.0; linux/amd64; engine reports 24 CPUs and about 15.2 GiB memory |
| Ubuntu Docker API | CLI available but /var/run/docker.sock not present |

Engine resource visibility is not model-serving capacity or free-memory measurement. The Ubuntu failure suggests missing/unavailable integration or socket configuration; its cause was not proven. Windows engine access does not prove Ubuntu integration. Check Docker Desktop's Ubuntu integration before installing another daemon.

No image was built or pulled. No container, benchmark, or Harness² task was run. No model credentials were inspected and no Meta credits were used.

## WSL and Docker design constraints

Microsoft recommends Linux filesystem storage for Linux-command-line projects. Keep the active checkout and dependencies in WSL, importing selected Windows inputs through a deliberate boundary. Cross-platform path conversion, file case, permissions and line endings remain test cases. [Microsoft filesystem guidance](https://learn.microsoft.com/en-us/windows/wsl/filesystems), [permissions](https://learn.microsoft.com/en-us/windows/wsl/file-permissions)

Docker Desktop supports a WSL2 backend and per-distro integration. Its documented minimum WSL version is 2.1.5, below the installed version. A Docker client in Ubuntu is insufficient if it cannot reach the engine. [Docker WSL backend](https://docs.docker.com/desktop/features/wsl/)

A Windows browser can normally reach WSL-hosted services through localhost. WSL-to-Windows access differs between NAT and mirrored networking; make model endpoint URLs configurable and test actual binding/firewall behavior. Containers have their own localhost; Docker Desktop supplies host.docker.internal for reaching host services. Linux Engine on a separate Linux host needs its own tested configuration. [WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking), [Docker Desktop networking](https://docs.docker.com/desktop/features/networking/networking-how-tos/)

Docker access is powerful: a client can ask the daemon to mount host files and launch privileged workloads. Keep the socket with the trusted controller, never the task worker. An ordinary container shares a kernel and is not a complete boundary for hostile code. This justifies task-scoped mounts and resource limits, without claiming universal sandbox security. [Docker security](https://docs.docker.com/engine/security/), [daemon access](https://docs.docker.com/engine/security/protect-access/)

No nested engine is needed for the scripted demo. A WSL controller can ask Desktop to launch sibling task containers. WorkBuddy's Harbor-based environment and bridge are a later adapter problem; running the entire controller in a container that itself launches containers introduces daemon access and mount translation concerns.

## Open questions for implementation

1. Is Ubuntu integration disabled, or is another socket/context issue responsible?
2. Does each pinned demo pass unchanged in WSL, and does the selected base pass in a Linux image?
3. Can one custom fixture exercise the fork's actual proposal/probe/composition path without external CLI credentials?
4. Does existing resume behavior preserve identities and handle interruption correctly in our chosen usage?
5. Which Meta-compatible agent channel supports the required model and complete tool loop?
6. What minimum usage/budget hooks are needed for a custom executor?
7. What changes are needed on a real Linux host, macOS and ARM64? All remain untested.

The next work is the ordered gated experiment in [prototype.md](prototype.md), not a broader framework survey or a full application build.

