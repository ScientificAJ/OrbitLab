# OrbitLab Module Flow and Factor Map

Authoritative deep-dive: `docs/SCIENTIFIC_METHODOLOGY.md` (method citations and
known deltas vs published pipelines). This file is the working map for locating
where each scientific factor lives and what consumes it.

## End-to-End Flow

```text
user query
  -> GET  /api/v1/search                      (mast.py: target resolution)
  -> GET  /api/v1/targets/{id}/products       (mast.py: product list)
  -> GET  /api/v1/tpf-preview                 (optional pixel preview)
  -> POST /api/v1/aperture-masks / artifact-masks   (optional user masks)
  -> POST /api/v1/analysis-jobs               (api/main.py -> storage job row)
  -> worker.py (inline or Celery)
       -> TPF download/cache                  (science/mast.py)
       -> light-curve extraction              (science/mast.py)
       -> quality cleaning                    (science/data_quality.py)
       -> Wotan detrending [paper mode]       (science/detrending.py)
       -> BLS broad periodogram + residual multi-candidate search (science/bls.py)
       -> TLS primary search [paper mode]     (science/tls_refinement.py)
       -> _difference_image_anchoring()       (science/pipeline.py)
            -> mission PRF kernel             (science/mission_prf.py)
            -> neighbor pixel coords via WCS  (science/catalog_context.py)
       -> orchestration of everything below   (science/pipeline.py: analyze_light_curve_arrays)
            -> sibling TCE masking            (science/pipeline.py: _vetting_arrays_for_candidate)
            -> SDE bin classification + gate  (science/sde_calibration.py: calibrated_sde_threshold)
            -> PRF centroid fit               (science/prf_centroid.py: fit_point_source)
            -> TCE ledger + promotion gates   (science/pipeline.py)
  -> GET /api/v1/analysis-jobs/{job_id}       (status polling)
  -> GET /api/v1/analysis-results/{result_id} (full science payload)
  -> frontend evidence workbench              (frontend/src/lib/api.ts, frontend/src/App.tsx)
```

API prefix is `/api/v1` (`backend/orbitlab/config.py`). Backend default port
8000, frontend 5173 (`./install.sh`).

## Factor → Module Map

| Scientific factor | Computed in | Key functions / notes |
| --- | --- | --- |
| Target resolution, product provenance | `science/mast.py` | MAST search, TPF resolution, LC extraction |
| Cadence quality masking, gap handling | `science/data_quality.py` | feeds `data_quality` payload + dominance flag |
| Detrending (Wotan biweight) | `science/detrending.py` | paper-grade flattening |
| Detrending robustness | `science/detrending_sensitivity.py` | `run_detrending_sensitivity`; sensitivity of detection to detrend choice |
| Period/depth/duration detection (BLS) | `science/bls.py` | broad periodogram + residual searches |
| TLS refinement / SDE | `science/tls_refinement.py` | paper-grade primary engine; raw SDE value |
| SDE bin classification + calibrated gate | `science/sde_calibration.py` | `classify_population`, `calibrated_sde_threshold`; bins by cadence/baseline/red-noise; table in `science/sde_calibration.toml`; red-noise bins deferred (fall back to `paper_tls_sde_min` floor); gate stored in result as `sde_population_bin`, `tls_sde_threshold_used`, `sde_threshold_source` |
| Mission PRF kernel (TESS 1B + Kepler) | `science/mission_prf.py` | `load_tess_prf_kernel`, `load_kepler_prf_kernel`; fetched/cached from MAST calibration dirs; consumed by `_difference_image_anchoring` and `prf_centroid` |
| PSF/PRF centroid fit | `science/prf_centroid.py` | `fit_point_source`; returns `PsfFitResult` with pixel offset and residual; used in `tpf_diagnostics.py` difference-image centroid |
| Neighbor indictment via WCS | `science/pipeline.py: _difference_image_anchoring` | converts catalog RA/Dec to pixel coords using WCS matrix from TPF metadata; neighbor list used by PRF centroid to test off-target contamination |
| Sibling TCE masking before per-TCE vetting | `science/pipeline.py: _vetting_arrays_for_candidate` | removes other accepted TCEs' in-transit cadences; `validation["sibling_signals_masked"]` records count |
| Phase folding | `science/folding.py` | shared by display + validation |
| SNR, odd/even depth + sigma, secondary eclipse SNR, duration plausibility, harmonic flag | `science/validation.py` | `validate_candidate`, `odd_even_significance`, `secondary_eclipse_snr`, `false_positive_flags` |
| Red-noise beta, phase coverage, evidence score | `science/evidence.py` | `estimate_red_noise_beta`, `phase_coverage_score`, `build_candidate_evidence` |
| Centroid shift, difference image, aperture stability | `science/tpf_diagnostics.py` | `centroid_hard_fail_pixels` gate; calls `fit_point_source` for PSF-based centroid |
| ModShift, RoboVet thresholds, SWEET sinusoid test | `science/dave_vetting.py` | uses compiled DAVE `modshift` binary (`scripts/build_dave_modshift.sh`) |
| TIC/Gaia nearby sources, TOI/pscomppars context | `science/catalog_context.py` | `query_tic_catalog_context`; external context only — never a discovery claim; also supplies neighbor coords for PRF centroid |
| FPP / NFPP | `science/triceratops_fpp.py` | `paper_triceratops_fpp_max=0.015`, `nfpp_max=0.001` |
| Planet radius, equilibrium temp, Kopparapu HZ | `science/physics.py` | `infer_planet_physics`, `kopparapu_habitable_zone` |
| Known-target priors, alias matching | `science/known_targets.py` | `resolve_known_target`, `match_known_planet` — drives guided candidates and "known planet" annotation |
| Injection recovery | `science/injection_recovery.py` | `inject_box_transit`, `inject_tls_like_transit`, `run_injection_recovery`, `summarize_recovery`, `run_recovery_grid` |
| Multi-sector consistency | `science/sector_consistency.py` | `summarize_sector_consistency`; cross-sector period/depth agreement |
| ML inference (Nigraha TESS CNN, AstroNet Kepler, ExoMAC K2) | `ml/nigraha_service.py`, `ml/astronet_adapter.py`, `ml/exomac_service.py` | checksum-pinned weights via `ml/artifact_registry.py`; `paper_ml_threshold` |
| Probability calibration | `ml/calibration.py` | calibrated probabilities for ML evidence |
| Promotion gates, structured flags, disposition, science readiness | `science/pipeline.py` | `_apply_paper_grade_vetting`, `_structured_flags`, `_disposition`, `_candidate_science_readiness` |
| Evidence packet export | `science/evidence_packet.py` + `scripts/export_evidence_packet.py` | reviewable artifact |

## Threshold Source of Truth

`backend/orbitlab/science/science_config.toml` — all gates emitted with results.
Key gates (verify current values in the file before citing):

- Standard promotion: `promotion_snr=6.0`, borderline `4.5`.
- Hard fails: secondary eclipse SNR ≥ 5.0, odd/even ≥ 3.0σ, centroid ≥ 1.0 px,
  quality-flag dominance ≥ 0.5, red-noise warning β ≥ 1.5.
- Paper grade: SNR ≥ 7.1, TLS SDE ≥ calibrated threshold (floor `paper_tls_sde_min=7.0`),
  ≥ 2 transits, ML ≥ 0.4, SWEET amplitude/depth fraction 0.5, ModShift 20 000 objects,
  TRICERATOPS FPP ≤ 0.015 / NFPP ≤ 0.001, catalog radius 120″.
- SDE calibration: `backend/orbitlab/science/sde_calibration.toml` — GEV tail fit per
  population bin (cadence × baseline × red-noise level). Red-noise bins are deferred
  (AR(1) null quantiles exceed real confirmed planets); the runtime falls back to the
  `paper_tls_sde_min` floor for those bins. The result payload exposes
  `sde_population_bin`, `tls_sde_threshold_used`, and `sde_threshold_source` for audit.
- Search profiles: `preview_fast`, `science_standard`, `science_deep`,
  `paper_grade`, `long_period` — different period grids and cadence caps, so
  preview results legitimately differ from science runs.

## Trust Boundaries (must survive every change)

```
typed query → catalog/MAST match → TCE (ledger, reviewable)
  → planet_candidates (passed current gates; follow-up candidate)
  → known/confirmed planet (external catalog context only)
  → release-room evidence (provenance, not target confirmation)
```

## Real-Life Behavior Expectations

- **Known confirmed planet**: should resolve via `known_targets.py`, produce a TCE
  at (or aliased to) the catalog period, pass SNR/odd-even/secondary gates, and be
  annotated with known-planet context — recovery failure here is a high-priority
  accuracy bug. If the SDE bin is deferred (red-noise), the fallback floor applies;
  inspect `sde_population_bin` and `sde_threshold_source` in the result.
- **Eclipsing binary**: should trip odd/even significance and/or secondary eclipse SNR
  hard fails and stay in `tces` with explanatory flags.
- **Systematic/alias**: should be caught by harmonic/alias annotation
  (`_period_alias_code`), red-noise beta, or quality-flag dominance.
- **Multi-planet system**: sibling masking (`sibling_signals_masked`) ensures each
  candidate is vetted on residual flux with co-transit cadences removed — check this
  field when a secondary candidate underperforms.
- **Off-target contamination**: PRF centroid (`prf_centroid.py`) + neighbor pixel
  indictment (WCS-projected TIC neighbors) should surface centroid displacement
  toward a known contaminant; check `centroid_significance` and any neighbor
  displacement flags in the validation payload.
- **Incomplete paper-grade evidence** (ModShift binary missing, TRICERATOPS failure,
  ML weights absent): must block promotion loudly, never downgrade silently.
