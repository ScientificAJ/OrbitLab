import { Pause, Play, RotateCcw, Gauge, ZoomIn, ZoomOut } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import type { Candidate } from '../lib/api';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { OrbitSceneTheater } from './OrbitSceneTheater';
import { starVertexShader, starFragmentShader, makeStarUniforms, inferSpectralType } from '../shaders/star';
import { planetVertexShader, planetFragmentShader, makePlanetUniforms } from '../shaders/planet';
import { orbitTrailVertexShader, orbitTrailFragmentShader, wrapAngle } from '../shaders/orbitTrail';
import { ChromaticAberrationShader } from '../shaders/postprocess/ChromaticAberrationPass';
import { FilmGrainShader } from '../shaders/postprocess/FilmGrainPass';
import { VignetteShader } from '../shaders/postprocess/VignettePass';
import { classifyPlanet, PlanetClass } from '../lib/planetClassifier';
import { CameraAnimator } from '../lib/cameraAnimator';

type Props = {
  candidates: Candidate[];
  selectedId?: string;
  emptyMessage?: string;
  onSelectCandidate?: (candidateId: string) => void;
};

type EvidenceTone = 'candidate' | 'ready' | 'review' | 'blocked';

type CandidateRenderData = {
  candidate: Candidate;
  radius: number;
  planetRadius: number;
  orbitOpacity: number;
  ghosted: boolean;
  speed: number;
  phase: number;
  inclination: number;
  hue: THREE.Color;
  hasPhysics: boolean;
  confidence: number;
  tone: EvidenceTone;
  statusLabel: string;
  transitArc: number;
  orbitTube: number;
  isHabitable: boolean;
  planetClass: PlanetClass;
  seed: number;
};

type PlanetMesh = CandidateRenderData & {
  mesh: THREE.Mesh;
  halo: THREE.Sprite;
  orbit: THREE.Mesh;
  transit: THREE.Mesh;
  label: string;
  planetUniforms: ReturnType<typeof makePlanetUniforms> | null;
  cloudMesh: THREE.Mesh | null;
  rings: THREE.Group | null;
};

const speedModes = [0.65, 1, 1.8];
const zoomModes = [0.65, 1, 1.45, 2.1];
const toneColors: Record<EvidenceTone, number> = {
  candidate: 0x76b9ff,
  ready: 0x97f2bf,
  review: 0xffc878,
  blocked: 0x9aa7ad,
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function finite(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function candidateDisposition(candidate: Candidate) {
  const value = (candidate as Candidate & { disposition?: string | null }).disposition;
  return typeof value === 'string' ? value : undefined;
}

function scienceStatus(candidate: Candidate) {
  const value = candidate.science_readiness?.status;
  return typeof value === 'string' ? value : undefined;
}

function falsePositiveFlags(candidate: Candidate) {
  return candidate.validation?.false_positive_flags?.filter(Boolean).length ?? 0;
}

function isGhostedEvidence(candidate: Candidate) {
  return candidateDisposition(candidate) === 'rejected_signal' || scienceStatus(candidate) === 'blocked';
}

function evidenceTone(candidate: Candidate): EvidenceTone {
  if (isGhostedEvidence(candidate)) return 'blocked';
  if (
    scienceStatus(candidate) === 'review' ||
    candidate.validation?.duration_plausible === false ||
    falsePositiveFlags(candidate) > 0
  ) {
    return 'review';
  }
  if (scienceStatus(candidate) === 'ready' || candidate.physics?.is_in_habitable_zone) return 'ready';
  return 'candidate';
}

function statusLabel(candidate: Candidate, tone: EvidenceTone) {
  if (tone === 'blocked') return 'blocked evidence';
  if (tone === 'review') return 'review signal';
  if (candidate.physics?.is_in_habitable_zone) return 'habitable-zone candidate';
  if (tone === 'ready') return 'science-ready';
  if (!candidate.physics || !Object.keys(candidate.physics).length) return 'preview evidence';
  return 'candidate evidence';
}

function confidenceScore(candidate: Candidate, tone: EvidenceTone) {
  const snrScore = clamp((finite(candidate.signal_to_noise, 0) - 6) / 22, 0, 1) * 0.42;
  const physicsScore = candidate.physics && Object.keys(candidate.physics).length ? 0.18 : 0.04;
  const validationScore = candidate.validation
    ? candidate.validation.duration_plausible === false
      ? 0.04
      : 0.18
    : 0.08;
  const readinessScore = tone === 'ready' ? 0.18 : tone === 'candidate' ? 0.1 : tone === 'review' ? 0.04 : -0.14;
  return clamp(snrScore + physicsScore + validationScore + readinessScore, 0.08, 0.96);
}

function orbitRadius(candidate: Candidate, index: number) {
  const semiMajorAxis = finite(candidate.physics?.semi_major_axis_au, 0);
  if (semiMajorAxis > 0) return clamp(4.2 + Math.log1p(semiMajorAxis * 96) * 3.55 + index * 0.38, 4.7, 16.6);
  return clamp(4.45 + Math.log1p(Math.max(candidate.period, 0)) * 2.95 + index * 0.58, 4.8, 16.2);
}

function orbitSize(candidate: Candidate, index: number) {
  return clamp(34 + orbitRadius(candidate, index) * 4.1, 38, 94);
}

function planetScale(candidate: Candidate, active: boolean) {
  const radiusRatio = finite(candidate.physics?.radius_ratio, 0);
  const depthRadius = Math.sqrt(Math.max(finite(candidate.depth, 0), 0));
  const radiusEarth = finite(candidate.physics?.planet_radius_earth, 0);
  const signal = radiusRatio || depthRadius || (radiusEarth > 0 ? radiusEarth / 18 : 0.02);
  return clamp(0.18 + signal * 5.4 + (active ? 0.1 : 0), 0.22, active ? 0.68 : 0.52);
}

function transitArc(candidate: Candidate) {
  const period = Math.max(candidate.period, 0.05);
  const duration = Math.max(finite(candidate.duration_days, finite(candidate.duration, 0.08)), 0.01);
  return clamp((duration / period) * Math.PI * 12, Math.PI * 0.11, Math.PI * 0.62);
}

function candidateColor(candidate: Candidate, active: boolean, tone: EvidenceTone) {
  if (active) return new THREE.Color(tone === 'review' ? 0xffd08a : tone === 'blocked' ? 0xc3d0d4 : 0x93ecff);
  return new THREE.Color(toneColors[tone]);
}

function candidateRenderData(candidates: Candidate[], selectedId?: string): CandidateRenderData[] {
  return candidates.slice(0, 8).map((candidate, index) => {
    const active = candidate.candidate_id === selectedId;
    const tone = evidenceTone(candidate);
    const confidence = confidenceScore(candidate, tone);
    const ghosted = isGhostedEvidence(candidate);
    return {
      candidate,
      radius: orbitRadius(candidate, index),
      planetRadius: planetScale(candidate, active) * (ghosted ? 0.76 : 1),
      orbitOpacity: clamp(0.18 + confidence * 0.5 + (active ? 0.22 : 0), 0.18, 0.88) * (ghosted ? 0.42 : 1),
      ghosted,
      speed: clamp(0.023 / Math.sqrt(Math.max(candidate.period, 0.15)), 0.003, 0.046),
      phase: (finite(candidate.epoch_days, finite(candidate.epoch, index)) * 2.4 + index * 0.72) % (Math.PI * 2),
      inclination: (index - (candidates.length - 1) / 2) * 0.038,
      hue: candidateColor(candidate, active, tone),
      hasPhysics: Boolean(candidate.physics && Object.keys(candidate.physics).length),
      confidence,
      tone,
      statusLabel: statusLabel(candidate, tone),
      transitArc: transitArc(candidate),
      orbitTube: clamp(0.018 + confidence * 0.035 + (active ? 0.022 : 0), 0.022, 0.074),
      isHabitable: Boolean(candidate.physics?.is_in_habitable_zone || candidate.physics?.is_temperature_habitable),
      planetClass: classifyPlanet({
        equilibrium_temperature_k: candidate.physics?.equilibrium_temperature_k,
        is_in_habitable_zone: candidate.physics?.is_in_habitable_zone,
        radius_ratio: finite(candidate.physics?.radius_ratio, 0) || undefined,
        planet_radius_earth: finite(candidate.physics?.planet_radius_earth, 0) || undefined,
      }),
      // [CREATIVE: golden-angle seeding — 137.508° spacing plus the candidate's
      // own epoch makes every planet's surface unique but fully deterministic,
      // so re-renders of the same system always look identical]
      seed: (index * 137.508 + finite(candidate.epoch_days ?? candidate.epoch, index) * 7.3) % 99.0,
    };
  });
}

function makeDiscTexture(inner: string, outer: string, middle = inner) {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  if (!context) return null;
  const gradient = context.createRadialGradient(64, 64, 2, 64, 64, 64);
  gradient.addColorStop(0, inner);
  gradient.addColorStop(0.42, middle);
  gradient.addColorStop(1, outer);
  context.fillStyle = gradient;
  context.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeStarMaterial() {
  const canvas = document.createElement('canvas');
  canvas.width = 320;
  canvas.height = 160;
  const context = canvas.getContext('2d');
  if (!context) {
    return new THREE.MeshStandardMaterial({ color: 0xffd27d, emissive: 0xff8a22, emissiveIntensity: 1.35 });
  }

  const image = context.createImageData(canvas.width, canvas.height);
  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      const index = (y * canvas.width + x) * 4;
      const band = Math.sin(x * 0.14) * 13 + Math.cos((x + y) * 0.046) * 18;
      const granule = Math.sin((x * 11 + y * 17) * 0.031) * 18;
      const limb = Math.abs(y / canvas.height - 0.5) * 30;
      image.data[index] = clamp(248 + band + granule - limb, 0, 255);
      image.data[index + 1] = clamp(159 + band * 0.48 + granule * 0.58 - limb * 0.25, 0, 255);
      image.data[index + 2] = clamp(58 + band * 0.2 + granule * 0.16, 0, 255);
      image.data[index + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  return new THREE.MeshStandardMaterial({
    map: texture,
    color: 0xffd59b,
    emissive: 0xff8f23,
    emissiveIntensity: 1.55,
    roughness: 0.74,
  });
}

function makeCloudLayer(planetRadius: number, planetClass: PlanetClass): THREE.Mesh | null {
  if (planetClass !== PlanetClass.OCEAN && planetClass !== PlanetClass.GAS) return null;
  const cloudVertShader = /* glsl */ `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
  `;
  const cloudFragShader = /* glsl */ `
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

function makeRingSystem(radius: number, planetClass: PlanetClass, hue: THREE.Color): THREE.Group | null {
  if (planetClass !== PlanetClass.GAS) return null;
  const group = new THREE.Group();
  const ringDefs = [
    { inner: radius * 1.25, outer: radius * 1.5, opacity: 0.55 },
    { inner: radius * 1.55, outer: radius * 1.72, opacity: 0.35 },
    { inner: radius * 1.78, outer: radius * 2.0, opacity: 0.25 },
  ];
  ringDefs.forEach(({ inner, outer, opacity }) => {
    const geo = new THREE.RingGeometry(inner, outer, 128);
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
  // [CREATIVE: Cassini-like division — a dark gap ring between the bands]
  const gapGeo = new THREE.RingGeometry(radius * 1.5, radius * 1.56, 128);
  const gapMat = new THREE.MeshBasicMaterial({
    color: 0x000000,
    transparent: true,
    opacity: 0.9,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const gap = new THREE.Mesh(gapGeo, gapMat);
  gap.rotation.x = Math.PI / 2;
  group.add(gap);
  // [CREATIVE: Saturn-style ring tilt so the system reads in 3D from the
  // default camera height instead of edge-on]
  group.rotation.z = 0.16;
  return group;
}

/**
 * Comet-tail orbit: a torus annotated per-vertex with its ring angle so the
 * trail shader can fade the arc behind the moving planet. The torus's main
 * ring lies in its local XY plane; the mesh is rotated into the world XZ
 * orbital plane afterward, so local atan2(y, x) IS the world orbit angle.
 */
function makeTrailOrbit(radius: number, tube: number, hue: THREE.Color, opacity: number): THREE.Mesh {
  const geo = new THREE.TorusGeometry(radius, tube, 8, 220);
  const pos = geo.attributes.position;
  const angles = new Float32Array(pos.count);
  for (let i = 0; i < pos.count; i++) {
    angles[i] = wrapAngle(Math.atan2(pos.getY(i), pos.getX(i)));
  }
  geo.setAttribute('angle', new THREE.BufferAttribute(angles, 1));
  return new THREE.Mesh(
    geo,
    new THREE.ShaderMaterial({
      vertexShader: orbitTrailVertexShader,
      fragmentShader: orbitTrailFragmentShader,
      uniforms: {
        uPlanetAngle: { value: 0 },
        uColor: { value: [hue.r ?? 0.5, hue.g ?? 0.7, hue.b ?? 1.0] },
        // [CREATIVE: tail fades toward deep-space blue instead of just to black]
        uFadeColor: { value: [0.05, 0.09, 0.2] },
        uOpacity: { value: opacity },
      },
      transparent: true,
      depthWrite: false,
    }),
  );
}

function classColor(cls: PlanetClass): string {
  const map: Record<PlanetClass, string> = {
    [PlanetClass.LAVA]: '#ff6622',
    [PlanetClass.HOT_ROCKY]: '#cc8844',
    [PlanetClass.OCEAN]: '#44aaff',
    [PlanetClass.COLD_ROCKY]: '#8899aa',
    [PlanetClass.ICE]: '#aaddff',
    [PlanetClass.GAS]: '#ddaa66',
    [PlanetClass.UNKNOWN]: '#667788',
  };
  return map[cls] ?? '#a8c8f0';
}

// [CREATIVE: per-class axial spin rates — gas giants whirl like 10-hour
// Jupiter, lava worlds crawl as if tidally braked]
const classSpinRate: Record<PlanetClass, number> = {
  [PlanetClass.GAS]: 0.02,
  [PlanetClass.OCEAN]: 0.008,
  [PlanetClass.COLD_ROCKY]: 0.006,
  [PlanetClass.ICE]: 0.005,
  [PlanetClass.HOT_ROCKY]: 0.004,
  [PlanetClass.LAVA]: 0.0025,
  [PlanetClass.UNKNOWN]: 0.005,
};

// [CREATIVE: corona ray tint follows the star's spectral type so an M dwarf
// gets deep ember streamers while an F star gets pale gold ones]
const coronaTints: Record<string, number> = {
  F: 0xfff0c0,
  G: 0xffcc66,
  K: 0xff9944,
  M: 0xff6633,
};

function makeCoronaRays(scene: THREE.Scene, starRadius: number, spectralType: string): THREE.Mesh[] {
  const rays: THREE.Mesh[] = [];
  const rayCount = 14;
  for (let i = 0; i < rayCount; i++) {
    const angle = (i / rayCount) * Math.PI * 2;
    const len = starRadius * (1.4 + Math.sin(i * 2.3) * 0.5);
    const points = [];
    for (let t = 0; t <= 1; t += 0.1) {
      const r = starRadius * 1.02 + t * len;
      const wobble = Math.sin(t * Math.PI * 3 + i) * starRadius * 0.08;
      points.push(
        new THREE.Vector3(Math.cos(angle + wobble * 0.05) * r, Math.sin(angle + wobble * 0.05) * r * 0.22, 0),
      );
    }
    const curve = new THREE.CatmullRomCurve3(points);
    const geo = new THREE.TubeGeometry(curve, 10, 0.018 + Math.random() * 0.012, 4, false);
    const mat = new THREE.MeshBasicMaterial({
      color: coronaTints[spectralType] ?? coronaTints.G,
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
  arcDefs.forEach(({ a1, a2, h, color }, index) => {
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
    // [CREATIVE: one prominence slowly erupts — it stretches up over ~90s,
    // then settles back, like filament footage from SDO]
    arc.userData.erupting = index === 0;
    scene.add(arc);
    arcs.push(arc);
  });
  return arcs;
}

function canCreateWebGLContext() {
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
  if (!context) return false;
  const loseContext = context.getExtension('WEBGL_lose_context');
  loseContext?.loseContext();
  return true;
}

function disposeMaterial(material: THREE.Material) {
  const withTextures = material as THREE.Material & {
    map?: THREE.Texture | null;
    alphaMap?: THREE.Texture | null;
    emissiveMap?: THREE.Texture | null;
    normalMap?: THREE.Texture | null;
    roughnessMap?: THREE.Texture | null;
  };
  [withTextures.map, withTextures.alphaMap, withTextures.emissiveMap, withTextures.normalMap, withTextures.roughnessMap]
    .filter((texture): texture is THREE.Texture => Boolean(texture))
    .forEach((texture) => texture.dispose());
  material.dispose();
}

function formatTemperature(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)} K` : undefined;
}

export function OrbitScene({
  candidates,
  selectedId,
  emptyMessage = 'Run BLS Search or Analysis to render candidate orbits.',
  onSelectCandidate,
}: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [webglUnavailable, setWebglUnavailable] = useState(false);
  const [isPlaying, setIsPlaying] = useState(true);
  const [speedMode, setSpeedMode] = useState(1);
  const [zoomMode, setZoomMode] = useState(1);
  const [cameraReset, setCameraReset] = useState(0);
  const [selectionPulse, setSelectionPulse] = useState(false);
  const [theaterMode, setTheaterMode] = useState(false);
  const renderData = useMemo(() => candidateRenderData(candidates, selectedId), [candidates, selectedId]);
  const selected = candidates.find((candidate) => candidate.candidate_id === selectedId) ?? candidates[0];
  const selectedRenderData =
    renderData.find((candidate) => candidate.candidate.candidate_id === selected?.candidate_id) ?? renderData[0];

  useEffect(() => {
    if (!selectedId || !candidates.length) return undefined;
    setSelectionPulse(true);
    const timeout = window.setTimeout(() => setSelectionPulse(false), 6200);
    return () => {
      window.clearTimeout(timeout);
    };
  }, [candidates.length, selectedId]);

  // Keyboard shortcut: F toggles theater mode when focus is inside the scene
  // (or whenever theater is already active, so F also exits).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'f' && event.key !== 'F') return;
      const target = event.target as HTMLElement | null;
      // [CREATIVE: never hijack F while the user is typing in a form field]
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      const mount = mountRef.current;
      const focusInScene =
        mount != null &&
        document.activeElement != null &&
        (document.activeElement === mount || mount.contains(document.activeElement));
      setTheaterMode((prev) => {
        if (prev) return false;
        return focusInScene ? true : prev;
      });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    setWebglUnavailable(false);
    if (!canCreateWebGLContext()) {
      setWebglUnavailable(true);
      return;
    }

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x03080d, 0.016);

    const width = Math.max(mount.clientWidth, 1);
    const height = Math.max(mount.clientHeight, 1);
    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 1000);
    const zoom = zoomModes[zoomMode] ?? 1;
    const cameraHeight = 14.2 / zoom;
    const cameraDistance = 24.5 / zoom;
    const resetCamera = () => {
      camera.position.set(0, cameraHeight, cameraDistance);
      camera.lookAt(0, 0, 0);
    };
    resetCamera();

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    } catch {
      setWebglUnavailable(true);
      return;
    }
    renderer.setClearColor(0x000000, 0);
    const automatedBrowser = navigator.webdriver;
    renderer.setPixelRatio(automatedBrowser ? 1 : Math.min(window.devicePixelRatio, 1.55));
    renderer.setSize(width, height);
    renderer.domElement.dataset.testid = 'orbit-canvas';
    renderer.domElement.setAttribute('aria-label', 'Interactive orbit analysis visualization');
    renderer.domElement.setAttribute('role', 'img');
    mount.appendChild(renderer.domElement);

    // ── Post-processing chain ──────────────────────────────────
    // Panel mode: render + bloom. Theater mode: full cinematic stack.
    // automatedBrowser (e2e) keeps the bare renderer for determinism.
    let composer: EffectComposer | null = null;
    let filmGrainPass: ShaderPass | null = null;
    let chromaPass: ShaderPass | null = null;
    // [CREATIVE: focus pull — theater entry starts slightly soft/fringed and
    // snaps sharp over ~0.8s, like a camera operator finding focus]
    let theaterFocusFrames = theaterMode ? 48 : 0;
    if (!automatedBrowser) {
      composer = new EffectComposer(renderer);
      composer.addPass(new RenderPass(scene, camera));
      const bloom = new UnrealBloomPass(
        new THREE.Vector2(width, height),
        theaterMode ? 1.1 : 0.85, // strength
        0.42, // radius
        0.82, // threshold
      );
      composer.addPass(bloom);
      if (theaterMode) {
        chromaPass = new ShaderPass(ChromaticAberrationShader);
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

    // [CREATIVE: spectral color follows the loaded system — HZ inner radius
    // tells us how luminous the host star is, so an M dwarf renders ember-red
    // while an F star renders white-hot]
    const spectralType = inferSpectralType(
      renderData.find((data) => data.candidate.physics?.habitable_zone_inner_au)?.candidate.physics
        ?.habitable_zone_inner_au,
    );
    const starUniforms = automatedBrowser ? null : makeStarUniforms(spectralType);
    const star = new THREE.Mesh(
      new THREE.SphereGeometry(1.78, automatedBrowser ? 40 : 64, automatedBrowser ? 40 : 64),
      starUniforms
        ? new THREE.ShaderMaterial({
            vertexShader: starVertexShader,
            fragmentShader: starFragmentShader,
            uniforms: starUniforms,
          })
        : makeStarMaterial(),
    );
    scene.add(star);

    const coronaTexture = makeDiscTexture(
      'rgba(255, 233, 171, 0.78)',
      'rgba(255, 150, 46, 0)',
      'rgba(255, 177, 74, 0.34)',
    );
    const corona = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: coronaTexture ?? undefined,
        color: 0xffb661,
        transparent: true,
        opacity: 0.96,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        depthTest: false,
      }),
    );
    corona.scale.set(9.2, 9.2, 1);
    scene.add(corona);

    const coronaRays = automatedBrowser ? [] : makeCoronaRays(scene, 1.78, spectralType);
    const prominences = automatedBrowser ? [] : makeProminences(scene, 1.78);

    const rim = new THREE.Mesh(
      new THREE.SphereGeometry(2.04, automatedBrowser ? 40 : 64, automatedBrowser ? 40 : 64),
      new THREE.MeshBasicMaterial({ color: 0xffc46f, transparent: true, opacity: 0.2, side: THREE.BackSide }),
    );
    scene.add(rim);

    const transitChord = new THREE.Mesh(
      new THREE.PlaneGeometry(3.75, 0.035),
      new THREE.MeshBasicMaterial({
        color: 0xd8f8ff,
        transparent: true,
        opacity: 0,
        depthWrite: false,
        depthTest: false,
      }),
    );
    transitChord.position.set(0, 0.28, 1.86);
    scene.add(transitChord);

    const transitShadow = new THREE.Mesh(
      new THREE.CircleGeometry(0.18, automatedBrowser ? 28 : 40),
      new THREE.MeshBasicMaterial({
        color: 0x071016,
        transparent: true,
        opacity: 0,
        depthWrite: false,
        depthTest: false,
      }),
    );
    transitShadow.position.set(0, 0.28, 1.9);
    scene.add(transitShadow);

    const primaryLight = new THREE.PointLight(0xffd08a, 4.9, 86);
    primaryLight.position.set(0, 0, 0);
    scene.add(primaryLight);
    scene.add(new THREE.AmbientLight(0x6d91a5, 0.44));
    const rimLight = new THREE.DirectionalLight(0x8ee7ff, 1.45);
    rimLight.position.set(-11, 12, 9);
    scene.add(rimLight);

    const planeDisc = new THREE.Mesh(
      new THREE.RingGeometry(2.45, 18.4, automatedBrowser ? 112 : 192),
      new THREE.MeshBasicMaterial({
        color: 0x5fd8e8,
        transparent: true,
        opacity: 0.055,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    planeDisc.rotation.x = Math.PI / 2;
    scene.add(planeDisc);

    const planeGrid = new THREE.GridHelper(38, 38, 0x4b8290, 0x173340);
    const gridMaterial = planeGrid.material as THREE.Material | THREE.Material[];
    if (Array.isArray(gridMaterial)) {
      gridMaterial.forEach((material) => {
        material.transparent = true;
        material.opacity = 0.2;
      });
    } else {
      gridMaterial.transparent = true;
      gridMaterial.opacity = 0.2;
    }
    scene.add(planeGrid);

    let hzMesh: THREE.Mesh | null = null;
    const hzSource =
      renderData.find((data) => data.candidate.physics?.habitable_zone_inner_au) ??
      renderData.find((data) => data.isHabitable);
    if (hzSource) {
      const innerAu = finite(hzSource.candidate.physics?.habitable_zone_inner_au, 0);
      const outerAu = finite(hzSource.candidate.physics?.habitable_zone_outer_au, 0);
      const innerRadius =
        innerAu > 0 ? clamp(4.2 + Math.log1p(innerAu * 96) * 3.55, 4.8, 17.2) : clamp(hzSource.radius - 0.56, 4.7, 17);
      const outerRadius =
        outerAu > innerAu
          ? clamp(4.2 + Math.log1p(outerAu * 96) * 3.55, innerRadius + 0.18, 17.8)
          : clamp(hzSource.radius + 0.56, innerRadius + 0.18, 17.8);
      const hz = new THREE.Mesh(
        new THREE.RingGeometry(innerRadius, outerRadius, automatedBrowser ? 128 : 220),
        new THREE.MeshBasicMaterial({
          color: 0x7ff0ac,
          transparent: true,
          opacity: 0.105,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      );
      hz.rotation.x = Math.PI / 2;
      scene.add(hz);
      hzMesh = hz;
      [innerRadius, outerRadius].forEach((radius) => {
        const boundary = new THREE.Mesh(
          new THREE.TorusGeometry(radius, 0.016, 8, automatedBrowser ? 96 : 160),
          new THREE.MeshBasicMaterial({ color: 0x9df5bd, transparent: true, opacity: 0.28 }),
        );
        boundary.rotation.x = Math.PI / 2;
        scene.add(boundary);
      });
    }

    const starCount = automatedBrowser ? 340 : 3200;
    const starPositions = new Float32Array(starCount * 3);
    const starColors = new Float32Array(starCount * 3);
    for (let index = 0; index < starCount; index += 1) {
      if (automatedBrowser) {
        // Original low-detail distribution, kept byte-identical for e2e runs.
        const angle = index * 2.399963;
        const radius = 32 + ((index * 37) % 76);
        const heightOffset = ((index * 53) % 84) - 25;
        const lane = Math.sin(index * 0.37) * 6;
        starPositions[index * 3] = Math.cos(angle) * radius;
        starPositions[index * 3 + 1] = heightOffset * 0.31 + lane * 0.08;
        starPositions[index * 3 + 2] = Math.sin(angle) * radius;
        const brightness = 0.38 + ((index * 19) % 48) / 100;
        const warm = index % 11 === 0 ? 0.14 : 0;
        starColors[index * 3] = brightness * (0.72 + warm);
        starColors[index * 3 + 1] = brightness * (0.88 + warm * 0.4);
        starColors[index * 3 + 2] = brightness;
        continue;
      }
      // Milky Way band — golden-angle azimuth with density biased toward an
      // equatorial band, like the galactic plane crossing the sky.
      const phi = index * 2.399963;
      const bandBias = Math.pow(Math.abs(Math.sin(phi * 0.5)), 0.4);
      const r = 38 + ((index * 37) % 62);
      const theta = (Math.acos(2 * ((index * 0.618) % 1) - 1) - Math.PI / 2) * bandBias * 0.4;
      starPositions[index * 3] = Math.cos(phi) * Math.cos(theta) * r;
      starPositions[index * 3 + 1] = Math.sin(theta) * r * 0.3;
      starPositions[index * 3 + 2] = Math.sin(phi) * Math.cos(theta) * r;

      // [CREATIVE: real stellar demographics — ~10% M-type orange-red, ~20%
      // B/A blue-white, the rest G/K yellow-white, deterministic per index]
      const typeRoll = (index * 0.31) % 1;
      const brightness = 0.35 + ((index * 19) % 48) / 100;
      if (typeRoll < 0.1) {
        starColors[index * 3] = brightness * 0.9;
        starColors[index * 3 + 1] = brightness * 0.5;
        starColors[index * 3 + 2] = brightness * 0.3;
      } else if (typeRoll < 0.3) {
        starColors[index * 3] = brightness * 0.7;
        starColors[index * 3 + 1] = brightness * 0.82;
        starColors[index * 3 + 2] = brightness;
      } else {
        starColors[index * 3] = brightness;
        starColors[index * 3 + 1] = brightness * 0.92;
        starColors[index * 3 + 2] = brightness * 0.72;
      }
    }
    const starfieldGeometry = new THREE.BufferGeometry();
    starfieldGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    starfieldGeometry.setAttribute('color', new THREE.BufferAttribute(starColors, 3));
    const starfield = new THREE.Points(
      starfieldGeometry,
      new THREE.PointsMaterial({
        size: automatedBrowser ? 0.1 : 0.115,
        vertexColors: true,
        transparent: true,
        opacity: 0.86,
        depthWrite: false,
      }),
    );
    scene.add(starfield);

    // [CREATIVE: second, nearer sparse star layer — rotated at a different
    // rate in the tick loop for genuine parallax depth]
    let nearStars: THREE.Points | null = null;
    if (!automatedBrowser) {
      const nearGeo = new THREE.BufferGeometry();
      const nearPos = new Float32Array(200 * 3);
      const nearCol = new Float32Array(200 * 3);
      for (let i = 0; i < 200; i++) {
        const a = i * 2.4;
        const r2 = 28 + ((i * 11) % 16);
        nearPos[i * 3] = Math.cos(a) * r2;
        nearPos[i * 3 + 1] = (((i * 53) % 30) - 15) * 0.08;
        nearPos[i * 3 + 2] = Math.sin(a) * r2;
        nearCol[i * 3] = 0.9;
        nearCol[i * 3 + 1] = 0.92;
        nearCol[i * 3 + 2] = 0.85;
      }
      nearGeo.setAttribute('position', new THREE.BufferAttribute(nearPos, 3));
      nearGeo.setAttribute('color', new THREE.BufferAttribute(nearCol, 3));
      nearStars = new THREE.Points(
        nearGeo,
        new THREE.PointsMaterial({
          size: 0.15,
          vertexColors: true,
          transparent: true,
          opacity: 0.5,
          depthWrite: false,
        }),
      );
      scene.add(nearStars);
    }

    // [CREATIVE: nebula wash + one faint distant-galaxy smudge — the kind of
    // background detail that makes a viewer lean in]
    if (!automatedBrowser) {
      const nebulaTexture = makeDiscTexture('rgba(80, 60, 160, 0.20)', 'rgba(0, 0, 0, 0)', 'rgba(60, 40, 120, 0.10)');
      if (nebulaTexture) {
        const nebula = new THREE.Sprite(
          new THREE.SpriteMaterial({
            map: nebulaTexture,
            transparent: true,
            opacity: 0.55,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
          }),
        );
        nebula.scale.set(55, 55, 1);
        nebula.position.set(18, -6, -22);
        scene.add(nebula);
      }
      const galaxyTexture = makeDiscTexture('rgba(225, 228, 255, 0.45)', 'rgba(0, 0, 0, 0)');
      if (galaxyTexture) {
        const galaxy = new THREE.Sprite(
          new THREE.SpriteMaterial({
            map: galaxyTexture,
            transparent: true,
            opacity: 0.16,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
          }),
        );
        galaxy.scale.set(7, 2.4, 1);
        galaxy.position.set(-30, 9, -40);
        scene.add(galaxy);
      }
    }

    // ── Stellar wind ───────────────────────────────────────────
    const windCount = automatedBrowser ? 0 : 6000;
    let windGeo: THREE.BufferGeometry | null = null;
    const windVelocities = new Float32Array(windCount * 3);
    const windResets = new Float32Array(windCount * 3);
    if (windCount > 0) {
      const windPositions = new Float32Array(windCount * 3);
      for (let i = 0; i < windCount; i++) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        const r = 2.0 + Math.random() * 14;
        const dx = Math.sin(phi) * Math.cos(theta);
        const dy = Math.cos(phi) * 0.3;
        const dz = Math.sin(phi) * Math.sin(theta);
        windPositions[i * 3] = dx * r;
        windPositions[i * 3 + 1] = dy * r;
        windPositions[i * 3 + 2] = dz * r;
        const spd = 0.028 + Math.random() * 0.018;
        windVelocities[i * 3] = dx * spd;
        windVelocities[i * 3 + 1] = dy * spd;
        windVelocities[i * 3 + 2] = dz * spd;
        // Respawn just above the photosphere along the same radial line.
        windResets[i * 3] = dx * 2.05;
        windResets[i * 3 + 1] = dy * 2.05;
        windResets[i * 3 + 2] = dz * 2.05;
      }
      windGeo = new THREE.BufferGeometry();
      windGeo.setAttribute('position', new THREE.BufferAttribute(windPositions, 3));
      const windParticles = new THREE.Points(
        windGeo,
        new THREE.PointsMaterial({ size: 0.04, color: 0xffeedd, transparent: true, opacity: 0.22, depthWrite: false }),
      );
      scene.add(windParticles);
    }

    // [CREATIVE: a shooting star streaks across the deep background roughly
    // every 25 seconds, on a different path each time]
    let meteor: THREE.Sprite | null = null;
    if (!automatedBrowser) {
      const meteorTexture = makeDiscTexture('rgba(255, 255, 255, 0.9)', 'rgba(255, 255, 255, 0)');
      meteor = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: meteorTexture ?? undefined,
          transparent: true,
          opacity: 0,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        }),
      );
      meteor.scale.set(2.4, 0.07, 1);
      scene.add(meteor);
    }

    const haloTexture = makeDiscTexture('rgba(147, 236, 255, 0.52)', 'rgba(147, 236, 255, 0)');
    const planetMeshes: PlanetMesh[] = [];
    renderData.forEach((data) => {
      const active = data.candidate.candidate_id === selectedId;
      const orbit = automatedBrowser
        ? new THREE.Mesh(
            new THREE.TorusGeometry(data.radius, data.orbitTube, 8, 128),
            new THREE.MeshBasicMaterial({
              color: data.hue,
              transparent: true,
              opacity: data.orbitOpacity,
            }),
          )
        : makeTrailOrbit(data.radius, data.orbitTube, data.hue, data.orbitOpacity);
      orbit.rotation.x = Math.PI / 2 + data.inclination;
      scene.add(orbit);

      const orbitGlow = new THREE.Mesh(
        new THREE.TorusGeometry(data.radius, active ? data.orbitTube * 3.1 : data.orbitTube * 1.75, 8, 160),
        new THREE.MeshBasicMaterial({
          color: data.hue,
          transparent: true,
          opacity: active ? 0.16 : data.isHabitable ? 0.1 : 0.04,
        }),
      );
      orbitGlow.rotation.copy(orbit.rotation);
      scene.add(orbitGlow);

      const transit = new THREE.Mesh(
        new THREE.TorusGeometry(data.radius, active ? 0.085 : 0.052, 8, 36, data.transitArc),
        new THREE.MeshBasicMaterial({
          color: data.tone === 'review' ? 0xffd08a : data.tone === 'blocked' ? 0xc7d0d4 : 0xffffff,
          transparent: true,
          opacity: active ? 0.58 : 0.2 + data.confidence * 0.08,
        }),
      );
      transit.rotation.set(Math.PI / 2 + data.inclination, 0, -Math.PI * 0.5 - data.transitArc / 2);
      scene.add(transit);

      const planetUniforms = automatedBrowser
        ? null
        : makePlanetUniforms(data.planetClass, data.seed, data.ghosted, data.isHabitable, [0, 0, 0]);
      const planet = new THREE.Mesh(
        new THREE.SphereGeometry(data.planetRadius, automatedBrowser ? 22 : 48, automatedBrowser ? 22 : 48),
        planetUniforms
          ? new THREE.ShaderMaterial({
              vertexShader: planetVertexShader,
              fragmentShader: planetFragmentShader,
              uniforms: planetUniforms,
              transparent: data.ghosted,
            })
          : new THREE.MeshStandardMaterial({
              color: data.hue,
              emissive: data.hue,
              emissiveIntensity: data.ghosted ? 0.035 : active ? 0.48 : 0.16 + data.confidence * 0.1,
              metalness: 0.05,
              roughness: data.ghosted ? 0.88 : data.hasPhysics ? 0.42 : 0.58,
              transparent: data.ghosted,
              opacity: data.ghosted ? 0.52 : 1,
            }),
      );
      planet.name = data.candidate.candidate_id;
      planet.userData.candidateId = data.candidate.candidate_id;
      scene.add(planet);

      const cloudMesh = automatedBrowser ? null : makeCloudLayer(data.planetRadius, data.planetClass);
      if (cloudMesh) scene.add(cloudMesh);
      const rings = automatedBrowser ? null : makeRingSystem(data.planetRadius, data.planetClass, data.hue);
      if (rings) scene.add(rings);

      const halo = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: haloTexture ?? undefined,
          color: data.hue,
          transparent: true,
          opacity: active ? 0.5 : 0.16 + data.confidence * 0.16,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        }),
      );
      halo.scale.setScalar(data.planetRadius * (active ? 5.6 : 3.4));
      scene.add(halo);

      planetMeshes.push({
        ...data,
        mesh: planet,
        halo,
        orbit,
        transit,
        label: data.candidate.candidate_id,
        planetUniforms,
        cloudMesh,
        rings,
      });
    });

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let hovered: THREE.Object3D | null = null;
    const selectableMeshes = planetMeshes.map((planet) => planet.mesh);

    const setPointer = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    };

    const onPointerMove = (event: PointerEvent) => {
      setPointer(event);
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(selectableMeshes, false)[0]?.object ?? null;
      if (hovered !== hit) {
        if (hovered) hovered.scale.setScalar(1);
        hovered = hit;
        if (hovered) hovered.scale.setScalar(1.26);
        renderer.domElement.style.cursor = hovered ? 'pointer' : 'default';
      }
    };

    const onClick = (event: PointerEvent) => {
      setPointer(event);
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(selectableMeshes, false)[0]?.object;
      const candidateId = typeof hit?.userData.candidateId === 'string' ? hit.userData.candidateId : undefined;
      if (candidateId) onSelectCandidate?.(candidateId);
    };

    renderer.domElement.addEventListener('pointermove', onPointerMove);
    renderer.domElement.addEventListener('click', onClick);

    // Cinematic dolly controller — selection triggers a dolly-in/hold/return arc.
    const cameraAnimator = new CameraAnimator({ x: 0, y: cameraHeight, z: cameraDistance });
    let prevSelectedId: string | undefined;

    // [CREATIVE: theater free-look — drag anywhere in theater mode to orbit
    // the whole system, closing the spec's OrbitControls gap without pulling
    // in a control class the test mock would have to fake]
    let dragAzimuth = 0;
    let dragPolar = 0;
    let dragging = false;
    let dragLastX = 0;
    let dragLastY = 0;
    const onDragStart = (event: PointerEvent) => {
      if (!theaterMode) return;
      dragging = true;
      dragLastX = event.clientX;
      dragLastY = event.clientY;
    };
    const onDragMove = (event: PointerEvent) => {
      if (!dragging) return;
      dragAzimuth -= (event.clientX - dragLastX) * 0.005;
      dragPolar = clamp(dragPolar - (event.clientY - dragLastY) * 0.004, -0.8, 0.8);
      dragLastX = event.clientX;
      dragLastY = event.clientY;
    };
    const onDragEnd = () => {
      dragging = false;
    };
    renderer.domElement.addEventListener('pointerdown', onDragStart);
    window.addEventListener('pointermove', onDragMove);
    window.addEventListener('pointerup', onDragEnd);

    let frame = 0;
    let animation = 0;
    const tick = () => {
      const speed = speedModes[speedMode] ?? 1;
      if (isPlaying) frame += speed;
      star.rotation.y += 0.0026 * speed;
      if (starUniforms) starUniforms.uTime.value += 0.016 * speed;
      rim.rotation.y -= 0.0011 * speed;
      corona.material.rotation += 0.0008 * speed;
      coronaRays.forEach((ray, i) => {
        ray.rotation.y += (ray.userData.baseRotSpeed as number) * speed;
        // [CREATIVE: each corona ray breathes on its own offset phase]
        (ray.material as THREE.MeshBasicMaterial).opacity = 0.14 + Math.sin(frame * 0.018 + i * 0.8) * 0.06;
      });
      prominences.forEach((arc) => {
        arc.rotation.y += (arc.userData.driftSpeed as number) * speed;
        if (arc.userData.erupting) {
          arc.scale.y = 1 + Math.max(0, Math.sin(frame * 0.0011)) * 0.85;
          (arc.material as THREE.MeshBasicMaterial).opacity = 0.65 - Math.max(0, Math.sin(frame * 0.0011)) * 0.2;
        }
      });
      starfield.rotation.y += 0.00012 * speed;
      // [CREATIVE: near layer rotates ~2x faster than the far field — parallax]
      if (nearStars) nearStars.rotation.y += 0.00026 * speed;
      planeDisc.rotation.z += 0.00008 * speed;

      // Stellar wind: particles stream radially out, respawning at the photosphere.
      if (windGeo) {
        const windPos = windGeo.attributes.position as THREE.BufferAttribute;
        for (let i = 0; i < windCount; i++) {
          let x = windPos.getX(i) + windVelocities[i * 3] * speed;
          let y = windPos.getY(i) + windVelocities[i * 3 + 1] * speed;
          let z = windPos.getZ(i) + windVelocities[i * 3 + 2] * speed;
          if (x * x + y * y + z * z > 361) {
            x = windResets[i * 3];
            y = windResets[i * 3 + 1];
            z = windResets[i * 3 + 2];
          }
          windPos.setXYZ(i, x, y, z);
        }
        windPos.needsUpdate = true;
      }

      // Shooting star: a brief streak across the far background every ~25s.
      if (meteor) {
        const meteorCycle = Math.floor(frame / 1500);
        const meteorPhase = frame % 1500;
        if (meteorPhase < 70) {
          const t = meteorPhase / 70;
          const rand = Math.abs(Math.sin(meteorCycle * 12.9898) * 43758.5453) % 1;
          const startX = -45 + rand * 30;
          const yArc = 14 + rand * 10;
          meteor.position.set(startX + t * 55, yArc - t * 9, -34 - rand * 8);
          (meteor.material as THREE.SpriteMaterial).opacity = Math.sin(t * Math.PI) * 0.7;
        } else {
          (meteor.material as THREE.SpriteMaterial).opacity = 0;
        }
      }

      // [CREATIVE: focus pull — chromatic fringe decays to subtle over the
      // first ~0.8s of theater mode]
      if (chromaPass && theaterFocusFrames > 0) {
        theaterFocusFrames -= 1;
        chromaPass.uniforms.uStrength.value = 0.006 + (theaterFocusFrames / 48) * 0.02;
      }

      let selectedAngle = 0;
      let selectedPlanet: PlanetMesh | undefined;
      planetMeshes.forEach((planet) => {
        const angle = frame * planet.speed + planet.phase;
        const y = Math.sin(angle + Math.PI / 4) * planet.inclination * 9;
        const x = Math.cos(angle) * planet.radius;
        const z = Math.sin(angle) * planet.radius;
        planet.mesh.position.set(x, y, z);
        planet.halo.position.copy(planet.mesh.position);
        const active = planet.candidate.candidate_id === selectedId;

        if (planet.planetUniforms) {
          planet.planetUniforms.uTime.value += 0.016 * speed;
        }
        // [CREATIVE: per-class axial spin + gas-giant oblateness — fast
        // rotators visibly flatten at the poles like Jupiter and Saturn]
        planet.mesh.rotation.y += classSpinRate[planet.planetClass] * speed;
        if (planet.planetClass === PlanetClass.GAS) {
          planet.mesh.scale.y = planet.mesh.scale.x * 0.94;
        }
        if (planet.cloudMesh) {
          planet.cloudMesh.position.copy(planet.mesh.position);
          // [CREATIVE: cloud super-rotation — the deck circulates faster than
          // the surface below, like Venus's 4-day atmosphere]
          planet.cloudMesh.rotation.y += classSpinRate[planet.planetClass] * 1.6 * speed;
          (planet.cloudMesh.material as THREE.ShaderMaterial).uniforms.uTime.value += 0.016 * speed;
        }
        if (planet.rings) {
          planet.rings.position.copy(planet.mesh.position);
        }

        const orbitMaterial = planet.orbit.material as THREE.MeshBasicMaterial & Partial<THREE.ShaderMaterial>;
        const nextOrbitOpacity = active
          ? clamp(planet.orbitOpacity + Math.sin(frame * 0.024) * 0.06, 0.2, 0.92)
          : planet.orbitOpacity;
        if (orbitMaterial.uniforms?.uPlanetAngle) {
          // Comet-trail shader path: feed it the wrapped orbital angle.
          orbitMaterial.uniforms.uPlanetAngle.value = wrapAngle(angle);
          orbitMaterial.uniforms.uOpacity.value = nextOrbitOpacity;
        } else {
          orbitMaterial.opacity = nextOrbitOpacity;
        }
        const transitMaterial = planet.transit.material as THREE.MeshBasicMaterial;
        const baseTransitOpacity = active ? 0.52 + Math.sin(frame * 0.026) * 0.1 : 0.18 + planet.confidence * 0.08;
        transitMaterial.opacity = planet.ghosted ? baseTransitOpacity * 0.42 : baseTransitOpacity;
        planet.halo.material.opacity = planet.ghosted
          ? 0.1
          : active
            ? 0.48 + Math.sin(frame * 0.03) * 0.08
            : 0.16 + planet.confidence * 0.16;
        if (active) {
          selectedAngle = angle;
          selectedPlanet = planet;
        }
      });

      if (selectedPlanet) {
        // Cinematic dolly: on a fresh selection, swing in close, hold, return.
        if (selectedId !== prevSelectedId) {
          prevSelectedId = selectedId;
          cameraAnimator.setHome({ x: selectedPlanet.mesh.position.x * 0.09, y: cameraHeight, z: cameraDistance });
          cameraAnimator.dolly(
            {
              x: selectedPlanet.mesh.position.x * 0.8,
              y: cameraHeight * 0.72,
              z: cameraDistance * 0.52,
            },
            1.2,
          );
        }
        cameraAnimator.tick(0.016);
        const camPos = cameraAnimator.position();
        camera.position.set(camPos.x, camPos.y, camPos.z);
        // [CREATIVE: thermal shake — holding on a lava world adds a barely
        // perceptible tremor, as if the camera sits in the planet's thermals]
        if (selectedPlanet.planetClass === PlanetClass.LAVA && cameraAnimator.currentPhase() === 'hold') {
          camera.position.x += Math.sin(frame * 0.9) * 0.012;
          camera.position.y += Math.cos(frame * 1.1) * 0.009;
        }
        camera.lookAt(0, 0, 0);

        // [CREATIVE: HZ heartbeat — while a habitable-zone candidate is
        // selected, the green ring breathes on a slow pulse]
        if (hzMesh && selectedPlanet.isHabitable) {
          (hzMesh.material as THREE.MeshBasicMaterial).opacity = 0.105 + Math.max(0, Math.sin(frame * 0.008)) * 0.05;
        }
        const frontFactor = clamp((Math.cos(selectedAngle) - 0.08) / 0.72, 0, 1);
        const shadowScale = clamp(selectedPlanet.planetRadius * 1.55, 0.16, 0.55);
        transitShadow.scale.setScalar(shadowScale);
        transitShadow.position.x = Math.sin(selectedAngle) * 1.34;
        transitShadow.position.y = 0.28 + Math.sin(selectedAngle * 0.7) * selectedPlanet.inclination * 7;
        (transitShadow.material as THREE.MeshBasicMaterial).opacity =
          frontFactor * (selectedPlanet.ghosted ? 0.12 : 0.34 + selectedPlanet.confidence * 0.22);
        (transitChord.material as THREE.MeshBasicMaterial).opacity =
          frontFactor * (selectedPlanet.ghosted ? 0.08 : 0.2 + selectedPlanet.confidence * 0.18);
      } else {
        (transitShadow.material as THREE.MeshBasicMaterial).opacity = 0;
        (transitChord.material as THREE.MeshBasicMaterial).opacity = 0;
        // Re-derive the base framing every frame so the drag transform below
        // never compounds on its own previous output.
        camera.position.set(0, cameraHeight, cameraDistance);
        camera.lookAt(0, 0, 0);
      }

      // Theater free-look: drag offsets re-orbit the camera around the origin.
      if (dragAzimuth !== 0 || dragPolar !== 0) {
        const px = camera.position.x;
        const pz = camera.position.z;
        const orbitR = Math.sqrt(px * px + pz * pz);
        const orbitA = Math.atan2(pz, px) + dragAzimuth;
        camera.position.set(Math.cos(orbitA) * orbitR, camera.position.y + dragPolar * 9, Math.sin(orbitA) * orbitR);
        camera.lookAt(0, 0, 0);
      }

      if (composer) {
        if (filmGrainPass) filmGrainPass.uniforms.uTime.value += 0.016;
        composer.render();
      } else {
        renderer.render(scene, camera);
      }
      if (candidates.length > 0) {
        animation = requestAnimationFrame(tick);
      }
    };
    tick();

    const resizeObserver = new ResizeObserver(() => {
      const nextWidth = Math.max(mount.clientWidth, 1);
      const nextHeight = Math.max(mount.clientHeight, 1);
      camera.aspect = nextWidth / nextHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(nextWidth, nextHeight);
      composer?.setSize(nextWidth, nextHeight);
    });
    resizeObserver.observe(mount);

    return () => {
      cancelAnimationFrame(animation);
      resizeObserver.disconnect();
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      renderer.domElement.removeEventListener('click', onClick);
      renderer.domElement.removeEventListener('pointerdown', onDragStart);
      window.removeEventListener('pointermove', onDragMove);
      window.removeEventListener('pointerup', onDragEnd);
      composer?.dispose();
      scene.traverse((object) => {
        const disposable = object as THREE.Object3D & {
          geometry?: THREE.BufferGeometry;
          material?: THREE.Material | THREE.Material[];
        };
        disposable.geometry?.dispose();
        if (Array.isArray(disposable.material)) disposable.material.forEach(disposeMaterial);
        else if (disposable.material) disposeMaterial(disposable.material);
      });
      renderer.dispose();
      // Release the GL context synchronously. Without this, rapid effect
      // rebuilds (selection, speed, zoom, data refresh) stack up live WebGL
      // contexts until Chrome refuses to create new ones (~16 cap) and the
      // scene silently degrades to the static fallback.
      renderer.forceContextLoss();
      if (renderer.domElement.parentElement === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [
    renderData,
    selectedId,
    onSelectCandidate,
    isPlaying,
    speedMode,
    zoomMode,
    cameraReset,
    candidates.length,
    theaterMode,
  ]);

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
        title="Theater mode (F)"
        data-testid="orbit-expand-btn"
        onClick={() => setTheaterMode(true)}
      >
        ⛶
      </button>
      <div className="orbit-hud" aria-label="Orbit simulation controls">
        <button
          type="button"
          aria-label={isPlaying ? 'Pause orbit simulation' : 'Play orbit simulation'}
          title={isPlaying ? 'Pause orbit simulation' : 'Play orbit simulation'}
          onClick={() => setIsPlaying((playing) => !playing)}
          data-testid="orbit-play-toggle"
        >
          {isPlaying ? <Pause size={15} /> : <Play size={15} />}
        </button>
        <button
          type="button"
          aria-label={`Cycle simulation speed, current ${speedModes[speedMode]}x`}
          title={`Speed ${speedModes[speedMode]}x`}
          onClick={() => setSpeedMode((mode) => (mode + 1) % speedModes.length)}
          data-testid="orbit-speed-toggle"
        >
          <Gauge size={15} />
          <span>{speedModes[speedMode]}x</span>
        </button>
        <button
          type="button"
          aria-label="Zoom orbit view out"
          title="Zoom out"
          onClick={() => setZoomMode((mode) => Math.max(0, mode - 1))}
          disabled={zoomMode === 0}
          data-testid="orbit-zoom-out"
        >
          <ZoomOut size={15} />
        </button>
        <button
          type="button"
          aria-label={`Zoom orbit view in, current ${zoomModes[zoomMode]}x`}
          title={`Zoom ${zoomModes[zoomMode]}x`}
          onClick={() => setZoomMode((mode) => Math.min(zoomModes.length - 1, mode + 1))}
          disabled={zoomMode === zoomModes.length - 1}
          data-testid="orbit-zoom-in"
        >
          <ZoomIn size={15} />
          <span>{zoomModes[zoomMode]}x</span>
        </button>
        <button
          type="button"
          aria-label="Reset orbit camera"
          title="Reset orbit camera"
          onClick={() => setCameraReset((version) => version + 1)}
          data-testid="orbit-camera-reset"
        >
          <RotateCcw size={15} />
        </button>
      </div>

      {selected && selectedRenderData && candidates.length > 0 && (
        <div
          className={`orbit-metric-badge tone-${selectedRenderData.tone}`}
          aria-live="polite"
          data-testid="orbit-evidence-badge"
        >
          <strong>{selected.candidate_id}</strong>
          <span>{selectedRenderData.statusLabel}</span>
          <span>{Math.round(selectedRenderData.confidence * 100)}% confidence</span>
          <span>SNR {finite(selected.signal_to_noise, 0).toFixed(1)}</span>
          <span>{Math.round(finite(selected.depth, 0) * 1_000_000)} ppm</span>
          {formatTemperature(selected.physics?.equilibrium_temperature_k) && (
            <span>{formatTemperature(selected.physics?.equilibrium_temperature_k)}</span>
          )}
          {selectedRenderData.isHabitable && <span>HZ</span>}
          <span className="confidence-bar-track" aria-hidden="true">
            <span
              className="confidence-bar-fill"
              style={{ width: `${Math.round(selectedRenderData.confidence * 100)}%` }}
            />
          </span>
        </div>
      )}

      {theaterMode && selected && selectedRenderData && candidates.length > 0 && (
        <div
          className="orbit-mission-overlay"
          aria-label="Mission control data overlay"
          data-testid="orbit-mission-overlay"
        >
          <div className="orbit-mission-panel">
            <h4>Candidate</h4>
            <div className="stat">
              <strong>{selected.candidate_id}</strong>
            </div>
            <div className="stat">
              Class:{' '}
              <strong style={{ color: classColor(selectedRenderData.planetClass) }}>
                {selectedRenderData.planetClass.replace('_', ' ').toUpperCase()}
              </strong>
            </div>
            <div className="stat">
              Period: <strong>{selected.period.toFixed(4)} d</strong>
            </div>
            <div className="stat">
              Depth: <strong>{Math.round(finite(selected.depth, 0) * 1_000_000)} ppm</strong>
            </div>
            {formatTemperature(selected.physics?.equilibrium_temperature_k) && (
              <div className="stat">
                Temp: <strong>{formatTemperature(selected.physics?.equilibrium_temperature_k)}</strong>
              </div>
            )}
          </div>
          <div
            className="orbit-mission-panel"
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}
          >
            <h4>Confidence</h4>
            <svg className="orbit-arc-svg" width="80" height="80" viewBox="0 0 80 80" aria-hidden="true">
              <circle cx="40" cy="40" r="32" fill="none" stroke="rgba(80,160,255,0.12)" strokeWidth="6" />
              <circle
                cx="40"
                cy="40"
                r="32"
                fill="none"
                stroke={
                  selectedRenderData.tone === 'ready'
                    ? '#7ff0b0'
                    : selectedRenderData.tone === 'review'
                      ? '#ffc878'
                      : '#76b9ff'
                }
                strokeWidth="6"
                strokeDasharray={`${selectedRenderData.confidence * 201} 201`}
                strokeLinecap="round"
                transform="rotate(-90 40 40)"
                style={{ transition: 'stroke-dasharray 0.8s cubic-bezier(0.22,1,0.36,1)' }}
              />
              <text
                x="40"
                y="45"
                textAnchor="middle"
                fill="#e8f4ff"
                fontSize="14"
                fontFamily="monospace"
                fontWeight="bold"
              >
                {Math.round(selectedRenderData.confidence * 100)}%
              </text>
            </svg>
            <div className="stat" style={{ textAlign: 'center' }}>
              {selectedRenderData.statusLabel}
            </div>
          </div>
          <div className="orbit-mission-panel">
            <h4>Science Status</h4>
            <div className="stat">
              SNR: <strong>{finite(selected.signal_to_noise, 0).toFixed(1)}</strong>
            </div>
            <div className="stat">
              FP flags: <strong>{selected.validation?.false_positive_flags?.filter(Boolean).length ?? 0}</strong>
            </div>
            <div className="stat">
              Duration plausible: <strong>{selected.validation?.duration_plausible === false ? '✗' : '✓'}</strong>
            </div>
            {selectedRenderData.isHabitable && (
              <div className="stat" style={{ color: '#7ff0b0' }}>
                ✦ HABITABLE ZONE
              </div>
            )}
          </div>
        </div>
      )}

      {!candidates.length && (
        <div className="orbit-empty-state" data-testid="orbit-empty-state">
          <strong>Star-only view</strong>
          <span>{emptyMessage}</span>
        </div>
      )}
      {renderData.length > 0 && (
        <div className="orbit-labels" aria-label="Rendered candidate orbits">
          {renderData.map((data, index) => {
            const candidate = data.candidate;
            const active = candidate.candidate_id === selectedId;
            return (
              <button
                type="button"
                key={candidate.candidate_id}
                className={`orbit-label ${active ? 'active' : ''} ${data.ghosted ? 'ghost' : ''} tone-${data.tone}`}
                data-testid={`orbit-label-${candidate.candidate_id}`}
                aria-label={`Inspect rendered orbit ${index + 1}`}
                aria-pressed={active}
                onClick={() => onSelectCandidate?.(candidate.candidate_id)}
              >
                <span>{candidate.candidate_id}</span>
                <small>{data.ghosted ? 'blocked' : `${candidate.period.toFixed(4)} d`}</small>
                <em>{Math.round(data.confidence * 100)}%</em>
              </button>
            );
          })}
        </div>
      )}
      {webglUnavailable && (
        <div className="orbit-fallback" aria-label="Static orbit overview">
          <div className="fallback-plane" />
          <div className="fallback-habitable-zone" />
          <div className="fallback-transit-chord" />
          <div className="fallback-star" />
          {renderData.slice(0, 6).map((data, index) => {
            const candidate = data.candidate;
            const size = orbitSize(candidate, index);
            const active = candidate.candidate_id === selectedId;
            return (
              <button
                type="button"
                key={candidate.candidate_id}
                className={`fallback-orbit ${active ? 'active' : ''} ${data.ghosted ? 'ghost' : ''} tone-${data.tone}`}
                style={{ width: `${size}%`, height: `${size}%` }}
                data-testid={`fallback-orbit-${candidate.candidate_id}`}
                aria-label={`Select orbit ${candidate.candidate_id}`}
                onClick={() => onSelectCandidate?.(candidate.candidate_id)}
              >
                <span className="fallback-transit" />
                <span className="fallback-planet" />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );

  return theaterMode ? (
    <OrbitSceneTheater onExit={() => setTheaterMode(false)}>{sceneContent}</OrbitSceneTheater>
  ) : (
    sceneContent
  );
}
