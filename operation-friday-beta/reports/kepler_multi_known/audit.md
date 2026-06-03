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
| `models` | 200 | 3.85 |
| `search` | 200 | 3.1 |
| `products` | 200 | 0.024 |
| `tpf_preview` | 200 | 1.38 |
| `aperture_mask` | 201 | 0.011 |
| `bls_preview` | 200 | 3.52 |
| `analysis_job_create` | 201 | 0.011 |
| `analysis_result` | 200 | 0.029 |
| `report` | 200 | 0.027 |
| `save_session` | 201 | 0.011 |
| `sessions` | 200 | 0.004 |
| `analysis_job_poll` | 200 | 15 polls, status `complete` |

## Science Snapshot

- Preview TCEs: `4`
- Analysis ledger entries: `2`
- Periodogram samples: `4096` periods, `4096` powers
- Folded curves: `2`
- `candidates` / `planet_candidates` alias match: `True`

## Analysis Candidate Ledger

| ID | Period d | Duration h | Depth ppm | SNR | Disposition | Action | Readiness | ML | Catalog |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `kepler-Kepler-10-tce-1` | 0.835992 | 1.907 | 9.9983e+05 | 18.77 | borderline_tce | review_needed | blocked | ml-unavailable | Kepler-10 b |
| `kepler-Kepler-10-tce-2` | 0.112908 | 1.92 | 24.759 | 7.128 | rejected_signal | none | blocked | ml-unavailable | - |

## Quarantined Artifacts

- `kepler-Kepler-10-tce-1` is quarantined as `borderline_tce`: implausibly deep signal (99.98% depth).
- `kepler-Kepler-10-tce-2` is quarantined as `rejected_signal`: large duration/period ratio (0.7085).

## Findings

- No automated scientific/API consistency findings.
