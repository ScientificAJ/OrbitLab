import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// Tear down the rendered tree between tests so each test starts clean.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// jsdom does not implement ResizeObserver; OrbitScene + Plotly rely on it.
// Track live instances so tests can fire the observed callback on demand.
export const resizeObserverInstances: ResizeObserverStub[] = [];
class ResizeObserverStub {
  callback: ResizeObserverCallback;
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    resizeObserverInstances.push(this);
  }
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  trigger(): void {
    this.callback([], this as unknown as ResizeObserver);
  }
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub);

// jsdom has no matchMedia; some responsive checks reference it.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

// requestAnimationFrame is a no-op that just hands back a numeric id. OrbitScene
// calls tick() once directly (which runs the full render-loop body for coverage)
// and then self-reschedules via rAF; invoking the callback here would recurse
// forever and hang the worker, so we deliberately do not call it back.
let rafId = 0;
window.requestAnimationFrame = (() => {
  rafId += 1;
  return rafId;
}) as typeof window.requestAnimationFrame;
window.cancelAnimationFrame = (() => {}) as typeof window.cancelAnimationFrame;
