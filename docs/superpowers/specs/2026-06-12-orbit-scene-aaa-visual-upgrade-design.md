# OrbitScene AAA Visual Upgrade — Design Spec
**Date:** 2026-06-12
**Status:** Approved for implementation
**Author:** Brainstorming session (user + Claude)

---

## Vision

Transform OrbitScene from a functional scientific diagram into a jaw-dropping, award-winning 3D planetary simulation — the kind that makes NASA scientists stop scrolling. The visual quality target is AAA: SpaceEngine, Elite Dangerous, No Man's Sky. Every planet looks like a real world. The star feels alive. The scene has cinematic depth, post-processing polish, and theatrical presence.

**The constraint that makes it special:** Every visual choice is grounded in real science data. A planet looks like a lava world because its equilibrium temperature is 1800 K — not because it was hand-painted. The beauty comes from the physics.

---

## Layout & Modes

### Panel Mode (default)
- OrbitScene stays embedded in the existing React panel alongside the science dashboard — same position, same dimensions, no layout disruption.
- A **fullscreen button** (expand icon, top-right corner of the panel, visible on hover) allows entering Theater Mode.

### Theater Mode (fullscreen)
- Triggered by the expand button or keyboard shortcut `F` while the scene is focused.
- The scene takes over the entire viewport with a smooth CSS transition (scale + fade, ~300ms).
- In theater mode: all HUD elements are visible, extra camera controls appear, the science badge expands into a full mission-control overlay panel.
- Exit via `Escape`, the collapse button, or clicking outside the scene.
- State is preserved between modes — selected candidate, camera position, animation state all carry over.

---

## Rendering Architecture

### Technology Stack
- **Three.js** (already in use) — keep existing scene graph structure
- **Three.js EffectComposer** (postprocessing) — for bloom, chromatic aberration, film grain, vignette
- **Custom GLSL ShaderMaterial** — replaces `MeshStandardMaterial` for all planets and the star
- **Three.js InstancedMesh** — for ring particles, asteroid belt, stellar wind
- All new shader code lives in `/frontend/src/shaders/` as `.glsl` files (or inline template literals)

### Performance Contract
- Panel mode: 60 fps on integrated GPU (M1/M2 MacBook, modern laptop). Reduced segment counts acceptable.
- Theater mode: full quality, may drop to 45 fps on integrated GPU — acceptable for immersive mode.
- Automated browser / test environment: existing `automatedBrowser` guard preserved — reduced geometry, no post-processing, deterministic output for snapshots.
- Graceful degradation: if `EffectComposer` fails (WebGL1, low-end GPU), fall back to current plain renderer. Science data and interactivity never break.

---

## The Star

### Photosphere
- Replace the current canvas-texture `MeshStandardMaterial` star with a custom `ShaderMaterial` sphere.
- Fragment shader computes **FBM (Fractional Brownian Motion) granulation** entirely on the GPU — 5–6 octaves of value noise, domain-warped for organic cell shapes.
- **Limb darkening** applied per-pixel using the Eddington approximation: `I(μ) = I₀(a + b·μ)` where `μ = cos(θ)` from center to limb.
- **Animated sunspot groups**: low-frequency noise threshold creates darker patches that drift slowly across the photosphere. Time-uniform drives the drift.
- **Spectral color** varies by star type: G-type (yellow-white, current), K-type (orange), F-type (white-yellow), M-type (deep orange-red). Derive from host star data if available in the candidate payload, otherwise default to G.

### Corona & Atmosphere
- **Animated corona rays**: 12–16 `CatmullRomCurve3`-based tube geometries rotating slowly around the star limb. Each ray has a gradient opacity material (bright at base, fade to zero). Rotation speed varies per ray for organic feel.
- **Solar prominences**: 3–5 arc-shaped tube meshes, quadratic bezier paths, orange-red additive material. Slowly animate along the limb. When a planet is in a close orbit, a prominence arc can reach toward it (cosmetic only).
- **Corona volumetric bloom**: handled by EffectComposer `UnrealBloomPass` — threshold tuned so only the star and lava planets trigger full bloom. Planets get secondary bloom at lower intensity.

### Lens Effects (post-processing, Theater Mode enhanced)
- **Lens flare spikes**: 8 `Lensflare` elements from Three.js (or custom sprite-based) — 4 primary spikes + 4 diagonal secondary. Scale with star screen-size.
- **Lens ghosts**: 3–4 secondary iris ghosts along the flare axis (the line from star through screen center), subtly colored (blue, amber, violet). Visible when star is in frame.
- **Godray shafts**: additive layered cone sprites from star toward camera, partially alpha-masked by planet silhouettes. 4–6 shafts at slight angular spread.

---

## Planet Classes & Shaders

Planet class is determined from `physics.equilibrium_temperature_k` and orbital/physical properties. If temperature data is unavailable, class falls back by SNR/period heuristics, then to a neutral "candidate" look.

| Class | Temperature Range | Visual |
|---|---|---|
| Lava / Ultra-hot | > 1200 K | Dark cracked crust, glowing magma veins, ember scatter, orange-red atmosphere |
| Hot Rocky / Desert | 600–1200 K | Crater fields, red-brown dust bands, haze |
| Temperate / Ocean | 200–400 K + HZ | Continents, polar ice caps, cloud layer, blue atmosphere, city lights on night side |
| Cold Rocky | 100–200 K | Grey craters, frost patches, thin atmosphere |
| Ice World | < 100 K | Frost fracture patterns, subsurface ocean hints, blue-white, thin haze |
| Gas Giant | High radius ratio or inferred from period/depth | Multi-layer atmospheric bands, Great Spot analogue, thick clouds |
| Unknown / Preview | No physics data | Neutral grey-blue, minimal detail, ghosted appearance |

### All Planet GLSL Shader Features
These apply to every planet class (implemented in shared planet vertex/fragment shader):

1. **FBM surface noise** — 5–6 octaves, domain-warped, UV-mapped to sphere. No repeated tiling artifacts.
2. **Per-pixel star lighting** — diffuse + specular computed in the shader from the star's world position uniform. No `MeshStandardMaterial` lighting — full control.
3. **Day/night terminator** — smooth transition zone ~15° wide. Night side receives `nightColor` tint (dark blue for ocean, near-black for rocky/lava).
4. **Atmosphere scattering rim** — view-angle-dependent fresnel rim glow toward the star. Color is class-specific (blue for ocean, orange for lava, teal for ice, amber for gas).
5. **Specular highlight** — ocean and ice worlds get a moving specular patch tracking the star angle. Lava worlds get specular on molten cracks.

### Class-Specific Additions

**Lava World:**
- Domain-warped FBM creates crust vs crack discrimination — crack pixels glow orange-red, crust pixels are near-black charcoal
- Ember scatter: secondary high-frequency noise layer brightens random crust pixels orange
- Animated: crust/crack pattern slowly scrolls (1 cycle per ~120 seconds)
- Atmosphere rim: orange-red, slightly pulsing opacity

**Temperate / Ocean World:**
- Three-layer surface: ocean (FBM-shaped, blue), land (threshold above sea-level noise, green-brown), polar ice caps (latitude-based fade)
- Cloud layer: second sphere 1.5% larger, semi-transparent `MeshBasicMaterial` with scrolling FBM noise, slightly self-illuminated
- **City lights** on night side: warm yellow-orange procedural clusters on land areas only, visible once terminator crosses. This is the most emotionally powerful detail.
- Specular ocean glint: bright moving highlight on the day-side ocean

**Gas Giant:**
- Multi-layer atmospheric band shader: 3–4 sine-wave band frequencies superimposed with noise perturbation for organic waviness
- Great Spot: an oval vortex region defined in UV space, slightly different hue, slowly drifting in longitude
- Animated cloud wisps: high-frequency noise scrolling faster than base bands
- Thick atmosphere rim: wide, warm amber

**Ice World:**
- Frost fracture network: FBM threshold creates bright crack lines on a blue-white base
- Subtle subsurface ocean hint: darker patches visible where "ice" is thinner (lower noise values)
- Thin haze: minimal atmosphere rim, pale blue-white

**Rocky / Desert:**
- Crater field: circular depression features generated from noise-seeded positions, dark-rimmed
- Dust band streaks: diagonal noise streaks in rust/brown across surface
- No clouds, minimal atmosphere

### Rings (Gas Giants & Large Rocky Worlds)
- Three `RingGeometry` meshes at different radii with noise-varied per-vertex alpha for density variation
- **Cassini division**: explicit gap between inner and outer ring mesh
- **Shadow projection**: ring casts a shadow band across the planet face (computed in planet shader as a UV-space stripe)
- Ring particle shimmer: subtle `UnrealBloomPass` contribution makes bright ring particles catch the star

### Moons
- 1–2 small companion spheres for large-radius candidates
- Their own simplified planet shader (low octave count)
- Orbit the planet with a period derived from the planet's own orbital period (cosmetic, not physical)
- Cast a tiny shadow on planet face when aligned

---

## Orbit Trails

Replace the current `TorusGeometry` orbit rings with **comet-tail trail geometry**:

- Custom `ShaderMaterial` applied to `TorusGeometry` — but a vertex/fragment shader attenuates alpha based on angular position relative to the planet's current position.
- The arc behind the planet is bright (full `orbitOpacity`); the arc ahead fades to zero over ~270°.
- Active/selected planet: trail is wider, brighter, with additive blending for a glowing trail effect.
- Ghosted/blocked candidates: trail is barely visible, desaturated.

---

## Background & Starfield

Replace the current 760-dot uniform starfield with a **layered Milky Way scene**:

- **3000+ background stars** distributed with realistic Milky Way density — denser toward a band across the scene, sparser at poles. Three.js `Points` with vertex colors.
- **Color temperature distribution**: 70% yellow-white (G/K dwarfs), 20% blue-white (hot B/A stars), 10% orange-red (M giants, cool stars). Each star tinted accordingly.
- **Parallax depth**: two or three `Points` layers at different `z` positions, each rotating at slightly different speeds for subtle depth.
- **Nebula cloud**: one large low-opacity `Sprite` with a softly-colored radial texture — blue-purple haze — placed off-center in the background. Adds colour and cosmic atmosphere.
- **Asteroid belt ring**: a faint `InstancedMesh` of 500–1000 tiny rock meshes in a torus between orbit slots, visible as a dusty band. Density tuned to not compete with planets.

---

## Particle Systems

### Stellar Wind
- `InstancedMesh` of 8000–15000 tiny point-like meshes streaming outward from the star in all directions
- Per-instance velocity: outward + small angular spread
- Each planet has a "magnetosphere bubble" — particles deflect around it (computed as a repulsion zone in the per-frame update loop)
- Color: pale yellow → fade to transparent at max radius
- Panel mode: reduced to 3000 particles. Theater mode: full count.

### Transit Shadow Disc
- When a planet's screen-projected position crosses the star disc (computed each frame), a dark `CircleGeometry` disc appears on the star face
- Disc radius = planet radius projected onto star face
- Soft penumbra: the disc material has a radial gradient (solid center, transparent edge)
- This is the core science event OrbitLab detects — seeing it happen in real time is a narrative payoff

---

## Post-Processing Stack (EffectComposer)

Order of passes:
1. **RenderPass** — scene render
2. **UnrealBloomPass** — threshold 0.85, strength 0.9, radius 0.4. Only star + lava planets exceed threshold.
3. **Custom ChromaticAberrationPass** — RGB channel offset, max 1.2px at screen edges, 0 at center. Increases in theater mode.
4. **Custom FilmGrainPass** — animated noise overlay, opacity 0.03 (subtle). Makes it feel captured, not rendered.
5. **Custom VignettePass** — radial darkening toward edges, darker in theater mode.
6. **OutputPass** — tone mapping + gamma correction

In panel mode: bloom only (passes 1, 2, 6). Full stack in theater mode. Automated browser: pass-through (no EffectComposer), existing plain renderer.

---

## Camera System

### Panel Mode Camera
- Existing camera logic preserved: lerp toward selected planet's x-offset, `lookAt(0,0,0)`.
- Same zoom modes and speed modes.

### Selection Dolly (new)
- When a candidate is selected, instead of a plain lerp: a **GSAP (or custom cubic bezier) camera animation** moves the camera along a smooth arc to a 3/4 closeup position of the selected planet.
- Dolly in over ~1.2 seconds → hold at closeup for 1.5 seconds showing surface detail → ease back to system view over 0.8 seconds.
- The dolly arc passes slightly above the planet's orbital plane for a cinematic angle.
- Only triggers when `selectedId` changes. Does not re-trigger on re-render with same selection.

### Theater Mode Camera
- **Orbit controls** (Three.js `OrbitControls` or equivalent) enabled — user can drag to rotate, scroll to zoom, right-drag to pan.
- Limits: min distance 4, max distance 60, polar angle 10°–170°, no restriction on azimuth.
- Double-click on a planet: snap camera to closeup of that planet (same dolly animation as above).
- Reset button: animated return to default position.

---

## HUD & Science Overlays

### Panel Mode Badge (enhanced)
- Existing `orbit-metric-badge` component kept and expanded.
- Animated fill bars: SNR confidence bar animates from 0 to current value when a new planet is selected.
- Temperature readout: color-coded — red for lava, green for HZ, blue for ice.
- Habitable zone badge glows green with a subtle pulse animation.

### Theater Mode Mission Control Overlay
- Full-width bottom HUD strip (semi-transparent, blurred background).
- Left panel: candidate ID, planet class name, key stats (period, temperature, SNR, depth, confidence %).
- Center: animated orbital period arc — a circular arc that sweeps as the planet completes one orbit in the simulation.
- Right panel: validation flags, science readiness status, false positive flags listed with severity colors.
- The overlay appears with a slide-up animation when entering theater mode.

---

## Science Data Contracts (unchanged)

The following contracts from the current implementation are **preserved without change**:

- `candidateRenderData()` function — same input/output signature
- `evidenceTone()`, `confidenceScore()`, `orbitRadius()`, `planetScale()` — all preserved
- `onSelectCandidate` callback — preserved
- `isPlaying`, `speedMode`, `zoomMode` controls — preserved
- `orbit-scene`, `orbit-hud`, `orbit-metric-badge`, `orbit-labels`, `orbit-empty-state`, `orbit-fallback` DOM structure and test IDs — preserved
- `automatedBrowser` guard — preserved, disables post-processing and reduces geometry

The new shader system reads from `CandidateRenderData` exactly as the current material system does. No backend changes required.

---

## File Structure

```
frontend/src/
  components/
    OrbitScene.tsx              ← main component (modified)
    OrbitSceneTheater.tsx       ← new: fullscreen portal wrapper
  shaders/
    planet.vert.glsl            ← shared planet vertex shader
    planet.frag.glsl            ← shared planet fragment shader (class-driven)
    star.vert.glsl
    star.frag.glsl
    orbitTrail.frag.glsl        ← comet-tail alpha attenuation
    postprocess/
      ChromaticAberration.ts
      FilmGrain.ts
      Vignette.ts
  lib/
    planetClassifier.ts         ← temperature → planet class enum
    shaderLoader.ts             ← loads .glsl files as strings
```

---

## Open Questions (resolved)

- **Embedded vs fullscreen?** → Both. Panel is default; fullscreen theater mode via expand button. ✓
- **Art direction?** → C (Data-Driven Worlds + Cinematic Polish) with all features from A and B. ✓
- **Star treatment?** → Epic Presence (C) — full lens flare, volumetric corona, godrays, filaments. ✓
- **Science data contract?** → Fully preserved. Visual layer only. ✓
- **Performance?** → 60fps panel mode; theater mode full quality. Graceful degradation on low-end. ✓

---

## Success Criteria

1. A NASA planetary scientist sees the simulation and says "that looks real."
2. Every planet's appearance can be explained by its science data — no arbitrary aesthetics.
3. The panel mode loads and runs at 60fps without disrupting the existing dashboard layout.
4. Theater mode expands and contracts without losing scene state.
5. All existing OrbitScene tests pass without modification.
6. The automated browser / CI path produces the same deterministic snapshots as before.
