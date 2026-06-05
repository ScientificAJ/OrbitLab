# Operation Friday Beta — Fix the three follow-ups (Nigraha / depth provenance / period+baseline)

- Task number: 2 of 3 in the current rolling cadence (task 1 = 2026-06-04 live re-run).
- Start time: 2026-06-05 (IST).
- Goal: Implement the approved plan (`fluffy-dazzling-otter.md`) fixing the three
  open Friday Beta findings:
  1. Nigraha TESS ML pinned at 0.3 — supply real stellar context (job → known_target → TIC).
  2. Top-level depth provenance fields null — declare them on TcePayload.
  3. Honor request period bounds (3a) + emit a baseline diagnostic note (3b).
- Expected verification level: HIGH for Fix 1 & 3 (science/ML + data contracts =
  high blast radius) → focused pytest + targeted regression + live API smoke on the
  affected TESS cases; Fix 2 is additive schema. Full preflight on task 3 of cadence.
- Initial state: working tree clean on main, after commit 900d7dc.

## Changes made
- `science/catalog_context.py`: extract Teff/rad/mass/logg/lum from the TIC row into a
  new `tic.stellar` block; added `query_tic_stellar_context()` — a fast, depth-independent
  stellar-only TIC lookup (no neighbor sweep, no NASA archive call) for pre-loop enrichment.
- `science/pipeline.py`:
  - `_effective_stellar_context()` merges job → known_target → TIC stellar params with
    per-field provenance; NO solar default applied here (imputation stays honest in the
    adapter). Resolved once before the candidate loop; TIC stellar lookup runs only for
    TESS, only when something is missing and the known-target table can't fill it, and
    never breaks the run on network failure.
  - ML call now receives the effective stellar values; ML payload gets `stellar_context_source`.
  - `_apply_request_period_window()` honors request min/max period (narrow freely, extend
    within 0.05–120 d safety bounds; grid bounded by profile.max_period_samples regardless),
    returns a replaced profile + `period_window` provenance.
  - `_baseline_period_note()` explains when max_period exceeds baseline/min_transits (the
    honest reason single-sector TOI-700 d is unrecoverable). Added `period_window` and
    `period_window_note` to the result.
- `api/schemas.py`: added top-level `depth_source`/`model_depth_fraction`/
  `measured_depth_fraction` to `TcePayload`; added optional `min_period`/`max_period`
  to `AnalysisJobCreate` with an optional-aware validator.
- `api/main.py`: thread `min_period`/`max_period` into `AnalysisJobRecord`.
- `storage/orm.py` + `storage/database.py`: new nullable `min_period`/`max_period`
  columns + migration entries (mirrors the stellar_* column pattern).
- `worker.py`: pass `request_min_period`/`request_max_period` to the pipeline.

## Verification log
- Focused pytest: 107 passed (followups, nigraha, final_fixes, worker, api_endpoints,
  science_hardening, paper_grade_engines, tce_vetting, model_service, goal_upgrades).
  Added backend/tests/test_friday_beta_followups.py (12 tests) + 2 nigraha tests.
- DEEPER ROOT CAUSE on Finding #2 (Nigraha): not a context gap — the released CNN
  needs standardized scalar features (Rao et al. 2021, MNRAS 502, 2845); OrbitLab fed
  RAW values, saturating the sigmoid to a constant. Golden fixture had encoded the same
  un-normalized pass. We lack upstream median/std constants. User chose "keep stellar
  wiring, gate the score honestly" (no invented normalization). Implemented saturation
  detection (|logit|>=50 -> score_confidence=degenerate_saturated, preprocessing_compatible
  =False, paper-cited caveat) which routes the score to domain_awareness=inconclusive via
  existing OOD logic.
- Live API smoke vs real MAST (paper-grade): re-ran all 3 TESS cases to completion
  (TIC 307210830, TOI-700, TIC 25155310) — all audit `pass`, 0 findings. Plus a direct
  custom-bounds job (min_period=2, max_period=8) proving Fix 3a honoring end-to-end.
  - Fix 1 live proof: ml.stellar_context_source all = tic_catalog (lookup complete);
    ml.score_confidence=degenerate_saturated, preprocessing_compatible=False everywhere.
  - Fix 2 live proof: top-level depth_source + measured_depth_fraction non-null on all TCEs.
  - Fix 3 live proof: period_window honored=true for custom bounds; period_window_note
    =baseline_limited on single-sector TESS (max recoverable ~10.9-12.3 d).
- Reports regenerated (--report-only); manual-visual-review.md updated with the 2026-06-05
  follow-up section (Findings 2 & 3 resolved, Nigraha re-diagnosed + honestly gated).
- (pending) ruff/lint + preflight before push.
