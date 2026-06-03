# Operation Friday Beta Task Log

- Task number: 3 of 3 in the rolling cadence.
- Start time: 2026-06-03 10:24:14 IST.
- Goal: Run API-only real-data workflows for five selected targets, audit scientific/API inaccuracies, fix issues immediately, write reports, run the full verification gate, and push.
- Expected verification: Full cadence and major-task gate: API-only live workflow evidence, generated reports, focused fixes, backend tests, frontend lint/unit/e2e/build, `scripts/preflight.sh`, relevant benchmark/report checks, CI/CodeQL after push.
- Cadence status: Task 3. This task pays the full-suite cadence and is also major enough to require full verification by itself.
- Initial state: local worktree was clean before adding operation files.
- Operation folder: `operation-friday-beta/`.
- Selected targets: `TIC 307210830`/TESS, `TOI-700`/TESS, `Kepler-10`/Kepler, `EPIC 201367065`/K2, and `TIC 25155310`/TESS control-style target.
- API workflow scope: health, models, search, products, TPF preview, aperture mask, BLS preview, analysis job, analysis polling, analysis result, report export, save session, and list sessions.
- Shakedown finding:
  - Initial runner picked a 269 MB TESS fast-cadence product for `TIC 307210830` because product selection compared mission by exact string and sorted product IDs lexicographically.
  - Stopped the partial run and backend analysis job.
  - Fixed runner product selection to treat `TESS Sector ...` as mission match and prefer standard/smaller TPFs before fast-cadence files.
  - Fixed runner to clean each case report directory before execution so interrupted artifacts do not pollute evidence.
