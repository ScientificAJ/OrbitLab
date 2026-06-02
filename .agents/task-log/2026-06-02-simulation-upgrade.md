# Task Log: Mission-Grade Simulation Upgrade

- Task number: 2 of 3 in the rolling cadence.
- Start time: 2026-06-02 Asia/Kolkata.
- Goal: Upgrade OrbitLab's in-place orbit simulation into a truth-coded, mission-grade scene with stronger transit/orbit, habitable-zone, and evidence-confidence visuals.
- Expected verification level: Major UI/simulation change. Run frontend lint, unit tests, build, focused Playwright coverage, canvas smoke, and the full frontend e2e suite if practical.
- Cadence status: Task 2. Full cadence suite is due on task 3, but this task is major enough to run broad verification now.
- Key risk: Preserve existing props, test IDs, workflow layout, theme persistence, WebGL fallback, and candidate-selection behavior while making the simulation meaningfully more beautiful and scientifically legible.
