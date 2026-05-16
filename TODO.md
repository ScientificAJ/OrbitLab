# OrbitLab TODO

## Completed In Repo

### Submission Polish

- [x] Add final judging notes that explain real-data limits, artifact readiness, and report export in `docs/SUBMISSION_CHECKLIST.md`.
- [x] Add a final demo dry-run checklist based on `docs/DEMO_TARGETS.md`.
- [x] Link deployment, release, and submission notes from `README.md`.

### Deployment

- [x] Add production deployment documentation for backend, worker, Redis/Postgres, and frontend in `docs/DEPLOYMENT.md`.
- [x] Decide on artifact storage for large model bundles outside git in `docs/DEPLOYMENT.md`.
- [x] Document environment-specific CORS and secret handling in `docs/DEPLOYMENT.md`.
- [x] Add deployment health checks for API, worker, database, Redis, and frontend in `docs/DEPLOYMENT.md`.
- [x] Add a rollback/restart checklist for the hosted demo in `docs/DEPLOYMENT.md`.

### Science And ML

- [x] Expand validation with additional false-positive flags.
- [x] Add richer stellar-context ingestion for analysis jobs.
- [x] Document model-input normalization for each mission adapter in `docs/model_artifacts.md`.

### Product

- [x] Add saved demo session fixture in `docs/api-fixtures/demo-session.json`.
- [x] Add sample exported report fixture for judge handoff in `docs/api-fixtures/sample-report.json`.
- [x] Add clearer frontend progress indicators for product lookup, BLS preview, and analysis jobs.
- [x] Add a visible demo status banner when backend health is unavailable or degraded.

### Contributor Experience

- [x] Keep CI coverage documented in `.github/workflows/ci.yml`.
- [x] Add issue labels and milestone plan in `docs/RELEASE.md`.
- [x] Document release tagging and changelog steps in `docs/RELEASE.md`.
- [x] Convert direct-push workflow to PR review when the team grows.

## Intentionally Skipped External Items

- [ ] Hosted demo URL: skipped because this requires external DNS/hosting access.
- [ ] Walkthrough video: skipped because this requires recording media from the final demo environment.
- [ ] Fresh real-data screenshots: skipped because these should be captured from the final demo machine with real target/product IDs.
