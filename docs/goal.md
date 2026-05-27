# OrbitLab Research-Grade TCE + Vetting Upgrade

## Summary

Upgrade OrbitLab into a TCE preservation and vetting pipeline. `planet_candidates` becomes the canonical promoted-candidate field; legacy `candidates` is generated as a response-time alias only. Borderline signals are preserved as TCEs, shown in the UI as `review_needed`, and exported with complete evidence.

For TIC 100100827:

- Scientific disposition: `borderline_tce`
- UI action label: `review_needed`
- Period: `0.9414760262 d`
- Best SNR: `5.77754`
- Planet candidate: no

## Public Interfaces

- Extend `AnalysisJobCreate`:
    - `vetting_mode: "fast" | "deep" | "paper" = "fast"`
- Store analysis payload with:
    - `schema_version: "orbitlab.analysis_result.v2"`
    - `pipeline_version: "orbitlab-tce-vetting-0.1.0"`
    - `science_config_hash`
    - `data_quality`
    - `tces`
    - `planet_candidates`
    - `validation_status`
    - `engine_status`
    - `deep_mode_progress`
- Do not store `candidates` in new v2 payloads.
    - API response models and report export should add `candidates = planet_candidates` at response time for backward compatibility.
    - Old stored results with only `candidates` should still load and export correctly.
- Add TCE fields:
    - `disposition: "planet_candidate" | "borderline_tce" | "rejected_signal"`
    - `action_label: "none" | "review_needed" | "follow_up_needed"`
    - `disposition_score`, ranking only
    - `confidence_band`
    - `flags: [{ code, severity: "info" | "warning" | "hard_fail", message }]`
    - all numeric metrics named with units, e.g. `depth_fraction`, `depth_ppm`, `period_days`, `duration_days`, `centroid_shift_pixels`, `centroid_shift_arcsec`.

## Science Config

- Add `backend/orbitlab/science/science_config.toml` and loader/hash helper.
- Initial config values:
    - `promotion_snr = 6.0`
    - `borderline_snr_min = 4.5`
    - `aperture_percentiles = [80, 85, 90, 92, 95]`
    - `max_duration_period_ratio = 0.2`
    - `secondary_eclipse_hard_fail_snr = 5.0`
    - `odd_even_hard_fail_sigma = 3.0`
    - `centroid_hard_fail_pixels = 1.0`
    - `quality_flag_dominance_fraction = 0.5`
    - `red_noise_warning_beta = 1.5`
    - `forced_period_tolerance_fraction = 0.01`
    - `paper_promotion_snr = 7.1`
    - `paper_tls_sde_min = 7.0`
    - `paper_min_transits = 2`
    - `paper_ml_threshold = 0.4`
    - `paper_sweet_sigma = 3.0`
    - `paper_model_shift_objects = 20000`
- Include the TOML content hash in every new analysis result as `science_config_hash`.

## Implementation Changes

- Add TCE ledger builder:
    - Always preserve top BLS peak.
    - Preserve additional peaks above `borderline_snr_min`.
    - Promote only into `planet_candidates` after vetting rules pass.
    - Assign `borderline_tce + review_needed` when signal is scientifically unresolved.
- Add evidence sections:
    - `data_quality`: raw/used cadence counts, baseline days, gap fraction, quality flag fraction, scatter ppm, red-noise beta.
    - `detection_metrics`: BLS SNR, SDE, transit count, local noise SNR, duration/period ratio, alias flags.
    - `aperture_stability`: pipeline mask plus configured percentiles.
    - `vetting`: odd/even, secondary eclipse, centroid, difference image, quality-cadence dominance.
    - `catalog_context`: TIC, Gaia, ExoFOP/TOI, NASA Exoplanet Archive, EB catalog status.
    - `fpp`: TRICERATOPS-style result or structured unavailable/skipped state.
    - `ml`: supporting evidence only, never sole promotion authority.
- Add Fast and Deep modes:
    - Fast: BLS, TCE ledger, aperture ensemble, core vetting, data quality, ML diagnostic where available.
    - Deep: Fast plus optional TLS, Wotan detrending, forced-period recovery, multi-sector checks, catalog enrichment, TRICERATOPS, injection-recovery summary.
    - Paper: opt-in mode using the deep search profile plus full TLS evidence, DAVE-style model-shift and SWEET checks, Nigraha's 0.4 TESS probability threshold, SNR >= 7.1, and Kopparapu 2014 habitable-zone boundaries before promotion.
    - Deep mode must produce partial results with `deep_mode_progress` on timeout/failure.
- Update frontend:
    - Add TCE Ledger panel.
    - Show `review_needed` for `borderline_tce`.
    - Keep candidate cards for `planet_candidates`.
    - Selecting a TCE renders its folded curve and evidence.
    - Old candidate-only results still render.

## Test Plan

- Backend:
    - TIC-like SNR `5.77754` signal becomes `borderline_tce` with `action_label: "review_needed"`.
    - SNR `>= 6.0` plus clean vetting becomes `planet_candidate`.
    - SNR `>= 6.0` plus hard-fail secondary becomes `rejected_signal`.
    - Missing optional engines report unavailable, not failed analysis.
    - All metrics use explicit unit-suffixed keys.
    - Science config thresholds drive disposition behavior.
- API/schema:
    - New stored payload has `planet_candidates` but no stored `candidates`.
    - API response adds `candidates` alias from `planet_candidates`.
    - Old stored candidates-only payload still reads successfully.
- Frontend/e2e:
    - Borderline TCE appears in TCE panel with `review_needed`.
    - Promoted candidates remain in candidate cards.
    - Flag severity badges render.
    - Optional engine states render clearly.
- Report/export:
    - Old candidates-only result exports correctly.
    - New TCE-ledger result exports correctly with `tces`, `planet_candidates`, and response-time `candidates` alias.

## Assumptions

- `AnalysisResultRecord.payload_json` remains storage for v1 of this upgrade.
- A normalized TCE table is deferred until batch search/filtering is needed.
- New science dependencies remain optional.
- Fast mode remains default.
- Deep mode is allowed to be slower and partially complete.
