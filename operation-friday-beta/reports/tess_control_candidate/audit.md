# Operation Friday Beta Audit: tess_control_candidate

- Query: `TIC 25155310`
- Mission: `TESS`
- Purpose: Control-style real TESS target where no confirmed planet is assumed by this operation.
- Status: `pass`

## Selected Target/Product

- Target: `TIC 25155310`
- Product ID: `60516122`
- Product URI: `mast:HLSP/tess-spoc/s0006/target/0000/0000/2515/5310/hlsp_tess-spoc_tess_phot_0000000025155310-s0006_tess_v1_tp.fits`

## API Flow Evidence

| Step | HTTP | Elapsed s |
| --- | ---: | ---: |
| `health` | 200 | 0.003 |
| `models` | 200 | 3.38 |
| `search` | 200 | 3.15 |
| `products` | 200 | 4.7 |
| `tpf_preview` | 200 | 0.384 |
| `aperture_mask` | 201 | 0.009 |
| `bls_preview` | 200 | 3.59 |
| `analysis_job_create` | 201 | 0.011 |
| `analysis_result` | 200 | 0.039 |
| `report` | 200 | 0.045 |
| `save_session` | 201 | 0.015 |
| `sessions` | 200 | 0.011 |
| `analysis_job_poll` | 200 | 54 polls, status `complete` |

## Science Snapshot

- Preview TCEs: `3`
- Analysis ledger entries: `2`
- Periodogram samples: `4096` periods, `4096` powers
- Folded curves: `2`
- `candidates` / `planet_candidates` alias match: `True`

## Analysis Candidate Ledger

| ID | Period d | Duration h | Depth ppm | Depth source | SNR | Disposition | Action | Readiness | ML | Catalog |
| --- | ---: | ---: | ---: | --- | ---: | --- | --- | --- | --- | --- |
| `tess-TIC 25155310-tce-1` | 3.29101 | 3.539 | 6403.7 | phase_window_median | 125.8 | rejected_signal | none | blocked | not-transit-like | - |
| `tess-TIC 25155310-tce-2` | 0.101461 | 1.92 | 100.12 | astropy_box_least_squares | 7.073 | rejected_signal | none | blocked | not-transit-like | - |

## Quarantined Artifacts

- `tess-TIC 25155310-tce-2` is quarantined as `rejected_signal`: large duration/period ratio (0.7885).

## Findings

- No automated scientific/API consistency findings.
