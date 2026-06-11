# Task: Investigate recent CI failure

- Task number: 1 of 3 in the current cadence
- Start: 2026-06-11T22:14:28+05:30
- Goal: identify the root cause of the latest failing GitHub Actions CI run on
  `main` without changing product behavior.
- Expected verification: inspect GitHub Actions jobs and failure logs, trace the
  failing test and implementation locally, and reproduce the focused failure.

## Status

- Investigation complete; no product or CI fix applied pending approval.

## Findings

- Latest failed run: GitHub Actions CI run `27346872370` for commit `c07237d`.
- Only `Backend tests` failed. Frontend, repository hygiene, and CodeQL passed.
- Failure: `test_sibling_tce_masking_unblocks_multiplanet_members` raises
  `KeyError: 'hard_fail'`.
- Root cause: the test calls `run_model_shift` without an explicit binary.
  `run_model_shift` resolves the default executable under
  `.orbitlab/external/DAVE/vetting/modshift`; `.orbitlab/` is gitignored and
  the CI workflow does not run `scripts/build_dave_modshift.sh`.
- In a clean CI checkout, `run_model_shift` correctly returns its engine-failed
  payload, which has `status`, `engine`, `detail`, and `source` but no
  `hard_fail`. The test assumes a successful engine payload and indexes
  `hard_fail`, causing the observed failure.
- The test was introduced by commit `c07237d`; the preceding CI run passed
  because this non-hermetic test did not exist yet.

## Verification

- Local focused test with the existing machine-local ModShift binary: passed.
- Same focused test with `ORBITLAB_DAVE_MODSHIFT` pointed at a missing path:
  reproduced the exact CI `KeyError: 'hard_fail'`.
- Direct probe with the missing path returned:
  `RuntimeError: Official DAVE modshift binary is missing ...`.
- Confirmed the executable is ignored and absent from `git ls-files`.
- Confirmed `.github/workflows/ci.yml` fetches Nigraha artifacts but does not
  provision the pinned DAVE ModShift binary.

## Recommended fix

- Preserve the real scientific integration check by provisioning the pinned
  DAVE ModShift executable in CI before backend tests, ideally with caching.
- Also make the test fail with an explicit engine-availability assertion before
  checking `hard_fail`, so future provisioning regressions report the real
  missing-engine cause instead of a misleading `KeyError`.
