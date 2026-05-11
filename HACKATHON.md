# OrbitLab Hackathon Notes

## Pitch

OrbitLab is a real-data exoplanet candidate workbench. It turns NASA MAST target pixel files into inspectable transit candidates with a transparent pipeline: product search, light-curve extraction, BLS detection, validation context, mission-aware model readiness, and a React interface for exploration.

## Target Users

- Hackathon judges who want to see reproducible science rather than mocked charts.
- Students learning exoplanet transit detection.
- Citizen-science teams triaging public TESS, Kepler, and K2 products.
- Contributors who want a clean place to add better validation, deployments, and model adapters.

## Core Innovation

OrbitLab combines a full-stack user experience with strict data provenance. The app does not invent model scores when artifacts are missing, and it distinguishes between what is downloadable now and what is only documented in papers.

## Demo Flow

1. Open the frontend and search for a real mission target.
2. Select a MAST target pixel file product.
3. Inspect the TPF preview and choose or adjust the aperture mask.
4. Run a BLS preview to surface candidate transit periods.
5. Start an analysis job and inspect folded curves plus validation context.
6. Open the model readiness view or call `GET /api/v1/models` to show artifact status.

## Current Capabilities

- FastAPI backend with session, product, mask, preview, job, report, and model-status endpoints.
- TPF-first light-curve extraction through astronomy Python tooling.
- BLS candidate search and folded curve generation.
- TESS Nigraha artifact registration.
- Kepler/K1 AstroNet-family checkpoint registration.
- K2 ExoMAC-KKT catalog-classifier registration.
- Docker Compose support for Redis/Postgres and a TensorFlow 1.x Kepler runtime path.
- React/Vite frontend for interactive exploration.

## Known Limits

- Hosted demo and walkthrough video are not part of this pass.
- MAST access, large model downloads, and Docker image pulls require network access.
- K2 AstroNet light-curve checkpoint inference is unavailable because OrbitLab has not registered a public downloadable checkpoint.
- ExoMAC-KKT is a K2-capable tabular classifier, not an AstroNet-K2 CNN.
- Candidate labels are decision support, not discovery confirmation.

## Judging Notes

- The strongest judging signal is transparency: every unavailable state should be visible instead of hidden.
- Use real targets and preserve the target/product identifiers in the demo.
- Do not present BLS candidates or ML scores as confirmed planets.
- Show the roadmap to make it clear which polish items are intentionally deferred.
