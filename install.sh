#!/usr/bin/env bash
set -euo pipefail

# OrbitLab one-shot installer.
#
# Installs everything a fresh checkout needs to run, test, and develop:
#   1. System packages, Python venv + [dev,science,api,ml] extras, locked
#      frontend packages, TESS/Kepler/K2 model artifacts, and the pinned
#      DAVE ModShift vetting binary (via BOOTSTRAP_ONLY=1 scripts/start_all.sh).
#   2. Playwright Chromium for frontend e2e tests (skipped when a system
#      Chrome is available, or with SKIP_PLAYWRIGHT_BROWSERS=1).
#   3. Docker image warm-up (redis, postgres, Kepler TF runtime) so the first
#      `scripts/start_all.sh` launch is fast (skip with SKIP_DOCKER_WARMUP=1).
#
# Safe to re-run: every step is idempotent and skips work that is already done.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

TF_IMAGE="${ORBITLAB_KEPLER_TF_IMAGE:-tensorflow/tensorflow:1.5.0-py3}"
CHROME_BIN="${PLAYWRIGHT_CHROME_EXECUTABLE_PATH:-/opt/google/chrome/chrome}"

log() {
  printf '[install] %s\n' "$*"
}

install_playwright_browsers() {
  if [[ "${SKIP_PLAYWRIGHT_BROWSERS:-0}" == "1" ]]; then
    log "SKIP_PLAYWRIGHT_BROWSERS=1; skipping Playwright browser install"
    return 0
  fi
  if [[ -x "$CHROME_BIN" ]]; then
    log "system Chrome found at $CHROME_BIN; e2e tests will use it directly"
    return 0
  fi

  log "installing Playwright Chromium for frontend e2e tests"
  if ! (cd frontend && npx playwright install chromium); then
    log "warning: Playwright browser download failed; run 'npx playwright install chromium' in frontend/ before e2e tests"
    return 0
  fi

  # Browser system libraries need root; try non-interactively and fall back to a hint.
  if (cd frontend && npx playwright install-deps chromium >/dev/null 2>&1); then
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && (cd frontend && sudo -n npx playwright install-deps chromium >/dev/null 2>&1); then
    return 0
  fi
  log "note: if e2e browsers fail to launch, run 'sudo npx playwright install-deps chromium' in frontend/"
}

warm_docker_images() {
  if [[ "${SKIP_DOCKER_WARMUP:-0}" == "1" ]]; then
    log "SKIP_DOCKER_WARMUP=1; skipping Docker image warm-up"
    return 0
  fi

  local docker_cmd=()
  if docker info >/dev/null 2>&1; then
    docker_cmd=(docker)
  elif command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
    docker_cmd=(sudo docker)
  else
    log "Docker daemon not reachable right now; images will be pulled on first start instead"
    return 0
  fi

  log "pre-pulling Docker images (redis, postgres, Kepler TF runtime) for a fast first start"
  "${docker_cmd[@]}" compose pull --quiet \
    || log "warning: docker compose pull failed; scripts/start_all.sh will retry at startup"
  if ! "${docker_cmd[@]}" image inspect "$TF_IMAGE" >/dev/null 2>&1; then
    "${docker_cmd[@]}" pull "$TF_IMAGE" \
      || log "warning: pull of $TF_IMAGE failed; scripts/start_all.sh will retry at startup"
  fi
}

log "bootstrapping system packages, Python environment, frontend packages, and science artifacts"
BOOTSTRAP_ONLY=1 scripts/start_all.sh

install_playwright_browsers
warm_docker_images

log "verifying installed toolchain"
log "python: $("$ROOT/.venv/bin/python" --version 2>&1)"
log "node:   $(node --version)"
log "npm:    $(npm --version)"

if [[ ! -f .env && -f .env.example ]]; then
  log "tip: copy .env.example to .env for optional local configuration"
fi

log "install complete"
log "next:  scripts/start_all.sh   # starts Docker services, backend, and frontend"
log "tests: scripts/preflight.sh   # backend + frontend verification suite"
