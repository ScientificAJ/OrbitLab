# Task: Fix ModShift CI provisioning

- Task number: 2 of 3 in the current cadence
- Start: 2026-06-11T22:20:19+05:30
- Goal: make the real sibling-masking ModShift regression test hermetic in
  GitHub Actions while preserving its scientific integration coverage.
- Expected verification: workflow diff review, shell syntax, backend lint,
  focused real-engine test, focused missing-engine diagnostic test, push, and
  GitHub Actions status.

## Plan

- Cache the pinned DAVE checkout/build using the runner platform and pinned
  build-script hash.
- Always run the idempotent pinned build script and verify the executable
  exists before backend tests.
- Make the regression test report engine provisioning failures directly before
  asserting ModShift science results.

## Status

- Implementation complete and ready to push.

## Changes

- Added an `actions/cache@v5` backend-CI step for
  `.orbitlab/external/DAVE`, keyed by runner OS/architecture and the pinned
  build-script hash.
- Added an always-run pinned DAVE build step plus an executable assertion
  before backend lint/tests.
- Added explicit successful-engine status assertions to the sibling-masking
  regression test so missing ModShift reports the provisioning error directly.

## Verification

- `ruff check backend scripts`: passed.
- Focused DAVE/paper-grade test set: 47 passed.
- Existing-checkout `scripts/build_dave_modshift.sh` plus executable check:
  passed.
- Clean-checkout build simulation in `/tmp`: cloned pinned commit
  `aea19a30d987b214fb4c0cf01aa733f127c411b9`, compiled, and produced an
  executable ModShift binary.
- Forced missing-engine focused test: failed at the new explicit status
  assertion and displayed the missing-binary detail; no misleading `KeyError`.
- Workflow YAML parse, `bash -n scripts/build_dave_modshift.sh`,
  `git diff --check`: passed.
- Full CI will run after push; this is task 2 of 3, so the cadence-wide full
  local suite is not due on this task.
