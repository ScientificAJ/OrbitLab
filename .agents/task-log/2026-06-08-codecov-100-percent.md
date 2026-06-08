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
