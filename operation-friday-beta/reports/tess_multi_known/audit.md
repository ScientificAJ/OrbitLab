# Operation Friday Beta Audit: tess_multi_known

- Query: `TOI-700`
- Mission: `TESS`
- Purpose: Known multi-planet TESS target and alias/catalog context check.
- Status: `pass`

## Selected Target/Product

- Target: `TOI-700`
- Product ID: `60474103`
- Product URI: `mast:HLSP/tess-spoc/s0006/target/0000/0001/5042/8135/hlsp_tess-spoc_tess_phot_0000000150428135-s0006_tess_v1_tp.fits`

## API Flow Evidence

| Step | HTTP | Elapsed s |
| --- | ---: | ---: |
| `health` | 200 | 0.052 |
| `models` | 200 | 3.04 |
| `search` | 200 | 3.29 |
| `products` | 200 | 21.3 |
| `tpf_preview` | 200 | 0.385 |
| `aperture_mask` | 201 | 0.011 |
| `bls_preview` | 200 | 3.71 |
| `analysis_job_create` | 201 | 0.011 |
| `analysis_result` | 200 | 0.026 |
| `report` | 200 | 0.028 |
| `save_session` | 201 | 0.011 |
| `sessions` | 200 | 0.008 |
| `analysis_job_poll` | 200 | 32 polls, status `complete` |

## Science Snapshot

- Preview TCEs: `4`
- Analysis ledger entries: `2`
- Periodogram samples: `4096` periods, `4096` powers
- Folded curves: `2`
- `candidates` / `planet_candidates` alias match: `True`

## Analysis Candidate Ledger

| ID | Period d | Duration h | Depth ppm | Depth source | SNR | Disposition | Action | Readiness | ML | Catalog |
| --- | ---: | ---: | ---: | --- | ---: | --- | --- | --- | --- | --- |
| `tess-TOI-700-tce-1` | 3.12649 | 2.209 | 536.2 | phase_window_median | 4.941 | rejected_signal | none | blocked | not-transit-like | - |
| `tess-TOI-700-tce-2` | 0.116755 | 1.92 | 142.7 | astropy_box_least_squares | 6.735 | rejected_signal | none | blocked | not-transit-like | - |

## Quarantined Artifacts

- `tess-TOI-700-tce-2` is quarantined as `rejected_signal`: large duration/period ratio (0.6852).

## Findings

- No automated scientific/API consistency findings.
