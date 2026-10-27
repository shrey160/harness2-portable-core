# Run the offline core prototype

Windows is the desktop; Ubuntu WSL2 runs Python and the controller. Docker Desktop supplies the existing Linux engine. No model credentials are needed for these checks.

## This machine

- Ubuntu 24.04.3 LTS / WSL2, Python 3.12.3.
- Docker Desktop 4.91.0 / Linux Engine 29.8.0.
- Ubuntu integration was enabled during implementation. Check Docker Desktop → Settings → Resources → WSL integration if it becomes unavailable.
- Project-scoped uv 0.13.6 is under `/home/shrey31/projects/harness2_portable_core/.tools/bin`.

## From PowerShell

Open this project's folder, then:

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 test
.\scripts\dev.ps1 demo
.\scripts\dev.ps1 reliability
```

`setup` syncs source to WSL, installs isolated environments and builds the Linux image. It downloads source/build dependencies when needed. `test` runs local and Docker integration tests. `reliability` repeats five crash/recover/retry/stop cycles per backend. `demo` creates a new evidence directory, checks both upstream demos, runs custom local/Docker refinement, proves resume and damaged-answer recovery, and tests the complete core inside a container. It makes no model calls.

Use `-Distro` if your Ubuntu distro has a different name. The launcher never changes PowerShell execution policy. If local policy prevents script execution, run the equivalent commands directly inside Ubuntu.

## Directly inside Ubuntu

On this machine the source is:

```bash
task_source=/mnt/c/Shrey_Projs/hackathons/harness2_portable_core
bash "$task_source/scripts/launch.sh" "$task_source" setup
bash "$task_source/scripts/launch.sh" "$task_source" test
bash "$task_source/scripts/launch.sh" "$task_source" demo
```

On another machine, set `task_source` to its actual project location. Setup expects Python 3.12 or 3.13, Git, curl, Docker and Linux access; it is not a WSL or Docker installer. The recorded base-image digest includes the selected Python image; only x86_64 has been tested.

## Source and runtime ownership

The Windows portable-core folder is the authoritative editable source and documentation. The original `harness2_capability_lab` is untouched.

The Linux execution root is `/home/shrey31/projects/harness2_portable_core`:

| Location | Purpose |
|---|---|
| `project/` | One-way execution mirror; `.source-sync.json` records source hashes |
| `project/.venv/` | Portable package plus selected CLI fork |
| `upstream/official/` | Pinned method reference with separate environment |
| `upstream/cli/` | Pinned application base with separate environment |
| `build-context/` | Versioned image build inputs and built wheels |
| `evidence/` | Runs, logs, harness candidates and validation reports |

Edit source in the Windows folder, then use the launcher to sync. The sync refuses to overwrite an execution-mirror file whose recorded hash changed locally. It does not sync Linux dependencies or run results back into source. Use a different `H2_PORTABLE_ROOT` only with a fresh setup.

The upstream revisions are locked in [upstream.lock.json](upstream.lock.json); the Python image is pinned in [image.lock.json](image.lock.json). The selected CLI fork is independent of Google. Its source is not patched. Its package and the official package share the `harness2` import name, so their reference environments stay separate.

## Foreground jobs

Inside Ubuntu:

```bash
cd ~/projects/harness2_portable_core/project
mkdir -p ../sample-input
printf 'example\n' > ../sample-input/input.txt
.venv/bin/h2portable run --id example --store ../job-store --backend docker \
  --image h2portable:offline --workspace ../sample-input --timeout 10 \
  -- python3 -c 'print("finished")'
.venv/bin/h2portable status --id example --store ../job-store
.venv/bin/h2portable stop --id example --store ../job-store
```

Run jobs in a terminal; status/stop can be invoked in another. Repeating a completed, identical job verifies saved artifacts and reuses it. Changes to command, image identity, timeout or input snapshot require a new ID. Ordinary failed attempts can retry with preserved history. Corrupt completed artifacts are explicitly rejected; repair them or use a new ID.

The wrapper owns job lifecycle, not task correctness. The custom fixture separately checks outputs after Harness² selection. There is no frontend, background service or real provider adapter yet.

## Limits to keep visible

- Local execution is for trusted fixtures and inherits the host environment. Generated/untrusted task work belongs in the Docker backend.
- Containers have no network, no credentials passed in, a non-root user, limited resources, a read-only root and one writable task workspace. Evaluator constants and tests are excluded from the image. Docker is not a hardened hostile-code boundary.
- Normal stop, Ctrl+C, timeouts and controller SIGKILL are tested. On status/start/stop, the controller verifies and recovers registered workers, including nested probes, before allowing retries. There is no background sweeper. Unverifiable or legacy identities and engine outages remain pending; never prune unrelated containers. A real VM power cut/daemon restart was not forced.
- Persisted stop verification uses Linux `/proc`; native Windows and macOS-host execution have not passed these tests. Linux outside WSL and ARM64 are also untested.
- Image build dependencies may use network; task execution does not pull missing images. Docker jobs resolve tags to immutable local image IDs before caching.
- Scripted edits establish method/runtime integration, not model intelligence, capability gains, SFT readiness or Meta compatibility.

See [RELIABILITY.md](RELIABILITY.md) for current results and limits. Current scope is core reliability; frontend work is deferred.
