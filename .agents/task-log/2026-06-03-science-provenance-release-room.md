# Task Log: Science Provenance Release Room

- Task number: 1 of 3 in the rolling cadence.
- Start time: 2026-06-03 01:14:49 IST.
- Goal: Implement all three layers of the Science Provenance Release Room in one pass and publish a new OrbitLab release/build because the first release is stale.
- Expected verification level: Full release-grade verification. Generate a local release room, validate checksums/SBOM/benchmark delta assets, run focused tests for the new generator, run full preflight, push, create the release, and verify GitHub release assets/workflows.
- Cadence status: Task 1. This task is high-risk enough to run the full suite immediately instead of delaying to task 3.
- Key risk: Release evidence must be generated from authoritative repo/model/benchmark state and must not imply stronger science confidence than the benchmark data proves.
- Completed fixes:
  - Added a Science Provenance Release Room generator for release metadata, model artifact checksums, calibration/source checksums, science benchmark reports, benchmark deltas, SPDX SBOM, release checksums, and a zipped release-room bundle.
  - Added a GitHub release workflow that builds the frontend, fetches pinned model artifacts, regenerates the release room, uploads release assets, and creates provenance/SBOM attestations.
  - Updated release documentation, changelog, backend/frontend package versions, and focused tests.
  - Fixed a UI animation-state race that full preflight exposed in the beginner preview flow by making reveal/pulse classes deterministic.
- Verification:
  - `ruff check backend scripts`: passed.
  - `pytest backend/tests/test_release_room.py`: 3 passed.
  - `npx prettier --check ../.github/workflows/*.yml ../.github/dependabot.yml`: passed.
  - `scripts/build_release_room.py --tag v0.2.0 --clean`: passed locally; 13 assets, benchmark passed, delta ready, 534 SBOM packages.
  - Focused Playwright retry for the failed beginner flow: passed.
  - `scripts/preflight.sh`: passed; backend 91 tests passed, frontend unit 8 passed, Playwright 25 passed / 1 skipped, production build passed, shell syntax passed, Python compile checks passed.
