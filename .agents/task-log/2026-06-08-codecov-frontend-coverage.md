# Task: Finish CodeCov setup + add frontend coverage

- Start: 2026-06-08
- Cadence: task 1 of 3
- Goal: Harden existing backend Codecov upload (token-aware, verbose) and add
  full frontend (vitest) coverage collection + upload with a `frontend` flag.
  Keep uploads non-blocking (user choice). Works tokenless now, auto-upgrades
  if `CODECOV_TOKEN` secret is added later.
- Expected verification: local backend `pytest --cov ... --cov-report=xml`
  generates coverage.xml; local frontend `npm run test:unit:coverage`
  generates `coverage/lcov.info`; codecov.yml validates; CI diff review.
- Files: .github/workflows/ci.yml, frontend/package.json,
  frontend/vite.config.ts, codecov.yml, .gitignore
