# OrbitLab Repository Structure

OrbitLab is organized around source, operations, documentation, and local runtime state.

## Source

- `backend/orbitlab/api/` - FastAPI routes and response schemas.
- `backend/orbitlab/science/` - MAST access, light-curve extraction, cleaning, BLS, folding, and validation.
- `backend/orbitlab/ml/` - artifact registry, adapters, and mission-specific ML services.
- `backend/orbitlab/storage/` - database engine and ORM records.
- `frontend/src/` - React application code and UI components.

## Tests

- `backend/tests/` - backend test suite.
- `backend/tests/fixtures/` - compact fixtures that are small enough to keep with tests.

## Operations

- `scripts/start_all.sh` - starts Docker services, backend, and frontend for local development.
- `scripts/fetch_kepler_astronet.py` - downloads and verifies the registered Kepler/K1 checkpoint.
- `scripts/fetch_nigraha_weights.py` - downloads and registers Nigraha/TESS artifacts.
- `scripts/predict_kepler_astronet_tf.py` - TensorFlow 1.x Docker-side Kepler inference helper.
- `scripts/convert_kepler_astronet_npz.py` - optional Kepler checkpoint conversion hook for a converter Docker image.
- `scripts/generate_nigraha_golden.py` - optional Nigraha parity fixture regeneration hook for the original Keras runtime.
- `scripts/dump_repo.py` - writes a compact source/config/docs dump.

## Documentation

- `docs/model_artifacts.md` - model registry and artifact expectations.
- `docs/published_checkpoints.md` - checkpoint provenance notes.
- `docs/REPO_STRUCTURE.md` - this map.

## Local Runtime State

Local runtime files belong under `.orbitlab/`, which is intentionally ignored by Git:

- `.orbitlab/mast/` - downloaded MAST products.
- `.orbitlab/models/` - downloaded model artifacts.
- `.orbitlab/logs/` - local server logs.
- `.orbitlab/pids/` - local process ids from `scripts/start_all.sh`.
- `.orbitlab/orbitlab.db` - default SQLite database when `DATABASE_URL` is not set.

Keep generated dumps, caches, and heavyweight artifacts out of source directories unless they are compact test fixtures with clear provenance.
