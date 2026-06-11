# OrbitLab Accuracy Playbook

Accuracy claims must name their denominator and preserve the distinction
between signal recovery, promotion, false-positive rejection, and missing
evidence.

## Predict

Before a run, record expected behavior for each case:

- **Known/injected planet**: recover the period or documented alias, preserve it
  in the TCE ledger, avoid evidence-against hard failures, and produce
  physically plausible radius when stellar context is available. Check
  `sde_population_bin` — if the bin is deferred (red-noise), the fallback SDE
  floor applies, not a calibrated tail fit.
- **Eclipsing binary**: odd/even, secondary, or official vetting evidence should
  reject it.
- **Noise/scrambled control**: must not promote.
- **Missing required engine**: must block paper promotion without labeling the
  signal itself false.
- **Multi-planet system**: sibling masking should remove co-transit cadences for
  each secondary candidate. `sibling_signals_masked > 0` is expected; zero is a
  warning if sibling periods are known.
- **Off-target contamination**: PRF centroid + WCS-projected neighbor indictment
  should show centroid displacement; `centroid_significance ≥ 3.0` is a hard-fail.

## Run

```bash
# Synthetic benchmark (no live API needed)
python scripts/run_orbitlab_science_benchmark.py --mode fast
python scripts/run_orbitlab_science_benchmark.py --mode deep
python scripts/run_orbitlab_science_benchmark.py --mode paper

# Live truth run against NASA golden targets
python scripts/live_planet_verification.py

# System health and dependency check
scripts/preflight.sh

# Single-target live API probe (deterministic product)
python .claude/skills/orbitlab-scientist/scripts/api_probe.py \
  --target "L 98-59" \
  --mission TESS \
  --product-substring s0002-0000000307210830-0121 \
  --mode paper \
  --output .orbitlab/benchmarks/api-probe-l98.json
```

Write each benchmark to a **new named output directory**. Do not overwrite the
baseline needed for before/after comparison.

## SDE Calibration Investigation Path

When a known planet is rejected by the SDE gate (`paper_tls_sde` hard fail):

1. Inspect `sde_population_bin` in the result — determines which row of
   `backend/orbitlab/science/sde_calibration.toml` was applied.
2. Inspect `sde_threshold_source`: `"calibrated"` means GEV tail fit was used;
   `"floor"` means the bin is deferred (red-noise) and the fallback
   `paper_tls_sde_min` floor applied.
3. For deferred bins: the AR(1) null quantiles exceeded real confirmed-planet
   SDEs, so no threshold is shipped — this is correct behavior, not a bug.
   Effective-SNR Pont et al. 2006 β-deflation already penalizes red-noise.
4. If the threshold looks wrong, rerun `scripts/calibrate_sde_thresholds.py`
   with `--smoke` to regenerate the table and compare bin values.

## PRF Centroid Investigation Path

When a centroid flag fires unexpectedly (or fails to fire for a known EB):

1. Check `centroid_significance` and `centroid_shift_pixels` in the validation
   payload of the relevant TCE.
2. Inspect `tpf_metadata` for `tess_camera`, `tess_ccd`, `tess_sector`,
   `target_pixel_row`, `target_pixel_col` — these are required for the PRF
   kernel load (`mission_prf.py`).
3. Check `neighbor_pixels` in the result — the WCS-projected TIC neighbor list.
   If empty despite known contaminants, check `wcs_pixel_scale_matrix` in
   `tpf_metadata`; missing WCS silently degrades centroiding to None.
4. Re-run with `--mode paper` — neighbor indictment only runs in paper-grade mode.

## Interpret

Report:

- Exact case count and case identities.
- Known/injected recovery rate.
- Promoted-planet recovery rate.
- False-positive rejection rate and escape list.
- Physics failures and period/radius errors.
- Engine failures, unstable cases, and missing evidence.
- Named live-target false rejections.
- SDE population bin and threshold source for each failing case.
- `sibling_signals_masked` values for multi-planet cases.
- PRF centroid status and neighbor indictment results where relevant.

A passing synthetic benchmark does not erase a failing live known-planet run.
Fix the responsible factor, add a regression, rerun the affected benchmark,
then rerun the live target.
