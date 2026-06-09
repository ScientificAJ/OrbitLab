# Task: Drive Codecov to literal 100% on backend + frontend

- Start: 2026-06-08 18:25
- Cadence: task 2 of 3 (prior: 2026-06-08-codecov-frontend-coverage = task 1)
- Goal: Reach literal 100% Codecov coverage on BOTH backend and frontend by
  writing real tests (no code deletion, no coverage exclusions). Add the
  React test stack (testing-library + jsdom), mock three/Plotly/network so
  every line + branch executes, then enforce 100% in codecov.yml.
- Decisions (user): test absolutely everything (no pragma/istanbul ignore);
  add full React test stack; one big push; deliver on a feature branch.
- Baseline measured: backend 86.25% line / 67.5% branch (596 missed lines /
  34 files); frontend ~7% true coverage across all src (App.tsx 2306 lines 0%).
- Expected verification (HIGH risk, full suite required this task):
  - backend: `.venv/bin/python -m pytest --cov=orbitlab --cov-report=term-missing
    --cov-report=xml` -> 100% line+branch, term-missing empty
  - frontend: `npm run test:unit:coverage --prefix frontend` -> 100/100/100/100,
    vitest threshold gate passes; `npm run lint` + `npm run build` clean
  - keep Playwright e2e green; `ruff check backend scripts` clean
- Files: frontend/package.json, frontend/vite.config.ts, frontend/src/test/*,
  frontend/src/**/*.test.{ts,tsx}, backend/tests/*, codecov.yml,
  .github/workflows/ci.yml
- Branch: coverage/full-100-percent
- Resume: 2026-06-08 22:20 IST with Codex after Claude stopped mid-App.tsx
  expansion. Current dirty state: modified OrbitScene branch test plus new
  App.test.tsx. Continue preserving behavior and science semantics; no
  production simplification for coverage.
- Codex checkpoint: frontend `npm run test:unit:coverage --prefix frontend`
  now reaches 100% line coverage (137 tests passing) but still fails local
  V8 statement/branch/function thresholds; remaining branch gaps are defensive
  or JSX-path coverage. Backend `.venv/bin/python -m pytest --cov=orbitlab
  --cov-report=term-missing --cov-report=xml` passes 238 tests but remains 82%
  overall with 596 missed lines.
- Backend milestone: the full backend suite now passes with literal 100% line
  and branch coverage: 369 passed; 4327 statements, 0 missed; 1224 branches,
  0 partial. Backend Ruff is also clean.
- Frontend completion pass started 2026-06-09. Delivery remains the separate
  `coverage/full-100-percent` test branch for user validation before any merge
  to main. Preserve all product/science behavior and use no coverage exclusions.
- Frontend completion milestone: `npm run test:unit:coverage --prefix frontend`
  passes 165 tests with literal 100% statements (1224/1224), branches
  (1129/1129), functions (250/250), and lines (1110/1110). `main.tsx` is
  included in the denominator; only tests, declarations, and shared test setup
  are excluded.
- Frontend regression verification: lint, Prettier check, production build,
  and full Playwright pass clean. Playwright result: 25 passed, 1 intentionally
  skipped live smoke. A focused rerun confirmed the beginner selection pulse
  and report-export UX after restoring the disabled export guard.
- Final cross-stack verification on 2026-06-09: backend coverage remains
  literal 100% with 369 passed and Ruff clean. Codecov now requires 100% for
  both backend and frontend flags, 100% patch coverage, zero threshold, and
  fails CI on upload errors.
