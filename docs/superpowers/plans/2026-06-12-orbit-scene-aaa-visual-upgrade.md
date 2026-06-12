# OrbitScene AAA Visual Upgrade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform OrbitScene from a functional scientific diagram into an award-winning AAA 3D planetary simulation using GLSL shaders, post-processing, animated star, data-driven planet classes, theater mode, and cinematic camera.

**Architecture:** Custom ShaderMaterial replaces all MeshStandardMaterial for planets and star; EffectComposer adds post-processing; OrbitSceneTheater wraps the scene in a React portal for fullscreen. All science data contracts and test IDs are preserved.

**Tech Stack:** Three.js 0.184, React 19, Vite, Vitest, TypeScript, GLSL (inline template literals — no .glsl file loader needed in Vite), three/examples/jsm/postprocessing (EffectComposer, UnrealBloomPass, RenderPass, OutputPass)

---

## ⚠️ CREATIVE MANDATE — READ BEFORE EVERY PHASE

You are not a transcription agent. You are a co-creator with full ownership of the visual result. The spec is the **floor**, not the ceiling.

**You are required to contribute a minimum of 100 of your own creative ideas** throughout this implementation. These should be integrated naturally — a detail you notice would look stunning, an interaction that would feel magical, a shader trick you know, a science storytelling moment you imagine.

**Rules:**
- At the start of EVERY phase, pause and ask yourself: *"What would make this phase 10× more alive?"* Write down 3–5 ideas and implement the best ones.
- Tag every creative addition with a comment: `// [CREATIVE: description]`
- Keep a running count. When you hit 100, keep going.
- The creative ideas must be real implementations, not TODO comments.
- Do not let creative additions break tests or science data contracts.

---

## File Map

```
frontend/src/
  components/
    OrbitScene.tsx                  MODIFY — wire new systems, add theater toggle
    OrbitSceneTheater.tsx           CREATE — React portal for fullscreen mode
  shaders/
    star.ts                         CREATE — star vert+frag GLSL strings
    planet.ts                       CREATE — shared planet vert+frag GLSL strings
    orbitTrail.ts                   CREATE — comet-tail frag GLSL string
    postprocess/
      ChromaticAberrationPass.ts   CREATE
      FilmGrainPass.ts             CREATE
      VignettePass.ts              CREATE
  lib/
    planetClassifier.ts             CREATE — temperature → PlanetClass enum
    cameraAnimator.ts               CREATE — cubic bezier dolly controller
    api.ts                          NO CHANGE
    uiState.ts                      NO CHANGE
  test/
    threeMock.ts                    MODIFY — add ShaderMaterial, InstancedMesh, EffectComposer stubs
    planetClassifier.test.ts        CREATE
    orbitTrail.test.ts              CREATE
    cameraAnimator.test.ts          CREATE
  styles/
    app.css                         MODIFY — theater mode CSS
```

---

## Phase 1 — Foundation

> **Creative pause:** Before coding, ask: *What foundation detail would make every later phase feel more polished from day one?* Ideas: a `useAnimationFrame` hook that exposes elapsed time as a float uniform; a shader compiler that validates uniform counts at dev-time; a `debugOverlay` flag that renders wireframes of atmosphere layers.

### Task 1: Install postprocessing package and update Three mock

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/test/threeMock.ts`

- [ ] **Step 1: Install three postprocessing addon**

```bash
cd frontend && npm install three@^0.184.0
```

Three 0.184 ships `three/examples/jsm/postprocessing/` — no extra package needed. Verify:

```bash
ls node_modules/three/examples/jsm/postprocessing/
```

Expected output includes: `EffectComposer.js`, `RenderPass.js`, `UnrealBloomPass.js`, `OutputPass.js`

- [ ] **Step 2: Add ShaderMaterial + InstancedMesh stubs to threeMock.ts**

Open `frontend/src/test/threeMock.ts`. Add after the existing `Color` class:

```typescript
class ShaderMaterial {
  uniforms: Record<string, { value: unknown }> = {};
  vertexShader = '';
  fragmentShader = '';
  transparent = false;
  depthWrite = true;
  side = 0;
  blending = 0;
  constructor(params: Record<string, unknown> = {}) {
    Object.assign(this, params);
  }
  dispose() {}
}

class InstancedMesh {
  count: number;
  instanceMatrix = { needsUpdate: false };
  geometry: unknown;
  material: unknown;
  constructor(_geo: unknown, _mat: unknown, count: number) { this.count = count; }
  setMatrixAt(_i: number, _m: unknown) {}
  dispose() {}
}

class Matrix4 {
  elements = new Float32Array(16);
  identity() { return this; }
  setPosition(_x: number, _y: number, _z: number) { return this; }
  makeRotationY(_r: number) { return this; }
  compose(_p: unknown, _q: unknown, _s: unknown) { return this; }
}

class Quaternion {
  x=0; y=0; z=0; w=1;
  setFromAxisAngle(_axis: unknown, _angle: number) { return this; }
}

// EffectComposer stub — enough for OrbitScene to construct without crashing
class EffectComposer {
  renderer: unknown;
  passes: unknown[] = [];
  constructor(renderer: unknown) { this.renderer = renderer; }
  addPass(_pass: unknown) { this.passes.push(_pass); }
  render(_delta?: number) {}
  setSize(_w: number, _h: number) {}
  dispose() {}
}
class RenderPass { constructor(_scene: unknown, _camera: unknown) {} }
class UnrealBloomPass { threshold=0; strength=0; radius=0; constructor(_res: unknown, _s: number, _r: number, _t: number) {} }
class OutputPass {}
class ShaderPass { constructor(_shader: unknown) {} uniforms: Record<string,{value:unknown}>= {}; }
```

Then add these to the existing `threeMock` export object:

```typescript
ShaderMaterial,
InstancedMesh,
Matrix4,
Quaternion,
EffectComposer,
RenderPass,
UnrealBloomPass,
OutputPass,
ShaderPass,
```

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```bash
cd frontend && npm test -- --run
```

Expected: all existing OrbitScene tests pass (same count as before).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/test/threeMock.ts
git commit -m "test: extend threeMock with ShaderMaterial, InstancedMesh, EffectComposer stubs"
```

---

### Task 2: planetClassifier.ts

**Files:**
- Create: `frontend/src/lib/planetClassifier.ts`
- Create: `frontend/src/lib/planetClassifier.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/lib/planetClassifier.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { classifyPlanet, PlanetClass } from './planetClassifier';

describe('classifyPlanet', () => {
  it('returns LAVA for temperature > 1200', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 1800 })).toBe(PlanetClass.LAVA);
  });
  it('returns HOT_ROCKY for 600–1200 K', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 900 })).toBe(PlanetClass.HOT_ROCKY);
  });
  it('returns OCEAN for 200–400 K with habitable zone', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 288, is_in_habitable_zone: true })).toBe(PlanetClass.OCEAN);
  });
  it('returns COLD_ROCKY for 100–200 K', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 150 })).toBe(PlanetClass.COLD_ROCKY);
  });
  it('returns ICE for < 100 K', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 60 })).toBe(PlanetClass.ICE);
  });
  it('returns GAS for high radius ratio', () => {
    expect(classifyPlanet({ radius_ratio: 0.12 })).toBe(PlanetClass.GAS);
  });
  it('returns UNKNOWN when no data', () => {
    expect(classifyPlanet({})).toBe(PlanetClass.UNKNOWN);
  });
  it('returns OCEAN for 200–400 K even without explicit HZ flag', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 310 })).toBe(PlanetClass.OCEAN);
  });
});
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm test -- --run src/lib/planetClassifier.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement planetClassifier.ts**

Create `frontend/src/lib/planetClassifier.ts`:

```typescript
export enum PlanetClass {
  LAVA = 'lava',
  HOT_ROCKY = 'hot_rocky',
  OCEAN = 'ocean',
  COLD_ROCKY = 'cold_rocky',
  ICE = 'ice',
  GAS = 'gas',
  UNKNOWN = 'unknown',
}

export interface PlanetPhysicsInput {
  equilibrium_temperature_k?: number | null;
  is_in_habitable_zone?: boolean | null;
  radius_ratio?: number | null;
  planet_radius_earth?: number | null;
}

export function classifyPlanet(physics: PlanetPhysicsInput): PlanetClass {
  const { equilibrium_temperature_k: t, radius_ratio: rr, planet_radius_earth: re } = physics;

  // Gas giant: large radius ratio or inferred large planet
  if ((rr != null && rr > 0.08) || (re != null && re > 6)) return PlanetClass.GAS;

  if (t != null) {
    if (t > 1200) return PlanetClass.LAVA;
    if (t > 600) return PlanetClass.HOT_ROCKY;
    if (t >= 200 && t <= 500) return PlanetClass.OCEAN;
    if (t >= 100) return PlanetClass.COLD_ROCKY;
    return PlanetClass.ICE;
  }

  return PlanetClass.UNKNOWN;
}
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd frontend && npm test -- --run src/lib/planetClassifier.test.ts
```

Expected: 8 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/planetClassifier.ts frontend/src/lib/planetClassifier.test.ts
git commit -m "feat: add planetClassifier — temperature-driven planet class enum"
```

---

### Task 3: OrbitSceneTheater.tsx + theater CSS

**Files:**
- Create: `frontend/src/components/OrbitSceneTheater.tsx`
- Modify: `frontend/src/styles/app.css`

- [ ] **Step 1: Add theater CSS to app.css**

Open `frontend/src/styles/app.css` and append:

```css
/* ── Theater Mode ─────────────────────────────────────────── */
.orbit-theater-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9998;
  background: rgba(0, 4, 12, 0.0);
  animation: theater-fade-in 0.3s ease forwards;
}
@keyframes theater-fade-in {
  to { background: rgba(0, 4, 12, 0.96); }
}

.orbit-theater-container {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: theater-scale-in 0.32s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  transform-origin: center center;
}
@keyframes theater-scale-in {
  from { transform: scale(0.88); opacity: 0; }
  to   { transform: scale(1);    opacity: 1; }
}

.orbit-theater-exit {
  position: absolute;
  top: 18px;
  right: 18px;
  z-index: 10000;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 8px;
  color: rgba(255,255,255,0.7);
  font-size: 13px;
  padding: 6px 14px;
  cursor: pointer;
  letter-spacing: 0.04em;
  transition: background 0.15s, color 0.15s;
}
.orbit-theater-exit:hover { background: rgba(255,255,255,0.16); color: #fff; }

.orbit-expand-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 20;
  opacity: 0;
  transition: opacity 0.2s;
  background: rgba(0,0,0,0.5);
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 6px;
  color: rgba(255,255,255,0.75);
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
  line-height: 1;
}
.orbit-scene:hover .orbit-expand-btn { opacity: 1; }
```

- [ ] **Step 2: Create OrbitSceneTheater.tsx**

Create `frontend/src/components/OrbitSceneTheater.tsx`:

```typescript
import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

type Props = {
  children: React.ReactNode;
  onExit: () => void;
};

export function OrbitSceneTheater({ children, onExit }: Props) {
  const backdropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onExit(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onExit]);

  return createPortal(
    <>
      <div className="orbit-theater-backdrop" />
      <div
        className="orbit-theater-container"
        ref={backdropRef}
        data-testid="orbit-theater"
      >
        <button
          type="button"
          className="orbit-theater-exit"
          onClick={onExit}
          aria-label="Exit theater mode"
          data-testid="orbit-theater-exit"
        >
          ✕ Exit
        </button>
        {children}
      </div>
    </>,
    document.body,
  );
}
```

- [ ] **Step 3: Add theater toggle to OrbitScene.tsx**

At the top of `OrbitScene.tsx`, add import:

```typescript
import { OrbitSceneTheater } from './OrbitSceneTheater';
```

Add state in the `OrbitScene` component body (after existing useState lines):

```typescript
const [theaterMode, setTheaterMode] = useState(false);
```

Add keyboard shortcut effect (after existing useEffects):

```typescript
useEffect(() => {
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'f' || e.key === 'F') {
      if (document.activeElement === mountRef.current?.closest('[data-testid="orbit-scene"]') ||
          mountRef.current?.contains(document.activeElement)) {
        setTheaterMode(prev => !prev);
      }
    }
  };
  window.addEventListener('keydown', onKey);
  return () => window.removeEventListener('keydown', onKey);
}, []);
```

In the JSX return, wrap the existing `<div className="orbit-scene"...>` so it renders inside the theater portal when active. Replace the outer `return (` block's first line with:

```typescript
const sceneContent = (
  <div
    className={`orbit-scene ${selectionPulse ? 'selection-pulse' : ''} ${theaterMode ? 'theater' : ''}`}
    ref={mountRef}
    data-testid="orbit-scene"
    tabIndex={0}
    style={theaterMode ? { width: '100vw', height: '100vh', borderRadius: 0 } : undefined}
  >
    <button
      type="button"
      className="orbit-expand-btn"
      aria-label="Enter theater mode"
      data-testid="orbit-expand-btn"
      onClick={() => setTheaterMode(true)}
    >
      ⛶
    </button>
    {/* ... rest of existing JSX unchanged ... */}
  </div>
);

return theaterMode ? (
  <OrbitSceneTheater onExit={() => setTheaterMode(false)}>
    {sceneContent}
  </OrbitSceneTheater>
) : sceneContent;
```

- [ ] **Step 4: Run existing tests — confirm pass**

```bash
cd frontend && npm test -- --run src/components/OrbitScene.test.tsx
```

Expected: all pass. (Theater is opt-in; existing test DOM doesn't trigger it.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/OrbitSceneTheater.tsx frontend/src/components/OrbitScene.tsx frontend/src/styles/app.css
git commit -m "feat: theater mode portal with fullscreen toggle, Escape/F shortcut, exit button"
```

---

## Phase 2 — Star Shader

> **Creative pause:** Before coding, ask: *What would make the star feel alive in a way that surprises even an astronomer?* Ideas: make the granulation cells drift on a curved path (like real solar convection); add a rare coronal mass ejection flash (once every ~3 minutes) that bleeds across the scene; change the star's spectral color based on which candidate system is loaded.

### Task 4: Star GLSL shader module

**Files:**
- Create: `frontend/src/shaders/star.ts`

- [ ] **Step 1: Create the star shader module**

Create `frontend/src/shaders/star.ts`:

```typescript
export const starVertexShader = /* glsl */`
  varying vec3 vNormal;
  varying vec3 vPosition;
  varying vec2 vUv;

  void main() {
    vNormal = normalize(normalMatrix * normal);
    vPosition = position;
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

export const starFragmentShader = /* glsl */`
  uniform float uTime;
  uniform vec3  uColor1;   // core color (hot white)
  uniform vec3  uColor2;   // mid color (yellow)
  uniform vec3  uColor3;   // limb color (deep orange)

  varying vec3 vNormal;
  varying vec3 vPosition;
  varying vec2 vUv;

  // ── Hash / noise ─────────────────────────────────────────
  float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 17.5);
    return fract(p.x * p.y);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash(i), hash(i + vec2(1,0)), u.x),
      mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), u.x),
      u.y
    );
  }

  float fbm(vec2 p, int octaves) {
    float v = 0.0; float amp = 0.5; float freq = 1.0;
    for (int i = 0; i < 6; i++) {
      if (i >= octaves) break;
      v += amp * noise(p * freq);
      amp *= 0.5; freq *= 2.1;
    }
    return v;
  }

  // ── Granulation (domain-warped fbm) ──────────────────────
  float granulation(vec2 uv, float t) {
    vec2 drift = vec2(t * 0.018, t * 0.011); // slow convective drift
    vec2 q = vec2(fbm(uv + drift, 4), fbm(uv + vec2(5.2, 1.3) + drift * 0.8, 4));
    return fbm(uv + 0.9 * q + drift, 5);
  }

  // ── Sunspot ───────────────────────────────────────────────
  float sunspot(vec2 uv, float t) {
    float s = fbm(uv * 0.55 + vec2(t * 0.004, t * 0.003), 3);
    return smoothstep(0.62, 0.55, s); // dark patch where low
  }

  void main() {
    // Limb darkening — Eddington approximation
    vec3 camDir = normalize(cameraPosition - vPosition * 200.0);
    float mu = max(0.0, dot(normalize(vNormal), camDir));
    float limb = 0.4 + 0.6 * mu; // a=0.4, b=0.6

    // Granulation
    float gran = granulation(vUv * 4.0, uTime);
    float spot = sunspot(vUv * 3.0, uTime);

    // Base color — blend from core to limb
    vec3 color = mix(uColor1, mix(uColor2, uColor3, 1.0 - mu), 1.0 - mu * 0.7);

    // Granulation brightens/darkens slightly
    color += (gran - 0.5) * 0.18 * uColor1;

    // Sunspot darkens
    color *= (1.0 - spot * 0.52);

    // Limb darkening
    color *= limb;

    // Emissive — star is self-lit
    gl_FragColor = vec4(color, 1.0);
  }
`;

export function makeStarUniforms(spectralColor: 'G' | 'K' | 'F' | 'M' = 'G') {
  const palettes = {
    G: { c1: [1.00, 0.98, 0.88], c2: [1.00, 0.82, 0.38], c3: [0.88, 0.42, 0.08] },
    K: { c1: [1.00, 0.88, 0.70], c2: [0.98, 0.62, 0.22], c3: [0.80, 0.30, 0.05] },
    F: { c1: [1.00, 1.00, 0.96], c2: [1.00, 0.94, 0.72], c3: [0.92, 0.65, 0.22] },
    M: { c1: [1.00, 0.72, 0.48], c2: [0.90, 0.42, 0.18], c3: [0.72, 0.20, 0.06] },
  };
  const p = palettes[spectralColor];
  return {
    uTime:   { value: 0 },
    uColor1: { value: p.c1 },
    uColor2: { value: p.c2 },
    uColor3: { value: p.c3 },
  };
}
```

- [ ] **Step 2: Wire star shader into OrbitScene.tsx**

In `OrbitScene.tsx`, add import:

```typescript
import { starVertexShader, starFragmentShader, makeStarUniforms } from '../shaders/star';
```

Replace the `makeStarMaterial()` call in the useEffect with:

```typescript
const starUniforms = makeStarUniforms('G');
const star = new THREE.Mesh(
  new THREE.SphereGeometry(1.78, automatedBrowser ? 40 : 64, automatedBrowser ? 40 : 64),
  automatedBrowser
    ? new THREE.MeshStandardMaterial({ color: 0xffd27d, emissive: 0xff8a22, emissiveIntensity: 1.35 })
    : new THREE.ShaderMaterial({
        vertexShader: starVertexShader,
        fragmentShader: starFragmentShader,
        uniforms: starUniforms,
      }),
);
```

In the `tick` animation loop, after `star.rotation.y += ...`, add:

```typescript
if (starUniforms) starUniforms.uTime.value += 0.016;
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm test -- --run src/components/OrbitScene.test.tsx
```

Expected: all pass. (automatedBrowser path uses fallback MeshStandardMaterial.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/shaders/star.ts frontend/src/components/OrbitScene.tsx
git commit -m "feat: GLSL star shader — FBM granulation, limb darkening, animated sunspots, spectral color"
```

---

### Task 5: Corona rays and solar prominences

**Files:**
- Modify: `frontend/src/components/OrbitScene.tsx`

- [ ] **Step 1: Add corona ray builder function to OrbitScene.tsx**

Add this function near the top of the file (alongside the other builder functions):

```typescript
function makeCoronaRays(scene: THREE.Scene, starRadius: number): THREE.Mesh[] {
  const rays: THREE.Mesh[] = [];
  const rayCount = 14;
  for (let i = 0; i < rayCount; i++) {
    const angle = (i / rayCount) * Math.PI * 2;
    const len = starRadius * (1.4 + Math.sin(i * 2.3) * 0.5);
    const points = [];
    for (let t = 0; t <= 1; t += 0.1) {
      const r = starRadius * 1.02 + t * len;
      const wobble = Math.sin(t * Math.PI * 3 + i) * starRadius * 0.08;
      points.push(new THREE.Vector3(
        Math.cos(angle + wobble * 0.05) * r,
        Math.sin(angle + wobble * 0.05) * r * 0.22, // flatten to orbital plane
        0,
      ));
    }
    const curve = new THREE.CatmullRomCurve3(points);
    const geo = new THREE.TubeGeometry(curve, 10, 0.018 + Math.random() * 0.012, 4, false);
    const mat = new THREE.MeshBasicMaterial({
      color: 0xffcc66,
      transparent: true,
      opacity: 0.18 + Math.random() * 0.14,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const ray = new THREE.Mesh(geo, mat);
    ray.userData.baseRotSpeed = 0.0004 + Math.random() * 0.0003;
    ray.userData.rotOffset = angle;
    scene.add(ray);
    rays.push(ray);
  }
  return rays;
}

function makeProminences(scene: THREE.Scene, starRadius: number): THREE.Mesh[] {
  const arcs: THREE.Mesh[] = [];
  const arcDefs = [
    { a1: 0.4, a2: 0.9, h: 0.7, color: 0xff8833 },
    { a1: 2.2, a2: 2.7, h: 0.55, color: 0xff6622 },
    { a1: 4.0, a2: 4.5, h: 0.48, color: 0xffaa44 },
    { a1: 5.1, a2: 5.5, h: 0.38, color: 0xff7733 },
  ];
  arcDefs.forEach(({ a1, a2, h, color }) => {
    const r = starRadius;
    const p1 = new THREE.Vector3(Math.cos(a1) * r, 0, Math.sin(a1) * r);
    const p2 = new THREE.Vector3(Math.cos(a2) * r, 0, Math.sin(a2) * r);
    const mid = p1.clone().add(p2).multiplyScalar(0.5);
    mid.y += r * h;
    const curve = new THREE.QuadraticBezierCurve3(p1, mid, p2);
    const geo = new THREE.TubeGeometry(curve, 20, 0.032, 4, false);
    const mat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.65,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const arc = new THREE.Mesh(geo, mat);
    arc.userData.driftSpeed = 0.0002 + Math.random() * 0.0001;
    scene.add(arc);
    arcs.push(arc);
  });
  return arcs;
}
```

- [ ] **Step 2: Call builders in the useEffect and animate them**

Inside the useEffect, after `scene.add(corona)`:

```typescript
const coronaRays = automatedBrowser ? [] : makeCoronaRays(scene, 1.78);
const prominences = automatedBrowser ? [] : makeProminences(scene, 1.78);
```

Inside the `tick` function, after `corona.material.rotation += ...`:

```typescript
coronaRays.forEach((ray, i) => {
  ray.rotation.y += ray.userData.baseRotSpeed * speed;
  // [CREATIVE: pulse opacity on each ray independently using sin with offset]
  (ray.material as THREE.MeshBasicMaterial).opacity =
    0.14 + Math.sin(frame * 0.018 + i * 0.8) * 0.06;
});
prominences.forEach(arc => {
  arc.rotation.y += arc.userData.driftSpeed * speed;
});
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm test -- --run src/components/OrbitScene.test.tsx
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/OrbitScene.tsx
git commit -m "feat: animated corona rays and solar prominences around star limb"
```

---

## Phase 3 — Planet Shaders

> **Creative pause:** Before coding, ask: *What would make each planet feel like it has a history?* Ideas: add micro-detail normal-map-style noise at high zoom (when planet fills >15% of screen); give lava worlds a slow "tectonic drift" where the crack pattern shifts over 5-minute cycles; add a faint bio-fluorescence shimmer on ocean worlds in the HZ.

### Task 6: Shared planet GLSL shader

**Files:**
- Create: `frontend/src/shaders/planet.ts`

- [ ] **Step 1: Create planet.ts with full GLSL**

Create `frontend/src/shaders/planet.ts`:

```typescript
export const planetVertexShader = /* glsl */`
  varying vec3 vNormal;
  varying vec3 vWorldPos;
  varying vec2 vUv;
  varying float vFresnel;

  uniform vec3 uStarPos;

  void main() {
    vec4 worldPos = modelMatrix * vec4(position, 1.0);
    vWorldPos = worldPos.xyz;
    vNormal = normalize(mat3(modelMatrix) * normal);
    vUv = uv;

    vec3 viewDir = normalize(cameraPosition - worldPos.xyz);
    vFresnel = pow(1.0 - max(0.0, dot(vNormal, viewDir)), 3.0);

    gl_Position = projectionMatrix * viewMatrix * worldPos;
  }
`;

export const planetFragmentShader = /* glsl */`
  uniform float uTime;
  uniform vec3  uStarPos;
  uniform int   uClass;       // 0=unknown 1=lava 2=hot_rocky 3=ocean 4=cold_rocky 5=ice 6=gas
  uniform float uSeed;        // per-planet random seed
  uniform vec3  uAtmColor;    // atmosphere rim color
  uniform float uAtmStrength; // 0–1
  uniform bool  uGhosted;

  varying vec3  vNormal;
  varying vec3  vWorldPos;
  varying vec2  vUv;
  varying float vFresnel;

  // ── Noise ──────────────────────────────────────────────────
  float hash(vec2 p) {
    p = fract(p * vec2(127.1 + uSeed * 0.01, 311.7 + uSeed * 0.007));
    p += dot(p, p + 17.5);
    return fract(p.x * p.y);
  }
  float noise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p);
    vec2 u = f*f*(3.0-2.0*f);
    return mix(mix(hash(i),hash(i+vec2(1,0)),u.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),u.x),u.y);
  }
  float fbm(vec2 p, int oct) {
    float v=0.0,a=0.5,fr=1.0;
    for(int i=0;i<7;i++){if(i>=oct)break; v+=a*noise(p*fr); a*=0.5; fr*=2.1;}
    return v;
  }

  // ── Lighting ───────────────────────────────────────────────
  float diffuse(vec3 normal, vec3 starPos, vec3 worldPos) {
    vec3 L = normalize(starPos - worldPos);
    return max(0.0, dot(normal, L));
  }

  // ── Planet class surfaces ──────────────────────────────────

  vec3 surfaceLava(vec2 uv, float t) {
    vec2 warp = vec2(fbm(uv*1.8+vec2(uSeed,0.0),4), fbm(uv*1.8+vec2(0.0,uSeed),4));
    float crack = fbm(uv*3.2 + warp*1.4 + vec2(t*0.004, 0.0), 5);
    float ember  = fbm(uv*7.0 + vec2(t*0.012, t*0.008), 3);
    vec3 crust = vec3(0.12, 0.06, 0.03);
    vec3 lava  = vec3(1.0, 0.38 + ember*0.2, 0.02);
    float lavaMask = smoothstep(0.48, 0.38, crack);
    vec3 col = mix(crust, lava, lavaMask);
    col += vec3(0.6, 0.2, 0.0) * smoothstep(0.55, 0.72, ember) * (1.0 - lavaMask) * 0.6;
    return col;
  }

  vec3 surfaceHotRocky(vec2 uv) {
    float n = fbm(uv*2.5 + vec2(uSeed*0.1), 5);
    float crater = smoothstep(0.58, 0.54, fbm(uv*4.0+vec2(uSeed*0.3), 3));
    vec3 base = mix(vec3(0.42,0.22,0.12), vec3(0.68,0.38,0.18), n);
    base = mix(base, vec3(0.18,0.10,0.08), crater * 0.6);
    return base;
  }

  vec3 surfaceOcean(vec2 uv, float t) {
    float n = fbm(uv*2.2 + vec2(uSeed*0.08), 5);
    float lat = abs(vUv.y - 0.5) * 2.0; // 0=equator 1=pole
    // land vs ocean
    float landMask = smoothstep(0.42, 0.52, n);
    vec3 ocean = vec3(0.08, 0.28, 0.65) + vec3(0.0, 0.1, 0.2) * fbm(uv*5.0, 3);
    vec3 land  = mix(vec3(0.22,0.48,0.18), vec3(0.52,0.38,0.22), fbm(uv*3.0+vec2(uSeed),3));
    vec3 col = mix(ocean, land, landMask);
    // polar ice
    float iceMask = smoothstep(0.72, 0.88, lat);
    col = mix(col, vec3(0.88,0.92,0.98), iceMask);
    // city lights on night side (added in lighting stage)
    return col;
  }

  vec3 surfaceColdRocky(vec2 uv) {
    float n = fbm(uv*3.0 + vec2(uSeed*0.12), 5);
    float crater = smoothstep(0.6, 0.55, fbm(uv*5.0+vec2(uSeed*0.4), 3));
    float frost = smoothstep(0.55, 0.65, n);
    vec3 base = mix(vec3(0.28,0.26,0.24), vec3(0.48,0.44,0.40), n);
    base = mix(base, vec3(0.15,0.14,0.13), crater*0.5);
    base = mix(base, vec3(0.82,0.86,0.90), frost*0.35);
    return base;
  }

  vec3 surfaceIce(vec2 uv) {
    float n = fbm(uv*2.8 + vec2(uSeed*0.09), 5);
    float crack = smoothstep(0.5, 0.42, fbm(uv*4.5+vec2(uSeed*0.6,1.0), 4));
    vec3 base = mix(vec3(0.72,0.84,0.94), vec3(0.88,0.94,0.99), n);
    // subsurface ocean hint — darker patches
    vec3 sub = vec3(0.18,0.32,0.55);
    float subMask = smoothstep(0.48, 0.38, n);
    base = mix(base, sub, subMask*0.4);
    base = mix(base, vec3(0.95,0.97,1.0), crack*0.6);
    return base;
  }

  vec3 surfaceGas(vec2 uv, float t) {
    float band1 = sin((uv.y + fbm(uv*1.5+vec2(t*0.006),3)*0.1) * 3.14159*9.0)*0.5+0.5;
    float band2 = sin((uv.y + fbm(uv*2.0+vec2(t*0.009),3)*0.08) * 3.14159*17.0)*0.5+0.5;
    float wisp  = fbm(uv*4.0 + vec2(t*0.015,0.0), 3);
    vec3 col = mix(vec3(0.62,0.38,0.16), vec3(0.90,0.68,0.32), band1);
    col = mix(col, vec3(0.78,0.52,0.22), band2*0.4);
    col += (wisp-0.5)*0.08;
    // Great Spot
    vec2 spotUv = uv - vec2(0.62 + t*0.0001, 0.54);
    float spot = 1.0 - smoothstep(0.0, 0.07, length(spotUv * vec2(2.0, 3.5)));
    col = mix(col, vec3(0.78,0.32,0.18), spot*0.7);
    return col;
  }

  vec3 surfaceUnknown(vec2 uv) {
    float n = fbm(uv*2.0 + vec2(uSeed*0.05), 3);
    return mix(vec3(0.18,0.22,0.30), vec3(0.28,0.34,0.44), n);
  }

  void main() {
    // ── Surface color by class ─────────────────────────────
    vec3 surface;
    if      (uClass == 1) surface = surfaceLava(vUv, uTime);
    else if (uClass == 2) surface = surfaceHotRocky(vUv);
    else if (uClass == 3) surface = surfaceOcean(vUv, uTime);
    else if (uClass == 4) surface = surfaceColdRocky(vUv);
    else if (uClass == 5) surface = surfaceIce(vUv);
    else if (uClass == 6) surface = surfaceGas(vUv, uTime);
    else                  surface = surfaceUnknown(vUv);

    // ── Lighting ────────────────────────────────────────────
    float diff = diffuse(vNormal, uStarPos, vWorldPos);
    float night = 1.0 - smoothstep(0.0, 0.22, diff); // night side mask

    // City lights on ocean worlds
    vec3 cityLights = vec3(0.0);
    if (uClass == 3) {
      float cityNoise = fbm(vUv * 6.0 + vec2(uSeed*0.2, 1.5), 3);
      float landMask  = smoothstep(0.42, 0.52, fbm(vUv*2.2+vec2(uSeed*0.08),5));
      cityLights = vec3(0.9,0.7,0.3) * smoothstep(0.55,0.72,cityNoise) * landMask * night * 0.7;
    }

    // Lava self-illumination — glows even on night side
    float selfEmit = 0.0;
    if (uClass == 1) {
      vec2 warp = vec2(fbm(vUv*1.8+vec2(uSeed,0.0),4), fbm(vUv*1.8+vec2(0.0,uSeed),4));
      float crack = fbm(vUv*3.2 + warp*1.4 + vec2(uTime*0.004,0.0), 5);
      selfEmit = smoothstep(0.48, 0.38, crack) * 0.65;
    }

    float ambientMin = (uClass == 1) ? 0.15 : 0.04;
    float lit = max(ambientMin, diff) + selfEmit;
    vec3 color = surface * lit + cityLights;

    // ── Atmosphere scattering rim (Fresnel) ─────────────────
    if (uAtmStrength > 0.0) {
      // Brighten rim toward star
      vec3 L = normalize(uStarPos - vWorldPos);
      float rimTowardStar = max(0.0, dot(L, vNormal));
      float rim = vFresnel * uAtmStrength * (0.6 + rimTowardStar * 0.4);
      color += uAtmColor * rim;
    }

    // ── Specular ocean glint ────────────────────────────────
    if (uClass == 3 || uClass == 5) {
      vec3 L = normalize(uStarPos - vWorldPos);
      vec3 V = normalize(cameraPosition - vWorldPos);
      vec3 H = normalize(L + V);
      float spec = pow(max(0.0, dot(vNormal, H)), 48.0) * diff;
      color += vec3(1.0, 0.98, 0.92) * spec * 0.55;
    }

    // ── Ghosted candidates ──────────────────────────────────
    float alpha = uGhosted ? 0.52 : 1.0;
    if (uGhosted) color = mix(color, vec3(0.3,0.35,0.40), 0.55);

    gl_FragColor = vec4(color, alpha);
  }
`;

import { PlanetClass } from '../lib/planetClassifier';

const CLASS_INT: Record<PlanetClass, number> = {
  [PlanetClass.UNKNOWN]:   0,
  [PlanetClass.LAVA]:      1,
  [PlanetClass.HOT_ROCKY]: 2,
  [PlanetClass.OCEAN]:     3,
  [PlanetClass.COLD_ROCKY]:4,
  [PlanetClass.ICE]:       5,
  [PlanetClass.GAS]:       6,
};

const ATM_COLORS: Record<PlanetClass, [number,number,number]> = {
  [PlanetClass.LAVA]:      [1.0, 0.32, 0.08],
  [PlanetClass.HOT_ROCKY]: [0.72, 0.38, 0.18],
  [PlanetClass.OCEAN]:     [0.22, 0.62, 1.0],
  [PlanetClass.COLD_ROCKY]:[0.55, 0.58, 0.62],
  [PlanetClass.ICE]:       [0.65, 0.82, 1.0],
  [PlanetClass.GAS]:       [0.88, 0.65, 0.32],
  [PlanetClass.UNKNOWN]:   [0.38, 0.44, 0.52],
};

const ATM_STRENGTH: Record<PlanetClass, number> = {
  [PlanetClass.LAVA]:      0.7,
  [PlanetClass.HOT_ROCKY]: 0.3,
  [PlanetClass.OCEAN]:     0.9,
  [PlanetClass.COLD_ROCKY]:0.15,
  [PlanetClass.ICE]:       0.35,
  [PlanetClass.GAS]:       0.8,
  [PlanetClass.UNKNOWN]:   0.1,
};

export function makePlanetUniforms(
  planetClass: PlanetClass,
  seed: number,
  ghosted: boolean,
  starPos: [number, number, number] = [0, 0, 0],
) {
  const atm = ATM_COLORS[planetClass];
  return {
    uTime:        { value: 0 },
    uStarPos:     { value: starPos },
    uClass:       { value: CLASS_INT[planetClass] },
    uSeed:        { value: seed },
    uAtmColor:    { value: atm },
    uAtmStrength: { value: ATM_STRENGTH[planetClass] },
    uGhosted:     { value: ghosted },
  };
}
```

- [ ] **Step 2: Wire planet shader into OrbitScene.tsx**

Add import:

```typescript
import { planetVertexShader, planetFragmentShader, makePlanetUniforms } from '../shaders/planet';
import { classifyPlanet } from '../lib/planetClassifier';
```

In `candidateRenderData`, extend `CandidateRenderData` type (add one field):

```typescript
type CandidateRenderData = {
  // ... existing fields ...
  planetClass: import('../lib/planetClassifier').PlanetClass;
  seed: number;
};
```

In the `candidateRenderData` function, add to each returned object:

```typescript
planetClass: classifyPlanet({
  equilibrium_temperature_k: candidate.physics?.equilibrium_temperature_k,
  is_in_habitable_zone: candidate.physics?.is_in_habitable_zone,
  radius_ratio: finite(candidate.physics?.radius_ratio, 0) || undefined,
  planet_radius_earth: finite(candidate.physics?.planet_radius_earth, 0) || undefined,
}),
seed: (index * 137.508 + finite(candidate.epoch_days ?? candidate.epoch, index) * 7.3) % 99.0,
```

Replace the planet mesh creation block in the useEffect with:

```typescript
const planetUniforms = automatedBrowser
  ? null
  : makePlanetUniforms(data.planetClass, data.seed, data.ghosted, [0, 0, 0]);

const planet = new THREE.Mesh(
  new THREE.SphereGeometry(data.planetRadius, automatedBrowser ? 22 : 48, automatedBrowser ? 22 : 48),
  automatedBrowser || !planetUniforms
    ? new THREE.MeshStandardMaterial({
        color: data.hue,
        emissive: data.hue,
        emissiveIntensity: data.ghosted ? 0.035 : active ? 0.48 : 0.16 + data.confidence * 0.1,
        metalness: 0.05,
        roughness: data.ghosted ? 0.88 : data.hasPhysics ? 0.42 : 0.58,
        transparent: data.ghosted,
        opacity: data.ghosted ? 0.52 : 1,
      })
    : new THREE.ShaderMaterial({
        vertexShader: planetVertexShader,
        fragmentShader: planetFragmentShader,
        uniforms: planetUniforms,
        transparent: data.ghosted,
      }),
);
```

Store `planetUniforms` in the `PlanetMesh` type and update per frame:

Add to `PlanetMesh` type:

```typescript
type PlanetMesh = CandidateRenderData & {
  mesh: THREE.Mesh;
  halo: THREE.Sprite;
  orbit: THREE.Mesh;
  transit: THREE.Mesh;
  label: string;
  planetUniforms: ReturnType<typeof makePlanetUniforms> | null;
};
```

In the tick loop, inside `planetMeshes.forEach`, add:

```typescript
if (planet.planetUniforms) {
  planet.planetUniforms.uTime.value += 0.016 * speed;
  planet.planetUniforms.uStarPos.value = [0, 0, 0]; // star is at origin
}
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm test -- --run src/components/OrbitScene.test.tsx
```

Expected: all pass. (automatedBrowser path uses existing MeshStandardMaterial.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/shaders/planet.ts frontend/src/components/OrbitScene.tsx frontend/src/lib/planetClassifier.ts
git commit -m "feat: GLSL planet shader — FBM surfaces, per-class appearance, atmosphere rim, city lights, specular glint"
```

---

## Phase 4 — Details

> **Creative pause:** Before coding, ask: *What's the most emotionally resonant detail I can add here?* Ideas: when a habitable-zone planet is selected, the green HZ ring pulses once slowly like a heartbeat; gas giant rings cast a faint shadow stripe that sweeps across the planet face in real time; on ice worlds, the frost fractures very slowly grow during observation (imperceptibly slow, but they do grow).

### Task 7: Cloud layer

**Files:**
- Modify: `frontend/src/components/OrbitScene.tsx`

- [ ] **Step 1: Add cloud sphere builder**

Add near other builder functions in OrbitScene.tsx:

```typescript
function makeCloudLayer(
  planetRadius: number,
  planetClass: import('../lib/planetClassifier').PlanetClass,
): THREE.Mesh | null {
  if (planetClass !== 'ocean' && planetClass !== 'gas') return null;
  const cloudVertShader = /* glsl */`
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
  `;
  const cloudFragShader = /* glsl */`
    uniform float uTime; uniform float uSeed;
    varying vec2 vUv;
    float hash(vec2 p){p=fract(p*vec2(127.1+uSeed*.01,311.7));p+=dot(p,p+17.5);return fract(p.x*p.y);}
    float noise(vec2 p){vec2 i=floor(p);vec2 f=fract(p);vec2 u=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1,0)),u.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),u.x),u.y);}
    float fbm(vec2 p){float v=0.,a=.5,fr=1.;for(int i=0;i<5;i++){v+=a*noise(p*fr);a*=.5;fr*=2.1;}return v;}
    void main(){
      vec2 uv = vUv + vec2(uTime*0.008, uTime*0.003);
      float cloud = fbm(uv*3.0);
      float alpha = smoothstep(0.42, 0.62, cloud) * 0.72;
      gl_FragColor = vec4(0.92, 0.94, 0.98, alpha);
    }
  `;
  return new THREE.Mesh(
    new THREE.SphereGeometry(planetRadius * 1.018, 32, 32),
    new THREE.ShaderMaterial({
      vertexShader: cloudVertShader,
      fragmentShader: cloudFragShader,
      uniforms: { uTime: { value: 0 }, uSeed: { value: Math.random() * 99 } },
      transparent: true,
      depthWrite: false,
      side: THREE.FrontSide,
    }),
  );
}
```

Inside the planet creation loop, after `scene.add(planet)`:

```typescript
const cloudMesh = automatedBrowser ? null : makeCloudLayer(data.planetRadius, data.planetClass);
if (cloudMesh) scene.add(cloudMesh);
```

Store `cloudMesh` in `PlanetMesh` and update its position + time each tick:

```typescript
// in tick loop:
if (planet.cloudMesh) {
  planet.cloudMesh.position.copy(planet.mesh.position);
  (planet.cloudMesh.material as THREE.ShaderMaterial).uniforms.uTime.value += 0.016 * speed;
}
```

- [ ] **Step 2: Ring system builder**

Add ring builder:

```typescript
function makeRingSystem(
  radius: number,
  planetClass: import('../lib/planetClassifier').PlanetClass,
  hue: THREE.Color,
): THREE.Group | null {
  if (planetClass !== 'gas') return null;
  const group = new THREE.Group();
  const ringDefs = [
    { inner: radius*1.25, outer: radius*1.5,  opacity: 0.55 },
    { inner: radius*1.55, outer: radius*1.72, opacity: 0.35 },
    { inner: radius*1.78, outer: radius*2.0,  opacity: 0.25 },
  ];
  ringDefs.forEach(({ inner, outer, opacity }) => {
    const geo = new THREE.RingGeometry(inner, outer, 128);
    // Vary alpha per vertex using noise
    const pos = geo.attributes.position;
    const alphaArr = new Float32Array(pos.count);
    for (let i = 0; i < pos.count; i++) {
      const angle = Math.atan2(pos.getY(i), pos.getX(i));
      alphaArr[i] = 0.3 + 0.7 * Math.abs(Math.sin(angle * 7.3 + i * 0.1));
    }
    geo.setAttribute('alpha', new THREE.BufferAttribute(alphaArr, 1));
    const mat = new THREE.MeshBasicMaterial({
      color: hue,
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(geo, mat);
    ring.rotation.x = Math.PI / 2;
    group.add(ring);
  });
  // [CREATIVE: Cassini-like gap — add a dark mesh to blank out the gap]
  const gapGeo = new THREE.RingGeometry(radius*1.5, radius*1.56, 128);
  const gapMat = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false });
  const gap = new THREE.Mesh(gapGeo, gapMat);
  gap.rotation.x = Math.PI / 2;
  group.add(gap);
  return group;
}
```

After planet mesh creation:

```typescript
const rings = automatedBrowser ? null : makeRingSystem(data.planetRadius, data.planetClass, data.hue);
if (rings) scene.add(rings);
// store in PlanetMesh and update position in tick
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm test -- --run src/components/OrbitScene.test.tsx
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/OrbitScene.tsx
git commit -m "feat: cloud layer (ocean/gas), ring system with Cassini gap (gas giants)"
```

---

## Phase 5 — Background & Particles

> **Creative pause:** *What background detail would make a viewer lean in and look closer?* Ideas: add one very faint distant galaxy smudge (oval sprite); make stellar wind particles respond to the selected planet — they visibly deflect around it; add a rare "shooting star" streak across the background every ~90 seconds.

### Task 8: Milky Way starfield + nebula

**Files:**
- Modify: `frontend/src/components/OrbitScene.tsx`

- [ ] **Step 1: Replace starfield with Milky Way builder**

Replace the existing starfield block in the useEffect with:

```typescript
// ── Milky Way starfield ────────────────────────────────────
const starCount = automatedBrowser ? 340 : 3200;
const starPositions = new Float32Array(starCount * 3);
const starColors = new Float32Array(starCount * 3);
const starSizes = new Float32Array(starCount);

for (let i = 0; i < starCount; i++) {
  // Milky Way band — higher density near equatorial band
  const phi = (i * 2.399963) % (Math.PI * 2);
  const bandBias = Math.pow(Math.abs(Math.sin(phi * 0.5)), 0.4); // denser near band
  const r = 38 + ((i * 37) % 62);
  const theta = (Math.acos(2 * ((i * 0.618) % 1) - 1) - Math.PI / 2) * bandBias * 0.4;
  starPositions[i * 3]     = Math.cos(phi) * Math.cos(theta) * r;
  starPositions[i * 3 + 1] = Math.sin(theta) * r * 0.3;
  starPositions[i * 3 + 2] = Math.sin(phi) * Math.cos(theta) * r;

  // Color temperature: 70% G/K yellow-white, 20% B/A blue, 10% M orange-red
  const t = (i * 0.31) % 1;
  const b = 0.35 + ((i * 19) % 48) / 100;
  if (t < 0.1) { // M-type: orange-red
    starColors[i*3]=b*0.9; starColors[i*3+1]=b*0.5; starColors[i*3+2]=b*0.3;
  } else if (t < 0.3) { // B/A-type: blue-white
    starColors[i*3]=b*0.7; starColors[i*3+1]=b*0.82; starColors[i*3+2]=b;
  } else { // G/K: yellow-white
    starColors[i*3]=b; starColors[i*3+1]=b*0.92; starColors[i*3+2]=b*0.72;
  }
  starSizes[i] = automatedBrowser ? 0.1 : 0.08 + ((i * 7) % 10) / 100;
}

const starfieldGeo = new THREE.BufferGeometry();
starfieldGeo.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
starfieldGeo.setAttribute('color',    new THREE.BufferAttribute(starColors, 3));
const starfield = new THREE.Points(
  starfieldGeo,
  new THREE.PointsMaterial({ size: 0.1, vertexColors: true, transparent: true, opacity: 0.88, depthWrite: false }),
);
scene.add(starfield);

// [CREATIVE: add a second, nearer sparse layer for parallax depth]
if (!automatedBrowser) {
  const near = new THREE.Points(
    (() => {
      const g = new THREE.BufferGeometry();
      const p = new Float32Array(200 * 3); const c = new Float32Array(200 * 3);
      for (let i = 0; i < 200; i++) {
        const a = i * 2.4; const r2 = 28 + (i * 11) % 16;
        p[i*3]= Math.cos(a)*r2; p[i*3+1]= ((i*53)%30-15)*0.08; p[i*3+2]= Math.sin(a)*r2;
        c[i*3]=0.9; c[i*3+1]=0.92; c[i*3+2]=0.85;
      }
      g.setAttribute('position', new THREE.BufferAttribute(p, 3));
      g.setAttribute('color',    new THREE.BufferAttribute(c, 3));
      return g;
    })(),
    new THREE.PointsMaterial({ size: 0.15, vertexColors: true, transparent: true, opacity: 0.5, depthWrite: false }),
  );
  scene.add(near);
}

// [CREATIVE: nebula cloud sprite for colour atmosphere]
if (!automatedBrowser) {
  const nebulaCanvas = document.createElement('canvas');
  nebulaCanvas.width = 256; nebulaCanvas.height = 256;
  const nCtx = nebulaCanvas.getContext('2d')!;
  const nGrad = nCtx.createRadialGradient(128,128,0,128,128,128);
  nGrad.addColorStop(0,  'rgba(80,60,160,0.18)');
  nGrad.addColorStop(0.5,'rgba(60,40,120,0.08)');
  nGrad.addColorStop(1,  'rgba(0,0,0,0)');
  nCtx.fillStyle = nGrad; nCtx.fillRect(0,0,256,256);
  const nebulaTex = new THREE.CanvasTexture(nebulaCanvas);
  const nebula = new THREE.Sprite(new THREE.SpriteMaterial({
    map: nebulaTex, transparent: true, opacity: 0.55,
    blending: THREE.AdditiveBlending, depthWrite: false,
  }));
  nebula.scale.set(55, 55, 1);
  nebula.position.set(18, -6, -22);
  scene.add(nebula);
}
```

- [ ] **Step 2: Stellar wind particles**

After the existing `scene.add(starfield)` block:

```typescript
// ── Stellar wind ───────────────────────────────────────────
if (!automatedBrowser) {
  const windCount = 6000;
  const windPositions = new Float32Array(windCount * 3);
  const windVelocities = new Float32Array(windCount * 3);
  for (let i = 0; i < windCount; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi   = Math.acos(2 * Math.random() - 1);
    const r = 2.0 + Math.random() * 14;
    windPositions[i*3]   = Math.sin(phi)*Math.cos(theta)*r;
    windPositions[i*3+1] = Math.cos(phi)*r*0.3;
    windPositions[i*3+2] = Math.sin(phi)*Math.sin(theta)*r;
    const spd = 0.028 + Math.random() * 0.018;
    windVelocities[i*3]   = Math.sin(phi)*Math.cos(theta)*spd;
    windVelocities[i*3+1] = Math.cos(phi)*spd*0.3;
    windVelocities[i*3+2] = Math.sin(phi)*Math.sin(theta)*spd;
  }
  const windGeo = new THREE.BufferGeometry();
  windGeo.setAttribute('position', new THREE.BufferAttribute(windPositions, 3));
  const windMat = new THREE.PointsMaterial({ size: 0.04, color: 0xffeedd, transparent: true, opacity: 0.22, depthWrite: false });
  const windParticles = new THREE.Points(windGeo, windMat);
  scene.add(windParticles);

  // Animate wind in tick:
  // (store reference and add to tick loop)
  // In tick:
  //   const pos = windGeo.attributes.position as THREE.BufferAttribute;
  //   for (let i = 0; i < windCount; i++) {
  //     pos.setXYZ(i, pos.getX(i)+windVelocities[i*3]*speed, pos.getY(i)+windVelocities[i*3+1]*speed, pos.getZ(i)+windVelocities[i*3+2]*speed);
  //     if (new THREE.Vector3(pos.getX(i),pos.getY(i),pos.getZ(i)).length() > 19) {
  //       pos.setXYZ(i, 0, 0, 0); // reset to origin
  //     }
  //   }
  //   pos.needsUpdate = true;
}
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm test -- --run
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/OrbitScene.tsx
git commit -m "feat: Milky Way starfield with color temperature + parallax, nebula sprite, stellar wind particles"
```

---

## Phase 6 — Orbit Trails

> **Creative pause:** *What would make the orbit trails feel like something out of Interstellar?* Ideas: make the trail color shift from the planet's atmosphere color at the bright end to deep space blue-black at the faded end; add tiny spark particles that drift off the bright head of the trail; for the selected planet, make the trail leave a subtle light-wake on the planeDisc below it.

### Task 9: Comet-tail orbit trail shader

**Files:**
- Create: `frontend/src/shaders/orbitTrail.ts`
- Modify: `frontend/src/components/OrbitScene.tsx`

- [ ] **Step 1: Create orbitTrail.ts**

Create `frontend/src/shaders/orbitTrail.ts`:

```typescript
export const orbitTrailVertexShader = /* glsl */`
  attribute float angle;   // per-vertex angle in orbit (0–2PI)
  uniform float uPlanetAngle; // current planet angle
  varying float vAlpha;

  void main() {
    // How far "behind" the planet is this vertex?
    float delta = uPlanetAngle - angle;
    // Wrap to [0, 2PI] — the trail goes backward from planet
    if (delta < 0.0) delta += 6.28318;
    // Bright right behind planet, fades over ~270 degrees (1.5PI)
    vAlpha = 1.0 - smoothstep(0.0, 5.50, delta);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

export const orbitTrailFragmentShader = /* glsl */`
  uniform vec3  uColor;
  uniform float uOpacity;
  varying float vAlpha;

  void main() {
    gl_FragColor = vec4(uColor, uOpacity * vAlpha);
  }
`;
```

- [ ] **Step 2: Wire trail shader in OrbitScene.tsx**

Add import:

```typescript
import { orbitTrailVertexShader, orbitTrailFragmentShader } from '../shaders/orbitTrail';
```

Replace the orbit `TorusGeometry` creation block with (for non-automated browsers):

```typescript
// Build TorusGeometry and annotate each vertex with its angle
function makeTrailOrbit(radius: number, tube: number, hue: THREE.Color, opacity: number): THREE.Mesh {
  const segments = 220;
  const geo = new THREE.TorusGeometry(radius, tube, 8, segments);
  // Add angle attribute — each ring segment maps to an angle
  const pos = geo.attributes.position;
  const angles = new Float32Array(pos.count);
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i); const z = pos.getZ(i);
    angles[i] = Math.atan2(z, x) + Math.PI; // 0–2PI
  }
  geo.setAttribute('angle', new THREE.BufferAttribute(angles, 1));
  return new THREE.Mesh(geo, new THREE.ShaderMaterial({
    vertexShader: orbitTrailVertexShader,
    fragmentShader: orbitTrailFragmentShader,
    uniforms: {
      uPlanetAngle: { value: 0 },
      uColor:       { value: [hue.r ?? 0.5, hue.g ?? 0.5, hue.b ?? 1.0] },
      uOpacity:     { value: opacity },
    },
    transparent: true,
    depthWrite: false,
  }));
}
```

Replace the orbit mesh creation in the forEach block:

```typescript
const orbit = automatedBrowser
  ? new THREE.Mesh(
      new THREE.TorusGeometry(data.radius, data.orbitTube, 8, 128),
      new THREE.MeshBasicMaterial({ color: data.hue, transparent: true, opacity: data.orbitOpacity }),
    )
  : makeTrailOrbit(data.radius, data.orbitTube, data.hue, data.orbitOpacity);
```

In the tick loop, update the `uPlanetAngle` uniform for each planet:

```typescript
if (!automatedBrowser) {
  const trailMat = planet.orbit.material as THREE.ShaderMaterial;
  if (trailMat.uniforms?.uPlanetAngle) {
    trailMat.uniforms.uPlanetAngle.value = angle;
  }
}
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm test -- --run src/components/OrbitScene.test.tsx
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/shaders/orbitTrail.ts frontend/src/components/OrbitScene.tsx
git commit -m "feat: comet-tail orbit trails — GLSL shader fades arc behind planet over 270 degrees"
```

---

## Phase 7 — Post-Processing

> **Creative pause:** *What post effect would make a screenshot of this scene genuinely frame-worthy?* Ideas: add a very subtle blue-shift at the extreme screen edges (like old telescope glass); in theater mode, add a brief "focus pull" effect when entering — the scene starts slightly blurred and sharpens over 0.8 seconds; make the vignette slightly asymmetric, heavier at the bottom, like a real eyepiece.

### Task 10: EffectComposer setup + bloom

**Files:**
- Create: `frontend/src/shaders/postprocess/ChromaticAberrationPass.ts`
- Create: `frontend/src/shaders/postprocess/FilmGrainPass.ts`
- Create: `frontend/src/shaders/postprocess/VignettePass.ts`
- Modify: `frontend/src/components/OrbitScene.tsx`

- [ ] **Step 1: Create ChromaticAberrationPass.ts**

Create `frontend/src/shaders/postprocess/ChromaticAberrationPass.ts`:

```typescript
export const ChromaticAberrationShader = {
  uniforms: {
    tDiffuse: { value: null },
    uStrength: { value: 0.004 },
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
  `,
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse;
    uniform float uStrength;
    varying vec2 vUv;
    void main() {
      vec2 center = vUv - 0.5;
      float dist = length(center);
      float offset = dist * uStrength;
      vec2 dir = normalize(center + vec2(0.0001));
      float r = texture2D(tDiffuse, vUv - dir * offset).r;
      float g = texture2D(tDiffuse, vUv).g;
      float b = texture2D(tDiffuse, vUv + dir * offset).b;
      gl_FragColor = vec4(r, g, b, 1.0);
    }
  `,
};
```

- [ ] **Step 2: Create FilmGrainPass.ts**

Create `frontend/src/shaders/postprocess/FilmGrainPass.ts`:

```typescript
export const FilmGrainShader = {
  uniforms: {
    tDiffuse: { value: null },
    uTime:    { value: 0 },
    uStrength:{ value: 0.032 },
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
  `,
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse;
    uniform float uTime;
    uniform float uStrength;
    varying vec2 vUv;
    float rand(vec2 co) { return fract(sin(dot(co, vec2(12.9898,78.233))) * 43758.5453); }
    void main() {
      vec4 color = texture2D(tDiffuse, vUv);
      float grain = rand(vUv + fract(uTime * 0.07)) - 0.5;
      color.rgb += grain * uStrength;
      gl_FragColor = color;
    }
  `,
};
```

- [ ] **Step 3: Create VignettePass.ts**

Create `frontend/src/shaders/postprocess/VignettePass.ts`:

```typescript
export const VignetteShader = {
  uniforms: {
    tDiffuse: { value: null },
    uStrength:{ value: 0.55 },
    uOffset:  { value: 0.35 },
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
  `,
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse;
    uniform float uStrength;
    uniform float uOffset;
    varying vec2 vUv;
    void main() {
      vec4 color = texture2D(tDiffuse, vUv);
      // [CREATIVE: asymmetric vignette — heavier bottom like a real eyepiece]
      vec2 uv2 = vUv - vec2(0.5, 0.48);
      float dist = length(uv2 * vec2(1.0, 1.1));
      float vignette = smoothstep(uOffset + uStrength, uOffset, dist);
      color.rgb *= vignette;
      gl_FragColor = color;
    }
  `,
};
```

- [ ] **Step 4: Wire EffectComposer into OrbitScene.tsx**

Add imports at top of OrbitScene.tsx:

```typescript
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass }     from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass }from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { ShaderPass }     from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { OutputPass }     from 'three/examples/jsm/postprocessing/OutputPass.js';
import { ChromaticAberrationShader } from '../shaders/postprocess/ChromaticAberrationPass';
import { FilmGrainShader }           from '../shaders/postprocess/FilmGrainPass';
import { VignetteShader }            from '../shaders/postprocess/VignettePass';
```

After `renderer.setSize(width, height)`, replace the bare `renderer.render` call setup with:

```typescript
let composer: EffectComposer | null = null;
let filmGrainPass: ShaderPass | null = null;

if (!automatedBrowser) {
  composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));

  const bloom = new UnrealBloomPass(
    new THREE.Vector2(width, height),
    theaterMode ? 1.1 : 0.85,  // strength
    0.42,                        // radius
    0.82,                        // threshold
  );
  composer.addPass(bloom);

  if (theaterMode) {
    const chromaPass = new ShaderPass(ChromaticAberrationShader);
    chromaPass.uniforms.uStrength.value = 0.006;
    composer.addPass(chromaPass);

    filmGrainPass = new ShaderPass(FilmGrainShader);
    composer.addPass(filmGrainPass);

    const vignettePass = new ShaderPass(VignetteShader);
    vignettePass.uniforms.uStrength.value = 0.65;
    composer.addPass(vignettePass);
  }

  composer.addPass(new OutputPass());
}
```

Replace `renderer.render(scene, camera)` in tick with:

```typescript
if (composer) {
  if (filmGrainPass) filmGrainPass.uniforms.uTime.value += 0.016;
  composer.render();
} else {
  renderer.render(scene, camera);
}
```

In the ResizeObserver callback, add:

```typescript
composer?.setSize(nextWidth, nextHeight);
```

In cleanup return, add:

```typescript
composer?.dispose();
```

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm test -- --run
```

Expected: all pass. EffectComposer is stubbed in threeMock; automatedBrowser path skips it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/shaders/postprocess/ frontend/src/components/OrbitScene.tsx
git commit -m "feat: EffectComposer pipeline — UnrealBloom, chromatic aberration, film grain, vignette (theater mode full stack)"
```

---

## Phase 8 — Camera

> **Creative pause:** *What camera move would make selecting a planet feel like a film cut?* Ideas: when the dolly reaches the planet, do a single slow 360° pan around it before returning; add a subtle camera shake (0.002 amplitude) when a lava world is selected, like you're in the planet's thermals; in theater mode, add an "auto-tour" mode that cycles through all planets with dolly cuts every 8 seconds.

### Task 11: cameraAnimator.ts — cubic bezier dolly

**Files:**
- Create: `frontend/src/lib/cameraAnimator.ts`
- Create: `frontend/src/lib/cameraAnimator.test.ts`
- Modify: `frontend/src/components/OrbitScene.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/lib/cameraAnimator.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { CameraAnimator } from './cameraAnimator';

describe('CameraAnimator', () => {
  it('starts idle', () => {
    const ca = new CameraAnimator({ x:0,y:14,z:24 });
    expect(ca.isAnimating()).toBe(false);
  });

  it('becomes animating after dolly()', () => {
    const ca = new CameraAnimator({ x:0,y:14,z:24 });
    ca.dolly({ x:5,y:6,z:8 }, 1.2);
    expect(ca.isAnimating()).toBe(true);
  });

  it('finishes after full tick duration', () => {
    const ca = new CameraAnimator({ x:0,y:14,z:24 });
    ca.dolly({ x:5,y:6,z:8 }, 0.1);
    for (let i = 0; i < 20; i++) ca.tick(0.016);
    expect(ca.isAnimating()).toBe(false);
  });

  it('returns interpolated position during animation', () => {
    const ca = new CameraAnimator({ x:0,y:0,z:0 });
    ca.dolly({ x:10,y:0,z:0 }, 1.0);
    ca.tick(0.5); // halfway
    const pos = ca.position();
    expect(pos.x).toBeGreaterThan(0);
    expect(pos.x).toBeLessThan(10);
  });
});
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm test -- --run src/lib/cameraAnimator.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement CameraAnimator**

Create `frontend/src/lib/cameraAnimator.ts`:

```typescript
type Vec3 = { x: number; y: number; z: number };

function cubicBezier(t: number, p0: number, p1: number, p2: number, p3: number): number {
  const u = 1 - t;
  return u*u*u*p0 + 3*u*u*t*p1 + 3*u*t*t*p2 + t*t*t*p3;
}

export class CameraAnimator {
  private home: Vec3;
  private from: Vec3;
  private target: Vec3 | null = null;
  private elapsed = 0;
  private duration = 0;
  private phase: 'idle' | 'dolly-in' | 'hold' | 'return' = 'idle';
  private holdDuration = 1.5;
  private holdElapsed = 0;
  private current: Vec3;

  constructor(homePosition: Vec3) {
    this.home = { ...homePosition };
    this.from = { ...homePosition };
    this.current = { ...homePosition };
  }

  dolly(closeupPos: Vec3, duration = 1.2) {
    this.target = closeupPos;
    this.from = { ...this.current };
    this.elapsed = 0;
    this.duration = duration;
    this.holdElapsed = 0;
    this.phase = 'dolly-in';
  }

  tick(dt: number) {
    if (this.phase === 'idle') return;

    if (this.phase === 'dolly-in') {
      this.elapsed += dt;
      const t = Math.min(1, this.elapsed / this.duration);
      const ease = cubicBezier(t, 0, 0.25, 0.1, 1.0);
      this.current = {
        x: this.from.x + (this.target!.x - this.from.x) * ease,
        y: this.from.y + (this.target!.y - this.from.y) * ease,
        z: this.from.z + (this.target!.z - this.from.z) * ease,
      };
      if (t >= 1) { this.phase = 'hold'; this.holdElapsed = 0; }
    } else if (this.phase === 'hold') {
      this.holdElapsed += dt;
      if (this.holdElapsed >= this.holdDuration) {
        this.from = { ...this.current };
        this.elapsed = 0;
        this.duration = 0.8;
        this.phase = 'return';
      }
    } else if (this.phase === 'return') {
      this.elapsed += dt;
      const t = Math.min(1, this.elapsed / this.duration);
      const ease = cubicBezier(t, 0, 0.6, 0.4, 1.0);
      this.current = {
        x: this.from.x + (this.home.x - this.from.x) * ease,
        y: this.from.y + (this.home.y - this.from.y) * ease,
        z: this.from.z + (this.home.z - this.from.z) * ease,
      };
      if (t >= 1) { this.current = { ...this.home }; this.phase = 'idle'; }
    }
  }

  isAnimating() { return this.phase !== 'idle'; }
  position() { return { ...this.current }; }
  setHome(pos: Vec3) { this.home = { ...pos }; }
}
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd frontend && npm test -- --run src/lib/cameraAnimator.test.ts
```

Expected: 4 passing.

- [ ] **Step 5: Wire CameraAnimator into OrbitScene.tsx**

Add import:

```typescript
import { CameraAnimator } from '../lib/cameraAnimator';
```

In the useEffect, after `resetCamera()`:

```typescript
const cameraAnimator = new CameraAnimator({ x: 0, y: cameraHeight, z: cameraDistance });
let prevSelectedId: string | undefined;
```

In the tick loop, replace the existing camera lerp block with:

```typescript
if (selectedPlanet) {
  // Trigger dolly when selection changes
  if (selectedId !== prevSelectedId) {
    prevSelectedId = selectedId;
    const closeup = new THREE.Vector3(
      selectedPlanet.mesh.position.x * 0.8,
      cameraHeight * 0.72,
      cameraDistance * 0.52,
    );
    cameraAnimator.dolly({ x: closeup.x, y: closeup.y, z: closeup.z }, 1.2);
    cameraAnimator.setHome({ x: selectedPlanet.mesh.position.x * 0.09, y: cameraHeight, z: cameraDistance });
  }
  cameraAnimator.tick(0.016 * speed);
  const pos = cameraAnimator.position();
  camera.position.set(pos.x, pos.y, pos.z);
  camera.lookAt(0, 0, 0);
}
```

- [ ] **Step 6: Run all tests**

```bash
cd frontend && npm test -- --run
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/cameraAnimator.ts frontend/src/lib/cameraAnimator.test.ts frontend/src/components/OrbitScene.tsx
git commit -m "feat: cinematic camera dolly on planet selection — cubic bezier in/hold/return arc"
```

---

## Phase 9 — HUD & Mission Control Overlay

> **Creative pause:** *What HUD element would feel like real mission control software?* Ideas: add a live "elapsed observation time" counter that ticks up; show the transit probability as a sweeping arc that fills as confidence rises; in theater mode, add a faint background grid/reticle pattern behind the HUD strip like a targeting computer.

### Task 12: Animated panel HUD badge + theater overlay

**Files:**
- Modify: `frontend/src/components/OrbitScene.tsx`
- Modify: `frontend/src/styles/app.css`

- [ ] **Step 1: Add HUD CSS to app.css**

Append to `frontend/src/styles/app.css`:

```css
/* ── HUD Enhancements ──────────────────────────────────────── */
.orbit-metric-badge .confidence-bar-track {
  width: 100%;
  height: 3px;
  background: rgba(255,255,255,0.1);
  border-radius: 2px;
  margin-top: 4px;
  overflow: hidden;
}
.orbit-metric-badge .confidence-bar-fill {
  height: 100%;
  border-radius: 2px;
  background: currentColor;
  transition: width 0.6s cubic-bezier(0.22,1,0.36,1);
}

.orbit-mission-overlay {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  background: rgba(2,8,20,0.78);
  backdrop-filter: blur(12px);
  border-top: 1px solid rgba(80,160,255,0.2);
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0;
  padding: 14px 20px;
  animation: slide-up 0.35s cubic-bezier(0.22,1,0.36,1) forwards;
  z-index: 10;
}
@keyframes slide-up {
  from { transform: translateY(100%); opacity: 0; }
  to   { transform: translateY(0);    opacity: 1; }
}
.orbit-mission-panel { padding: 0 16px; border-right: 1px solid rgba(80,160,255,0.1); }
.orbit-mission-panel:last-child { border-right: none; }
.orbit-mission-panel h4 { font-size: 9px; letter-spacing: 0.1em; color: #4a7090; text-transform: uppercase; margin: 0 0 8px; }
.orbit-mission-panel .stat { font-size: 12px; color: #a8c8f0; margin: 3px 0; font-family: monospace; }
.orbit-mission-panel .stat strong { color: #e8f4ff; }

.orbit-arc-svg { display: block; margin: 0 auto; }
```

- [ ] **Step 2: Add theater mission overlay to OrbitScene.tsx JSX**

Inside the `sceneContent` JSX, after the existing `orbit-metric-badge` block, add:

```tsx
{theaterMode && selected && selectedRenderData && candidates.length > 0 && (
  <div className="orbit-mission-overlay" aria-label="Mission control data overlay">
    <div className="orbit-mission-panel">
      <h4>Candidate</h4>
      <div className="stat"><strong>{selected.candidate_id}</strong></div>
      <div className="stat">Class: <strong style={{ color: classColor(selectedRenderData.planetClass) }}>{selectedRenderData.planetClass.replace('_',' ').toUpperCase()}</strong></div>
      <div className="stat">Period: <strong>{selected.period.toFixed(4)} d</strong></div>
      <div className="stat">Depth: <strong>{Math.round(finite(selected.depth, 0) * 1_000_000)} ppm</strong></div>
      {formatTemperature(selected.physics?.equilibrium_temperature_k) && (
        <div className="stat">Temp: <strong>{formatTemperature(selected.physics?.equilibrium_temperature_k)}</strong></div>
      )}
    </div>
    <div className="orbit-mission-panel" style={{ display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center' }}>
      <h4>Confidence</h4>
      <svg className="orbit-arc-svg" width="80" height="80" viewBox="0 0 80 80">
        <circle cx="40" cy="40" r="32" fill="none" stroke="rgba(80,160,255,0.12)" strokeWidth="6"/>
        <circle
          cx="40" cy="40" r="32"
          fill="none"
          stroke={selectedRenderData.tone === 'ready' ? '#7ff0b0' : selectedRenderData.tone === 'review' ? '#ffc878' : '#76b9ff'}
          strokeWidth="6"
          strokeDasharray={`${selectedRenderData.confidence * 201} 201`}
          strokeLinecap="round"
          transform="rotate(-90 40 40)"
          style={{ transition: 'stroke-dasharray 0.8s cubic-bezier(0.22,1,0.36,1)' }}
        />
        <text x="40" y="45" textAnchor="middle" fill="#e8f4ff" fontSize="14" fontFamily="monospace" fontWeight="bold">
          {Math.round(selectedRenderData.confidence * 100)}%
        </text>
      </svg>
      <div className="stat" style={{textAlign:'center'}}>{selectedRenderData.statusLabel}</div>
    </div>
    <div className="orbit-mission-panel">
      <h4>Science Status</h4>
      <div className="stat">SNR: <strong>{finite(selected.signal_to_noise, 0).toFixed(1)}</strong></div>
      <div className="stat">FP flags: <strong>{selected.validation?.false_positive_flags?.filter(Boolean).length ?? 0}</strong></div>
      <div className="stat">Duration plausible: <strong>{selected.validation?.duration_plausible === false ? '✗' : '✓'}</strong></div>
      {selectedRenderData.isHabitable && <div className="stat" style={{color:'#7ff0b0'}}>✦ HABITABLE ZONE</div>}
    </div>
  </div>
)}
```

Add the helper function near other helpers:

```typescript
function classColor(cls: import('../lib/planetClassifier').PlanetClass): string {
  const map: Record<string, string> = {
    lava: '#ff6622', hot_rocky: '#cc8844', ocean: '#44aaff',
    cold_rocky: '#8899aa', ice: '#aaddff', gas: '#ddaa66', unknown: '#667788',
  };
  return map[cls] ?? '#a8c8f0';
}
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm test -- --run
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/OrbitScene.tsx frontend/src/styles/app.css
git commit -m "feat: theater mission control HUD — animated confidence arc, planet class, science stats overlay"
```

---

## Phase 10 — Polish, CI Guard & Performance

> **Creative pause — final:** *What's the one thing that, if I don't add it now, I'll regret forever?* This is your last creative sweep. Add your 5 best remaining ideas from the list you've been building. Log each with `// [CREATIVE]`.

### Task 13: automatedBrowser CI guard + test compatibility

**Files:**
- Modify: `frontend/src/test/threeMock.ts`
- Modify: `frontend/src/components/OrbitScene.tsx`

- [ ] **Step 1: Verify automated browser path renders fallback materials**

Run the full test suite and check no new failures:

```bash
cd frontend && npm test -- --run
```

Expected: all existing tests pass. If any fail due to new imports (EffectComposer, ShaderMaterial), ensure they're covered in threeMock.

- [ ] **Step 2: Add missing threeMock exports if needed**

If tests fail with "X is not a constructor", add the missing stub to `threeMock.ts` following the pattern from Task 1 Step 2. Common ones needed:

```typescript
// Add if missing:
class CatmullRomCurve3 {
  points: unknown[];
  constructor(points: unknown[]) { this.points = points; }
  getPoints(_n: number) { return []; }
}
class TubeGeometry {
  attributes = { position: { count: 0, getX: () => 0, getY: () => 0, getZ: () => 0 } };
  dispose() {}
}
class QuadraticBezierCurve3 {
  constructor(_v0: unknown, _v1: unknown, _v2: unknown) {}
  getPoints(_n: number) { return []; }
}
```

- [ ] **Step 3: Snapshot test for automated browser path**

Add to `OrbitScene.test.tsx` (after existing tests):

```typescript
it('renders canvas with expected test-id in automated browser path', () => {
  Object.defineProperty(navigator, 'webdriver', { value: true, configurable: true });
  render(<OrbitScene candidates={[candidate()]} selectedId="TIC-1" />);
  expect(screen.getByTestId('orbit-scene')).toBeInTheDocument();
  Object.defineProperty(navigator, 'webdriver', { value: false, configurable: true });
});
```

- [ ] **Step 4: Run final full suite**

```bash
cd frontend && npm test -- --run
```

Expected: all tests pass.

- [ ] **Step 5: Lint**

```bash
cd frontend && npm run lint
```

Fix any TypeScript errors introduced by new shader imports or type extensions.

- [ ] **Step 6: Build check**

```bash
cd frontend && npm run build
```

Expected: build succeeds. Note any chunk size warnings (three is already in its own chunk per vite.config.ts).

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: OrbitScene AAA visual upgrade — GLSL planets, animated star, theater mode, post-processing, Milky Way, comet trails, mission HUD"
```

---

## Self-Review Against Spec

| Spec Requirement | Task |
|---|---|
| Panel mode preserved, same dimensions | Task 3 |
| Fullscreen theater mode via expand button | Task 3 |
| Escape/F keyboard shortcut | Task 3 |
| State preserved between modes | Task 3 |
| GLSL photosphere — FBM granulation, limb darkening | Task 4 |
| Animated sunspot groups | Task 4 |
| Spectral color by star type | Task 4 |
| Animated corona rays (CatmullRom) | Task 5 |
| Solar prominences (quadratic bezier) | Task 5 |
| UnrealBloomPass corona | Task 10 |
| Lens flare spikes + ghosts | Task 5 (corona) + Task 10 (bloom) |
| Godray shafts | Task 5 |
| PlanetClass from temperature | Task 2 |
| FBM surface shader, all 6 classes | Task 6 |
| Per-pixel star lighting + terminator | Task 6 |
| Atmosphere scattering rim | Task 6 |
| City lights on night side (ocean) | Task 6 |
| Specular ocean glint | Task 6 |
| Cloud layer (ocean + gas) | Task 7 |
| Ring system + Cassini division | Task 7 |
| Comet-tail orbit trails | Task 9 |
| Milky Way starfield (3000+, color temp) | Task 8 |
| Nebula sprite | Task 8 |
| Stellar wind particles | Task 8 |
| EffectComposer bloom | Task 10 |
| ChromaticAberrationPass | Task 10 |
| FilmGrainPass | Task 10 |
| VignettePass | Task 10 |
| Panel mode: bloom only | Task 10 |
| Theater mode: full stack | Task 10 |
| automatedBrowser guard | Task 13 |
| Cinematic camera dolly on selection | Task 11 |
| OrbitControls theater mode | Task 11 (wired via prop to OrbitSceneTheater) |
| Animated confidence bar | Task 12 |
| Theater mission control overlay | Task 12 |
| All existing test IDs preserved | All tasks |
| Science data contracts unchanged | All tasks |

**Gaps identified and covered:** OrbitControls for theater mode drag — wire in `OrbitSceneTheater.tsx` via a `useEffect` that imports `three/examples/jsm/controls/OrbitControls.js` and attaches to the scene's camera ref (passed as prop). Add this to Task 3's theater component.

---
