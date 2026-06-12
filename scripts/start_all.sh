#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/.orbitlab/logs"
PID_DIR="$ROOT/.orbitlab/pids"
STATE_DIR="$ROOT/.orbitlab/bootstrap"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
TF_IMAGE="${ORBITLAB_KEPLER_TF_IMAGE:-tensorflow/tensorflow:1.5.0-py3}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MIN_PYTHON_MINOR=11
MIN_NODE_MAJOR=20
DOCKER=()

mkdir -p "$LOG_DIR" "$PID_DIR" "$STATE_DIR"
cd "$ROOT"

log() {
  printf '[orbitlab] %s\n' "$*"
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

as_root() {
  if [[ "$(id -u)" == "0" ]]; then
    "$@"
  elif have_cmd sudo; then
    sudo "$@"
  else
    printf 'Root privileges are required to install missing system packages. Install sudo or rerun as root.\n' >&2
    exit 1
  fi
}

apt_package_available() {
  apt-cache show "$1" >/dev/null 2>&1
}

install_system_dependencies() {
  local packages=()
  have_cmd git || packages+=(git)
  have_cmd make || packages+=(make)
  have_cmd g++ || packages+=(g++)
  if ! have_cmd "$PYTHON_BIN"; then
    packages+=(python3 python3-venv)
  fi
  if ! have_cmd node || ! have_cmd npm; then
    packages+=(nodejs npm)
  fi
  have_cmd docker || packages+=(docker.io)

  if have_cmd "$PYTHON_BIN" && ! "$PYTHON_BIN" -c 'import ensurepip, venv' >/dev/null 2>&1; then
    packages+=(python3-venv)
  fi

  if (( ${#packages[@]} > 0 )); then
    if ! have_cmd apt-get; then
      printf 'Missing system tools: %s\n' "${packages[*]}" >&2
      printf 'Automatic system-package installation currently supports Debian/Ubuntu via apt-get.\n' >&2
      exit 1
    fi
    log "installing missing system packages: ${packages[*]}"
    as_root apt-get update
    as_root apt-get install -y "${packages[@]}"
  fi

  if ! docker compose version >/dev/null 2>&1; then
    if ! have_cmd apt-get; then
      printf 'Docker Compose plugin is required: docker compose\n' >&2
      exit 1
    fi
    local compose_package=""
    if apt_package_available docker-compose-v2; then
      compose_package="docker-compose-v2"
    elif apt_package_available docker-compose-plugin; then
      compose_package="docker-compose-plugin"
    fi
    if [[ -z "$compose_package" ]]; then
      printf 'Docker Compose plugin is missing and no apt package candidate was found.\n' >&2
      exit 1
    fi
    log "installing Docker Compose plugin: $compose_package"
    as_root apt-get update
    as_root apt-get install -y "$compose_package"
  fi
}

verify_tool_versions() {
  local python_minor
  python_minor="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.minor if sys.version_info.major == 3 else -1)')"
  if (( python_minor < MIN_PYTHON_MINOR )); then
    printf 'Python 3.%s+ is required; found %s\n' "$MIN_PYTHON_MINOR" "$("$PYTHON_BIN" --version 2>&1)" >&2
    exit 1
  fi

  local node_major
  node_major="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
  if [[ ! "$node_major" =~ ^[0-9]+$ ]] || (( node_major < MIN_NODE_MAJOR )); then
    printf 'Node.js %s+ is required; found %s. Install a current Node.js release and rerun.\n' \
      "$MIN_NODE_MAJOR" "$(node --version 2>&1)" >&2
    exit 1
  fi
}

configure_docker() {
  if docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    DOCKER=(docker)
    return
  fi

  if have_cmd systemctl; then
    as_root systemctl start docker >/dev/null 2>&1 || true
  elif have_cmd service; then
    as_root service docker start >/dev/null 2>&1 || true
  fi

  if docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    DOCKER=(docker)
  elif [[ "$(id -u)" == "0" ]]; then
    printf 'Docker daemon is unavailable after installation/start attempt.\n' >&2
    exit 1
  elif have_cmd sudo && sudo docker info >/dev/null 2>&1 && sudo docker compose version >/dev/null 2>&1; then
    DOCKER=(sudo docker)
  else
    printf 'Docker daemon is unavailable or inaccessible. Start Docker and rerun this script.\n' >&2
    exit 1
  fi
}

manifest_hash() {
  git hash-object "$@"
}

sync_project_dependencies() {
  if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    log "creating Python virtual environment"
    "$PYTHON_BIN" -m venv "$ROOT/.venv"
  fi

  local python_hash
  python_hash="$(manifest_hash pyproject.toml)"
  if [[ ! -f "$STATE_DIR/python-dependencies.sha" ]] || [[ "$(<"$STATE_DIR/python-dependencies.sha")" != "$python_hash" ]]; then
    log "installing Python API, science, ML, and development dependencies"
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -e ".[dev,science,api,ml]"
    printf '%s\n' "$python_hash" >"$STATE_DIR/python-dependencies.sha"
  fi

  local frontend_hash
  frontend_hash="$(manifest_hash frontend/package-lock.json)"
  if [[ ! -d "$ROOT/frontend/node_modules" ]] || [[ ! -f "$STATE_DIR/frontend-dependencies.sha" ]] \
    || [[ "$(<"$STATE_DIR/frontend-dependencies.sha")" != "$frontend_hash" ]] \
    || ! npm ls --prefix frontend --depth=0 >/dev/null 2>&1; then
    log "installing locked frontend dependencies"
    npm ci --prefix frontend
    printf '%s\n' "$frontend_hash" >"$STATE_DIR/frontend-dependencies.sha"
  fi
}

provision_playwright_browsers() {
  local chrome_bin="${PLAYWRIGHT_CHROME_EXECUTABLE_PATH:-/opt/google/chrome/chrome}"
  if [[ "${SKIP_PLAYWRIGHT_BROWSERS:-0}" == "1" ]]; then
    log "SKIP_PLAYWRIGHT_BROWSERS=1; skipping Playwright browser install"
    return 0
  fi
  if [[ -x "$chrome_bin" ]]; then
    log "system Chrome found at $chrome_bin; frontend e2e tests will use it directly"
    return 0
  fi

  log "installing Playwright Chromium for frontend e2e tests"
  if ! (cd "$ROOT/frontend" && npx playwright install chromium); then
    log "warning: Playwright browser download failed; run 'npx playwright install chromium' in frontend/ before e2e tests"
    return 0
  fi

  # Browser system libraries need root; try non-interactively and fall back to a hint.
  if (cd "$ROOT/frontend" && npx playwright install-deps chromium >/dev/null 2>&1); then
    return 0
  fi
  if have_cmd sudo && (cd "$ROOT/frontend" && sudo -n npx playwright install-deps chromium >/dev/null 2>&1); then
    return 0
  fi
  log "note: if e2e browsers fail to launch, run 'sudo npx playwright install-deps chromium' in frontend/"
}

warm_docker_images_best_effort() {
  if [[ "${SKIP_DOCKER_WARMUP:-0}" == "1" ]]; then
    log "SKIP_DOCKER_WARMUP=1; skipping Docker image warm-up"
    return 0
  fi

  local docker_cmd=()
  if docker info >/dev/null 2>&1; then
    docker_cmd=(docker)
  elif have_cmd sudo && sudo -n docker info >/dev/null 2>&1; then
    docker_cmd=(sudo docker)
  else
    log "Docker daemon not reachable right now; images will be pulled on first full start instead"
    return 0
  fi

  log "pre-pulling Docker images (redis, postgres, Kepler TF runtime) for a fast first start"
  "${docker_cmd[@]}" compose pull --quiet \
    || log "warning: docker compose pull failed; the full start will retry"
  if ! "${docker_cmd[@]}" image inspect "$TF_IMAGE" >/dev/null 2>&1; then
    "${docker_cmd[@]}" pull "$TF_IMAGE" \
      || log "warning: pull of $TF_IMAGE failed; the full start will retry"
  fi
}

artifact_ready() {
  .venv/bin/python - "$1" <<'PY' >/dev/null 2>&1
import sys
from orbitlab.ml.artifact_registry import artifact_status

raise SystemExit(0 if artifact_status(sys.argv[1]).get("status") == "ready" else 1)
PY
}

provision_science_dependencies() {
  local nigraha_id="nigraha-tess-global-nodropout-binary-ensemble"
  local kepler_id="kepler-astronet-cnn-bilstm-attention"
  local k2_id="k2-exomac-kkt-randomforest"

  if ! artifact_ready "$nigraha_id"; then
    log "Nigraha/TESS ensemble is not ready; fetching and registering it"
    scripts/fetch_nigraha_weights.py
  fi
  if ! artifact_ready "$kepler_id"; then
    log "Kepler/K1 checkpoint is not ready; fetching and registering it"
    scripts/fetch_kepler_astronet.py
  fi
  if ! artifact_ready "$k2_id"; then
    log "K2 ExoMAC-KKT model is not ready; fetching and registering it"
    scripts/fetch_k2_exomac_kkt.py
  fi

  log "ensuring pinned DAVE ModShift binary is built"
  scripts/build_dave_modshift.sh >/dev/null
  if [[ ! -x "$ROOT/.orbitlab/external/DAVE/vetting/modshift" ]]; then
    printf 'DAVE ModShift build did not produce an executable binary.\n' >&2
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

install_system_dependencies
verify_tool_versions
sync_project_dependencies
provision_playwright_browsers
provision_science_dependencies

if [[ "${BOOTSTRAP_ONLY:-0}" == "1" ]]; then
  warm_docker_images_best_effort
  log "bootstrap complete"
  exit 0
fi

configure_docker

log "starting Docker services from docker-compose.yml"
"${DOCKER[@]}" compose up -d
wait_port 127.0.0.1 6379 redis
wait_port 127.0.0.1 5435 postgres

log "ensuring Kepler/K1 TensorFlow Docker runtime image exists"
"${DOCKER[@]}" image inspect "$TF_IMAGE" >/dev/null 2>&1 || "${DOCKER[@]}" pull "$TF_IMAGE"

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://orbitlab:orbitlab@127.0.0.1:5435/orbitlab}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export ORBITLAB_RUN_JOBS_INLINE="${ORBITLAB_RUN_JOBS_INLINE:-1}"

start_process backend .venv/bin/uvicorn orbitlab.api.main:app --app-dir backend --host "$BACKEND_HOST" --port "$BACKEND_PORT"
wait_port "$BACKEND_HOST" "$BACKEND_PORT" backend

if [[ "${START_CELERY:-0}" == "1" ]]; then
  start_process celery .venv/bin/celery -A orbitlab.worker.celery_app worker --loglevel=INFO
fi

start_process frontend npm run dev --prefix frontend -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
wait_port "$FRONTEND_HOST" "$FRONTEND_PORT" frontend

log "OrbitLab is up"
log "frontend: http://$FRONTEND_HOST:$FRONTEND_PORT"
log "backend:  http://$BACKEND_HOST:$BACKEND_PORT"
log "logs:     $LOG_DIR"
log "pids:     $PID_DIR"
