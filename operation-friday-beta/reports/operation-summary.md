# Operation Friday Beta Summary

- Cases run: `5`

| Case | Mission | Target | Product | Audit | Findings |
| --- | --- | --- | --- | --- | ---: |
| tess_known_hot_jupiter | TESS | TIC 307210830 | 62575661 | pass | 0 |
| tess_multi_known | TESS | TOI-700 | 60474103 | pass | 0 |
| kepler_multi_known | Kepler | Kepler-10 | 582316 | pass | 0 |
| k2_multi_known | K2 | EPIC 201367065 | 1073804 | pass | 0 |
| tess_control_candidate | TESS | TIC 25155310 | 60516122 | pass | 0 |

## Notes

- Raw endpoint responses are stored under each case's `raw/` directory.
- `review_needed` means the automated audit found a possible scientific/API issue to inspect or fix.
- Per-case audits include API timing, candidate ledger semantics, folded/periodogram health, and quarantined artifacts.
