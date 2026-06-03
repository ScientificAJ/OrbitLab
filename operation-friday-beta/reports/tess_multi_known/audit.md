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
| `health` | 200 | 0.005 |
| `models` | 200 | 4.06 |
| `search` | 200 | 3.77 |
| `products` | 200 | 24.7 |
| `tpf_preview` | 200 | 0.394 |
| `aperture_mask` | 201 | 0.015 |
| `bls_preview` | 200 | 3.92 |
| `analysis_job_create` | 201 | 0.01 |
| `analysis_result` | 200 | 0.039 |
| `report` | 200 | 0.036 |
| `save_session` | 201 | 0.012 |
| `sessions` | 200 | 0.003 |
| `analysis_job_poll` | 200 | 35 polls, status `complete` |

## Science Snapshot

- Preview TCEs: `4`
- Analysis ledger entries: `2`
- Periodogram samples: `4096` periods, `4096` powers
- Folded curves: `2`
- `candidates` / `planet_candidates` alias match: `True`

## Analysis Candidate Ledger

| ID | Period d | Duration h | Depth ppm | SNR | Disposition | Action | Readiness | ML | Catalog |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `tess-TOI-700-tce-1` | 3.12649 | 2.209 | 9.9924e+05 | 6.198 | rejected_signal | none | blocked | not-transit-like | - |
| `tess-TOI-700-tce-2` | 0.116755 | 1.92 | 142.7 | 6.735 | rejected_signal | none | blocked | not-transit-like | - |

## Quarantined Artifacts

- `tess-TOI-700-tce-1` is quarantined as `rejected_signal`: implausibly deep signal (99.92% depth).
- `tess-TOI-700-tce-2` is quarantined as `rejected_signal`: large duration/period ratio (0.6852).

## Findings

- No automated scientific/API consistency findings.
