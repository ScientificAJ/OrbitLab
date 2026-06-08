/**
 * Faithful-enough mock of the subset of three.js that OrbitScene.tsx uses.
 *
 * The real library needs a GPU/WebGL context that jsdom cannot provide, so we
 * substitute lightweight stand-ins that expose every property and method the
 * component touches (positions, rotations, materials, geometry/material dispose,
 * raycasting, renderer lifecycle). This lets the full WebGL effect body — setup,
 * the animation tick, pointer/click handlers, resize, and teardown — execute and
 * be measured for coverage without a real renderer.
 */
import { vi } from 'vitest';

class Vector2 {
  x = 0;
  y = 0;
  set(x: number, y: number) {
    this.x = x;
    this.y = y;
    return this;
  }
}

class Vector3 {
  x = 0;
  y = 0;
  z = 0;
  constructor(x = 0, y = 0, z = 0) {
    this.x = x;
    this.y = y;
    this.z = z;
  }
  set(x: number, y: number, z: number) {
    this.x = x;
    this.y = y;
    this.z = z;
    return this;
  }
  copy(v: Vector3) {
    this.x = v.x;
    this.y = v.y;
    this.z = v.z;
    return this;
  }
  lerp(v: Vector3, alpha: number) {
    this.x += (v.x - this.x) * alpha;
    this.y += (v.y - this.y) * alpha;
    this.z += (v.z - this.z) * alpha;
    return this;
  }
  setScalar(s: number) {
    this.x = this.y = this.z = s;
    return this;
  }
}

class Euler {
  x = 0;
  y = 0;
  z = 0;
  set(x: number, y: number, z: number) {
    this.x = x;
    this.y = y;
    this.z = z;
    return this;
  }
  copy(e: Euler) {
    this.x = e.x;
    this.y = e.y;
    this.z = e.z;
    return this;
  }
}

class Color {
  value: number;
  constructor(value = 0xffffff) {
    this.value = value;
  }
}

class Object3D {
  position = new Vector3();
  rotation = new Euler();
  scale = new Vector3(1, 1, 1);
  name = '';
  userData: Record<string, unknown> = {};
  children: Object3D[] = [];
  parent: Object3D | null = null;
  add(child: Object3D) {
    this.children.push(child);
    child.parent = this;
    return this;
  }
  traverse(cb: (object: Object3D) => void) {
    cb(this);
    this.children.forEach((child) => child.traverse(cb));
  }
}

class Scene extends Object3D {
  fog: unknown = null;
}

class Mesh extends Object3D {
  geometry: { dispose: () => void };
  material: unknown;
  constructor(geometry?: { dispose: () => void }, material?: unknown) {
    super();
    this.geometry = geometry ?? { dispose: vi.fn() };
    this.material = material;
  }
}

class Points extends Object3D {
  geometry: { dispose: () => void };
  material: unknown;
  constructor(geometry?: { dispose: () => void }, material?: unknown) {
    super();
    this.geometry = geometry ?? { dispose: vi.fn() };
    this.material = material;
  }
}

class Sprite extends Object3D {
  material: { rotation: number; opacity: number; dispose: () => void };
  constructor(material?: { rotation?: number; opacity?: number }) {
    super();
    this.material = {
      rotation: 0,
      opacity: material?.opacity ?? 1,
      ...material,
      dispose: vi.fn(),
    } as { rotation: number; opacity: number; dispose: () => void };
  }
}

class PerspectiveCamera extends Object3D {
  aspect: number;
  constructor(_fov?: number, aspect = 1) {
    super();
    this.aspect = aspect;
  }
  lookAt() {}
  updateProjectionMatrix() {}
}

function disposableMaterial(props: Record<string, unknown> = {}) {
  return {
    opacity: 1,
    rotation: 0,
    transparent: false,
    map: null,
    ...props,
    dispose: vi.fn(),
  };
}

class MeshBasicMaterial {
  constructor(props: Record<string, unknown> = {}) {
    Object.assign(this, disposableMaterial(props));
  }
  dispose = vi.fn();
}
class MeshStandardMaterial {
  constructor(props: Record<string, unknown> = {}) {
    Object.assign(this, disposableMaterial(props));
  }
  dispose = vi.fn();
}
class SpriteMaterial {
  constructor(props: Record<string, unknown> = {}) {
    Object.assign(this, disposableMaterial(props));
  }
  dispose = vi.fn();
}
class PointsMaterial {
  constructor(props: Record<string, unknown> = {}) {
    Object.assign(this, disposableMaterial(props));
  }
  dispose = vi.fn();
}

class BufferGeometry {
  setAttribute = vi.fn();
  dispose = vi.fn();
}
function geometry() {
  return { dispose: vi.fn() };
}

class BufferAttribute {
  constructor(
    public array: ArrayLike<number>,
    public itemSize: number,
  ) {}
}

class GridHelper extends Object3D {
  // When arrayMaterial is true, expose material as an array to exercise the
  // Array.isArray branch in OrbitScene's grid-styling code.
  static arrayMaterial = false;
  material:
    | { transparent: boolean; opacity: number; dispose: () => void }
    | Array<{ transparent: boolean; opacity: number; dispose: () => void }>;
  constructor() {
    super();
    this.material = GridHelper.arrayMaterial
      ? [
          { transparent: false, opacity: 1, dispose: vi.fn() },
          { transparent: false, opacity: 1, dispose: vi.fn() },
        ]
      : { transparent: false, opacity: 1, dispose: vi.fn() };
  }
}

class Raycaster {
  intersections: Array<{ object: Object3D }> = [];
  setFromCamera = vi.fn();
  intersectObjects() {
    return this.intersections;
  }
}

class WebGLRenderer {
  domElement: HTMLCanvasElement;
  static shouldThrow = false;
  static instances: WebGLRenderer[] = [];
  constructor() {
    if (WebGLRenderer.shouldThrow) {
      throw new Error('forced renderer failure');
    }
    this.domElement = document.createElement('canvas');
    WebGLRenderer.instances.push(this);
  }
  setClearColor = vi.fn();
  setPixelRatio = vi.fn();
  setSize = vi.fn();
  render = vi.fn();
  dispose = vi.fn();
}

class CanvasTexture {
  colorSpace = '';
  wrapS = 0;
  wrapT = 0;
  dispose = vi.fn();
  constructor(public image?: unknown) {}
}

// Geometry constructors all return a disposable; OrbitScene only needs dispose().
const SphereGeometry = vi.fn(geometry);
const PlaneGeometry = vi.fn(geometry);
const CircleGeometry = vi.fn(geometry);
const RingGeometry = vi.fn(geometry);
const TorusGeometry = vi.fn(geometry);

class FogExp2 {
  constructor(
    public color: number,
    public density: number,
  ) {}
}
class PointLight extends Object3D {}
class AmbientLight extends Object3D {}
class DirectionalLight extends Object3D {}

export const threeMock = {
  Object3D,
  Scene,
  Mesh,
  Points,
  Sprite,
  PerspectiveCamera,
  WebGLRenderer,
  Raycaster,
  Vector2,
  Vector3,
  Color,
  Euler,
  BufferGeometry,
  BufferAttribute,
  GridHelper,
  CanvasTexture,
  FogExp2,
  PointLight,
  AmbientLight,
  DirectionalLight,
  MeshBasicMaterial,
  MeshStandardMaterial,
  SpriteMaterial,
  PointsMaterial,
  SphereGeometry,
  PlaneGeometry,
  CircleGeometry,
  RingGeometry,
  TorusGeometry,
  SRGBColorSpace: 'srgb',
  RepeatWrapping: 1000,
  AdditiveBlending: 2,
  BackSide: 1,
  DoubleSide: 2,
  __WebGLRenderer: WebGLRenderer,
};
