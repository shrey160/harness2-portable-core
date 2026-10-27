# Upstream provenance — vendored Harness² engine

Updated: 28 October 2026 · Asia/Calcutta
Task: CORE-002-C2. This file records where the vendored engine came from, how it
was imported, and how it may be changed. The machine-readable pins live in
[upstream.lock.json](upstream.lock.json).

## Pinned revisions (do not silently upgrade)

| Component | Repository | Pinned revision | Role in this project |
|---|---|---|---|
| Application engine | https://github.com/3ae3ae/harness2-cli | `0c811344a4edfe34960b2fc8f286369d7e81fb27` | Vendored under `vendor/harness2-cli/`; the only `harness2` runtime dependency |
| Official method reference | https://github.com/google-research/harness2 | `1cfe254e8d25b15f37048c3730134686abe60335` | Isolated development/test reference only; never a second competing runtime dependency |

The CLI fork is independent of Google. Both projects use the Python import name
`harness2`; only the vendored CLI engine may be active in the application
environment.

## What was vendored

- Location: `vendor/harness2-cli/` in this repository.
- Content: exactly the tracked files of the pinned commit — 174 files,
  including `pyproject.toml` (`harness2-cli` distribution metadata, version
  `0.1.0`), the `harness2/` package (`core/`, `cli/`, `substrate/`, …),
  tracked tests, docs, plugins, and assets.
- Attribution retained verbatim: `LICENSE` (Apache License 2.0), the
  `plugins/harness2-benchmarks/` licenses and `third_party/` LICENSE /
  PROVENANCE files, README, CHANGELOG, and upstream copyright headers.
  No vendored file was edited during import.
- The `harness2` import namespace and the `harness2-cli` distribution
  metadata are intentionally intact. The upstream CLI reads its installed
  distribution metadata; copying Python files without that metadata
  previously caused a container startup failure.

## Import procedure (as performed, 28 Oct 2026)

Source of truth for the import was the existing WSL checkout at the pinned
revision (verified clean before export):

```bash
# in WSL, upstream/cli checkout
git rev-parse HEAD            # == 0c811344a4edfe34960b2fc8f286369d7e81fb27
git status --porcelain --untracked-files=no   # empty (no tracked modifications)
git archive HEAD | tar -x -C <repo>/vendor/harness2-cli
```

`git archive` exports tracked files only. Excluded by construction, and
verified absent after import: `.git/`, virtual environments, `__pycache__`,
`*.pyc`, `*.egg-info`, `build/` debris, credentials / `.env*` files, caches,
and runtime datasets/downloads. No tracked filename matched a secret pattern.

## Verification (observed, not assumed)

- File count: 174 vendored files, matching `git ls-files` at the pin.
- Content: SHA-256 of every vendored file compared against
  `git show HEAD:<path>` for the same path — 174 checked, 0 mismatches,
  0 extra files in the vendor tree.
- `LICENSE` present and headed “Apache License, Version 2.0”;
  `pyproject.toml` declares `name = "harness2-cli"`,
  `requires-python = ">=3.12,<3.14"`, and no mandatory runtime dependencies
  in the audited revision. (An empty Python dependency list is not a fully
  bundled agent runtime: real model-backed channels can still need external
  agent CLIs, credentials, or optional dependencies such as the declared
  `bridge` extra.)

## Patch history

- At import: none. The vendored tree is byte-identical to the pinned commit.
- Policy: keep modifications small and reviewable. Prefer adapter changes in
  `src/h2portable/` over patching vendored upstream code. Any future patch
  to `vendor/harness2-cli/` must be recorded here, in order, with date,
  files touched, reason, and the resulting divergence from the pinned
  commit — and re-verified against the test/reliability suite.

## Updating the pin (explicit, never silent)

1. Choose the new upstream revision deliberately; record why.
2. Re-export with the procedure above into a clean `vendor/harness2-cli/`.
3. Update `upstream.lock.json` and this file in the same change.
4. Re-run the full test suite, Docker build, and crash campaign; save new
   evidence. Prior pass counts do not carry over to a new pin.

## Official reference

The official Google repository at `1cfe254…` remains available only as an
isolated reference environment (currently the WSL `upstream/official/`
checkout). It is not vendored here, is not installed into the application
environment, and must not become a second runtime dependency.
