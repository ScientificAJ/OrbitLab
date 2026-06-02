# OrbitLab Repository Structure

Status: current for OrbitLab `v0.2.0`.

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
- `scripts/run_orbitlab_science_benchmark.py` - benchmark harness for known planets, injected transits, false positives, scrambled controls, and variability cases.
- `scripts/build_release_room.py` - generates release-room provenance assets, benchmark deltas, SPDX SBOM data, release checksums, and the release-room zip.
- `scripts/export_evidence_packet.py` - exports per-result evidence packets after full analysis.
- `scripts/dump_repo.py` - writes a compact source/config/docs dump.

## GitHub Automation

- `.github/workflows/ci.yml` - backend/frontend validation.
- `.github/workflows/codeql.yml` - CodeQL security analysis.
- `.github/workflows/release-room.yml` - builds, uploads, and attests Science Provenance Release Room assets for public releases.
- `.github/dependabot.yml` - dependency update automation.
- `.github/CODEOWNERS` - ownership hints for review routing.

## Documentation

- `docs/model_artifacts.md` - model registry and artifact expectations.
- `docs/published_checkpoints.md` - checkpoint provenance notes.
- `docs/SCIENTIFIC_METHODOLOGY.md` - implementation-backed science methodology and trust boundaries.
- `docs/RELEASE.md` - release process and Science Provenance Release Room runbook.
- `docs/REPO_STRUCTURE.md` - this map.

## Agent Handoff State

- `.agents/task-log/` - task-start notes, verification expectations, and cadence markers for agent handoffs. These notes are intentionally lightweight and should not replace commits, release notes, or test evidence.

## Local Runtime State

Local runtime files belong under `.orbitlab/`, which is intentionally ignored by Git:

- `.orbitlab/mast/` - downloaded MAST products.
- `.orbitlab/models/` - downloaded model artifacts.
- `.orbitlab/logs/` - local server logs.
- `.orbitlab/pids/` - local process ids from `scripts/start_all.sh`.
- `.orbitlab/orbitlab.db` - default SQLite database when `DATABASE_URL` is not set.
- `.orbitlab/releases/` - locally generated release-room packets.
- `.orbitlab/benchmarks/` - local benchmark reports and baselines.
- `.orbitlab/evidence-packets/` - exported per-analysis evidence packets.

Keep generated dumps, caches, and heavyweight artifacts out of source directories unless they are compact test fixtures with clear provenance.
