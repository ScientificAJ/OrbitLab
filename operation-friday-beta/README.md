# Operation Friday Beta

Status: live API sweep completed 2026-06-03.

Objective: use the OrbitLab API only to exercise the full user workflow on real archive data, inspect scientific/API inaccuracies, fix issues immediately, and write evidence-backed reports.

## Scope

The operation simulates the user workflow through API calls:

1. `GET /api/v1/health`
2. `GET /api/v1/models`
3. `GET /api/v1/search`
4. `GET /api/v1/targets/{target_id}/products`
5. `GET /api/v1/tpf-preview`
6. `POST /api/v1/aperture-masks`
7. `POST /api/v1/bls-preview`
8. `POST /api/v1/analysis-jobs`
9. `GET /api/v1/analysis-jobs/{job_id}`
10. `GET /api/v1/analysis-results/{result_id}`
11. `GET /api/v1/reports/{result_id}`
12. `POST /api/v1/sessions`
13. `GET /api/v1/sessions`

## Target Set

Chosen to cover known planet hosts, multi-planet systems, K2, Kepler, TESS, and a likely control/no-famous-planet target:

| Case                   | Query          | Mission | Purpose                                                                               |
| ---------------------- | -------------- | ------- | ------------------------------------------------------------------------------------- |
| tess_known_hot_jupiter | TIC 307210830  | TESS    | Known TESS demo target and hot-Jupiter style signal check.                            |
| tess_multi_known       | TOI-700        | TESS    | Known multi-planet target and alias/catalog context check.                            |
| kepler_multi_known     | Kepler-10      | Kepler  | Kepler known-system check.                                                            |
| k2_multi_known         | EPIC 201367065 | K2      | K2/ExoMAC model path and multi-planet system check.                                   |
| tess_control_candidate | TIC 25155310   | TESS    | Control-style real TESS target where no confirmed planet is assumed by the operation. |

## Report Outputs

- `reports/operation-summary.md`
- `reports/<case>/workflow.json`
- `reports/<case>/audit.md`
- `reports/<case>/raw/*.json`
- `reports/visual-audit/*.png`
- `reports/visual-audit/manual-visual-review.md`

## Result

The final API sweep completed all five cases with passing automated
scientific/API consistency audits:

- TESS `TIC 307210830`
- TESS `TOI-700`
- Kepler `Kepler-10`
- K2 `EPIC 201367065`
- TESS `TIC 25155310`

The audits now include endpoint timing, selected target/product, candidate
ledger semantics, periodogram/folded-curve health, alias consistency, and
quarantined artifacts. Quarantined artifacts are suspicious detections that
remain blocked or rejected; they are documented because the numbers are
science-facing even when the conclusion is safe.

A follow-up manual visual review rendered every saved workflow as a board with
the TPF aperture, periodogram, folded curves, candidate depth, SNR, disposition,
readiness, and depth provenance. That review found one real reporting bug:
TLS model depths could be scientifically misleading when used directly as
candidate depths. Candidate depth reporting now uses measured transit-window
depth when available and keeps the model depth as provenance.

The visual review conclusion is stricter than the API pass label: Kepler-10 is
the strongest transit-like recovery, but it remains blocked pending paper-grade
readiness; the TESS and K2 cases do not visually justify automated planet
promotion in this run.

## Fixes Made During The Operation

- Product selection now prefers mission-matching standard TPFs over large
  fast-cadence products.
- NASA Archive catalog context failures fall back instead of crashing analysis.
- TESS alias targets such as `TOI-700` resolve the numeric TIC ID before
  catalog-context lookup.
- TRICERATOPS/FPP failures are captured as blocked evidence instead of killing
  the analysis job.
- Analysis-result storage converts NumPy, masked, and Astropy quantity values
  into JSON-safe payloads.
- API `candidates` and `planet_candidates` aliases preserve the same TCE
  payload shape.
- Catalog-matched signals blocked by science-readiness gates cannot remain
  promoted as `planet_candidate`.
- BLS/TLS candidate depth reporting now prefers measured phase-window depth and
  records model depth, measured depth, and `depth_source` provenance.
- Visual audit boards and a manual review now distinguish API consistency from
  scientific visual confidence.
- Operation reports now expose timing, science snapshots, candidate ledgers,
  and quarantined artifacts from the real run.

## Trust Boundary

The operation can identify mismatches, weak evidence, broken API contracts,
suspicious period/folded-curve behavior, misleading result semantics, or
model/readiness problems. It does not convert API candidates into confirmed
planets. An automated `pass` means the API and payload contracts held together;
manual visual/scientific review is still required before treating a candidate as
planet-like.
