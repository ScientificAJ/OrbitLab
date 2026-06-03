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
| `models` | 200 | 3.02 |
| `search` | 200 | 2.74 |
| `products` | 200 | 14.1 |
| `tpf_preview` | 200 | 0.365 |
| `aperture_mask` | 201 | 0.012 |
| `bls_preview` | 200 | 3.5 |
| `analysis_job_create` | 201 | 0.013 |
| `analysis_result` | 200 | 0.031 |
| `report` | 200 | 0.027 |
| `save_session` | 201 | 0.009 |
| `sessions` | 200 | 0.004 |
| `analysis_job_poll` | 200 | 35 polls, status `complete` |

## Science Snapshot

- Preview TCEs: `3`
- Analysis ledger entries: `2`
- Periodogram samples: `4096` periods, `4096` powers
- Folded curves: `2`
- `candidates` / `planet_candidates` alias match: `True`

## Analysis Candidate Ledger

| ID | Period d | Duration h | Depth ppm | SNR | Disposition | Action | Readiness | ML | Catalog |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `tess-TIC 25155310-tce-1` | 3.29101 | 3.539 | 9.9323e+05 | 68.18 | rejected_signal | none | blocked | not-transit-like | - |
| `tess-TIC 25155310-tce-2` | 0.101461 | 1.92 | 100.12 | 7.073 | rejected_signal | none | blocked | not-transit-like | - |

## Quarantined Artifacts

- `tess-TIC 25155310-tce-1` is quarantined as `rejected_signal`: implausibly deep signal (99.32% depth).
- `tess-TIC 25155310-tce-2` is quarantined as `rejected_signal`: large duration/period ratio (0.7885).

## Findings

- No automated scientific/API consistency findings.
