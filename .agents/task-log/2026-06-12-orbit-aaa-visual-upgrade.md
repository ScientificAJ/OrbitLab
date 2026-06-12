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

## Progress
- Commits on feature/orbit-aaa-visuals (pushed):
  - 33dbe48 threeMock extensions
  - 7365592 planetClassifier (+500K gap fix, 11 tests)
  - 95235e4 theater mode (+4 tests: expand/exit/Escape/F/form-field guard)
  - b590623 star shader (granulation, limb darkening, sunspot cycle, CME, HZ-spectral inference)
  - a006a39 corona rays + prominences (spectral tint, eruption cycle)
  - 354011a consolidated: planet shaders, trails, Milky Way, wind, meteor, clouds,
    rings, composer (bloom/chroma/grain/vignette), cameraAnimator (7 tests),
    theater free-look drag, mission HUD overlay (+1 overlay test)
- Verification: 178/178 unit tests, eslint clean, prettier clean, vite build OK.
- Live smoke (full, real WebGL 2.0 via Playwright Chromium with webdriver
  spoofed false so the full shader path runs):
  - TIC 307210830 preview loaded a real candidate (hot-rocky 933 K, blocked
    evidence → ghosted). Star, corona rays, prominences, Milky Way, wind,
    comet trail, planet, dolly close-up, theater mode + mission overlay all
    verified visually. Zero console errors entire session.
  - Found+fixed live: WebGL context exhaustion across effect rebuilds
    (forceContextLoss), composer-vs-premultiplied-alpha black screen (opaque
    scene.background under composer), linear-blend overlay amplification
    (overlayAlpha 0.32x), theater drag compounding, film grain too hot.
- Known pre-existing issue (NOT from this branch, reproduced identically on
  main): with candidates loaded at 1680x1000 the .center-stage grid row gives
  .orbit-scene a 6405px height. Panel still renders correctly inside; worth a
  separate layout fix.
- Note: chrome-devtools MCP browser reports navigator.webdriver=true → it only
  exercises the automatedBrowser fallback path; its headless instance also
  blocklisted WebGL after the context-exhaustion bug. Use Playwright +
  addInitScript(webdriver=false) for shader smoke tests.
