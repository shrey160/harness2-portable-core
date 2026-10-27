# Core reliability results

Updated: 28 October 2026 · Asia/Calcutta  
Current scope: execution-core reliability. Frontend work is deferred.

The final offline validation passed **51 tests** with no skipped Docker cases (42 pre-vendoring baseline tests + 9 new packaging/optimize tests added by CORE-002), plus **10 repeated crash/recover/retry/stop cycles**: five local and five Docker. This establishes the tested WSL/Docker infrastructure behavior. It does not establish live Meta model/tool-loop reliability.

## Evidence

- [Final validation](evidence/validation-20261027T214029922053Z/validation.json) and [51-test log](evidence/validation-20261027T214029922053Z/tests.log) (post-vendoring, 28 Oct 2026).
- [Crash campaign](evidence/reliability-20261027T214140223919Z/reliability.json): all ten cycles passed.
- [Full validation archive](evidence/validation-20261027T214029922053Z/full-run.zip) and [crash-campaign archive](evidence/reliability-20261027T214140223919Z/full-run.zip).
- Prior runs (superseded links, dirs retained): `evidence/validation-20261027T192235771699Z/` (42 tests, pre-vendoring), `evidence/validation-20261027T184224946461Z/`, `evidence/reliability-20261027T184343983565Z/`.
- Each export includes an export.json containing its archive checksum.

The filenames use UTC timestamps from October 27; the local client date when this report was completed is October 28.

## What changed

Local workers now wait behind a launch gate until their process identity is durable. If registration fails or the controller dies before the gate opens, task code does not start. Records include PID, group, start ticks, Linux boot/PID namespace, and parent controller identity.

Docker intent is recorded before creation, and the exact CID is added before start. Recovery verifies the generated name, CID and ownership labels before collecting visible logs and removing a container.

Trusted local workflow processes inherit a controller-owned registry location. Nested runners register there; task containers receive neither its mount nor environment variable. This lets recovery stop the workflow parent, rescan its registered workers and remove concurrent task containers without trusting files inside their writable task workspaces.

Job status/start/stop reconcile abandoned resources under the existing exclusive job lock. Retries are blocked while cleanup is pending. Normal command completion also drains tracked nested resources before a job can be accepted as completed. Stop uses Linux process-instance handles and validates boot, namespace and start ticks.

Input/state checks reject symlinks, FIFOs and other non-regular inputs, malformed histories and log paths outside the attempt. Credential filenames are excluded from input capture, source synchronization, image contexts and evidence archives. The agent did not open, read, hash or copy the actual .env.

## Tests that matter

| Scenario | Observed result |
|---|---|
| Controller SIGKILL during local work, including a descendant ignoring TERM | Verified owned group stopped; late marker not produced; retry permitted only after cleanup |
| Controller SIGKILL during Docker work | Exact owned CID removed; state remains interrupted rather than successful |
| Trusted workflow with two simultaneous Docker workers | Parent and both workers recovered; registry stayed outside task mounts/environment |
| Actual scripted Harness² loop interrupted mid-probe | Workers recovered; same stable method-output directory resumed; completed rollout record and backend ID unchanged |
| Concurrent status observers, then retry and stop | Five local and five Docker cycles passed with two-attempt histories |
| Docker unavailable, then available | Mocked outage left recovery pending; verified cleanup succeeded on retry |
| PID reuse, changed boot/namespace, foreign container labels | Unverified instances were not signalled/removed; unsafe retries blocked where identity could not be established |
| Corrupt resource/state records or linked log directories | Actionable failure/pending state; no foreign resource scan |
| Storage failure before launch registration | Payload did not run |
| Completed-job artifacts removed or changed | Cached success rejected |
| Independent task verification | Plausible valid JSON with an incorrect total rejected |

Both upstream demos, the custom local/Docker optimization path, zero-work completed resume, damaged-answer recovery and complete-core container execution also passed in the final pipeline.

The scripted teacher keeps the method deterministic for these tests. This is real process/container execution through the actual upstream method, not a real-model capability experiment.

## Reproduce

From the Windows portable-core folder:

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 test
.\scripts\dev.ps1 demo
.\scripts\dev.ps1 reliability
```

The last command performs five crash cycles per backend. The current implementation uses the pinned independent CLI fork and an isolated official reference; neither upstream source has been patched.

Final tested image: sha256:f1e6ebcc0abbb7b92d0ceabc8704155fe655848cb3463b19abb6d77b1ad79866 (fresh isolated rebuild from this repository's context only, 28 Oct 2026; the post-vendoring validation run above used `sha256:99f30541…` from the same wheels-only context — rebuilds are not byte-identical). Previous: `sha256:58f9015f…` (pre-vendoring).

## CORE-002 vendoring update (28 Oct 2026)

The pinned `harness2-cli` engine is now vendored at `vendor/harness2-cli/` (174 tracked files of `0c81134…`, SHA-256 verified against the commit; see [UPSTREAM.md](UPSTREAM.md)) and installed through a declared uv source dependency with a committed `uv.lock`. External CLI checkouts, home-path defaults, and `PYTHONPATH` injection were removed from the fixture, tests, validation script, sync/setup scripts, and Dockerfile; the image now installs project + engine wheels built from this repository only. `h2portable optimize` runs the deterministic declared task adapter through the managed job lifecycle with a persistent method-output directory. Independence proof: a fresh isolated WSL root with **no upstream CLI checkout at all** synced from this repository, passed `uv sync --locked`, imported `harness2` from the vendored tree under a bare environment (`env -i`, no PYTHONPATH), passed all 51 tests, completed an `optimize` smoke run (2 done / 0 failed, 16 executions), and left no managed containers. Exported archives were scanned: no `.env*` files present. One timing-sensitive recovery test (`test_dead_controller_recovers_group_and_allows_new_attempt`) failed once with recovery still `pending` during a full-suite run; it passed standalone and in two subsequent full-suite runs (validation pipeline and isolated root) — recorded here as an observed flake, not hidden.

## Limits and current next work

Recovery is triggered by status/start/stop, not by a permanent background monitor. It covers registered runner resources and local process groups. Legacy runs without identities, changed/unverifiable local groups, unsupported custom Docker wrappers, or unavailable Docker can require operator review; pending recovery blocks a retry rather than guessing ownership.

A full VM power cut or real daemon restart was not performed. Boot changes and transport outages were tested through controlled cases/mocks. Ordinary Docker containers are not a hardened boundary for hostile code.

Only Windows x64 + Ubuntu WSL2 + Docker Desktop Linux amd64 is validated here. Other OS/architectures and live Meta/provider tool loops remain unverified.

Keep the next work on the core: review reproducibility on a clean environment, add representative task coverage, and define/test the model-executor/improver protocol without bringing in a frontend. A user-entered Meta key exists locally but has not been read or used by the agent. No model requests or Meta credits were spent.

