# OrbitLab TODO

## Submission Polish

- Add hosted demo URL after deployment is stable.
- Record a short walkthrough video with real MAST data and visible target/product IDs.
- Add fresh screenshots to `README.md`.
- Dry-run the final demo script from `docs/DEMO_TARGETS.md` on the submission machine.
- Add final judging notes that explain real-data limits, artifact readiness, and report export.

## Deployment

- Add production deployment documentation for backend, worker, Redis/Postgres, and frontend.
- Decide on artifact storage for large model bundles outside git.
- Add environment-specific CORS and secret handling.
- Add deployment health checks for API, worker, database, Redis, and frontend.
- Add a rollback/restart checklist for the hosted demo.

## Science And ML

- Expand validation with centroid checks and stronger false-positive heuristics.
- Add richer stellar-context ingestion.
- Document and test model-input normalization for each mission adapter.

## Product

- Add saved demo sessions.
- Add a sample exported report fixture for judge handoff.
- Add clearer progress indicators for long MAST downloads and analysis jobs.
- Add a visible hosted-demo status banner when the backend is warming up or unavailable.

## Contributor Experience

- Keep CI green on backend tests and frontend builds.
- Add issue labels and a milestone plan after the hackathon.
- Document release tagging and changelog steps.
- [x] Convert direct-push workflow to PR review when the team grows.
