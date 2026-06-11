# Task: First-run install welcome popup + install.sh

- Start: 2026-06-11
- Cadence: task 3 of 3 — full appropriate suite due at the end of this task.
- Goal:
  1. Create root `install.sh` as the canonical one-shot dependency installer
     (delegates to `BOOTSTRAP_ONLY=1 scripts/start_all.sh`, then adds the
     dependencies nothing currently installs: Playwright e2e browsers and
     pre-pulled Docker images for fast first start).
  2. Add a bright, futuristic first-run popup in the frontend that appears the
     first time someone opens OrbitLab (localStorage gate
     `orbitlab-first-run-acknowledged`) and points them at `./install.sh`,
     then hands off to the beginner tour.
  3. Update unit/e2e tests (new modal appears on fresh storage), preflight
     syntax checks, and README Quick Start.
- Expected verification: full `scripts/preflight.sh` (backend tests, frontend
  format/lint/unit/e2e/build, shell syntax, py-compile) per cadence rule.
- Push: required after verification.

## Notes

- No `install.sh` existed before this task; `scripts/start_all.sh` (commit
  cb79e7d) already bootstraps system packages, venv + `[dev,science,api,ml]`,
  `npm ci`, the three ML artifacts, and the DAVE ModShift binary via
  `BOOTSTRAP_ONLY=1`.
- Missing from any installer today: Playwright browsers (needed by
  `npm run test:e2e` when `/opt/google/chrome/chrome` is absent) and Docker
  image pre-pull (redis:7-alpine, postgres:16-alpine,
  tensorflow/tensorflow:1.5.0-py3).
- e2e `openApp` helper defaults to seeding the new ack flag; live smoke spec
  seeds it via addInitScript; unit-test global beforeEach seeds it.

## Verification (completed 2026-06-12)

- Full `scripts/preflight.sh`: backend 419 passed; frontend format/lint OK,
  155 unit tests passed (8 new first-run tests).
- First e2e pass failed on a Playwright strict-mode violation in the new test
  (`getByText('Choose a mission')` matched both the tour heading and the
  beginner workflow message); fixed to `getByRole('heading', ...)`; full e2e
  rerun: 26 passed, 1 skipped (LIVE_ORBITLAB gate). Production build OK.
- Live browser smoke on a scratch Vite server (port 5174): popup appears on
  fresh profile, dismiss hands off to the beginner tour, ack persists, reload
  does not re-show; checked on space and light themes via screenshots.
- `./install.sh` live run: completed the venv `[ml]` extra (TensorFlow etc.),
  `npm ci`, ModShift check, skipped Playwright download because system Chrome
  exists, pre-pulled Docker images; exit 0. Idempotent re-run: 6.8s.
- Because the live install changed the venv, backend pytest + ruff were rerun
  against the final environment before push.
