# Task Log: GitHub Setup And Full-Body Gate

- Task number: 3 of 3 in the rolling cadence.
- Start time: 2026-06-03 Asia/Kolkata.
- Goal: Upgrade OrbitLab's GitHub setup toward production-grade repository hygiene and run the full-body verification gate required by the cadence.
- Expected verification level: Full suite. Run `scripts/preflight.sh`, inspect/fix failures, verify GitHub workflow syntax/configuration, and rerun impacted checks.
- Cadence status: Task 3. This task must pay the delayed-suite debt for the previous two tasks.
- Key risk: CI and repository automation must improve trust without making hackathon direct-push workflow unusable or silently dropping science/ML provenance checks.
- Completed fixes:
  - Added backend Ruff linting to CI after resolving existing backend/script lint failures.
  - Aligned the frontend CI job name with the protected-branch required status check.
  - Added CI concurrency, permissions, timeouts, workflow dispatch, failure artifacts, repository hygiene checks, and stricter ruleset expectations.
  - Strengthened CODEOWNERS, Dependabot commit conventions, and PR validation prompts.
- Verification:
  - `ruff check backend scripts`: passed.
  - `npm run format:check` in `frontend`: passed.
  - `npx prettier --check ../.github/workflows/ci.yml ../.github/workflows/codeql.yml ../.github/dependabot.yml`: passed.
  - `python -m json.tool .github/rulesets/main.json`: passed.
  - `bash -n scripts/preflight.sh scripts/start_all.sh`: passed.
  - `scripts/preflight.sh`: passed; backend 88 tests passed, frontend unit 8 passed, Playwright 25 passed / 1 skipped, production build passed, shell syntax passed, Python compile checks passed.
