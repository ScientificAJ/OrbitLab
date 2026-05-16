# OrbitLab

![OrbitLab satellite-imagery header](docs/assets/ORBITLAB.png)

[![CI](https://github.com/ScientificAJ/OrbitLab/actions/workflows/ci.yml/badge.svg)](https://github.com/ScientificAJ/OrbitLab/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ScientificAJ/OrbitLab/actions/workflows/codeql.yml/badge.svg)](https://github.com/ScientificAJ/OrbitLab/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/ScientificAJ/OrbitLab?include_prereleases&label=release)](https://github.com/ScientificAJ/OrbitLab/releases/tag/v0.1.0-mvp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](backend/orbitlab/api/main.py)
[![React + Vite](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-646CFF.svg)](frontend/package.json)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](docker-compose.yml)

Research-grade exoplanet candidate workbench for real TESS, Kepler, and K2 target pixel files.

OrbitLab helps students, judges, and citizen-science teams inspect candidate transits from NASA mission data without pretending certainty. It searches MAST products, extracts light curves from target pixel files, runs BLS transit searches, applies basic validation and physics checks, and reports mission-aware pretrained ML readiness through a public API.

The project is intentionally strict: the backend does not fabricate planets, light curves, model scores, charts, screenshots, or downloaded artifacts. If data or a checksum-verified model artifact is missing, OrbitLab says so.

## Problem

Public exoplanet archives are powerful, but a reproducible target-to-candidate workflow usually requires astronomy tooling, Python environment setup, model-artifact discipline, and careful caveats. Hackathon demos often skip those details and show polished but synthetic results.

OrbitLab is the opposite tradeoff: a usable full-stack workbench that keeps the scientific chain visible.

## What It Does

- Searches real MAST TESS, Kepler, and K2 products.
- Extracts light curves from target pixel files with optional aperture and artifact masks.
- Runs BLS candidate detection and multi-candidate previews.
- Produces folded light curves, periodograms, candidate metadata, and validation context.
- Reports model availability at `GET /api/v1/models` using local artifact checksums.
- Keeps model downloads reproducible through pinned fetch scripts.
- Starts the local stack with `scripts/start_all.sh`.

## Model Readiness

| Mission     | OrbitLab model surface                          | Source                                                                                       | Status policy                                                                                 |
| ----------- | ----------------------------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| TESS        | Nigraha global no-dropout binary ensemble       | `ExoplanetML/Nigraha` at pinned commit `c4365b41dd02b187c3210189ffe8e3ead584f4f5`            | Ready only when all registered HDF5 weights exist and match expected SHA-256 values.          |
| Kepler/K1   | AstroNet-family CNN/BiLSTM/attention checkpoint | `bibinthomas123/Astronet` at pinned commit `9809ce92306f11fbdc96f9830b522026710a3883`        | Ready only when the TensorFlow checkpoint is fetched, registered, and checksum-valid.         |
| K2          | ExoMAC-KKT RandomForest catalog classifier      | `ZapatoProgramming/ExoMAC-KKT` at pinned revision `5cda5310d5a163679c6915f9463a4d6afc312483` | Ready only when the sklearn bundle, feature schema, labels, metadata, and checksums validate. |
| K2 AstroNet | Paper/provenance note only                      | Published AstroNet-K2 work                                                                   | Marked unavailable because no public downloadable checkpoint is registered.                   |

See [docs/MODEL_CARDS.md](docs/MODEL_CARDS.md) and [docs/model_artifacts.md](docs/model_artifacts.md) for provenance and limitations.

## Screenshots

Add fresh screenshots before submission once the demo machine has fetched real MAST products and model artifacts:

- Search and product selection.
- TPF preview with aperture controls.
- BLS periodogram and folded candidates.
- Model readiness panel from `/api/v1/models`.

Do not add mocked science screenshots unless they are clearly labeled as UI-only mockups.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,science,api,ml]"
npm ci --prefix frontend
```

Optional local configuration can be copied from `.env.example`.

Fetch model artifacts as needed:

```bash
scripts/fetch_nigraha_weights.py
scripts/fetch_kepler_astronet.py
scripts/fetch_k2_exomac_kkt.py
```

Start the full local stack:

```bash
scripts/start_all.sh
```

The script starts Docker Compose services, ensures the Kepler/K1 TensorFlow runtime image is present, fetches registered Kepler and K2 artifacts when needed, then starts the backend and frontend. Logs and pid files live under `.orbitlab/`.

For step-by-step app usage, LAN access, target search, BLS preview, full analysis, and troubleshooting, see [docs/USAGE.md](docs/USAGE.md).
For deployment and release operations, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and [docs/RELEASE.md](docs/RELEASE.md).

For manual startup:

```bash
uvicorn orbitlab.api.main:app --reload --app-dir backend
npm run dev --prefix frontend
```

For production-style workers, set `ORBITLAB_RUN_JOBS_INLINE=0` and start Celery:

```bash
celery -A orbitlab.worker.celery_app worker --loglevel=info -Q analysis
```

## Demo Script

Use [docs/DEMO_TARGETS.md](docs/DEMO_TARGETS.md) for known-good target ideas and runtime caveats.
Use [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md) for final dry-run and judging notes.

1. Search a target such as `TIC 307210830`.
2. Select a real target pixel file product and keep the product ID visible.
3. Open Aperture, select bright pixels, and apply the custom mask.
4. Run BLS Search and inspect candidates, periodogram, folded curve, and light curve.
5. Run Analysis and review validation, physics, and ML context.
6. Open ML Status to show artifact readiness truth.
7. Save/restore a session, then export a report only after a full analysis result exists.

## API Summary

Base prefix: `/api/v1`

- `GET /search`
- `GET /targets/{target_id}/products`
- `GET /tpf-preview`
- `POST /bls-preview`
- `POST /analysis-jobs`
- `GET /analysis-jobs/{job_id}`
- `GET /analysis-results/{result_id}`
- `POST /artifact-masks`
- `POST /aperture-masks`
- `GET /models`
- `GET /sessions`
- `POST /sessions`
- `GET /reports/{report_id}`
- `GET /health`

`GET /api/v1/models` is the public truth for ML readiness. It reports unavailable states instead of silently falling back to fake scores.

## Repository Layout

- `backend/orbitlab/` - FastAPI app, storage, science pipeline, and ML services.
- `backend/tests/` - backend unit and integration tests.
- `frontend/src/` - React/Vite application.
- `scripts/` - repeatable artifact, startup, and operational scripts.
- `docs/` - architecture, model cards, artifact policy, and repo notes.
- `.orbitlab/` - ignored local runtime state: cached MAST products, model artifacts, logs, pid files, and the default SQLite database.

## Judging Highlights

- Real archive data first: no generated light curves or model outputs.
- Reproducible artifact provenance with pinned sources and checksums.
- Mission-aware ML behavior for TESS, Kepler/K1, and K2.
- Clear unavailable states for missing models and missing public K2 AstroNet weights.
- Full-stack demo path with FastAPI, React/Vite, Docker Compose, and local preflight checks.

Run the same core checks used by contributors:

```bash
scripts/preflight.sh
```

Frontend checks are split so fast regressions and live smoke are explicit:

```bash
npm run test:unit --prefix frontend
npm run test:e2e --prefix frontend
LIVE_ORBITLAB=1 npm run test:e2e:live --prefix frontend
```

The live smoke expects the local stack to already be running and will touch the real API. The regular Playwright suite keeps mocked API data isolated under `frontend/e2e`.

## License

OrbitLab is released under the MIT License. See [LICENSE](LICENSE).
