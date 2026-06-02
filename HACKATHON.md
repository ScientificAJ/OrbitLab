# OrbitLab Hackathon Notes

Status: current for OrbitLab `v0.2.0`.

## Pitch

OrbitLab is a real-data exoplanet candidate workbench. It turns NASA MAST target pixel files into inspectable transit candidates with a transparent pipeline: product search, light-curve extraction, BLS detection, validation context, mission-aware model readiness, and a React interface for exploration.

## Target Users

- Hackathon judges who want to see reproducible science rather than mocked charts.
- Students learning exoplanet transit detection.
- Citizen-science teams triaging public TESS, Kepler, and K2 products.
- Contributors who want a clean place to add better validation, deployments, and model adapters.

## Core Innovation

OrbitLab combines a full-stack user experience with strict data provenance. The app does not invent model scores when artifacts are missing, distinguishes between what is downloadable now and what is only documented in papers, and publishes release-room evidence so judges can audit what a public release actually contained.

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
- Science Provenance Release Room assets for public releases: model checksums, calibration/source checksums, benchmark deltas, SPDX SBOM, release asset checksums, zip packet, and GitHub attestation evidence.

## Known Limits

- Hosted demo and walkthrough video are not part of this pass.
- MAST access, large model downloads, and Docker image pulls require network access.
- K2 uses ExoMAC-KKT as the registered replacement model for mission-aware ML readiness and inference.
- ExoMAC-KKT is a K2-capable tabular classifier, not a light-curve CNN.
- Candidate labels are decision support, not discovery confirmation.
- Release-room evidence proves provenance and benchmark state; it does not confirm planets.

## Judging Notes

- The strongest judging signal is transparency: every unavailable state should be visible instead of hidden.
- Use real targets and preserve the target/product identifiers in the demo.
- Do not present BLS candidates or ML scores as confirmed planets.
- Show the release-room packet when judges ask how the release can be audited after the demo.
- Show the roadmap to make it clear which polish items are intentionally deferred.
