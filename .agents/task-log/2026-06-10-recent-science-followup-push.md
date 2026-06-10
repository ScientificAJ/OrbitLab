# Task: Recent science follow-up push audit

- Start: 2026-06-10 22:21:18 IST
- Cadence: task 2 of 3
- Goal: inspect the recent uncommitted science follow-up, fix any incomplete
  detail, verify the high-risk behavior, and push only ready repository work.
- Expected verification: diff review, `git diff --check`, focused backend
  regression tests, Ruff, full backend pytest, and preflight.
- Scope note: untracked `.claude/` files are excluded because they are
  unrelated local configuration and are not part of the reviewed science
  follow-up.

## Readiness findings and fixes

- Found and corrected an incomplete TRICERATOPS payload contract: the wrapper
  correctly stopped passing TPF-relative aperture pixels into a different
  coordinate frame, but still reported `aperture_used=true`. It now reports
  `aperture_available` separately and truthfully reports `aperture_used=false`.
- Updated the methodology and regression tests to describe and prove the
  default TRICERATOPS 5x5 `calc_depths` mode.

## Verification

- `git diff --check`: passed.
- Focused science/contract tests: 49 passed.
- Ruff on changed Python files: passed.
- Full backend preflight: 386 passed, 2 existing all-NaN warnings, 99% total
  measured coverage.
- Frontend format check and lint: passed.
- Frontend unit tests: 147 passed.
- Frontend E2E: initial preflight run had one transient missing-toast failure
  after the session state had visibly restored; exact test rerun passed, then
  full rerun passed 25 with 1 intentional live-smoke skip.
- Frontend production build, shell syntax, and Python compile checks: passed.
