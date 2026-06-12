/**
 * Cinematic camera dolly controller for OrbitScene.
 *
 * Three-phase arc on planet selection: a cubic-bezier eased dolly-in toward
 * the planet, a hold beat so the viewer can take it in, then a gentler
 * return toward the (possibly updated) home framing. Pure math, no Three.js
 * dependency, so it is unit-testable without a renderer.
 */

type Vec3 = { x: number; y: number; z: number };

function cubicBezier(t: number, p0: number, p1: number, p2: number, p3: number): number {
  const u = 1 - t;
  return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3;
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
    this.target = { ...closeupPos };
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
      if (t >= 1) {
        this.phase = 'hold';
        this.holdElapsed = 0;
      }
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
      if (t >= 1) {
        this.current = { ...this.home };
        this.phase = 'idle';
      }
    }
  }

  isAnimating() {
    return this.phase !== 'idle';
  }

  /** Current phase, exposed so callers can layer effects (e.g. hold-phase shake). */
  currentPhase() {
    return this.phase;
  }

  position() {
    return { ...this.current };
  }

  setHome(pos: Vec3) {
    this.home = { ...pos };
  }
}
