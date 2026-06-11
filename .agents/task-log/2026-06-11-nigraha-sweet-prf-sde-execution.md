# Task: Nigraha/SWEET fixes + PRF 1A + SDE calibration (execution)

- Start: 2026-06-11
- Cadence: tasks 1-3 of a new cycle executed together; full-suite + benchmark
  + live verification run before push (cycle's full-verification obligation
  satisfied in-line).
- Goal: execute `.agents/task-log/handover-2026-06-11-nigraha-sweet-prf-sde.md`
  (user redirected: same agent implements AND verifies+pushes).

## Completed

### Nigraha units fix (Part 1.2/2.x of handover)
- `_tls_depth_flux` conversion verified by controlled probe: depth ladder
  0.0005..0.010 now scores 0.9995/0.9999/0.9994/0.9984/0.9974/0.9924
  (pre-fix: 0.62/0.92/0.51/0.38/0.31/0.19). Depth scalar prints 1-delta.
- Discrimination intact: pure noise 0.0001, sinusoid-as-candidate 0.0000.
  EB (odd/even + secondary) scores 0.83 — by design EBs are killed by the
  odd/even + secondary-eclipse + ModShift gates, not the CNN; benchmark trap
  cases verify.
- Golden fixture regenerated under the corrected units contract (its
  artifact note already said it was a NumPy-path regression golden, Keras
  cross-check pending). New checksum ba602be1..., probability 0.99990.
- `test_nigraha_service_discriminates_across_stellar_context` moved from
  depth 0.02 (saturates at ~0.999 post-fix) to marginal 0.002 (spread 0.19).

### SWEET Robovetter gate (Part 1.1)
- Probe-verified both directions; 2 new regression tests
  (`test_sweet_requires_amplitude_comparable_to_depth`,
  `test_sweet_variability_note_is_info_not_blocking`) plus
  `test_nigraha_depth_features_use_tls_flux_convention` and
  `test_nigraha_scores_deep_and_shallow_planets_in_domain` (weights-gated).

### PRF 1A (Part 3)
- `backend/orbitlab/science/prf_centroid.py` + integration in
  `difference_image_diagnostics` (PSF numbers replace moment numbers in the
  gate-facing keys when both fits succeed; `centroid_method` provenance;
  moments kept as `moment_centroid_*`).
- Design deviations from handover, with reasons:
  - No hard reduced-chi2 rejection gate: covariance is scaled by reduced
    chi2, so model mismatch inflates the uncertainty honestly; a hard gate
    rejected well-localized fits on blended cutouts.
  - OOT fit windowed (`fit_radius=3.5` px) around the target because a
    single-source model on a full cutout containing neighbors is
    mis-specified; difference image stays full-frame (source-isolated by
    construction).
- 4 tests in `backend/tests/test_prf_centroid.py` incl. neighbor-localization
  (>3 sigma onto the neighbor where moments smeared toward the target).

### SDE calibration (Part 4)
- `sde_calibration.py` (classify_population, calibrated_sde_threshold with
  floor semantics + provenance), `scripts/calibrate_sde_thresholds.py`
  (permutation + block-bootstrap nulls, AR(1) red bins, GEV tail fit),
  pipeline wiring (support carries cadence_seconds/baseline_days;
  thresholds payload: tls_sde_threshold_used/sde_population_bin/
  sde_threshold_source/sde_table_version; tls_sde_min retained as floor).
- 4 tests in `backend/tests/test_sde_calibration.py`.
- No table committed yet -> runtime currently identical to before (floor
  everywhere) with explicit `uncalibrated_floor` provenance. Full-grid
  generation is a background compute task; smoke run validates plumbing.

## Verification log
- Fast truth benchmark with Nigraha+SWEET fixes: PASSED
  (`.orbitlab/benchmarks/nigraha-sweet-fix-fast/`).
- Full suite at Nigraha/SWEET point: exit 0. Re-running with PRF+SDE.
- ruff: clean after import-order/datetime.UTC autofixes.
- Pending: smoke table, full-grid table, live round-5 (WASP-126 + L 98-59).

## Deferred
- PRF 1B (mission PRF kernels + WCS catalog-position offset): precision
  upgrade, not semantics; documented as future work in methodology docs.
