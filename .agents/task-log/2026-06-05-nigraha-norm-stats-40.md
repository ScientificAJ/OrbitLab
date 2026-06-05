# 2026-06-05 — Fix #40: recover Nigraha upstream norm stats (un-saturate TESS CNN)

- Task number: 1 (this body of work); cadence position: 1 of 3.
- Start time: 2026-06-05 (branch fix/nigraha-norm-stats-40 off clean main).
- Goal: properly fix the saturated Nigraha TESS CNN score by recovering the EXACT
  upstream scalar standardization and applying it, superseding the honest-gate
  workaround (commit 203000d). User directive: all work on a branch; merge to main
  only if the result is clearly better than the saturated state.
- Expected verification level: HIGH (science logic, schema version bump, verdict
  fields) -> full backend suite + preflight + live Friday Beta re-run before any
  merge to main.

## Key finding (corrects issue #40 premise)
There is no saved upstream scaler. ExoplanetML/Nigraha @ c4365b41 computes
`(x - median)/std` inline over the catalog population in data/preprocess.py, and
only standardizes the 6 stellar features (Teff, Radius, logg, Mass, lum, rho);
the 5 transit features are in `raw_columns` and stay raw. The "exact upstream
stats" = median/std of those 6 features over the filtered training catalog
(period_info-tces-dl3.csv, dropna'd -> 3015 rows), which is reproducible from
committed upstream data.

## Changes
- scripts/recover_nigraha_norm_stats.py (NEW) — reproduces upstream filtering,
  emits .orbitlab/models/nigraha/norm_stats_global_nodropout_binary.json (gitignored).
- backend/orbitlab/config.py — nigraha_norm_stats_path setting.
- backend/orbitlab/ml/nigraha_adapter.py — load stats (cached, graceful absence),
  standardize the 6 stellar features after imputation; NigrahaTensors gains
  standardized/standardized_features; schema -> v2-standardized.
- backend/orbitlab/ml/nigraha_service.py — gate retained as SAFETY NET; verdict
  gains standardized/standardized_features; caveat reflects fallback nature.
- backend/tests/fixtures/nigraha_golden_model1.json — regenerated (numpy pass with
  standardization; Keras cross-check pending: no docker image/forward script here).
- backend/tests/test_nigraha_integration.py — standardization split test,
  nominal-path test, discrimination test, gate-fallback test.
- backend/tests/test_recover_nigraha_norm_stats.py (NEW) — filtering/stats units.

## Before/after (numpy ensemble, synthetic transit)
- hot giant: 0.3 (sat, logit -2608) -> 0.727 (nominal, logit +1.43)
- cool dwarf: 0.3 (sat, logit -933) -> 0.570 (nominal, logit +0.47)
- solar-like: 0.3 (sat, logit -1690) -> 0.762 (nominal, logit +1.55)
- Cross-candidate spread across stellar contexts: 0.07–0.23 (was ~0 / pinned).

## Verification log
- pytest backend/tests/test_nigraha_integration.py + test_recover_nigraha_norm_stats.py:
  11 passed.
- (pending) full backend suite + preflight + live Friday Beta re-run.
- Merge gate: branch pushed regardless; merge to main only if live re-run shows
  varying probabilities + sound dispositions.
