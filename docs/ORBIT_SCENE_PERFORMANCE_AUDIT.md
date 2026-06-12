# OrbitScene Performance Audit

Date: 2026-06-12

Compared commits:

- Current: `d03c10f` (`feat: OrbitScene AAA visual upgrade (#47)`)
- Previous: `3f365ec` (`docs: OrbitScene AAA visual upgrade implementation plan`)

## Verdict

The AAA visual upgrade substantially improves the OrbitScene presentation, but
it also materially increases real-user rendering cost. The backend and science
pipeline are unaffected. The main risk is lower frame rate, increased power
usage, and interaction lag on mobile devices, integrated GPUs, and older
hardware.

The exact FPS regression has not yet been quantified because the existing
automated browser path detects `navigator.webdriver` and deliberately skips the
expensive visual path.

## Change Summary

The latest commit changed 18 files with 2,276 insertions and 58 deletions.

Major runtime additions:

- `frontend/src/components/OrbitScene.tsx`: 842 insertions and 47 deletions.
- `frontend/src/shaders/planet.ts`: new procedural planet shader.
- `frontend/src/shaders/star.ts`: new procedural star shader.
- `frontend/src/shaders/orbitTrail.ts`: new animated orbit-trail shader.
- `frontend/src/shaders/postprocess/`: bloom-adjacent cinematic post-processing
  passes for chromatic aberration, film grain, and vignette.
- `frontend/src/components/OrbitSceneTheater.tsx`: full-screen theater mode.
- `frontend/src/lib/cameraAnimator.ts`: cinematic camera movement.

## Highest-Risk Performance Changes

### 1. Per-frame JavaScript particle updates

`frontend/src/components/OrbitScene.tsx` creates 6,000 stellar-wind particles
and updates every particle position in JavaScript on every animation frame.
This is the clearest CPU-side lag risk.

Relevant areas:

- Stellar-wind allocation: around lines 889-921.
- Per-frame particle loop: around lines 1129-1144.

### 2. Always-on post-processing for normal users

Normal users now render through an `EffectComposer`. Panel mode includes bloom,
while theater mode adds chromatic aberration, film grain, and vignette. These
full-screen passes increase GPU fill-rate and memory-bandwidth cost.

Relevant areas:

- Post-processing setup: around lines 570-612.
- Per-frame composer render: around lines 1285-1290.

### 3. Increased scene complexity

- Background stars increased from 760 to 3,200.
- A second 200-star parallax layer was added.
- Corona rays, prominences, nebula, galaxy, meteor, clouds, and rings add draw
  calls and geometry.
- Planet sphere geometry increased from `32x32` to `48x48`.
- Procedural planet and star shaders perform repeated FBM/noise calculations.

Relevant areas:

- Star layers: around lines 758-851.
- Extra background and stellar effects: around lines 853-939.
- Planet geometry and materials: around lines 943-1035.
- Planet shader: `frontend/src/shaders/planet.ts`.
- Star shader: `frontend/src/shaders/star.ts`.

### 4. Full scene rebuilds

The WebGL effect depends on selection, playback, speed, zoom, reset, candidate
count, and theater mode. Changes to these values dispose and rebuild the full
scene. Cleanup is careful, but rebuilding an increasingly expensive scene can
still cause visible interaction stalls.

Relevant area:

- Effect dependency list and cleanup: around lines 1307-1345.

## Existing Safeguards

- Device pixel ratio is capped at `1.55`.
- `?orbitfx=off` disables post-processing for diagnosis.
- Automated-browser rendering uses a lower-detail fallback.
- Composer, geometry, materials, textures, renderer, and WebGL contexts are
  explicitly disposed.
- Reduced-motion CSS disables theater and mission-overlay transitions.

These safeguards reduce some risk, but they do not provide adaptive runtime
quality or protect real users from low frame rates.

## Required Performance Work

1. Establish a real-user-path performance benchmark with
   `navigator.webdriver=false`.
2. Record panel and theater-mode FPS, frame time, CPU time, GPU time where
   available, long tasks, memory, and interaction latency.
3. Move stellar-wind animation from the 6,000-item JavaScript frame loop to a
   GPU shader, or sharply reduce the particle count on lower quality tiers.
4. Introduce adaptive quality tiers using device capability and measured frame
   time.
5. Disable or reduce bloom and cinematic post-processing when frame time
   exceeds budget.
6. Pause rendering when OrbitScene is offscreen, the document is hidden, or no
   candidate animation is needed.
7. Avoid full scene rebuilds for playback, speed, zoom, selection, and theater
   changes where mutable uniforms or refs can update safely.
8. Respect `prefers-reduced-motion` inside the WebGL renderer, not only in CSS.
9. Add a performance regression check that exercises the full shader path.

## Acceptance Criteria

- Maintain at least 55 FPS in panel mode and 45 FPS in theater mode on the
  agreed reference machine with representative candidates.
- No frame over 100 ms during selection, speed, zoom, pause, reset, or theater
  transitions.
- No continuous animation work while OrbitScene is offscreen or the document
  is hidden.
- No WebGL context leaks after repeated scene rebuilds and theater toggles.
- Preserve the AAA visual direction; degrade effects progressively instead of
  removing the feature.

## Verification Performed During Audit

- Focused frontend tests passed: 41/41.
- Current production build passed in 112.71 seconds with approximately 2.31 GB
  peak resident memory.
- Current Three.js production chunk: 531.45 KB, 133.31 KB gzip.
- `git diff --check HEAD^ HEAD` passed.
- Previous-commit production builds were terminated by the local environment
  during chunk rendering, so no honest before/after bundle-size delta was
  recorded.
