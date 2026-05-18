import { Pause, Play, RotateCcw, Gauge } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import type { Candidate } from '../lib/api';

type Props = {
  candidates: Candidate[];
  selectedId?: string;
  emptyMessage?: string;
  onSelectCandidate?: (candidateId: string) => void;
};

type CandidateRenderData = {
  candidate: Candidate;
  radius: number;
  planetRadius: number;
  orbitOpacity: number;
  speed: number;
  phase: number;
  inclination: number;
  hue: THREE.Color;
  hasPhysics: boolean;
};

type PlanetMesh = CandidateRenderData & {
  mesh: THREE.Mesh;
  orbit: THREE.Mesh;
  transit: THREE.Mesh;
  label: string;
};

const speedModes = [0.65, 1, 1.8];

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function finite(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function orbitRadius(candidate: Candidate, index: number) {
  const semiMajorAxis = finite(candidate.physics?.semi_major_axis_au, 0);
  if (semiMajorAxis > 0) return clamp(4.3 + Math.log1p(semiMajorAxis * 90) * 3.4 + index * 0.45, 4.6, 15.5);
  return clamp(4.4 + Math.log1p(Math.max(candidate.period, 0)) * 2.85 + index * 0.6, 4.6, 15.5);
}

function orbitSize(candidate: Candidate, index: number) {
  return clamp(34 + orbitRadius(candidate, index) * 4.1, 38, 94);
}

function planetScale(candidate: Candidate, active: boolean) {
  const radiusRatio = finite(candidate.physics?.radius_ratio, 0);
  const depthRadius = Math.sqrt(Math.max(finite(candidate.depth, 0), 0));
  const radiusEarth = finite(candidate.physics?.planet_radius_earth, 0);
  const signal = radiusRatio || depthRadius || (radiusEarth > 0 ? radiusEarth / 18 : 0.02);
  return clamp(0.18 + signal * 5.2 + (active ? 0.08 : 0), 0.22, active ? 0.62 : 0.48);
}

function candidateColor(candidate: Candidate, active: boolean) {
  if (active) return new THREE.Color(0x93ecff);
  if (candidate.physics?.is_in_habitable_zone) return new THREE.Color(0x99f2bc);
  if (candidate.validation?.duration_plausible === false) return new THREE.Color(0xffc28a);
  return new THREE.Color(0x76b9ff);
}

function candidateRenderData(candidates: Candidate[], selectedId?: string): CandidateRenderData[] {
  return candidates.slice(0, 8).map((candidate, index) => {
    const active = candidate.candidate_id === selectedId;
    const snr = clamp(finite(candidate.signal_to_noise, 6), 4, 35);
    return {
      candidate,
      radius: orbitRadius(candidate, index),
      planetRadius: planetScale(candidate, active),
      orbitOpacity: clamp(0.22 + snr / 58 + (active ? 0.28 : 0), 0.24, 0.92),
      speed: clamp(0.022 / Math.sqrt(Math.max(candidate.period, 0.15)), 0.003, 0.045),
      phase: (finite(candidate.epoch, index) * 2.4 + index * 0.72) % (Math.PI * 2),
      inclination: (index - (candidates.length - 1) / 2) * 0.035,
      hue: candidateColor(candidate, active),
      hasPhysics: Boolean(candidate.physics && Object.keys(candidate.physics).length),
    };
  });
}

function makeDiscTexture(inner: string, outer: string) {
  const canvas = document.createElement('canvas');
  canvas.width = 96;
  canvas.height = 96;
  const context = canvas.getContext('2d');
  if (!context) return null;
  const gradient = context.createRadialGradient(48, 48, 2, 48, 48, 48);
  gradient.addColorStop(0, inner);
  gradient.addColorStop(0.35, inner);
  gradient.addColorStop(1, outer);
  context.fillStyle = gradient;
  context.fillRect(0, 0, 96, 96);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeStarMaterial() {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  if (!context) {
    return new THREE.MeshStandardMaterial({ color: 0xffd27d, emissive: 0xff8a22, emissiveIntensity: 1.25 });
  }

  const image = context.createImageData(canvas.width, canvas.height);
  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      const index = (y * canvas.width + x) * 4;
      const band = Math.sin(x * 0.18) * 12 + Math.cos((x + y) * 0.055) * 18;
      const grain = ((x * 17 + y * 31 + ((x * y) % 29)) % 37) - 18;
      image.data[index] = clamp(244 + band + grain, 0, 255);
      image.data[index + 1] = clamp(153 + band * 0.45 + grain, 0, 255);
      image.data[index + 2] = clamp(55 + band * 0.18, 0, 255);
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
    color: 0xffd19a,
    emissive: 0xff8f23,
    emissiveIntensity: 1.35,
    roughness: 0.72,
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
  const [cameraReset, setCameraReset] = useState(0);
  const renderData = useMemo(() => candidateRenderData(candidates, selectedId), [candidates, selectedId]);
  const selected = candidates.find((candidate) => candidate.candidate_id === selectedId) ?? candidates[0];

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    setWebglUnavailable(false);
    if (!canCreateWebGLContext()) {
      setWebglUnavailable(true);
      return;
    }

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x03080d);
    scene.fog = new THREE.FogExp2(0x03080d, 0.018);

    const width = Math.max(mount.clientWidth, 1);
    const height = Math.max(mount.clientHeight, 1);
    const camera = new THREE.PerspectiveCamera(43, width / height, 0.1, 1000);
    const resetCamera = () => {
      camera.position.set(0, 14.5, 24);
      camera.lookAt(0, 0, 0);
    };
    resetCamera();

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setWebglUnavailable(true);
      return;
    }
    const automatedBrowser = navigator.webdriver;
    renderer.setPixelRatio(automatedBrowser ? 1 : Math.min(window.devicePixelRatio, 1.6));
    renderer.setSize(width, height);
    renderer.domElement.dataset.testid = 'orbit-canvas';
    renderer.domElement.setAttribute('aria-label', 'Interactive orbit analysis visualization');
    renderer.domElement.setAttribute('role', 'img');
    mount.appendChild(renderer.domElement);

    const starTexture = makeStarMaterial();
    const star = new THREE.Mesh(
      new THREE.SphereGeometry(1.72, automatedBrowser ? 40 : 56, automatedBrowser ? 40 : 56),
      starTexture,
    );
    scene.add(star);

    const coronaTexture = makeDiscTexture('rgba(255, 220, 142, 0.52)', 'rgba(255, 160, 56, 0)');
    const corona = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: coronaTexture ?? undefined, color: 0xffb661, transparent: true, opacity: 0.88 }),
    );
    corona.scale.set(8.2, 8.2, 1);
    scene.add(corona);

    const rim = new THREE.Mesh(
      new THREE.SphereGeometry(1.9, 64, 64),
      new THREE.MeshBasicMaterial({ color: 0xffc46f, transparent: true, opacity: 0.18, side: THREE.BackSide }),
    );
    scene.add(rim);

    const primaryLight = new THREE.PointLight(0xffd08a, 4.5, 80);
    primaryLight.position.set(0, 0, 0);
    scene.add(primaryLight);
    scene.add(new THREE.AmbientLight(0x6c91a5, 0.5));
    const rimLight = new THREE.DirectionalLight(0x8ee7ff, 1.25);
    rimLight.position.set(-10, 12, 8);
    scene.add(rimLight);

    const planeGrid = new THREE.GridHelper(36, 36, 0x315968, 0x142833);
    const gridMaterial = planeGrid.material as THREE.Material | THREE.Material[];
    if (Array.isArray(gridMaterial)) {
      gridMaterial.forEach((material) => {
        material.transparent = true;
        material.opacity = 0.28;
      });
    } else {
      gridMaterial.transparent = true;
      gridMaterial.opacity = 0.28;
    }
    scene.add(planeGrid);

    const starCount = automatedBrowser ? 260 : 520;
    const starPositions = new Float32Array(starCount * 3);
    const starColors = new Float32Array(starCount * 3);
    for (let index = 0; index < starCount; index += 1) {
      const angle = index * 2.399963;
      const radius = 34 + ((index * 37) % 64);
      const heightOffset = ((index * 53) % 70) - 20;
      starPositions[index * 3] = Math.cos(angle) * radius;
      starPositions[index * 3 + 1] = heightOffset * 0.34;
      starPositions[index * 3 + 2] = Math.sin(angle) * radius;
      const brightness = 0.45 + ((index * 19) % 40) / 100;
      starColors[index * 3] = brightness * 0.72;
      starColors[index * 3 + 1] = brightness * 0.9;
      starColors[index * 3 + 2] = brightness;
    }
    const starfieldGeometry = new THREE.BufferGeometry();
    starfieldGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    starfieldGeometry.setAttribute('color', new THREE.BufferAttribute(starColors, 3));
    const starfield = new THREE.Points(
      starfieldGeometry,
      new THREE.PointsMaterial({ size: 0.09, vertexColors: true, transparent: true, opacity: 0.84 }),
    );
    scene.add(starfield);

    const planetMeshes: PlanetMesh[] = [];
    renderData.forEach((data) => {
      const active = data.candidate.candidate_id === selectedId;
      const orbitMaterial = new THREE.MeshBasicMaterial({
        color: data.hue,
        transparent: true,
        opacity: data.orbitOpacity,
      });
      const orbit = new THREE.Mesh(
        new THREE.TorusGeometry(data.radius, active ? 0.045 : 0.026, 8, automatedBrowser ? 112 : 176),
        orbitMaterial,
      );
      orbit.rotation.x = Math.PI / 2 + data.inclination;
      scene.add(orbit);

      if (active || data.candidate.physics?.is_in_habitable_zone) {
        const orbitGlow = new THREE.Mesh(
          new THREE.TorusGeometry(data.radius, active ? 0.1 : 0.06, 8, automatedBrowser ? 112 : 176),
          new THREE.MeshBasicMaterial({
            color: data.hue,
            transparent: true,
            opacity: active ? 0.2 : 0.1,
          }),
        );
        orbitGlow.rotation.copy(orbit.rotation);
        scene.add(orbitGlow);
      }

      const transit = new THREE.Mesh(
        new THREE.TorusGeometry(data.radius, 0.065, 8, 28, Math.PI * 0.19),
        new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: active ? 0.52 : 0.22 }),
      );
      transit.rotation.set(Math.PI / 2 + data.inclination, 0, -Math.PI * 0.08);
      scene.add(transit);

      const planet = new THREE.Mesh(
        new THREE.SphereGeometry(data.planetRadius, automatedBrowser ? 20 : 28, automatedBrowser ? 20 : 28),
        new THREE.MeshStandardMaterial({
          color: data.hue,
          emissive: data.hue,
          emissiveIntensity: active ? 0.42 : 0.14,
          metalness: 0.05,
          roughness: 0.48,
        }),
      );
      planet.name = data.candidate.candidate_id;
      planet.userData.candidateId = data.candidate.candidate_id;
      scene.add(planet);
      planetMeshes.push({ ...data, mesh: planet, orbit, transit, label: data.candidate.candidate_id });
    });

    const physicsCandidate = renderData.find((data) => data.candidate.physics?.habitable_zone_inner_au);
    if (physicsCandidate) {
      const inner = finite(physicsCandidate.candidate.physics?.habitable_zone_inner_au, 0.6);
      const outer = finite(physicsCandidate.candidate.physics?.habitable_zone_outer_au, inner + 0.4);
      const center = clamp(4.3 + Math.log1p(((inner + outer) / 2) * 90) * 3.4, 5.2, 16.8);
      const widthAu = clamp(Math.abs(outer - inner) * 7, 0.08, 0.36);
      const hz = new THREE.Mesh(
        new THREE.TorusGeometry(center, widthAu, 8, 192),
        new THREE.MeshBasicMaterial({ color: 0x83f4ad, transparent: true, opacity: 0.16 }),
      );
      hz.rotation.x = Math.PI / 2;
      scene.add(hz);
    }

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
        if (hovered) hovered.scale.setScalar(1.24);
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
      star.rotation.y += 0.0025 * speed;
      rim.rotation.y -= 0.0012 * speed;
      corona.material.rotation += 0.0008 * speed;
      starfield.rotation.y += 0.0001 * speed;

      planetMeshes.forEach((planet) => {
        const angle = frame * planet.speed + planet.phase;
        const y = Math.sin(angle + Math.PI / 4) * planet.inclination * 9;
        planet.mesh.position.set(Math.cos(angle) * planet.radius, y, Math.sin(angle) * planet.radius);
        const transitMaterial = planet.transit.material as THREE.MeshBasicMaterial;
        transitMaterial.opacity =
          planet.candidate.candidate_id === selectedId ? 0.42 + Math.sin(frame * 0.025) * 0.1 : 0.18;
      });

      const selectedPlanet = planetMeshes.find((planet) => planet.candidate.candidate_id === selectedId);
      if (selectedPlanet) {
        const desired = new THREE.Vector3(selectedPlanet.mesh.position.x * 0.08, 14.5, 24);
        camera.position.lerp(desired, 0.018);
        camera.lookAt(0, 0, 0);
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
        const mesh = object as THREE.Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(material)) material.forEach((item) => item.dispose());
        else material?.dispose();
      });
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [renderData, selectedId, onSelectCandidate, isPlaying, speedMode, cameraReset]);

  return (
    <div className="orbit-scene" ref={mountRef} data-testid="orbit-scene">
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
          aria-label="Reset orbit camera"
          title="Reset orbit camera"
          onClick={() => setCameraReset((version) => version + 1)}
          data-testid="orbit-camera-reset"
        >
          <RotateCcw size={15} />
        </button>
      </div>

      {selected && candidates.length > 0 && (
        <div className="orbit-metric-badge" aria-live="polite">
          <strong>{selected.candidate_id}</strong>
          <span>SNR {finite(selected.signal_to_noise, 0).toFixed(1)}</span>
          <span>{Math.round(finite(selected.depth, 0) * 1_000_000)} ppm</span>
          {selected.physics?.equilibrium_temperature_k && (
            <span>{Math.round(selected.physics.equilibrium_temperature_k)} K</span>
          )}
        </div>
      )}

      {!candidates.length && (
        <div className="orbit-empty-state" data-testid="orbit-empty-state">
          <strong>Star-only view</strong>
          <span>{emptyMessage}</span>
        </div>
      )}
      {candidates.length > 0 && (
        <div className="orbit-labels" aria-label="Rendered candidate orbits">
          {candidates.map((candidate, index) => {
            const active = candidate.candidate_id === selectedId;
            return (
              <button
                type="button"
                key={candidate.candidate_id}
                className={`orbit-label ${active ? 'active' : ''}`}
                data-testid={`orbit-label-${candidate.candidate_id}`}
                aria-label={`Inspect rendered orbit ${index + 1}`}
                aria-pressed={active}
                onClick={() => onSelectCandidate?.(candidate.candidate_id)}
              >
                <span>{candidate.candidate_id}</span>
                <small>{candidate.period.toFixed(4)} d</small>
              </button>
            );
          })}
        </div>
      )}
      {webglUnavailable && (
        <div className="orbit-fallback" aria-label="Static orbit overview">
          <div className="fallback-plane" />
          <div className="fallback-star" />
          {candidates.slice(0, 6).map((candidate, index) => {
            const size = orbitSize(candidate, index);
            const active = candidate.candidate_id === selectedId;
            return (
              <button
                type="button"
                key={candidate.candidate_id}
                className={`fallback-orbit ${active ? 'active' : ''}`}
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
