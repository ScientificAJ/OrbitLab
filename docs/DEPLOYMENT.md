# OrbitLab Deployment Runbook

Status: current for OrbitLab `v0.2.0`.

This runbook covers a production-style deployment without storing model bundles in git.

## Components

- Backend API: FastAPI app from `backend/orbitlab/api/main.py`.
- Worker: Celery worker using `orbitlab.worker.celery_app`.
- Queue/cache: Redis.
- Database: PostgreSQL for shared deployments; SQLite is local-only.
- Frontend: Vite build output from `frontend/dist`.
- Model artifacts: external object storage or a mounted volume referenced by `ORBITLAB_MODEL_REGISTRY`.

## Environment

Set these per environment:

```bash
DATABASE_URL=postgresql+psycopg://user:password@host:5432/orbitlab
REDIS_URL=redis://redis-host:6379/0
ORBITLAB_RUN_JOBS_INLINE=0
ORBITLAB_CORS_ORIGINS=https://your-frontend.example
ORBITLAB_MAST_CACHE_DIR=/var/lib/orbitlab/mast
ORBITLAB_MODEL_REGISTRY=/var/lib/orbitlab/models.json
```

Secrets belong in the host or platform secret manager, not in the repository.

## Artifact Storage

Keep model bundles outside git because they are large scientific dependencies. Use one of:

- A persistent server volume mounted at `/var/lib/orbitlab/models`.
- Object storage synced before release.
- A private artifact bucket with checksummed fetch scripts.

After fetching, run:

```bash
scripts/fetch_nigraha_weights.py
scripts/fetch_kepler_astronet.py
scripts/fetch_k2_exomac_kkt.py
```

Then verify:

```bash
curl https://api.example/api/v1/models
```

## Release Provenance Before Deployment

Before deploying a public tag, confirm the release-room packet exists for that tag:

```bash
gh release view vX.Y.Z
gh run list --workflow release-room.yml --limit 5
```

Minimum expected release assets:

- `orbitlab-release-report.md`
- `release-metadata.json`
- `model-artifact-checksums.json`
- `calibration-source-checksums.json`
- `science-benchmark-current.json`
- `science-benchmark-delta.json`
- `sbom.spdx.json`
- `release-room-assets.sha256`
- `orbitlab-release-room-vX.Y.Z.zip`

For production-style deployments, compare the deployed model readiness with the release packet:

```bash
curl https://api.example/api/v1/models
```

If the deployment has different readiness than the release room, document why. Common valid reasons are a newer mounted artifact volume, a deliberately unavailable model for a lightweight demo host, or a release generated before artifacts were fetched.

## Health Checks

- API: `GET /api/v1/health` returns `status`, `database`, and `worker_mode`.
- Models: `GET /api/v1/models` confirms artifact readiness.
- Frontend: request `/` from the deployed frontend.
- Worker: submit a small analysis job or inspect Celery worker heartbeats.
- Redis/Postgres: use platform health checks plus the API health response.
- Release room: verify the latest public tag has release-room assets and GitHub attestation when deployment is promoted as a public release.

## Rollback And Restart

1. Put the frontend in maintenance mode or show the demo status banner.
2. Stop workers first so no new analysis writes are in flight.
3. Roll backend and worker images back to the previous tag.
4. Restore the previous frontend build.
5. Confirm `GET /api/v1/health` and `GET /api/v1/models`.
6. Re-run the demo script in `docs/DEMO_TARGETS.md`.

## Demo Host Notes

The hosted demo URL is intentionally not committed until DNS, TLS, backend, worker, database, and model storage are stable.
