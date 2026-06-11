# OrbitLab Scientific Methodology

Status: source-backed methodology for the current OrbitLab implementation as of OrbitLab `v0.2.0` on 2026-06-03.

Audience: scientists, hackathon judges, maintainers, and advanced users who need to understand exactly what the system does, what research method each module follows, where OrbitLab is one-to-one with published or reference implementations, and where a published pipeline remains scientifically stronger.

Scope: entire product workflow, including archive data ingestion, target pixel file extraction, light-curve cleaning, detrending, detection, TCE preservation, paper-grade vetting, model inference, physics estimates, API/job storage, frontend evidence display, tests, artifacts, and known methodology deltas.

## Executive Summary

OrbitLab is a real-data exoplanet transit workbench. It starts from public mission data products, extracts a light curve from target pixel files, searches for transit-like periodic dimming, preserves threshold-crossing events (TCEs), and promotes a TCE into `planet_candidates` only after evidence gates pass.

The default `paper` mode is intentionally strict. It uses:

- MAST/TESS/Kepler/K2 target pixel products as the data source.
- Wotan biweight detrending for paper-grade light-curve flattening.
- Transit Least Squares (TLS) as the paper-grade primary search engine.
- Astropy Box Least Squares (BLS) as the broad periodogram and residual multi-candidate search engine.
- DAVE ModShift through the compiled official DAVE `modshift` executable.
- DAVE RoboVet threshold logic copied into OrbitLab with the same decision inequalities as the upstream `RoboVet.py`.
- DAVE-style SWEET sinusoid testing at P/2, P, and 2P.
- TIC/Gaia nearby-source context through `astroquery.mast.Catalogs`.
- NASA Exoplanet Archive TOI and `pscomppars` context through `astroquery.ipac.nexsci.nasa_exoplanet_archive`.
- TRICERATOPS `target.calc_probs` for TESS FPP and NFPP.
- Nigraha TESS CNN ensemble inference when the checksum-validated weights are present.
- Mission-specific Kepler/K2 ML evidence where applicable.
- Explicit red-noise, odd/even, secondary eclipse, centroid, aperture stability, phase coverage, and data quality evidence.

OrbitLab does not claim that a promoted signal is a confirmed planet. The strongest product-level claim is: this TCE passed OrbitLab's current evidence gates and should be treated as a follow-up candidate. Confirmation still requires the usual astrophysical validation, follow-up observations, and expert review.

## Design Principles

1. Real products first. The workflow begins from public archive products or local cached copies of those products.
2. Evidence separation. `tces` stores every reviewable signal. `planet_candidates` stores only signals that passed promotion logic.
3. No silent scientific substitution. Paper-grade promotion is blocked when required paper-grade evidence does not complete.
4. ML as supporting evidence. Machine learning can raise or lower confidence, but it is not the only promotion authority.
5. Traceable thresholds. Numeric gates live in `backend/orbitlab/science/science_config.toml` and are emitted with results.
6. Reproducible artifact policy. Model artifacts are pinned, checksum validated, and fetched by scripts rather than fabricated.
7. Honest limitations. The app distinguishes exact attached paper methods from useful approximations and still-stronger external pipelines.
8. Release-level provenance. Public releases include model checksums, calibration/source checksums, benchmark deltas, SBOM data, release asset checksums, and GitHub attestations so scientific evidence can be audited after the demo.

## Primary Code Map

| Area                                                | Code                                           |
| --------------------------------------------------- | ---------------------------------------------- |
| FastAPI endpoints and job creation                  | `backend/orbitlab/api/main.py`                 |
| API schemas                                         | `backend/orbitlab/api/schemas.py`              |
| Worker execution                                    | `backend/orbitlab/worker.py`                   |
| MAST search, TPF resolution, light-curve extraction | `backend/orbitlab/science/mast.py`             |
| Data cleaning                                       | `backend/orbitlab/science/data_quality.py`     |
| BLS detection and residual search                   | `backend/orbitlab/science/bls.py`              |
| Wotan detrending                                    | `backend/orbitlab/science/detrending.py`       |
| TLS search/refinement                               | `backend/orbitlab/science/tls_refinement.py`   |
| Main science orchestration                          | `backend/orbitlab/science/pipeline.py`         |
| Core validation metrics                             | `backend/orbitlab/science/validation.py`       |
| Evidence scoring                                    | `backend/orbitlab/science/evidence.py`         |
| Difference image and aperture diagnostics           | `backend/orbitlab/science/tpf_diagnostics.py`  |
| DAVE ModShift, RoboVet, SWEET                       | `backend/orbitlab/science/dave_vetting.py`     |
| TIC/Gaia/NASA Archive context                       | `backend/orbitlab/science/catalog_context.py`  |
| TRICERATOPS FPP/NFPP wrapper                        | `backend/orbitlab/science/triceratops_fpp.py`  |
| Planet physics and Kopparapu HZ                     | `backend/orbitlab/science/physics.py`          |
| Nigraha tensorization                               | `backend/orbitlab/ml/nigraha_adapter.py`       |
| Nigraha HDF5 ensemble inference                     | `backend/orbitlab/ml/nigraha_service.py`       |
| Frontend data contract                              | `frontend/src/lib/api.ts`                      |
| Frontend workbench                                  | `frontend/src/App.tsx`                         |
| Method thresholds                                   | `backend/orbitlab/science/science_config.toml` |
| Full repo gate                                      | `scripts/preflight.sh`                         |
| DAVE binary build                                   | `scripts/build_dave_modshift.sh`               |
| Release-room provenance                             | `scripts/build_release_room.py`                |

## End-to-End Data Flow

```text
User target query
  -> /api/v1/search
  -> MAST/mission target resolution
  -> /api/v1/targets/{target_id}/products
  -> product_uri chosen by user
  -> optional TPF preview
  -> optional aperture mask
  -> optional artifact mask
  -> /api/v1/analysis-jobs
  -> SQLAlchemy job row
  -> inline worker or Celery worker
  -> target pixel file download/cache resolution
  -> light curve extraction
  -> quality cleaning
  -> paper-mode Wotan detrending
  -> BLS broad search
  -> paper-mode TLS primary search
  -> residual multi-candidate search
  -> TCE ledger construction
  -> physics, validation, diagnostics, ML, catalog context, FPP
  -> paper-grade gates
  -> tces and planet_candidates payload
  -> stored result
  -> frontend evidence workbench
  -> optional evidence export
  -> release-room provenance packet for tagged releases
```

## Result Trust Boundaries

OrbitLab uses separate evidence layers because mixing them creates false certainty:

| Layer                          | Meaning                                                                                | User-facing wording                                                       |
| ------------------------------ | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Typed target query             | Text the user entered.                                                                 | Search input only; not proof of a catalog match.                          |
| Catalog/MAST match             | A resolved mission target/product returned by archive tooling.                         | Real target/product selection.                                            |
| TCE                            | A reviewable threshold-crossing signal preserved in the ledger.                        | Needs review; may be borderline or rejected.                              |
| `planet_candidates`            | TCEs promoted by OrbitLab's current evidence gates.                                    | Follow-up candidate, not confirmed.                                       |
| Known/confirmed planet context | External archive/catalog context such as NASA Exoplanet Archive rows.                  | External catalog context, not OrbitLab's own discovery claim.             |
| Release-room evidence          | Checksums, benchmarks, SBOM, release assets, and attestations generated for a release. | Reproducibility and provenance evidence, not a target-level confirmation. |

Any UI, API, report, release note, or demo narration must preserve these boundaries. The safe sentence is: "This signal is a real TCE found in real mission data; its displayed disposition describes how it performed under OrbitLab's current evidence gates."

## Data Acquisition Methodology

OrbitLab works from target pixel files because pixel-level data enables aperture control and centroid/difference-image diagnostics. This is closer to a real vetting workflow than using only a pre-extracted light curve.

Relevant implementation:

- `backend/orbitlab/science/mast.py`
- `backend/orbitlab/worker.py`
- `backend/orbitlab/api/main.py`

Research/reference methodology:

- TESS-SPOC and MAST provide calibrated target pixel files, light curves, data-validation products, and TCE products. MAST's TESS-SPOC documentation states that SPOC generates target pixel files, light curves, and data-validation products for TCEs in TESS-SPOC products.
- Lightkurve documents that Kepler/K2/TESS products on MAST include light-curve products and target pixel file products, with TPFs represented as stacks of pixel-level images at observation times.

OrbitLab method:

1. Search target products with MAST-oriented helpers.
2. Resolve `product_uri` into a cached FITS path or download it.
3. Extract the target pixel cube.
4. Use the selected aperture mask or the pipeline mask.
5. Sum selected pixels into a flux series.
6. Preserve quality flags.
7. Preserve pixel cube and pixel scale for difference-image diagnostics when no manual artifact mask destroys alignment.

Important output fields:

- `light_curve.time`
- `light_curve.flux`
- `bls_light_curve`
- `preprocessing`
- `data_quality`
- `aperture_stability`
- `vetting.difference_image`

Where the research pipeline is stronger:

SPOC is a mission-scale pipeline with calibrated DV products, cotrending basis vectors, multi-sector searches, transit model fitting, and formal data-validation reports. OrbitLab is an interactive workbench around selected products, not a full replacement for SPOC TPS/DV. SPOC is better for mission-uniform survey products and multi-sector production catalogs. OrbitLab is better for transparent educational inspection and interactive candidate-level evidence.

## Light-Curve Cleaning

Relevant implementation:

- `backend/orbitlab/science/data_quality.py`
- `backend/orbitlab/science/bls.py`
- `backend/orbitlab/science/pipeline.py`

The cleaning stage removes non-finite cadences and applies quality filtering where a mission quality array is present. BLS additionally performs robust asymmetric sigma clipping:

```text
median = nanmedian(flux)
mad = nanmedian(abs(flux - median))
robust_sigma = 1.4826 * mad
keep = (flux - median <= 6.0 * robust_sigma) and (median - flux <= 50.0 * robust_sigma)
```

The use of `1.4826 * MAD` estimates Gaussian-equivalent scatter from the median absolute deviation. It is more outlier-resistant than standard deviation when scattered cosmic rays, momentum dumps, or short instrumental artifacts are present.

The clip is intentionally asymmetric. Positive outliers (flares, cosmic rays, scattered light) are removed at 6 robust sigma, but negative excursions are exactly the signal a transit search exists to find: a 1% hot-Jupiter transit over 300 ppm scatter is roughly 30 sigma deep, so a symmetric clip would delete the strongest planets before the periodogram ever ran. The 50-sigma lower bound only removes gross instrumental dropouts.

Data-quality fields emitted:

| Field                   | Meaning                                                   |
| ----------------------- | --------------------------------------------------------- |
| `raw_cadence_count`     | Number of input samples before cleaning.                  |
| `used_cadence_count`    | Number of samples after cleaning.                         |
| `baseline_days`         | Time span of finite input data.                           |
| `gap_fraction`          | Approximate missing-cadence fraction from median cadence. |
| `quality_flag_fraction` | Fraction of cadences with nonzero mission quality flag.   |
| `scatter_ppm`           | Standard deviation of cleaned residuals in ppm.           |
| `red_noise_beta`        | Correlated-noise inflation estimate.                      |

Where research pipelines are stronger:

Mission pipelines such as SPOC perform calibrated systematics correction and data validation at scale. OrbitLab cleaning is intentionally compact and transparent. It is suitable for visible evidence generation, but mission pipeline detrending and cotrending remain stronger for catalog-level uniformity.

## Wotan Detrending

Relevant implementation:

- `backend/orbitlab/science/detrending.py`
- `backend/orbitlab/science/pipeline.py`

Research methodology:

- Hippke et al. describe Wotan as a comprehensive time-series detrending package.
- Their benchmark concludes that a time-windowed slider with Tukey's biweight is the ideal method for many shallow transit recovery cases.
- The official Wotan README demonstrates `flatten(time, flux, window_length=0.5, method='biweight', return_trend=True)` and lists `biweight` as a robust time-windowed M-estimator.

OrbitLab method:

```python
detrended, trend = flatten(
    clean_time,
    clean_flux,
    method="biweight",
    window_length=window_length_days,
    return_trend=True,
)
```

Window selection:

```text
cadence_days = median(diff(sort(time)))
baseline_days = max(time) - min(time)
window_length_days = clip(0.75, lower=max(5 * cadence_days, 0.1), upper=max(baseline_days / 3, 0.1))
```

Paper-grade mode applies Wotan before BLS/TLS:

```text
clean_flux, detrending = detrend_with_wotan(clean_time, clean_flux, method="biweight")
```

One-to-one alignment:

The method uses the real `wotan.flatten` package and the Wotan-recommended `biweight` detrending family.

Methodology delta:

Wotan's paper explores different detrenders and parameter choices, including spline/Huber behavior for young or highly variable stars. OrbitLab currently fixes paper-grade mode to biweight. The Wotan paper is better when the stellar variability class requires method selection beyond biweight.

## BLS Detection

Relevant implementation:

- `backend/orbitlab/science/bls.py`
- `backend/orbitlab/science/pipeline.py`

Research methodology:

- Kovacs, Zucker, and Mazeh introduced Box-fitting Least Squares (BLS) for periodic box-shaped transits.
- Astropy's `BoxLeastSquares` documentation states that it computes the BLS periodogram and cites Kovacs et al. 2002.

OrbitLab method:

1. Clean and sigma clip.
2. Flatten with `transit_safe_flatten`, a Savitzky-Golay style trend removal used inside the BLS search path.
3. Bin the search light curve if it exceeds `max_search_cadences`.
4. Clamp period range to the available baseline and requested minimum transit count.
5. Generate an adaptive duration grid.
6. Build a period grid from Astropy autoperiod, geometric spacing, and frequency spacing.
7. Cap the period count to an effective maximum.
8. Run `astropy.timeseries.BoxLeastSquares.power`.
9. Select the maximum power period.
10. Refine the peak with a narrow linear grid (±1.5%, 2001 samples). Geometric broad grids leave ~0.1% period error, which drifts folded phases by a large fraction of the transit duration across a full baseline and smears odd/even and secondary diagnostics enough to hide eclipsing binaries.
11. Compute SNR on the full clipped light curve, not only the binned search light curve.

Key equations:

```text
phase = ((time - epoch + 0.5 * period) % period) - 0.5 * period
in_transit = abs(phase) <= 0.5 * duration
out_of_transit = abs(phase) >= duration
scatter = 1.4826 * MAD(out_of_transit_flux - median(out_of_transit_flux))
SNR = depth / scatter * sqrt(N_in_transit)
```

Search profile thresholds:

| Profile            | min_period | max_period | period_samples | max_period_samples | min_transits | max_search_cadences |
| ------------------ | ---------: | ---------: | -------------: | -----------------: | -----------: | ------------------: |
| `preview_fast`     |      0.5 d |       30 d |           4096 |              50000 |            2 |                6000 |
| `science_standard` |      0.2 d |       60 d |           8192 |              50000 |            2 |                6000 |
| `science_deep`     |      0.1 d |       60 d |          50000 |              50000 |            2 |                9000 |
| `paper_grade`      |      0.1 d |       60 d |          50000 |              50000 |            2 |                9000 |
| `long_period`      |       10 d |      120 d |          50000 |              50000 |            1 |                9000 |

One-to-one alignment:

OrbitLab uses Astropy's BLS implementation, which is explicitly based on the BLS method. The local implementation adds pragmatic binning, period-grid caps, and robust full-resolution SNR.

Where the research method is better:

The original BLS paper's mathematical detection statistic is the clean reference for box-shaped transit detection. OrbitLab modifies the search grid and computes a custom SNR so it can stay interactive. For publication-grade blind searches, a survey pipeline would calibrate the statistic and false-alarm behavior against injected signals over the exact cadence/noise population.

## TLS Primary Search

Relevant implementation:

- `backend/orbitlab/science/tls_refinement.py`
- `backend/orbitlab/science/pipeline.py`

Research methodology:

- Hippke and Heller introduced Transit Least Squares (TLS), which searches transit-like features using stellar limb darkening, ingress, egress, physically plausible durations, and optimized period sampling.
- The TLS paper reports that SDE thresholds around 7 reach roughly 1 percent false-positive rate in their injection-retrieval setup, with higher recovery than BLS for shallow Earth-size signals.
- The official TLS GitHub README says TLS can be installed with `pip install transitleastsquares` and cites Hippke and Heller 2019.

OrbitLab paper-grade method:

```python
paper_tls_primary = search_with_tls(
    clean_time,
    clean_flux,
    min_period=profile.min_period,
    max_period=profile.max_period,
    stellar_radius_solar=stellar_radius_solar,
    stellar_mass_solar=stellar_mass_solar,
    transit_depth_min=10e-6,
    n_transits_min=config.paper_min_transits,
    oversampling_factor=3,
    duration_grid_step=1.1,
)
primary = _tls_primary_candidate(paper_tls_primary)
```

TLS output fields:

| Field                      | Meaning                                          |
| -------------------------- | ------------------------------------------------ |
| `period_days`              | Best TLS period.                                 |
| `duration_days`            | TLS duration.                                    |
| `epoch_days`               | TLS T0.                                          |
| `depth_fraction`           | TLS depth.                                       |
| `snr`                      | TLS SNR where available.                         |
| `sde`                      | TLS signal detection efficiency.                 |
| `sde_raw`                  | Raw SDE where available.                         |
| `fap`                      | TLS false-alarm probability where available.     |
| `transit_count`            | TLS transit count where available.               |
| `distinct_transit_count`   | Distinct TLS transit count where available.      |
| `periodogram_period_count` | Number of TLS periods evaluated where available. |

Paper-grade gates:

```text
paper_tls_sde_min = 7.0
paper_min_transits = 2
```

One-to-one alignment:

OrbitLab uses the real `transitleastsquares` package for the full paper-grade primary search.

Where TLS is better than BLS in OrbitLab:

TLS is better for shallow, planet-like transits where a box profile loses information about ingress, egress, and limb darkening. OrbitLab therefore uses TLS as the paper-grade primary search and keeps BLS as the broad/residual search and visible periodogram engine.

Methodology delta:

TLS paper analyses stress full, physically calibrated injection-retrieval experiments. OrbitLab does not yet perform target-population-specific SDE calibration at runtime. Its SDE threshold is anchored to the TLS paper and exposed in config, but not recalibrated for every mission sector, cadence, aperture, and stellar noise regime.

## TCE Ledger and Promotion Model

Relevant implementation:

- `backend/orbitlab/science/pipeline.py`
- `backend/orbitlab/api/schemas.py`
- `frontend/src/App.tsx`

OrbitLab separates detection from promotion.

```text
tces = all reviewable threshold-crossing events kept for evidence display
planet_candidates = subset of tces promoted after gates pass
candidates = API response-time compatibility alias for planet_candidates
```

This avoids the common failure mode where a low-SNR but scientifically reviewable periodogram peak disappears from the UI because it does not pass planet-candidate promotion.

Disposition logic:

| Disposition        | Action label       | Meaning                                                       |
| ------------------ | ------------------ | ------------------------------------------------------------- |
| `planet_candidate` | `follow_up_needed` | Passed current promotion gates.                               |
| `borderline_tce`   | `review_needed`    | Reviewable signal: not promoted, or required evidence missing. |
| `rejected_signal`  | `none`             | Evidence-against hard fail, or too weak to review.            |

Hard-fail flags are split into two scientific classes:

- Evidence-against codes (secondary eclipse, odd/even mismatch, implausible duration, DAVE false-positive verdicts, TRICERATOPS FPP/NFPP in the Giacalone et al. 2021 likely-false-positive zone, paper SNR/transit-count shortfalls) reject the signal.
- Missing-evidence codes (`paper_tls_required`, `dave_model_shift_required`, `sweet_required`, `nigraha_required`, `triceratops_required`) mean a required engine did not complete. They block promotion loudly, but the signal stays a reviewable `borderline_tce`: "DAVE unavailable" is not "signal failed DAVE".

Warning flags are likewise split. Soft review-context warnings (`catalog_contamination`, `nigraha_low_probability`, `known_period_low_snr`, `planetary_secondary`, `weak_residual_signal`, `red_noise`, `odd_even_depth_mismatch`, `triceratops_fpp_inconclusive`, `triceratops_nfpp_inconclusive`) do not veto a strong promotion because their information is either review context or already priced into effective SNR (red-noise beta deflates effective SNR per Pont, Zucker & Queloz 2006, so blocking on the warning as well would double-penalize). Detection-quality warnings such as `low_snr` or `stellar_rotation_harmonic` still block promotion.

Core promotion thresholds:

```text
promotion_snr = 6.0
borderline_snr_min = 4.5
paper_promotion_snr = 7.1
strong promotion: final_score >= 0.80 and effective_snr >= paper_promotion_snr with only soft warnings
standard promotion: final_score >= 0.65 and effective_snr >= promotion_snr with no warnings
```

Paper-grade gate:

```text
paper_grade.pass == True
no hard_fail flags
disposition == "planet_candidate"
```

## Core Validation

Relevant implementation:

- `backend/orbitlab/science/validation.py`
- `backend/orbitlab/science/pipeline.py`

Validation metrics:

| Metric                        | Formula or rule                         | Threshold behavior                               |
| ----------------------------- | --------------------------------------- | ------------------------------------------------ |
| Duration plausibility         | `0 < duration < 0.5 * period`           | Implausible duration is hard fail.               |
| Odd/even depth delta          | `abs(depth_odd - depth_even)`           | Event-level sigma >= 3.0 hard fail; a pooled sigma >= 3.0 is only hard when the parity split is also >= 20% of transit depth. |
| Secondary eclipse SNR         | secondary depth over robust scatter     | SNR >= 5.0 hard fail in structured flags.        |
| Stellar rotation harmonic     | period/rotation near 0.25, 0.5, 1, 2, 4 | warning.                                         |
| Centroid significance         | `centroid_shift / centroid_uncertainty` | >= 2 sigma warning, >= 3 sigma stronger warning. |
| Pixel fallback centroid shift | pixels > 1.0 if no uncertainty          | warning.                                         |
| SAP/PDCSAP agreement          | correlation < 0.8 if both supplied      | warning.                                         |

Odd/even calculation:

```text
transit_number = round((time - epoch) / period)
in_transit = abs(phase_time) < 0.5 * duration
event_depth = baseline - median(flux[in each distinct transit event])
odd_depth = median(event_depths for odd events)
even_depth = median(event_depths for even events)
odd_err/even_err = robust standard error of the median event depth
sigma = abs(odd_depth - even_depth) / sqrt(odd_err^2 + even_err^2)
```

Event numbering uses nearest-integer rounding because the in-transit window is centered on the epoch: floor-based numbering would split each event's cadences across two adjacent transit numbers, mixing odd and even samples and collapsing the depth difference this diagnostic exists to measure (the classic eclipsing-binary half-period discriminator). Uncertainty is estimated across distinct event depths when each parity has at least three events; treating every cadence as independent makes long, densely sampled light curves arbitrarily overconfident and can falsely reject real planets with ordinary transit-to-transit variation. OrbitLab retains the cadence-pooled significance only as a large-effect guard: it becomes hard evidence when it exceeds the configured sigma threshold and the parity depth split is at least 20% of the detected transit depth.

Secondary eclipse calculation:

```text
secondary_phase = abs(((time - epoch) % period) / period - 0.5)
secondary = secondary_phase < duration / period / 2
secondary_snr = secondary_depth / baseline_scatter * sqrt(N_secondary)
```

Where external vetters are stronger:

Full Kepler/TESS DV products fit transit models, evaluate centroid offsets with calibrated PRFs, evaluate rolling band and systematic events, and use mission-specific data-validation products. OrbitLab's core validation is transparent and useful, but not a full SPOC/Kepler DV clone.

## Difference Image and Aperture Stability

Relevant implementation:

- `backend/orbitlab/science/tpf_diagnostics.py`
- `backend/orbitlab/worker.py`

Difference-image diagnostics use the pixel cube:

```text
in_image = median(pixel_flux[in_transit], axis=0)
out_image = median(pixel_flux[out_of_transit], axis=0)
diff_image = out_image - in_image
pixel_snr = diff_image / std(pixel_flux[out_of_transit], axis=0) * sqrt(N_in_transit)
```

Centroids are weighted by positive flux above a low percentile floor:

```text
floor = percentile(image, 5)
weights = max(image - floor, 0)
centroid_row = sum(row * weights) / sum(weights)
centroid_col = sum(col * weights) / sum(weights)
```

Aperture stability tests the selected mask and percentile-derived masks:

```text
aperture_percentiles = [80, 85, 90, 92, 95]
relative_snr_scatter = std(mask_snrs) / abs(median(mask_snrs))
score = 1 - clip(relative_snr_scatter, 0, 1)
```

Where research methods are stronger:

Pixel response function (PRF) centroiding and formal centroid uncertainty estimation in mission DV products are stronger than OrbitLab's direct image-moment centroid. OrbitLab's advantage is that the diagnostic is visible, fast, and tied to the user's chosen aperture.

## DAVE ModShift and RoboVet

Relevant implementation:

- `backend/orbitlab/science/dave_vetting.py`
- `scripts/build_dave_modshift.sh`
- `.orbitlab/external/DAVE/vetting/RoboVet.py` after the DAVE build script runs

Research/reference methodology:

- DAVE is an open-source automated vetting pipeline for exoplanet candidates.
- The DAVE paper describes adapting Kepler vetting tools for K2 and packaging them in DAVE.
- The DAVE GitHub repository includes TESS usage, requires legacy data directories for K2/PRF work, and includes Fortran/C++/Python components.

OrbitLab attachment:

1. `scripts/build_dave_modshift.sh` clones `https://github.com/exoplanetvetting/DAVE.git`.
2. It checks out pinned commit `aea19a30d987b214fb4c0cf01aa733f127c411b9`.
3. It runs `make -C "$dave_dir/vetting" modshift`.
4. Runtime uses `.orbitlab/external/DAVE/vetting/modshift` or `ORBITLAB_DAVE_MODSHIFT`.
5. OrbitLab writes a three-column input file: time, flux, box model.
6. It calls the official binary.
7. It parses official output fields.
8. It applies DAVE RoboVet logic with the same inequalities as upstream `RoboVet.py`.

Parsed ModShift fields:

| OrbitLab key      | Meaning                                   |
| ----------------- | ----------------------------------------- |
| `mod_sig_pri`     | primary event significance                |
| `mod_sig_sec`     | secondary event significance              |
| `mod_sig_ter`     | tertiary event significance               |
| `mod_sig_pos`     | positive-going event significance         |
| `mod_sig_oe`      | odd/even model-shift significance         |
| `mod_dmm`         | depth mean/median metric                  |
| `mod_shape`       | shape/sinusoidal metric                   |
| `mod_sig_fa1`     | first false-alarm significance threshold  |
| `mod_sig_fa2`     | second false-alarm significance threshold |
| `mod_Fred`        | red-noise factor                          |
| `mod_ph_pri`      | primary phase                             |
| `mod_ph_sec`      | secondary phase                           |
| `mod_ph_ter`      | tertiary phase                            |
| `mod_ph_pos`      | positive event phase                      |
| `mod_secdepth`    | secondary depth                           |
| `mod_secdeptherr` | secondary depth uncertainty               |

Exact RoboVet inequalities implemented:

```text
not transit-like if:
  mod_sig_pri / mod_Fred < mod_sig_fa1 and mod_sig_pri > 0
  mod_sig_pri - mod_sig_ter < mod_sig_fa2 and mod_sig_pri > 0 and mod_sig_ter > 0
  mod_sig_pri - mod_sig_pos < mod_sig_fa2 and mod_sig_pri > 0 and mod_sig_pos > 0
  mod_dmm > 1.5
  mod_shape > 0.3

significant secondary if:
  mod_sig_sec / mod_Fred > mod_sig_fa1
  and mod_sig_sec > 0
  and (mod_sig_sec - mod_sig_ter > mod_sig_fa2 or mod_sig_ter > 0)
  and (mod_sig_sec - mod_sig_pri > mod_sig_fa2 or mod_sig_pri > 0)

odd/even model-shift secondary flag if:
  mod_sig_oe > mod_sig_fa1

disposition:
  false positive if not_trans_like > 0 or sig_sec > 0
  candidate otherwise
```

One-to-one alignment:

The ModShift executable is official DAVE code. The RoboVet thresholds and comments are reproduced from upstream `RoboVet.py`.

Methodology delta:

OrbitLab attaches the official ModShift binary and RoboVet decision logic, but not the entire legacy DAVE Python2/Octave/Gnuplot/PRF pipeline. Full DAVE remains stronger when using its complete PRF, trap-fit, and pipeline-specific context. OrbitLab's one-to-one claim is limited to ModShift binary execution plus RoboVet inequalities.

## SWEET Sinusoid Test

Relevant implementation:

- `backend/orbitlab/science/dave_vetting.py`

Research/reference methodology:

DAVE includes SWEET-style sinusoidal variability vetting to identify stellar variability and eclipsing binary behavior at harmonics of the candidate period.

OrbitLab method:

1. Remove primary transit cadences from the fit.
2. Evaluate periods P/2, P, and 2P.
3. Fit:

```text
flux_oot = a * sin(2*pi*time/period) + b * cos(2*pi*time/period) + c
amplitude = sqrt(a^2 + b^2)
sigma = amplitude / (robust_residual_scatter / sqrt(N_oot / 2))
```

4. Mark a warning if any tested sinusoid has `sigma >= paper_sweet_sigma`.

Current threshold:

```text
paper_sweet_sigma = 3.0
```

Methodology delta:

OrbitLab's SWEET is a DAVE-style reimplementation rather than a direct call into a full upstream SWEET module. It is useful as a harmonic-sinusoid screen, but full DAVE remains stronger for exact historical reproducibility.

## TIC/Gaia Nearby-Source and Archive Context

Relevant implementation:

- `backend/orbitlab/science/catalog_context.py`

External methodology:

- TRICERATOPS and TESS follow-up workflows rely on nearby star context because a nearby eclipsing binary can dilute into the target aperture and mimic a planet transit.
- The NASA Exoplanet Archive TAP service exposes `toi` and `pscomppars` tables.
- Astroquery documents `NasaExoplanetArchive.query_criteria` for TAP-backed queries and lists `toi` and `pscomppars` tables.

OrbitLab method:

1. Parse a numeric TIC ID from the target string.
2. Query TIC via `astroquery.mast.Catalogs.query_object`.
3. Choose the target TIC row where possible.
4. Compute angular separation using spherical haversine formula.
5. For each neighbor:

```text
delta_tmag = Tmag_neighbor - Tmag_target
flux_ratio = 10^(-0.4 * delta_tmag)
max_diluted_eclipse_depth = flux_ratio / (1 + flux_ratio)
can_mimic_observed_depth = observed_depth <= max_diluted_eclipse_depth
```

6. Query NASA Archive TOI rows:

```text
table="toi"
select="toi,tid,tfopwg_disp,pl_orbper,pl_trandep,pl_trandurh,toi_created,rowupdate"
where="tid={tic_id}"
```

7. Query confirmed planet rows:

```text
table="pscomppars"
select="pl_name,hostname,tic_id,gaia_id,discoverymethod,disc_year,pl_orbper,pl_rade"
where="tic_id like '%{tic_id}%'"
```

Current threshold:

```text
paper_catalog_radius_arcsec = 120.0
```

One-to-one alignment:

OrbitLab uses live Astroquery catalog/API mechanisms, not a static fake catalog.

Where external methods are better:

Catalog context is not the same as follow-up imaging, spectroscopy, or aperture-level PSF modeling. TIC/Gaia context can flag possible contaminants; it cannot rule all of them out.

## TRICERATOPS FPP/NFPP

Relevant implementation:

- `backend/orbitlab/science/triceratops_fpp.py`
- `backend/orbitlab/science/pipeline.py`

Research methodology:

- TRICERATOPS is a Bayesian tool for vetting and validating TESS Objects of Interest.
- Its documentation states that it computes false-positive probability (FPP) and nearby false-positive probability (NFPP) by analyzing transit data and the surrounding field of stars.
- The TESS example demonstrates `target = tr.target(ID, sectors)`, aperture/nearby-star inspection, optional `calc_depths`, and `target.calc_probs(time, flux_0, flux_err_0, P_orb)`.
- Giacalone et al. define validation criteria using `FPP < 0.015` and `NFPP < 1e-3`, and rejection criteria using `FPP > 0.5` (likely false positive) and `NFPP > 0.1` (likely nearby false positive). Between the two regimes the statistic is inconclusive: it withholds validation but is not evidence against the signal.

OrbitLab method:

1. Parse TIC ID from target.
2. Parse TESS sector from `product_uri`.
3. Phase-fold time around the candidate epoch.
4. Bin the folded curve to approximately 100 bins.
5. Estimate `flux_err` from residual standard deviation.
6. Instantiate `triceratops.triceratops.target(ID=tic_id, sectors=np.array([sector]))`.
7. Call:

```python
target.calc_probs(
    time=binned_time,
    flux_0=binned_flux,
    flux_err_0=flux_err,
    P_orb=float(candidate.period),
    N=int(samples),
    parallel=parallel,
    verbose=0,
)
```

8. Emit:

```text
fpp = target.FPP
nfpp = target.NFPP
samples = 1000000
```

Current thresholds:

```text
paper_triceratops_fpp_max = 0.015      # validation ceiling
paper_triceratops_nfpp_max = 0.001     # validation ceiling
paper_triceratops_fpp_reject = 0.5     # likely-false-positive floor
paper_triceratops_nfpp_reject = 0.1    # likely-nearby-false-positive floor
paper_triceratops_samples = 1000000
```

Threshold semantics map TRICERATOPS' three regimes onto OrbitLab flags: values within the validation ceilings add no flags; values above a rejection floor are evidence-against hard fails (`triceratops_fpp` / `triceratops_nfpp`); values in between raise soft review warnings (`triceratops_fpp_inconclusive` / `triceratops_nfpp_inconclusive`) that block paper-grade statistical validation without branding the signal a false positive — confirmed planets routinely land in this gray zone.

One-to-one alignment:

OrbitLab uses the real `triceratops` package and the paper's validation thresholds.

TRILEGAL resilience:

TRICERATOPS queries the TRILEGAL galactic model at `stev.oapd.inaf.it`, whose server omits its ZeroSSL intermediate certificate, so default verification fails. OrbitLab repairs the chain client-side: it AIA-chases the published intermediate, appends it to the certifi bundle (`.orbitlab/calibration/trilegal-ca-bundle.pem`), and scopes `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE` to the TRICERATOPS call. Verification still anchors at a trusted certifi root — this is chain repair, never `verify=False`. Successful TRILEGAL results are cached per TIC under `.orbitlab/calibration/trilegal/` and replayed through TRICERATOPS' native `trilegal_fname` parameter, making paper-grade runs reproducible and resilient to the service's outages. The payload reports `trilegal_source` (`cached_file`, `live_query`, or `unavailable_scenarios_reduced`). When targets are searched by name, the TIC id is recovered from the product URI.

Methodology delta:

TRICERATOPS with follow-up constraints (contrast curves, spectroscopy) remains stronger than OrbitLab's wrapper. OrbitLab calls `calc_depths` with TRICERATOPS' validated default 5x5 aperture because the selected TPF aperture is in a different pixel frame; passing that aperture safely requires future WCS conversion. OrbitLab does not yet supply follow-up observation constraints.

## Nigraha TESS ML

Relevant implementation:

- `backend/orbitlab/ml/nigraha_adapter.py`
- `backend/orbitlab/ml/nigraha_service.py`
- `scripts/fetch_nigraha_weights.py`

Research methodology:

- Nigraha is a neural-network-based TESS candidate pipeline.
- ASCL summarizes it as using high-SNR shallow transits, supervised ML, and detailed vetting to identify candidates missed by previous searches.
- The Nigraha repository describes preparing global/local views and generating scores for TCEs.

OrbitLab tensor contract:

| Input           | Shape         | Construction                                                                                  |
| --------------- | ------------- | --------------------------------------------------------------------------------------------- |
| `global_view`   | `(1, 201, 1)` | Full folded curve binned to 201 bins.                                                         |
| `local_view`    | `(1, 81, 1)`  | Window around primary transit, width based on duration/period.                                |
| `odd_even_view` | `(1, 162, 1)` | Concatenated secondary/half-period local view plus primary local view.                        |
| Scalars         | `(1, 1)` each | Depth, duration, Teff, radius, logg, mass, luminosity, density, rp/rs, even depth, odd depth. |

Scaling:

```text
arr = flux - median(flux)
scale = abs(min(arr)) or std(arr)
scaled = (arr / scale) * 2 + 1
```

Model execution:

1. Registered artifact path is read from the artifact registry.
2. The path must be a directory.
3. Exactly 10 `models_*.hdf5` files must exist.
4. SHA-256 directory checksum must match the registry.
5. HDF5 weights are loaded into a NumPy implementation of the Nigraha architecture.
6. The ensemble score is the mean of the 10 model outputs.

Current paper threshold:

```text
paper_ml_threshold = 0.4
```

Cadence domain guard:

Nigraha's ensemble was trained on 2-minute SPOC cadence. When the analyzed product's median cadence exceeds 300 s (FFI-derived 10/30-minute products), the score is marked `cadence_out_of_domain`: it contributes a neutral ML component to evidence scoring, and paper-grade promotion blocks on `nigraha_out_of_domain` as missing evidence rather than judging an out-of-domain number. Product listings carry `cadence_seconds` and rank short-cadence products first so the ML surface runs in-domain whenever the archive offers it.

One-to-one alignment:

OrbitLab uses the released Nigraha HDF5 weights and reproduces inference with local NumPy operations rather than requiring TensorFlow for the TESS ensemble. It preserves artifact checksums and input tensor checksums.

Methodology delta:

The full Nigraha repository pipeline includes sector-by-sector catalog construction, TFRecord generation, training, and TOI catalog federation. OrbitLab attaches the inference side and tensorization but does not reproduce the full upstream training and catalog-generation workflow. The upstream Nigraha implementation is stronger for reproducing the original training/evaluation pipeline.

## Kepler AstroNet and K2 ExoMAC-KKT Evidence

Relevant implementation:

- `backend/orbitlab/ml/astronet_adapter.py`
- `backend/orbitlab/ml/service.py`
- `backend/orbitlab/ml/exomac_service.py`
- `docs/model_artifacts.md`
- `docs/MODEL_CARDS.md`

Research methodology:

- Shallue and Vanderburg trained a deep convolutional neural network to classify Kepler signals as transiting exoplanets or false positives and reported that it ranked plausible planets higher than false positives 98.8 percent of the time in their test set.
- OrbitLab uses Kepler/K2 ML only as supporting evidence.

OrbitLab method:

- Kepler/K1: AstroNet-family global/local folded views are passed to a registered checkpoint/runtime or compatible artifact.
- K2: ExoMAC-KKT is a registered sklearn bundle with fixed catalog features.
- Both require artifact registration and checksum validation.

Methodology delta:

Published AstroNet work is a Kepler-focused neural ranking/triage method, not a universal confirmation engine. OrbitLab therefore keeps ML evidence subordinate to physics, vetting, data quality, and paper-grade gates.

## Planet Physics and Habitability Estimates

Relevant implementation:

- `backend/orbitlab/science/physics.py`
- `backend/orbitlab/science/pipeline.py`

Derived quantities:

```text
radius_ratio = sqrt(depth)
planet_radius_m = stellar_radius_solar * R_sun * radius_ratio
planet_radius_earth = planet_radius_m / R_earth

period_seconds = period_days * 86400
semi_major_axis_m = (G * M_star * period_seconds^2 / (4*pi^2))^(1/3)
semi_major_axis_au = semi_major_axis_m / AU

luminosity_solar = stellar_radius_solar^2 * (stellar_teff / 5778)^4
Teq = stellar_teff * sqrt(R_star_au / (2*a_au)) * (1 - A)^(1/4), with A = 0.3
```

Kopparapu habitable-zone model:

```text
S_eff = S_eff_sun + a*T_* + b*T_*^2 + c*T_*^3 + d*T_*^4
T_* = stellar_teff - 5780
distance_au = sqrt(luminosity_solar / S_eff)
```

Current limits used:

| Boundary           | Use                |
| ------------------ | ------------------ |
| Recent Venus       | optimistic inner   |
| Runaway greenhouse | conservative inner |
| Maximum greenhouse | conservative outer |
| Early Mars         | optimistic outer   |

Stellar context resolution:

Physics consumes the merged stellar context with per-field provenance, in trust order: (1) explicit analysis-job values, (2) the curated `known_targets` entry, (3) the live TIC catalog row. Solar-like defaults apply only when every source is empty; in that case `interpretation_locked` is set, the physics fields are flagged, and habitability is marked insufficiently constrained. Locked physics is a review warning for the candidate, not a candidacy veto, because the transit detection itself is flux-relative evidence.

Methodology delta:

When stellar radius and mass are not available from any source, OrbitLab uses solar-like defaults only for physics continuity and marks habitability as insufficiently constrained. This is useful for display, not for a scientific habitability claim. Kopparapu-style habitable-zone analysis is stronger when stellar parameters and uncertainties are measured.

## Evidence Scoring

Relevant implementation:

- `backend/orbitlab/science/evidence.py`
- `backend/orbitlab/science/pipeline.py`

Red-noise beta (estimated on out-of-transit residuals only — a real transit is a coherent dip, so binned scatter that includes it inflates beta and punishes exactly the strongest signals; Pont, Zucker & Queloz 2006 estimate correlated noise on residuals after the transit model is removed):

```text
white_sigma = std(residuals)
for bin_size in (5, 10, 20, 40):
    binned = mean(residuals grouped by bin_size)
    expected = white_sigma / sqrt(bin_size)
    beta_i = max(1, std(binned) / expected)
red_noise_beta = median(beta_i)
effective_snr = raw_snr / red_noise_beta
```

Phase coverage:

```text
phase = ((time - epoch) % period) / period
phase_coverage_score = occupied_phase_bins / 24
```

Final score:

```text
final_score =
    0.25 * detection_score
  + 0.20 * vetting_score
  + 0.15 * data_quality_score
  + 0.15 * centroid_score
  + 0.10 * physics_plausibility_score
  + 0.15 * ml_component
```

The score is a ranking/explanation aid. Promotion still depends on hard gates.

## Paper-Grade Gate Matrix

Relevant implementation:

- `backend/orbitlab/science/pipeline.py`
- `backend/orbitlab/science/science_config.toml`

| Gate                  | Config                        | Current value | Severity on failure                                    | Purpose                                                    |
| --------------------- | ----------------------------- | ------------: | ------------------------------------------------------ | ---------------------------------------------------------- |
| Effective SNR         | `paper_promotion_snr`         |           7.1 | hard fail                                              | Require strong signal before paper promotion.              |
| Observed transits     | `paper_min_transits`          |             2 | hard fail                                              | Reject single-event promotions.                            |
| TLS SDE               | `paper_tls_sde_min`           |           7.0 | hard fail                                              | Require published TLS-style detection strength.            |
| TLS transit count     | `paper_min_transits`          |             2 | hard fail                                              | Ensure repeated TLS support.                               |
| DAVE ModShift         | official binary status        |     pass/fail | hard fail                                              | Reject non-transit-like or significant secondary behavior. |
| DAVE SWEET            | `paper_sweet_sigma`           |           3.0 | warning or hard fail if not complete                   | Flag sinusoidal variability.                               |
| Nigraha probability   | `paper_ml_threshold`          |           0.4 | warning if low, hard fail if absent for TESS paper run | Require supporting TESS ML evidence.                       |
| TRICERATOPS FPP       | `paper_triceratops_fpp_max`   |         0.015 | warning above (inconclusive)                           | Statistical validation false-positive ceiling.             |
| TRICERATOPS FPP       | `paper_triceratops_fpp_reject` |          0.5 | hard fail above                                        | Giacalone et al. 2021 likely-false-positive criterion.     |
| TRICERATOPS NFPP      | `paper_triceratops_nfpp_max`  |         0.001 | warning above (inconclusive)                           | Nearby false-positive validation ceiling.                  |
| TRICERATOPS NFPP      | `paper_triceratops_nfpp_reject` |         0.1 | hard fail above                                        | Likely-nearby-false-positive criterion.                    |
| Catalog contamination | `paper_catalog_radius_arcsec` |    120 arcsec | warning                                                | Identify nearby stars capable of mimicking depth.          |

## Module-by-Module Research Comparison

| OrbitLab module                   | What OrbitLab does                                                                                                                       | Paper/reference method                                                | GitHub/reference implementation                | One-to-one status                                                         | Where the paper/reference is better                                                      |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `mast.py`                         | Searches/downloads mission products and extracts TPF light curves.                                                                       | SPOC/MAST mission products and DV products.                           | MAST, Lightkurve/Astroquery ecosystem.         | Uses real archive products.                                               | SPOC DV is stronger for calibrated mission-scale TCE products.                           |
| `data_quality.py`                 | Removes invalid/quality cadences and supports manual artifact masks.                                                                     | Mission quality masks and calibrated data conditioning.               | Lightkurve/Astroquery mission products.        | Partial.                                                                  | Mission pipelines model systematics more deeply.                                         |
| `detrending.py`                   | Runs `wotan.flatten(..., method="biweight")`.                                                                                            | Wotan biweight recommended for shallow-transit recovery.              | `hippke/wotan`.                                | Strong for biweight detrending.                                           | Wotan paper's method selection is better for special variability classes.                |
| `detrending_sensitivity.py`       | Re-runs local candidate recovery across raw cleaned flux, Wotan windows, and transit-masked detrending.                                  | Robust transit validation should not depend on one flattening choice. | Wotan plus OrbitLab BLS recovery checks.       | Local stress test attached to deep/paper results.                         | Full injection-calibrated detrending model selection remains stronger.                   |
| `bls.py`                          | Runs Astropy BLS with adaptive period/duration grid, binning, robust SNR.                                                                | Kovacs et al. BLS box model.                                          | `astropy.timeseries.BoxLeastSquares`.          | Uses reference BLS implementation.                                        | Survey-calibrated BLS false-alarm behavior is stronger than local thresholding.          |
| `tls_refinement.py`               | Runs `transitleastsquares` for paper primary and deep refinement.                                                                        | Hippke and Heller TLS.                                                | `hippke/tls`.                                  | Strong. Uses real package.                                                | Runtime does not recalibrate SDE for every target population.                            |
| `injection_recovery.py`           | Injects box and smooth TLS-like transits into light curves, reruns recovery, and reports sensitivity summaries.                          | Kepler/TLS injection-retrieval methodology.                           | Local injection plus Astropy BLS recovery.     | Attached for deep/paper analyses and benchmark grids.                     | Pixel-level mission injection campaigns remain stronger.                                 |
| `sector_consistency.py`           | Emits per-sector period, depth, SNR, centroid, and aperture evidence; marks single-product runs as `single_sector_only`.                 | TESS/Kepler DV-style multi-sector consistency review.                 | Local BLS plus pixel diagnostics.              | Attached to every TCE payload.                                            | Full stitched multi-sector product retrieval and joint fitting remain stronger.          |
| `pipeline.py`                     | Builds TCE ledger, applies gates, emits evidence.                                                                                        | Kepler/TESS candidate triage separates TCEs from planet candidates.   | Local OrbitLab orchestration.                  | Local synthesis.                                                          | Full mission DV/Robovetter pipelines are more exhaustive.                                |
| `validation.py`                   | Odd/even, secondary, duration, harmonic, centroid checks.                                                                                | DV and vetting diagnostics.                                           | Local implementation.                          | Partial.                                                                  | Formal DV diagnostics are stronger.                                                      |
| `tpf_diagnostics.py`              | Difference-image and aperture stability evidence from pixel cube.                                                                        | DV centroid and PRF diagnostics.                                      | Local implementation.                          | Partial.                                                                  | PRF centroiding is better for source localization.                                       |
| `dave_vetting.py` ModShift        | Calls official DAVE `modshift` binary.                                                                                                   | DAVE ModShift.                                                        | `exoplanetvetting/DAVE`.                       | Strong for ModShift executable.                                           | Full DAVE pipeline has more context.                                                     |
| `dave_vetting.py` RoboVet         | Applies exact upstream inequalities.                                                                                                     | DAVE `RoboVet.py`.                                                    | `.orbitlab/external/DAVE/vetting/RoboVet.py`.  | Strong for copied logic.                                                  | Full DAVE end-to-end trap-fit context remains stronger.                                  |
| `dave_vetting.py` SWEET           | Fits sin/cos harmonics at P/2, P, 2P.                                                                                                    | DAVE SWEET sinusoid screen.                                           | DAVE vetting family.                           | Approximate.                                                              | Official SWEET in full DAVE is better for exact reproduction.                            |
| `catalog_context.py`              | TIC/Gaia neighbor screening and NASA Archive TOI/confirmed context.                                                                      | TESS follow-up context and archive federation.                        | Astroquery MAST and NASA Archive.              | Strong for live catalog/API use.                                          | Does not replace follow-up observations.                                                 |
| `triceratops_fpp.py`              | Calls real `target.calc_depths` with TRICERATOPS' own default 5x5 aperture, then `target.calc_probs`, and emits FPP/NFPP and scenario probabilities. | TRICERATOPS Bayesian FPP/NFPP with nearby-source context.             | `stevengiacalone/triceratops`.                 | Strong for `calc_probs` and thresholds; selected-TPF-aperture coordinates are not passed across the incompatible pixel frame. | WCS-converted aperture, contrast-curve, and follow-up-observation constraints remain stronger when available. |
| `nigraha_adapter.py`              | Builds global/local/odd-even tensors and scalar features.                                                                                | Nigraha TESS CNN input representation.                                | `ExoplanetML/Nigraha`.                         | Partial.                                                                  | Full upstream TFRecord/training/catalog workflow is stronger.                            |
| `nigraha_service.py`              | Runs checksum-validated 10-HDF5 ensemble in NumPy.                                                                                       | Nigraha supervised ML ensemble.                                       | `ExoplanetML/Nigraha`.                         | Strong for inference from released weights.                               | Upstream TensorFlow pipeline is stronger for exact training reproduction.                |
| `benchmarks/science_benchmark.py` | Runs a truth-set harness over known-planet, injected, false-positive, scrambled, and stellar-variability cases.                          | Kepler DR25 completeness/reliability benchmark discipline.            | Local benchmark runner.                        | Attached as a repeatable project check.                                   | NASA archive-scale benchmark products are broader and calibrated on mission populations. |
| `evidence_packet.py`              | Exports manifests, light curves, periodograms, folded curves, vetting, catalog, TRICERATOPS, ML, and final disposition files.            | Follow-up review depends on reproducible evidence packets.            | Local exporter.                                | Strong for OrbitLab payload reproducibility.                              | Formal mission DV reports include many more specialized diagnostics.                     |
| `physics.py`                      | Calculates radius, semi-major axis, Teq, Kopparapu HZ.                                                                                   | Kepler's law, transit depth, Kopparapu HZ.                            | Local implementation from published equations. | Strong for equations, weak when stellar inputs absent.                    | Stellar characterization with uncertainties is better.                                   |
| `App.tsx`                         | Shows Accuracy/paper mode by default and evidence panels.                                                                                | Scientific review workflow requires visible evidence.                 | Local UI.                                      | Product implementation.                                                   | Expert vetting tools may expose deeper plots and raw products.                           |

## Exact Threshold Registry

All current thresholds are in `backend/orbitlab/science/science_config.toml`.

```text
promotion_snr = 6.0
borderline_snr_min = 4.5
aperture_percentiles = [80, 85, 90, 92, 95]
max_duration_period_ratio = 0.2
secondary_eclipse_hard_fail_snr = 5.0
odd_even_hard_fail_sigma = 3.0
odd_even_large_effect_fraction = 0.2
transit_support_depth_fraction = 0.5
centroid_hard_fail_pixels = 1.0
quality_flag_dominance_fraction = 0.5
red_noise_warning_beta = 1.5
forced_period_tolerance_fraction = 0.01
paper_promotion_snr = 7.1
paper_tls_sde_min = 7.0
paper_min_transits = 2
paper_ml_threshold = 0.4
paper_sweet_sigma = 3.0
paper_model_shift_objects = 20000
paper_triceratops_fpp_max = 0.015
paper_triceratops_nfpp_max = 0.001
paper_triceratops_fpp_reject = 0.5
paper_triceratops_nfpp_reject = 0.1
paper_triceratops_samples = 1000000
paper_catalog_radius_arcsec = 120.0
```

## API and Storage Methodology

Relevant implementation:

- `backend/orbitlab/api/main.py`
- `backend/orbitlab/api/schemas.py`
- `backend/orbitlab/storage/orm.py`
- `backend/orbitlab/worker.py`

Job schema:

```text
AnalysisJobCreate:
  target_id
  product_uri
  mission in {"TESS", "Kepler", "K2"}
  aperture_mask_id
  artifact_mask_id
  max_candidates: 1..8
  vetting_mode: "paper" | "deep" | "fast", default "paper"
  optional stellar context
```

Result schema:

```text
AnalysisResult:
  schema_version
  pipeline_version
  science_config_hash
  vetting_mode
  search_profile
  data_quality
  tces
  planet_candidates
  validation_status
  engine_status
  deep_mode_progress
  injection_recovery
  periodogram
  folded_curves
  light_curve
  bls_light_curve
  stellar_context
  preprocessing
```

Storage behavior:

1. API creates an `AnalysisJobRecord`.
2. Worker marks job `running`.
3. Worker extracts product data.
4. Worker calls `analyze_light_curve_arrays`.
5. Worker stores one `AnalysisResultRecord`.
6. Worker marks job `complete`.
7. On exception, worker marks job `failed` with the error text.

This is important scientifically because execution errors are not converted into successful planet claims.

## Frontend UX Methodology

Relevant implementation:

- `frontend/src/App.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/components/SciencePlot.tsx`
- `frontend/src/components/OrbitScene.tsx`

Default accuracy behavior:

```text
const [vettingMode, setVettingMode] = useState<VettingMode>("paper")
normalizeVettingMode(value) -> "paper" unless value is "deep" or "fast"
```

The advanced selector labels the default as `Accuracy (paper-grade)`. The workbench exposes:

- Periodogram.
- Folded curve.
- Light curve.
- TCE ledger.
- Candidate evidence scores.
- Flags with severity.
- DAVE RoboVet disposition.
- SWEET status.
- TRICERATOPS status, FPP, NFPP.
- Catalog status.
- TOI match count.
- Known confirmed planet count.
- Nearby capable source count.
- ML model probabilities and artifact readiness.

Scientific UX intent:

The UI is not a "planet discovery scoreboard." It is an evidence review surface. Borderline TCEs remain visible for review even when not promoted.

## Verification and Tests

Relevant implementation:

- `backend/tests/test_paper_grade_engines.py`
- `backend/tests/test_tce_vetting.py`
- `backend/tests/test_science_hardening.py`
- `backend/tests/test_final_fixes.py`
- `scripts/preflight.sh`

High-value coverage:

| Test area           | Evidence covered                                                               |
| ------------------- | ------------------------------------------------------------------------------ |
| Paper-grade engines | Wotan package call, catalog context, TRICERATOPS wrapper, DAVE RoboVet parser. |
| TCE vetting         | Dispositions, paper-grade required engines, threshold-driven promotion.        |
| Science hardening   | BLS reliability, numeric candidate evidence, validation behavior.              |
| Final fixes         | Regression coverage from previous OrbitLab reliability passes.                 |
| Frontend tests      | UI state, Playwright evidence rendering, production build.                     |

Recommended verification commands:

```bash
.venv/bin/ruff check backend/orbitlab backend/tests
.venv/bin/pytest backend/tests/test_paper_grade_engines.py backend/tests/test_tce_vetting.py
npm --prefix frontend run lint
npm --prefix frontend run build
scripts/preflight.sh
```

DAVE binary verification:

```bash
scripts/build_dave_modshift.sh
test -x .orbitlab/external/DAVE/vetting/modshift
```

Dependency import verification:

```bash
.venv/bin/python -c "import numpy, wotan, transitleastsquares, triceratops; print('science imports ok')"
```

## Known Methodology Deltas and Honest Limits

This section is intentionally blunt.

1. SPOC/TESS DV is stronger for production mission catalogs.
   OrbitLab starts from selected products and exposes candidate evidence. It does not reproduce the whole SPOC TPS/DV system.

2. TLS is attached through the real package, and OrbitLab now runs local box/TLS-like injection-recovery checks.
   The paper's SDE discussion is still used as a threshold anchor; OrbitLab does not yet replace mission-population false-positive calibration for every sector, cadence, aperture, and stellar-noise regime.

3. Wotan is attached through the real package, but paper-grade mode uses fixed biweight detrending.
   The Wotan paper's broader method comparison is stronger for young stars, high-variability stars, or cases where a spline/Huber method is better.

4. DAVE ModShift and RoboVet are attached one-to-one only for the compiled ModShift binary and RoboVet inequalities.
   OrbitLab does not run the full DAVE legacy Python2/Octave/Gnuplot/PRF pipeline.

5. SWEET is DAVE-style, not a direct full DAVE submodule call.
   It fits harmonic sinusoids and provides useful evidence, but exact DAVE SWEET reproducibility would require the full upstream execution environment.

6. TRICERATOPS uses the real package and validation thresholds, but current OrbitLab does not pass the selected aperture into TRICERATOPS.
   The TRICERATOPS tutorial's aperture-aware `calc_depths` path and follow-up constraints are stronger.

7. TIC/Gaia contamination checks are catalog screens, not follow-up observations.
   Nearby-source warnings should be treated as "needs review" evidence, not definitive astrophysical rejection.

8. Nigraha inference is attached, but not the full upstream training/catalog-generation workflow.
   OrbitLab validates and runs the released weights; it does not recreate the entire paper's training data and sector-by-sector catalog production.

9. ML is not confirmation.
   OrbitLab uses ML as supporting evidence only. A high ML probability does not override DAVE, TRICERATOPS, centroid, secondary eclipse, or data-quality hard failures.

10. Habitability estimates are only as good as stellar context.
    When stellar context is missing, OrbitLab marks habitability as insufficiently constrained and avoids a real habitability claim.

11. A promoted `planet_candidate` is still not a confirmed planet.
    It is a high-priority follow-up candidate under OrbitLab's evidence policy.

## Reproducibility Contract

To reproduce paper-grade behavior:

1. Install the project with science dependencies.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,science,api,ml]"
```

2. Build the DAVE ModShift executable.

```bash
scripts/build_dave_modshift.sh
```

3. Fetch required ML artifacts.

```bash
scripts/fetch_nigraha_weights.py
scripts/fetch_kepler_astronet.py
scripts/fetch_k2_exomac_kkt.py
```

4. Run preflight.

```bash
scripts/preflight.sh
```

5. Start the app.

```bash
scripts/start_all.sh
```

6. Run analysis in default Accuracy/paper mode.

Expected result semantics:

- `tces` should contain reviewable events.
- `planet_candidates` should contain only promoted events.
- `engine_status` should disclose engine completion.
- `science_config_hash` should identify the threshold configuration used.
- `paper_grade.thresholds` should show the exact promotion gates.
- `flags` should explain warnings and hard failures.

## Source References

Primary and implementation references used for this methodology document:

- Transit Least Squares GitHub: https://github.com/hippke/tls
- Transit Least Squares paper: https://arxiv.org/abs/1901.02015
- Transit Least Squares docs: https://transitleastsquares.readthedocs.io/
- Wotan GitHub: https://github.com/hippke/wotan
- Wotan paper: https://arxiv.org/abs/1906.00966
- Astropy BoxLeastSquares docs: https://docs.astropy.org/en/stable/api/astropy.timeseries.BoxLeastSquares.html
- BLS paper: https://arxiv.org/abs/astro-ph/0206099
- DAVE GitHub: https://github.com/exoplanetvetting/DAVE
- DAVE paper: https://arxiv.org/abs/1901.07459
- TRICERATOPS docs: https://triceratops.readthedocs.io/
- TRICERATOPS TESS tutorial: https://triceratops.readthedocs.io/en/latest/tutorials/example.html
- TRICERATOPS paper: https://arxiv.org/abs/2002.00691
- Nigraha GitHub: https://github.com/ExoplanetML/Nigraha
- Nigraha ASCL entry: https://ascl.net/2101.011
- Nigraha paper: https://arxiv.org/abs/2101.09227
- TESS-SPOC MAST products: https://archive.stsci.edu/hlsp/tess-spoc
- NASA Exoplanet Archive TAP docs: https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html
- Astroquery NASA Exoplanet Archive docs: https://astroquery.readthedocs.io/en/latest/ipac/nexsci/nasa_exoplanet_archive.html
- Lightkurve data product guide: https://lightkurve.github.io/lightkurve/tutorials/1-getting-started/searching-for-data-products.html
- AstroNet paper: https://arxiv.org/abs/1712.05044
- Google Research AstroNet page: https://research.google/pubs/identifying-exoplanets-with-deep-learning-a-five-planet-resonant-chain-around-kepler-80-and-an-eighth-planet-around-kepler-90/
- Kopparapu et al. 2014 habitable zones: https://arxiv.org/abs/1404.5292

## Final Scientific Position

OrbitLab is now best described as a transparent, real-data, paper-method-attached exoplanet candidate workbench. It is not a replacement for SPOC, DAVE end-to-end, TRICERATOPS with full aperture/follow-up constraints, or expert astronomical validation. Its strength is that each promoted candidate carries a visible chain of evidence from archive product to light curve, search result, vetting metrics, ML support, catalog context, FPP/NFPP, and final disposition.

The correct scientific reading of an OrbitLab result is:

```text
This signal is a real TCE found in real mission data. Its displayed disposition describes how it performed under OrbitLab's current evidence gates. Promotion means follow-up priority, not confirmed planet status.
```
