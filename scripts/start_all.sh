#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/.orbitlab/logs"
PID_DIR="$ROOT/.orbitlab/pids"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
TF_IMAGE="${ORBITLAB_KEPLER_TF_IMAGE:-tensorflow/tensorflow:1.5.0-py3}"

mkdir -p "$LOG_DIR" "$PID_DIR"
cd "$ROOT"

log() {
  printf '[orbitlab] %s\n' "$*"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

wait_port() {
  local host="$1"
  local port="$2"
  local name="$3"
  local attempts="${4:-60}"
  for _ in $(seq 1 "$attempts"); do
    if .venv/bin/python - "$host" "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
with socket.create_connection((host, port), timeout=1):
    pass
PY
    then
      log "$name is listening on $host:$port"
      return 0
    fi
    sleep 1
  done
  printf '%s did not become ready on %s:%s\n' "$name" "$host" "$port" >&2
  return 1
}

start_process() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"
  shift

  if [[ -f "$pid_file" ]]; then
    local old_pid
    old_pid="$(cat "$pid_file")"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
      log "$name already running as pid $old_pid"
      return 0
    fi
  fi

  log "starting $name"
  nohup "$@" >"$LOG_DIR/$name.log" 2>&1 &
  printf '%s\n' "$!" >"$pid_file"
}

need_cmd docker
need_cmd npm

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  printf 'Missing .venv. Create it and install dependencies first: python3 -m venv .venv && .venv/bin/pip install -e ".[dev,science,api,ml]"\n' >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  printf 'Docker Compose plugin is required: docker compose\n' >&2
  exit 1
fi

log "starting Docker services from docker-compose.yml"
docker compose up -d
wait_port 127.0.0.1 6379 redis
wait_port 127.0.0.1 5432 postgres

log "ensuring Kepler/K1 TensorFlow Docker runtime image exists"
docker image inspect "$TF_IMAGE" >/dev/null 2>&1 || docker pull "$TF_IMAGE"

if ! .venv/bin/python - <<'PY' >/dev/null 2>&1
from orbitlab.ml.artifact_registry import KEPLER_ASTRONET_MODEL_ID, artifact_status

raise SystemExit(0 if artifact_status(KEPLER_ASTRONET_MODEL_ID).get("status") == "ready" else 1)
PY
then
  log "Kepler/K1 checkpoint is not ready; fetching and registering it"
  scripts/fetch_kepler_astronet.py
fi

if ! .venv/bin/python - <<'PY' >/dev/null 2>&1
from orbitlab.ml.artifact_registry import K2_EXOMAC_MODEL_ID, artifact_status

raise SystemExit(0 if artifact_status(K2_EXOMAC_MODEL_ID).get("status") == "ready" else 1)
PY
then
  log "K2 ExoMAC-KKT model is not ready; fetching and registering it"
  scripts/fetch_k2_exomac_kkt.py
fi

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://orbitlab:orbitlab@127.0.0.1:5432/orbitlab}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export ORBITLAB_RUN_JOBS_INLINE="${ORBITLAB_RUN_JOBS_INLINE:-1}"

start_process backend .venv/bin/uvicorn orbitlab.api.main:app --app-dir backend --host "$BACKEND_HOST" --port "$BACKEND_PORT"
wait_port "$BACKEND_HOST" "$BACKEND_PORT" backend

if [[ "${START_CELERY:-0}" == "1" ]]; then
  start_process celery .venv/bin/celery -A orbitlab.worker.celery_app worker --loglevel=INFO
fi

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  log "installing frontend dependencies"
  npm install --prefix frontend
fi

start_process frontend npm run dev --prefix frontend -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
wait_port "$FRONTEND_HOST" "$FRONTEND_PORT" frontend

log "OrbitLab is up"
log "frontend: http://$FRONTEND_HOST:$FRONTEND_PORT"
log "backend:  http://$BACKEND_HOST:$BACKEND_PORT"
log "logs:     $LOG_DIR"
log "pids:     $PID_DIR"
