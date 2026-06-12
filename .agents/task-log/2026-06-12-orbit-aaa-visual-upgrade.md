# Task: OrbitScene AAA Visual Upgrade (plan execution)

- **Start:** 2026-06-12
- **Cadence:** task 1 of 3 (major task — full suite + lint + build run at the end regardless)
- **Goal:** Execute docs/superpowers/plans/2026-06-12-orbit-scene-aaa-visual-upgrade.md — GLSL star + planet shaders, theater mode, post-processing, Milky Way background, comet orbit trails, cinematic camera, mission HUD. Creative mandate: 100+ tagged `[CREATIVE]` additions.
- **Branch:** feature/orbit-aaa-visuals (repo requires PR + squash merge to main)
- **Expected verification:** vitest unit suite per task, lint + tsc build at end, live smoke via Vite dev server + browser screenshot if practical.
- **Known plan corrections (found in pre-execution review):**
  1. jsdom tests run the FULL detail path (navigator.webdriver falsy) — threeMock needs Group, curves, geometry attributes, Color.r/g/b; `three/examples/jsm/*` imports need their own vi.mock entries.
  2. orbitTrail shader: torus ring angle is atan2(y,x) in local space (mesh rotated into XZ), and uPlanetAngle must be wrapped mod 2π.
  3. classifyPlanet 501–600 K gap → close boundary at 500 K.
  4. theaterMode must join the scene useEffect deps (composer config differs per mode).
  5. Keep makeStarMaterial() as the automatedBrowser fallback (don't degrade e2e visuals).
