# Operation Friday Beta Audit: tess_known_hot_jupiter

- Query: `TIC 307210830`
- Mission: `TESS`
- Purpose: Known TESS demo target and hot-Jupiter style signal check.
- Status: `pass`

## Selected Target/Product

- Target: `TIC 307210830`
- Product ID: `62575661`
- Product URI: `mast:HLSP/tess-spoc/s0008/target/0000/0003/0721/0830/hlsp_tess-spoc_tess_phot_0000000307210830-s0008_tess_v1_tp.fits`

## API Flow Evidence

| Step | HTTP | Elapsed s |
| --- | ---: | ---: |
| `health` | 200 | 0.06 |
| `models` | 200 | 3.03 |
| `search` | 200 | 10.1 |
| `products` | 200 | 7.51 |
| `tpf_preview` | 200 | 0.369 |
| `aperture_mask` | 201 | 0.025 |
| `bls_preview` | 200 | 4.64 |
| `analysis_job_create` | 201 | 0.026 |
| `analysis_result` | 200 | 0.04 |
| `report` | 200 | 0.037 |
| `save_session` | 201 | 0.012 |
| `sessions` | 200 | 0.005 |
| `analysis_job_poll` | 200 | 51 polls, status `complete` |

## Science Snapshot

- Preview TCEs: `4`
- Analysis ledger entries: `4`
- Periodogram samples: `4096` periods, `4096` powers
- Folded curves: `4`
- `candidates` / `planet_candidates` alias match: `True`

## Analysis Candidate Ledger

| ID | Period d | Duration h | Depth ppm | Depth source | SNR | Disposition | Action | Readiness | ML | Catalog |
| --- | ---: | ---: | ---: | --- | ---: | --- | --- | --- | --- | --- |
| `tess-TIC 307210830-tce-1` | 3.68956 | 0.9714 | 1508.3 | phase_window_median | 16.54 | rejected_signal | none | blocked | not-transit-like | - |
| `tess-TIC 307210830-tce-2` | 9.31022 | 1.536 | 1031 | phase_window_median | 10.85 | rejected_signal | none | blocked | not-transit-like | - |
| `tess-TIC 307210830-tce-3` | 5.29476 | 1.536 | 1036.1 | phase_window_median | 11.2 | rejected_signal | none | blocked | not-transit-like | - |
| `tess-TIC 307210830-tce-4` | 0.100783 | 1.92 | 96.069 | astropy_box_least_squares | 9.582 | rejected_signal | none | blocked | not-transit-like | - |

## Quarantined Artifacts

- `tess-TIC 307210830-tce-4` is quarantined as `rejected_signal`: large duration/period ratio (0.7938).

## Findings

- No automated scientific/API consistency findings.
