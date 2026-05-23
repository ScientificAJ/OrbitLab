#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() {
  printf '[preflight] %s\n' "$*"
}

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
PYTEST="${PYTEST:-$ROOT/.venv/bin/pytest}"

if [[ ! -x "$PYTHON" ]]; then
  printf 'Missing virtualenv Python at %s\n' "$PYTHON" >&2
  printf 'Create it with: python3 -m venv .venv && .venv/bin/pip install -e ".[dev,science,api,ml]"\n' >&2
  exit 1
fi

if [[ ! -x "$PYTEST" ]]; then
  printf 'Missing pytest at %s\n' "$PYTEST" >&2
  printf 'Install dev dependencies with: .venv/bin/pip install -e ".[dev,science,api,ml]"\n' >&2
  exit 1
fi

log "backend tests"
"$PYTEST" --cov=orbitlab --cov-report=term-missing

log "frontend build"
if [[ -d frontend/node_modules ]]; then
  npm run format:check --prefix frontend
  npm run lint --prefix frontend
  npm run test:unit --prefix frontend
  npm run test:e2e --prefix frontend
  npm run build --prefix frontend
else
  printf 'Missing frontend/node_modules. Run: npm ci --prefix frontend\n' >&2
  exit 1
fi

log "shell syntax"
bash -n scripts/start_all.sh
bash -n scripts/preflight.sh

log "python compile checks"
"$PYTHON" -m py_compile \
  scripts/convert_kepler_astronet_npz.py \
  scripts/dump_repo.py \
  scripts/fetch_calibration_sources.py \
  scripts/fetch_k2_exomac_kkt.py \
  scripts/fetch_kepler_astronet.py \
  scripts/fetch_nigraha_weights.py \
  scripts/generate_nigraha_golden.py \
  scripts/predict_kepler_astronet_tf.py \
  scripts/register_astronet_artifact.py \
  scripts/train_probability_calibration.py

log "ok"
