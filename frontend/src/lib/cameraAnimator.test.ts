import { describe, expect, it } from 'vitest';
import { CameraAnimator } from './cameraAnimator';

describe('CameraAnimator', () => {
  it('starts idle at the home position', () => {
    const ca = new CameraAnimator({ x: 0, y: 14, z: 24 });
    expect(ca.isAnimating()).toBe(false);
    expect(ca.position()).toEqual({ x: 0, y: 14, z: 24 });
  });

  it('becomes animating after dolly()', () => {
    const ca = new CameraAnimator({ x: 0, y: 14, z: 24 });
    ca.dolly({ x: 5, y: 6, z: 8 }, 1.2);
    expect(ca.isAnimating()).toBe(true);
    expect(ca.currentPhase()).toBe('dolly-in');
  });

  it('passes through hold then return then finishes idle at home', () => {
    const ca = new CameraAnimator({ x: 0, y: 14, z: 24 });
    ca.dolly({ x: 5, y: 6, z: 8 }, 0.1);
    ca.tick(0.12); // completes dolly-in
    expect(ca.currentPhase()).toBe('hold');
    ca.tick(1.6); // exceeds 1.5s hold
    expect(ca.currentPhase()).toBe('return');
    ca.tick(0.9); // exceeds 0.8s return
    expect(ca.isAnimating()).toBe(false);
    expect(ca.position()).toEqual({ x: 0, y: 14, z: 24 });
  });

  it('returns interpolated position during animation', () => {
    const ca = new CameraAnimator({ x: 0, y: 0, z: 0 });
    ca.dolly({ x: 10, y: 0, z: 0 }, 1.0);
    ca.tick(0.5);
    const pos = ca.position();
    expect(pos.x).toBeGreaterThan(0);
    expect(pos.x).toBeLessThan(10);
  });

  it('returns toward an updated home set mid-flight', () => {
    const ca = new CameraAnimator({ x: 0, y: 14, z: 24 });
    ca.dolly({ x: 5, y: 6, z: 8 }, 0.1);
    ca.setHome({ x: 1, y: 14, z: 24 });
    ca.tick(0.12);
    ca.tick(1.6);
    ca.tick(0.9);
    expect(ca.position()).toEqual({ x: 1, y: 14, z: 24 });
  });

  it('restarts cleanly when dolly is called during an active animation', () => {
    const ca = new CameraAnimator({ x: 0, y: 0, z: 0 });
    ca.dolly({ x: 10, y: 0, z: 0 }, 1.0);
    ca.tick(0.5);
    const mid = ca.position().x;
    ca.dolly({ x: -10, y: 0, z: 0 }, 1.0);
    expect(ca.currentPhase()).toBe('dolly-in');
    ca.tick(0.5);
    // Now heading toward -10 from the mid point, so x must have decreased.
    expect(ca.position().x).toBeLessThan(mid);
  });

  it('tick is a no-op while idle', () => {
    const ca = new CameraAnimator({ x: 3, y: 3, z: 3 });
    ca.tick(5);
    expect(ca.position()).toEqual({ x: 3, y: 3, z: 3 });
  });
});
