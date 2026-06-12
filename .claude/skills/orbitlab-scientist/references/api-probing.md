# OrbitLab Live API Probing

Use live probing when result behavior matters. Unit mocks prove contracts; a
live probe proves that MAST products, job orchestration, installed science
engines, and payload semantics work together.

## Start And Check

```bash
./install.sh
curl -sS http://127.0.0.1:8000/api/v1/health
python .claude/skills/orbitlab-scientist/scripts/api_probe.py --help
```

The probe follows:

```text
health -> target search -> product listing -> analysis job -> polling -> result
```

Use a deterministic product substring when comparing runs across sessions:

```bash
python .claude/skills/orbitlab-scientist/scripts/api_probe.py \
  --target "L 98-59" \
  --mission TESS \
  --product-substring s0002-0000000307210830-0121 \
  --mode paper \
  --output .orbitlab/benchmarks/api-probe-l98.json
```

## Full Multi-Target Live Truth Run

`scripts/live_planet_verification.py` is the maintained multi-target truth
harness. It probes the live API end-to-end against a golden table of NASA
Exoplanet Archive values and compares recovered ephemerides and physics. No
mocks: real MAST products, real engines (TLS, DAVE ModShift, SWEET,
TRICERATOPS, ML artifacts when registered). Results are for human review —
the script collects evidence; scientific judgement requires comparing against
the golden table manually.

```bash
python scripts/live_planet_verification.py
python scripts/live_planet_verification.py --output .orbitlab/benchmarks/live-truth-$(date +%Y%m%d).json
```

## Payload Audit Checklist

Start with the top-level result, then drill into each TCE:

**Top-level fields**
- Confirm `target_id`, `product_uri`, mission, and cadence match the intended product.
- `science_readiness.status` — overall disposition.
- `tces` count vs `planet_candidates` count — understand what was promoted vs retained.

**Per-TCE fields**
- `period`, `depth`, `duration` — compare to catalog ephemerides for known planets.
- `disposition` — `promoted`, `review`, `rejected_signal`, `borderline`.
- `validation.snr`, `validation.odd_even_sigma`, `validation.secondary_eclipse_snr`.
- `validation.centroid_significance`, `validation.centroid_shift_pixels` — for
  centroid flags; check against `centroid_hard_fail_pixels=1.0` gate.
- `validation.sibling_signals_masked` — non-zero is expected in multi-planet runs.
- `thresholds.sde_population_bin` — which SDE calibration bin applied.
- `thresholds.tls_sde_threshold_used` — the actual gate value used (≥ floor).
- `thresholds.sde_threshold_source` — `"calibrated"` or `"floor"` (deferred bin).
- `flags` list — separate `hard_fail` from `warning` entries.
- `evidence_against` hard failures vs `missing_engine` hard failures — these are
  different signals: one indicts the target, the other indicts the setup.

**Paper-grade extras**
- `tls_sde` vs `tls_sde_threshold_used` — margin above the calibrated gate.
- `modshift` fields — check `modshift_status` and `modshift_objects`.
- `sweet_sigma`, `sweet_amplitude_depth_fraction`.
- `ml_score`, `ml_domain`, `ml_available`.
- `triceratops.fpp`, `triceratops.nfpp`, `triceratops.status`.
- Neighbor indictment: look for any neighbor-displacement or centroid flags from
  WCS-projected TIC neighbors (paper mode only).

**Annotation fields**
- `known_planet` annotation (from `known_targets.py`) — presence means the system
  recognized the catalog match; absence for a well-known target is a bug.
- `period_alias_code` — explains period aliases; a recovered half/double period
  is not a failure when the alias is documented.

A known planet marked `rejected_signal` is a false-rejection investigation,
even when the API request itself succeeded.
