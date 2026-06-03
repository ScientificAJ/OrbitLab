# Support

Status: current for OrbitLab `v0.2.0`.

OrbitLab is a student hackathon project with a real-data science workflow. The fastest way to get useful help is to include enough provenance for someone else to reproduce what you saw.

## Start Here

- Local setup and app workflow: [docs/USAGE.md](docs/USAGE.md)
- Deployment and operations: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- Model readiness and artifact policy: [docs/MODEL_CARDS.md](docs/MODEL_CARDS.md) and [docs/model_artifacts.md](docs/model_artifacts.md)
- Science limits and candidate interpretation: [docs/SCIENTIFIC_METHODOLOGY.md](docs/SCIENTIFIC_METHODOLOGY.md)
- Release provenance and audit packets: [docs/RELEASE.md](docs/RELEASE.md)
- GitHub labels, milestones, and issue routing: [docs/GITHUB_ORGANIZATION.md](docs/GITHUB_ORGANIZATION.md)
- Collaboration expectations: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Security reports: [SECURITY.md](SECURITY.md)

## Opening An Issue

Use the issue templates when the question belongs in public project history. Include:

- Target name or ID, mission, product URI, and product ID when a data product is involved.
- Command, API request, or UI workflow that reproduced the issue.
- Backend/frontend versions, OS, Docker availability, and whether `.orbitlab/` already contained cached artifacts.
- `GET /api/v1/models` output or a clear statement that model artifacts were not fetched.
- Release tag and release-room asset details when the issue is about public release provenance.
- Screenshots only when they show a concrete UI state; do not use screenshots as a substitute for target/product IDs.

Do not paste secrets, private tokens, local credentials, or large downloaded science/model artifacts into issues.

## Expectations

OrbitLab should report unavailable data and missing model artifacts plainly. A missing artifact, failed MAST download, or single-sector-only warning is often a valid state rather than a bug.
