# OrbitLab TODO

## Submission Polish

- Add hosted demo URL after deployment is stable.
- Record a short walkthrough video with real MAST data and visible target/product IDs.
- Add fresh screenshots to `README.md`.
- Add a reproducible demo target list with known-good products and expected runtime notes.

## Deployment

- Add production deployment documentation for backend, worker, Redis/Postgres, and frontend.
- Decide on artifact storage for large model bundles outside git.
- Add environment-specific CORS and secret handling.
- Add deployment health checks for API, worker, database, Redis, and frontend.

## Science And ML

- Expand validation with centroid checks and stronger false-positive heuristics.
- Add richer stellar-context ingestion.
- Document and test model-input normalization for each mission adapter.
- Add golden API fixtures for `/api/v1/models`.
- Track public K2 AstroNet checkpoint availability without claiming support before an artifact exists.

## Product

- Improve empty and unavailable states in the frontend.
- Add saved demo sessions.
- Add exportable reports for judge handoff.
- Add clearer progress indicators for long MAST downloads and analysis jobs.

## Contributor Experience

- Keep CI green on backend tests and frontend builds.
- Add lightweight linting once formatting conventions settle.
- Add issue labels and a milestone plan after the hackathon.
- [x] Convert direct-push workflow to PR review when the team grows.
