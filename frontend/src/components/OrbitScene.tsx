import { Pause, Play, RotateCcw, Gauge, ZoomIn, ZoomOut } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import type { Candidate } from '../lib/api';

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
};

type PlanetMesh = CandidateRenderData & {
  mesh: THREE.Mesh;
  halo: THREE.Sprite;
  orbit: THREE.Mesh;
  transit: THREE.Mesh;
  label: string;
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

    const star = new THREE.Mesh(
      new THREE.SphereGeometry(1.78, automatedBrowser ? 40 : 64, automatedBrowser ? 40 : 64),
      makeStarMaterial(),
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
      [innerRadius, outerRadius].forEach((radius) => {
        const boundary = new THREE.Mesh(
          new THREE.TorusGeometry(radius, 0.016, 8, automatedBrowser ? 96 : 160),
          new THREE.MeshBasicMaterial({ color: 0x9df5bd, transparent: true, opacity: 0.28 }),
        );
        boundary.rotation.x = Math.PI / 2;
        scene.add(boundary);
      });
    }

    const starCount = automatedBrowser ? 340 : 760;
    const starPositions = new Float32Array(starCount * 3);
    const starColors = new Float32Array(starCount * 3);
    for (let index = 0; index < starCount; index += 1) {
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

    const haloTexture = makeDiscTexture('rgba(147, 236, 255, 0.52)', 'rgba(147, 236, 255, 0)');
    const planetMeshes: PlanetMesh[] = [];
    renderData.forEach((data) => {
      const active = data.candidate.candidate_id === selectedId;
      const orbitMaterial = new THREE.MeshBasicMaterial({
        color: data.hue,
        transparent: true,
        opacity: data.orbitOpacity,
      });
      const orbit = new THREE.Mesh(
        new THREE.TorusGeometry(data.radius, data.orbitTube, 8, automatedBrowser ? 128 : 220),
        orbitMaterial,
      );
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

      const planet = new THREE.Mesh(
        new THREE.SphereGeometry(data.planetRadius, automatedBrowser ? 22 : 32, automatedBrowser ? 22 : 32),
        new THREE.MeshStandardMaterial({
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

      planetMeshes.push({ ...data, mesh: planet, halo, orbit, transit, label: data.candidate.candidate_id });
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

    let frame = 0;
    let animation = 0;
    const tick = () => {
      const speed = speedModes[speedMode] ?? 1;
      if (isPlaying) frame += speed;
      star.rotation.y += 0.0026 * speed;
      rim.rotation.y -= 0.0011 * speed;
      corona.material.rotation += 0.0008 * speed;
      starfield.rotation.y += 0.00012 * speed;
      planeDisc.rotation.z += 0.00008 * speed;

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
        const orbitMaterial = planet.orbit.material as THREE.MeshBasicMaterial;
        orbitMaterial.opacity = active
          ? clamp(planet.orbitOpacity + Math.sin(frame * 0.024) * 0.06, 0.2, 0.92)
          : planet.orbitOpacity;
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
        const desired = new THREE.Vector3(selectedPlanet.mesh.position.x * 0.09, cameraHeight, cameraDistance);
        camera.position.lerp(desired, 0.02);
        camera.lookAt(0, 0, 0);
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
      }

      renderer.render(scene, camera);
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
    });
    resizeObserver.observe(mount);

    return () => {
      cancelAnimationFrame(animation);
      resizeObserver.disconnect();
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      renderer.domElement.removeEventListener('click', onClick);
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
      if (renderer.domElement.parentElement === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [renderData, selectedId, onSelectCandidate, isPlaying, speedMode, zoomMode, cameraReset, candidates.length]);

  return (
    <div className={`orbit-scene ${selectionPulse ? 'selection-pulse' : ''}`} ref={mountRef} data-testid="orbit-scene">
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
}
