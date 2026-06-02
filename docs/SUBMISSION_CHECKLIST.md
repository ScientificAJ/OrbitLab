# OrbitLab Submission Checklist

Status: current for OrbitLab `v0.2.0`.

Use this before a judged demo.

## Local Dry Run

1. Start the stack with `scripts/start_all.sh`.
2. Open the frontend and confirm `GET /api/v1/health` reports `status: ok`.
3. Search a target from `docs/DEMO_TARGETS.md`.
4. Select a real product and keep the target/product IDs visible.
5. Run BLS preview.
6. Run full analysis.
7. Save and restore a session.
8. Export a report and compare the shape with `docs/api-fixtures/sample-report.json`.

## Judging Notes

- OrbitLab uses real MAST products and does not fabricate light curves or model scores.
- Missing model artifacts appear as unavailable readiness, not as fake predictions.
- Candidate outputs are triage signals, not planet confirmations.
- K2 ML uses the registered ExoMAC-KKT tabular replacement model.
- Report export is available only after full analysis, not preview-only BLS results.
- Public releases include a Science Provenance Release Room with model checksums, calibration/source checksums, benchmark deltas, SBOM, release asset checksums, and GitHub attestation evidence.

## Release Evidence

Before a final public demo or judge handoff, confirm:

1. `CHANGELOG.md` matches the release body.
2. `docs/RELEASE.md` lists the release-room assets expected for the tag.
3. The GitHub release contains `orbitlab-release-report.md`, JSON benchmark/checksum assets, `sbom.spdx.json`, `release-room-assets.sha256`, and `orbitlab-release-room-vX.Y.Z.zip`.
4. The release-room zip attestation verifies with GitHub for the repository.
5. Any model readiness mismatch between the release packet and the demo machine is explained plainly.

## Media

Fresh screenshots and walkthrough video should be captured from the final demo machine so they show real target/product IDs and real artifact readiness.

## External Items Skipped In Repo Automation

- Hosted demo URL.
- DNS/TLS/subdomain setup.
- Recorded walkthrough video.
- Fresh real-data screenshots.
