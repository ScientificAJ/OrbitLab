import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import type { Candidate } from '../lib/api';

type Props = {
  candidates: Candidate[];
  selectedId?: string;
};

function canCreateWebGLContext() {
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
  if (!context) return false;
  const loseContext = context.getExtension('WEBGL_lose_context');
  loseContext?.loseContext();
  return true;
}

export function OrbitScene({ candidates, selectedId }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [webglUnavailable, setWebglUnavailable] = useState(false);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    setWebglUnavailable(false);
    if (!canCreateWebGLContext()) {
      setWebglUnavailable(true);
      return;
    }

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x071016);
    const width = Math.max(mount.clientWidth, 1);
    const height = Math.max(mount.clientHeight, 1);
    const camera = new THREE.PerspectiveCamera(46, width / height, 0.1, 1000);
    camera.position.set(0, 16, 26);
    camera.lookAt(0, 0, 0);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch (error) {
      setWebglUnavailable(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    mount.appendChild(renderer.domElement);

    const light = new THREE.PointLight(0xffffff, 3, 80);
    scene.add(light);
    scene.add(new THREE.AmbientLight(0x86a8b8, 0.8));

    const star = new THREE.Mesh(
      new THREE.SphereGeometry(1.7, 48, 48),
      new THREE.MeshStandardMaterial({ color: 0xffd17a, emissive: 0xffa629, emissiveIntensity: 1.2 })
    );
    scene.add(star);

    const planetMeshes: Array<{ mesh: THREE.Mesh; radius: number; speed: number; phase: number }> = [];
    candidates.forEach((candidate, index) => {
      const radius = 4 + Math.log1p(candidate.period) * 2.4 + index * 0.8;
      const orbit = new THREE.Mesh(
        new THREE.TorusGeometry(radius, 0.012, 8, 160),
        new THREE.MeshBasicMaterial({ color: candidate.candidate_id === selectedId ? 0x76e4f7 : 0x315765 })
      );
      orbit.rotation.x = Math.PI / 2;
      scene.add(orbit);

      const planet = new THREE.Mesh(
        new THREE.SphereGeometry(candidate.candidate_id === selectedId ? 0.36 : 0.25, 32, 32),
        new THREE.MeshStandardMaterial({ color: candidate.candidate_id === selectedId ? 0x8ee7ff : 0xb6ccd2 })
      );
      scene.add(planet);
      planetMeshes.push({
        mesh: planet,
        radius,
        speed: Math.max(0.001, 0.03 / candidate.period),
        phase: candidate.epoch % Math.PI
      });
    });

    const grid = new THREE.GridHelper(36, 36, 0x27424b, 0x12252d);
    scene.add(grid);

    let frame = 0;
    let animation = 0;
    const tick = () => {
      frame += 1;
      star.rotation.y += 0.003;
      planetMeshes.forEach((planet) => {
        const angle = frame * planet.speed + planet.phase;
        planet.mesh.position.set(Math.cos(angle) * planet.radius, 0, Math.sin(angle) * planet.radius);
      });
      renderer.render(scene, camera);
      animation = requestAnimationFrame(tick);
    };
    tick();

    const resizeObserver = new ResizeObserver(() => {
      if (!mount) return;
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
      scene.traverse((object: any) => {
        if (object.geometry) {
          object.geometry.dispose();
        }
        if (object.material) {
          if (Array.isArray(object.material)) {
            object.material.forEach((m: any) => m.dispose());
          } else {
            object.material.dispose();
          }
        }
      });
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [candidates, selectedId]);

  return (
    <div className="orbit-scene" ref={mountRef}>
      {webglUnavailable && (
        <div className="orbit-fallback" aria-label="Static orbit overview">
          <div className="fallback-star" />
          {candidates.slice(0, 6).map((candidate, index) => {
            const size = Math.min(92, 34 + Math.log1p(candidate.period) * 22 + index * 8);
            const active = candidate.candidate_id === selectedId;
            return (
              <div
                key={candidate.candidate_id}
                className={`fallback-orbit ${active ? 'active' : ''}`}
                style={{ width: `${size}%`, height: `${size}%` }}
              >
                <span className="fallback-planet" />
              </div>
            );
          })}
          {!candidates.length && <span className="fallback-empty">Awaiting candidate orbits</span>}
        </div>
      )}
    </div>
  );
}
