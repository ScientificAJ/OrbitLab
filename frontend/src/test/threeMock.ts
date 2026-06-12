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
  clone() {
    return new Vector3(this.x, this.y, this.z);
  }
  add(v: Vector3) {
    this.x += v.x;
    this.y += v.y;
    this.z += v.z;
    return this;
  }
  sub(v: Vector3) {
    this.x -= v.x;
    this.y -= v.y;
    this.z -= v.z;
    return this;
  }
  multiplyScalar(s: number) {
    this.x *= s;
    this.y *= s;
    this.z *= s;
    return this;
  }
  normalize() {
    const l = this.length() || 1;
    return this.multiplyScalar(1 / l);
  }
  length() {
    return Math.sqrt(this.x * this.x + this.y * this.y + this.z * this.z);
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
  r: number;
  g: number;
  b: number;
  constructor(value = 0xffffff) {
    this.value = value;
    // Expose r/g/b channels so shader-uniform color plumbing can read them.
    this.r = ((value >> 16) & 0xff) / 255;
    this.g = ((value >> 8) & 0xff) / 255;
    this.b = (value & 0xff) / 255;
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

class BufferAttribute {
  needsUpdate = false;
  constructor(
    public array: number[] | Float32Array,
    public itemSize: number,
  ) {}
  get count() {
    return Math.floor(this.array.length / this.itemSize);
  }
  getX(i: number) {
    return this.array[i * this.itemSize] ?? 0;
  }
  getY(i: number) {
    return this.array[i * this.itemSize + 1] ?? 0;
  }
  getZ(i: number) {
    return this.array[i * this.itemSize + 2] ?? 0;
  }
  setXYZ(i: number, x: number, y: number, z: number) {
    const arr = this.array as Float32Array;
    arr[i * this.itemSize] = x;
    arr[i * this.itemSize + 1] = y;
    arr[i * this.itemSize + 2] = z;
    return this;
  }
}

class BufferGeometry {
  attributes: Record<string, BufferAttribute> = {};
  dispose = vi.fn();
  setAttribute(name: string, attribute: BufferAttribute) {
    this.attributes[name] = attribute;
    return this;
  }
}

// Parameterised geometries the shader paths walk vertex-by-vertex: expose a
// small deterministic position attribute so angle/alpha annotation loops run.
function fakePositionAttribute(count = 16) {
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    const angle = (i / count) * Math.PI * 2;
    positions[i * 3] = Math.cos(angle);
    positions[i * 3 + 1] = Math.sin(angle);
    positions[i * 3 + 2] = 0;
  }
  return new BufferAttribute(positions, 3);
}

class AnnotatableGeometry extends BufferGeometry {
  constructor() {
    super();
    this.attributes.position = fakePositionAttribute();
  }
}

function geometry() {
  return { dispose: vi.fn() };
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

// Geometry constructors return disposables. Torus/Ring additionally carry a
// deterministic position attribute because the trail/ring shader builders
// annotate their vertices (angle attribute, per-vertex alpha).
const SphereGeometry = vi.fn(geometry);
const PlaneGeometry = vi.fn(geometry);
const CircleGeometry = vi.fn(geometry);
class RingGeometry extends AnnotatableGeometry {}
class TorusGeometry extends AnnotatableGeometry {}
class TubeGeometry extends AnnotatableGeometry {}

class CatmullRomCurve3 {
  constructor(public points: Vector3[]) {}
  getPoints(n: number) {
    return Array.from({ length: n + 1 }, () => new Vector3());
  }
}
class QuadraticBezierCurve3 {
  constructor(
    public v0: Vector3,
    public v1: Vector3,
    public v2: Vector3,
  ) {}
  getPoints(n: number) {
    return Array.from({ length: n + 1 }, () => new Vector3());
  }
}

class Group extends Object3D {}

class ShaderMaterial {
  uniforms: Record<string, { value: unknown }> = {};
  vertexShader = '';
  fragmentShader = '';
  transparent = false;
  depthWrite = true;
  side = 0;
  blending = 0;
  opacity = 1;
  constructor(params: Record<string, unknown> = {}) {
    Object.assign(this, params);
  }
  dispose = vi.fn();
}

class Matrix4 {
  elements = new Float32Array(16);
  identity() {
    return this;
  }
  setPosition(_x: number, _y: number, _z: number) {
    return this;
  }
  makeRotationY(_r: number) {
    return this;
  }
  compose(_p: unknown, _q: unknown, _s: unknown) {
    return this;
  }
}

class Quaternion {
  x = 0;
  y = 0;
  z = 0;
  w = 1;
  setFromAxisAngle(_axis: unknown, _angle: number) {
    return this;
  }
}

class InstancedMesh extends Object3D {
  count: number;
  instanceMatrix = { needsUpdate: false };
  geometry: { dispose: () => void };
  material: unknown;
  constructor(geo: { dispose: () => void } | undefined, mat: unknown, count: number) {
    super();
    this.geometry = geo ?? { dispose: vi.fn() };
    this.material = mat;
    this.count = count;
  }
  setMatrixAt(_i: number, _m: unknown) {}
  dispose = vi.fn();
}

// ---------------------------------------------------------------------------
// Post-processing stubs. vi.mock('three') does NOT intercept the
// 'three/examples/jsm/postprocessing/*' module specifiers, so test files mock
// those paths explicitly and point them at these classes.
// ---------------------------------------------------------------------------
class EffectComposer {
  renderer: unknown;
  passes: unknown[] = [];
  constructor(renderer: unknown) {
    this.renderer = renderer;
  }
  addPass(pass: unknown) {
    this.passes.push(pass);
  }
  render = vi.fn();
  setSize = vi.fn();
  dispose = vi.fn();
}
class RenderPass {
  constructor(
    public scene: unknown,
    public camera: unknown,
  ) {}
}
class UnrealBloomPass {
  threshold = 0;
  strength = 0;
  radius = 0;
  constructor(_resolution: unknown, strength: number, radius: number, threshold: number) {
    this.strength = strength;
    this.radius = radius;
    this.threshold = threshold;
  }
}
class OutputPass {}
class ShaderPass {
  uniforms: Record<string, { value: unknown }> = {};
  constructor(shader: { uniforms?: Record<string, { value: unknown }> } = {}) {
    // Clone uniform slots like the real ShaderPass so per-pass tweaks work.
    Object.entries(shader.uniforms ?? {}).forEach(([key, uniform]) => {
      this.uniforms[key] = { value: uniform.value };
    });
  }
}

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
  TubeGeometry,
  CatmullRomCurve3,
  QuadraticBezierCurve3,
  Group,
  ShaderMaterial,
  Matrix4,
  Quaternion,
  InstancedMesh,
  SRGBColorSpace: 'srgb',
  RepeatWrapping: 1000,
  AdditiveBlending: 2,
  NormalBlending: 1,
  BackSide: 1,
  DoubleSide: 2,
  FrontSide: 0,
  __WebGLRenderer: WebGLRenderer,
};

// Exported separately so test files can vi.mock the
// 'three/examples/jsm/postprocessing/*' module paths with these stubs.
export const postprocessingMock = {
  EffectComposer,
  RenderPass,
  UnrealBloomPass,
  OutputPass,
  ShaderPass,
};
