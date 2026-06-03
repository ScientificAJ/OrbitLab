# Operation Friday Beta Audit: kepler_multi_known

- Query: `Kepler-10`
- Mission: `Kepler`
- Purpose: Kepler known-system check.
- Status: `pass`

## Selected Target/Product

- Target: `Kepler-10`
- Product ID: `582316`
- Product URI: `mast:KEPLER/url/missions/kepler/target_pixel_files/0119/011904151/kplr011904151-2009131105131_lpd-targ.fits.gz`

## API Flow Evidence

| Step | HTTP | Elapsed s |
| --- | ---: | ---: |
| `health` | 200 | 0.003 |
| `models` | 200 | 2.93 |
| `search` | 200 | 4 |
| `products` | 200 | 11.6 |
| `tpf_preview` | 200 | 0.373 |
| `aperture_mask` | 201 | 0.008 |
| `bls_preview` | 200 | 3.46 |
| `analysis_job_create` | 201 | 0.012 |
| `analysis_result` | 200 | 0.028 |
| `report` | 200 | 0.027 |
| `save_session` | 201 | 0.012 |
| `sessions` | 200 | 0.004 |
| `analysis_job_poll` | 200 | 14 polls, status `complete` |

## Science Snapshot

- Preview TCEs: `4`
- Analysis ledger entries: `2`
- Periodogram samples: `4096` periods, `4096` powers
- Folded curves: `2`
- `candidates` / `planet_candidates` alias match: `True`

## Analysis Candidate Ledger

| ID | Period d | Duration h | Depth ppm | Depth source | SNR | Disposition | Action | Readiness | ML | Catalog |
| --- | ---: | ---: | ---: | --- | ---: | --- | --- | --- | --- | --- |
| `kepler-Kepler-10-tce-1` | 0.835992 | 1.907 | 159.29 | phase_window_median | 20.9 | borderline_tce | review_needed | blocked | ml-unavailable | Kepler-10 b |
| `kepler-Kepler-10-tce-2` | 0.112908 | 1.92 | 24.759 | astropy_box_least_squares | 7.128 | rejected_signal | none | blocked | ml-unavailable | - |

## Quarantined Artifacts

- `kepler-Kepler-10-tce-2` is quarantined as `rejected_signal`: large duration/period ratio (0.7085).

## Findings

- No automated scientific/API consistency findings.
