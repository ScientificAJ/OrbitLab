# Operation Friday Beta Audit: k2_multi_known

- Query: `EPIC 201367065`
- Mission: `K2`
- Purpose: K2/ExoMAC model path and multi-planet system check.
- Status: `pass`

## Selected Target/Product

- Target: `EPIC 201367065`
- Product ID: `1073804`
- Product URI: `mast:K2/url/missions/k2/target_pixel_files/c1/201300000/67000/ktwo201367065-c01_lpd-targ.fits.gz`

## API Flow Evidence

| Step | HTTP | Elapsed s |
| --- | ---: | ---: |
| `health` | 200 | 0.004 |
| `models` | 200 | 3.52 |
| `search` | 200 | 2.64 |
| `products` | 200 | 2.21 |
| `tpf_preview` | 200 | 0.997 |
| `aperture_mask` | 201 | 0.012 |
| `bls_preview` | 200 | 7.02 |
| `analysis_job_create` | 201 | 0.011 |
| `analysis_result` | 200 | 0.041 |
| `report` | 200 | 0.047 |
| `save_session` | 201 | 0.008 |
| `sessions` | 200 | 0.005 |
| `analysis_job_poll` | 200 | 104 polls, status `complete` |

## Science Snapshot

- Preview TCEs: `3`
- Analysis ledger entries: `2`
- Periodogram samples: `6652` periods, `6652` powers
- Folded curves: `2`
- `candidates` / `planet_candidates` alias match: `True`

## Analysis Candidate Ledger

| ID | Period d | Duration h | Depth ppm | Depth source | SNR | Disposition | Action | Readiness | ML | Catalog |
| --- | ---: | ---: | ---: | --- | ---: | --- | --- | --- | --- | --- |
| `k2-EPIC 201367065-tce-1` | 10.0552 | 2.496 | 1264.5 | phase_window_median | 32.67 | borderline_tce | review_needed | blocked | confirmed | - |
| `k2-EPIC 201367065-tce-2` | 0.245543 | 1.92 | 53.883 | phase_window_median | 7.353 | rejected_signal | none | blocked | false-positive | - |

## Quarantined Artifacts

- `k2-EPIC 201367065-tce-2` is quarantined as `rejected_signal`: large duration/period ratio (0.3258).

## Findings

- No automated scientific/API consistency findings.
