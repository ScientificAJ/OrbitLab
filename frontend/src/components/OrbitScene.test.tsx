import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { threeMock } from '../test/threeMock';
import type { Candidate } from '../lib/api';

vi.mock('three', () => threeMock);

import { OrbitScene } from './OrbitScene';

const WebGLRendererMock = threeMock.__WebGLRenderer;

// ---------------------------------------------------------------------------
// Canvas context plumbing. jsdom returns null for getContext, which would push
// OrbitScene straight to its no-WebGL fallback and skip the texture-build
// branches. We install fakes so both the WebGL render path and the 2d-texture
// paths execute.
// ---------------------------------------------------------------------------
function fakeWebglContext() {
  return {
    getExtension: vi.fn().mockReturnValue({ loseContext: vi.fn() }),
  } as unknown as RenderingContext;
}

function fake2dContext() {
  return {
    createRadialGradient: vi.fn().mockReturnValue({ addColorStop: vi.fn() }),
    fillRect: vi.fn(),
    createImageData: vi.fn().mockReturnValue({ data: new Uint8ClampedArray(320 * 160 * 4) }),
    putImageData: vi.fn(),
    set fillStyle(_v: unknown) {},
  } as unknown as CanvasRenderingContext2D;
}

let webglEnabled = true;
let canvas2dEnabled = true;

beforeEach(() => {
  webglEnabled = true;
  canvas2dEnabled = true;
  WebGLRendererMock.shouldThrow = false;
  WebGLRendererMock.instances = [];
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(((type: string) => {
    if (type === 'webgl2' || type === 'webgl') return webglEnabled ? fakeWebglContext() : null;
    if (type === '2d') return canvas2dEnabled ? fake2dContext() : null;
    return null;
  }) as typeof HTMLCanvasElement.prototype.getContext);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Candidate fixtures designed to hit every branch in candidateRenderData,
// evidenceTone, statusLabel, confidenceScore and the render loop.
// ---------------------------------------------------------------------------
function candidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    candidate_id: 'TIC-1',
    period: 3.5,
    epoch: 1.2,
    duration: 0.1,
    depth: 0.002,
    signal_to_noise: 12,
    ...overrides,
  } as Candidate;
}

const readyHabitable = candidate({
  candidate_id: 'ready-hz',
  signal_to_noise: 28,
  physics: {
    semi_major_axis_au: 0.9,
    radius_ratio: 0.04,
    planet_radius_earth: 1.1,
    is_in_habitable_zone: true,
    is_temperature_habitable: true,
    equilibrium_temperature_k: 288,
    habitable_zone_inner_au: 0.8,
    habitable_zone_outer_au: 1.2,
  },
  science_readiness: { status: 'ready' },
  validation: { duration_plausible: true, false_positive_flags: [] },
  epoch_days: 2.0,
  duration_days: 0.12,
});

const reviewSignal = candidate({
  candidate_id: 'review-1',
  signal_to_noise: 7,
  science_readiness: { status: 'review' },
  validation: { duration_plausible: false, false_positive_flags: ['odd_even'] },
});

const blockedSignal = candidate({
  candidate_id: 'blocked-1',
  signal_to_noise: 5,
  disposition: 'rejected_signal',
  science_readiness: { status: 'blocked' },
} as Partial<Candidate>);

const previewOnly = candidate({
  candidate_id: 'preview-1',
  signal_to_noise: 9,
  physics: {},
});

// Physics present (keys) but not ready/review/blocked/habitable -> tone
// 'candidate' with the "candidate evidence" status label, and the 0.18
// physicsScore + validation 0.18 branches.
const candidateEvidence = candidate({
  candidate_id: 'cand-1',
  signal_to_noise: 11,
  physics: { semi_major_axis_au: 0.3, radius_ratio: 0.02 },
  validation: { duration_plausible: true },
});

// Habitable by temperature only (no habitable_zone_inner_au) so the HZ-source
// lookup falls through to the isHabitable branch.
const habitableNoZone = candidate({
  candidate_id: 'hz-temp',
  signal_to_noise: 14,
  physics: { is_temperature_habitable: true },
});

// No validation object at all -> validationScore 0.08 branch.
const noValidation = candidate({ candidate_id: 'noval-1', signal_to_noise: 10, validation: undefined });

// science-ready but NOT habitable -> statusLabel 'science-ready' (line 94).
// Also has only planet_radius_earth (no radius_ratio, depth 0) to cover the
// planetScale radiusEarth branch.
const readyOnly = candidate({
  candidate_id: 'ready-only',
  signal_to_noise: 20,
  depth: 0,
  physics: { planet_radius_earth: 2.3 },
  science_readiness: { status: 'ready' },
  validation: { duration_plausible: true },
});

describe('OrbitScene WebGL path', () => {
  it('renders the canvas, evidence badge and orbit labels for candidates', async () => {
    render(
      <OrbitScene
        candidates={[readyHabitable, reviewSignal, blockedSignal, previewOnly]}
        selectedId="ready-hz"
        onSelectCandidate={vi.fn()}
      />,
    );

    expect(screen.getByTestId('orbit-scene')).toBeInTheDocument();
    await screen.findByTestId('orbit-canvas');
    expect(screen.getByTestId('orbit-evidence-badge')).toHaveTextContent('ready-hz');
    expect(screen.getByText('HZ')).toBeInTheDocument();
    expect(screen.getByTestId('orbit-label-review-1')).toBeInTheDocument();
    // ghosted candidate shows "blocked" instead of a period
    expect(screen.getByTestId('orbit-label-blocked-1')).toHaveTextContent('blocked');
    expect(screen.queryByTestId('orbit-empty-state')).not.toBeInTheDocument();
  });

  it('shows the star-only empty state when there are no candidates', async () => {
    render(<OrbitScene candidates={[]} emptyMessage="Nothing yet" />);
    expect(screen.getByTestId('orbit-empty-state')).toHaveTextContent('Nothing yet');
    await screen.findByTestId('orbit-canvas');
  });

  it('drives the HUD controls: play/pause, speed, zoom in/out, camera reset', async () => {
    const user = userEvent.setup();
    render(<OrbitScene candidates={[readyHabitable]} selectedId="ready-hz" />);
    await screen.findByTestId('orbit-canvas');

    const play = screen.getByTestId('orbit-play-toggle');
    expect(play).toHaveAttribute('aria-label', 'Pause orbit simulation');
    await user.click(play);
    expect(play).toHaveAttribute('aria-label', 'Play orbit simulation');

    const speed = screen.getByTestId('orbit-speed-toggle');
    await user.click(speed); // 1 -> 1.8
    await user.click(speed); // 1.8 -> 0.65 (wraps)

    const zoomOut = screen.getByTestId('orbit-zoom-out');
    const zoomIn = screen.getByTestId('orbit-zoom-in');
    await user.click(zoomIn); // 1 -> 1.45
    await user.click(zoomIn); // 1.45 -> 2.1 (max)
    expect(zoomIn).toBeDisabled();
    await user.click(zoomOut);
    await user.click(zoomOut);
    await user.click(zoomOut); // down to 0
    expect(zoomOut).toBeDisabled();

    await user.click(screen.getByTestId('orbit-camera-reset'));
  });

  it('selects a candidate when an orbit label is clicked', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<OrbitScene candidates={[readyHabitable, reviewSignal]} onSelectCandidate={onSelect} />);
    await screen.findByTestId('orbit-canvas');
    await user.click(screen.getByTestId('orbit-label-review-1'));
    expect(onSelect).toHaveBeenCalledWith('review-1');
  });

  it('handles pointer hover (hit then miss) and a click that selects', async () => {
    const onSelect = vi.fn();
    const hitObject = Object.assign(new threeMock.Object3D(), { userData: { candidateId: 'ready-hz' } });
    const raycastSpy = vi
      .spyOn(threeMock.Raycaster.prototype, 'intersectObjects')
      // pointermove #1 -> hit (hovered becomes object, cursor pointer)
      .mockReturnValueOnce([{ object: hitObject }])
      // pointermove #2 -> miss (hovered cleared, cursor default)
      .mockReturnValueOnce([])
      // click -> hit with a candidate id
      .mockReturnValueOnce([{ object: hitObject }])
      .mockReturnValue([]);
    render(<OrbitScene candidates={[readyHabitable]} selectedId="ready-hz" onSelectCandidate={onSelect} />);
    await screen.findByTestId('orbit-canvas');

    const canvas = document.querySelector('canvas')!;
    await act(async () => {
      canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 10, clientY: 10, bubbles: true }));
    });
    await act(async () => {
      canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 20, clientY: 20, bubbles: true }));
    });
    await act(async () => {
      canvas.dispatchEvent(new MouseEvent('click', { clientX: 10, clientY: 10, bubbles: true }));
    });
    expect(onSelect).toHaveBeenCalledWith('ready-hz');
    raycastSpy.mockRestore();
  });

  it('ignores a click that hits an object without a candidate id', async () => {
    const onSelect = vi.fn();
    const bare = new threeMock.Object3D();
    const raycastSpy = vi
      .spyOn(threeMock.Raycaster.prototype, 'intersectObjects')
      .mockReturnValue([{ object: bare }]);
    render(<OrbitScene candidates={[readyHabitable]} selectedId="ready-hz" onSelectCandidate={onSelect} />);
    await screen.findByTestId('orbit-canvas');
    const canvas = document.querySelector('canvas')!;
    await act(async () => {
      canvas.dispatchEvent(new MouseEvent('click', { clientX: 5, clientY: 5, bubbles: true }));
    });
    expect(onSelect).not.toHaveBeenCalled();
    raycastSpy.mockRestore();
  });

  it('covers the automated-browser (webdriver) low-detail render branch', async () => {
    const original = Object.getOwnPropertyDescriptor(navigator, 'webdriver');
    Object.defineProperty(navigator, 'webdriver', { value: true, configurable: true });
    render(<OrbitScene candidates={[readyHabitable]} selectedId="ready-hz" />);
    await screen.findByTestId('orbit-canvas');
    if (original) Object.defineProperty(navigator, 'webdriver', original);
    else Object.defineProperty(navigator, 'webdriver', { value: false, configurable: true });
  });

  it('covers active review/blocked colors and a selected ghosted planet', async () => {
    // Select the blocked candidate so the tick loop runs the ghosted shadow/chord
    // branch, and include an active review candidate variant.
    const { rerender } = render(
      <OrbitScene candidates={[blockedSignal, reviewSignal, readyOnly]} selectedId="blocked-1" />,
    );
    await screen.findByTestId('orbit-canvas');
    rerender(<OrbitScene candidates={[blockedSignal, reviewSignal, readyOnly]} selectedId="review-1" />);
    await screen.findByTestId('orbit-canvas');
  });

  it('fires the selection-pulse timeout (setTimeout callback)', async () => {
    vi.useFakeTimers();
    try {
      const scene = render(<OrbitScene candidates={[readyHabitable]} selectedId="ready-hz" />);
      expect(scene.container.querySelector('.selection-pulse')).not.toBeNull();
      act(() => vi.advanceTimersByTime(6300));
      expect(scene.container.querySelector('.selection-pulse')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('uses the 0.02 fallback signal when no physics size hints exist', async () => {
    const sizeless = candidate({ candidate_id: 'sizeless', depth: 0, physics: { semi_major_axis_au: 0.1 } });
    render(<OrbitScene candidates={[sizeless]} selectedId="sizeless" />);
    await screen.findByTestId('orbit-canvas');
    expect(screen.getByTestId('orbit-label-sizeless')).toBeInTheDocument();
  });

  it('keeps the same hover target when the raycast hits it twice (no-op branch)', async () => {
    const hit = Object.assign(new threeMock.Object3D(), { userData: { candidateId: 'ready-hz' } });
    const raycastSpy = vi.spyOn(threeMock.Raycaster.prototype, 'intersectObjects').mockReturnValue([{ object: hit }]);
    render(<OrbitScene candidates={[readyHabitable]} selectedId="ready-hz" onSelectCandidate={vi.fn()} />);
    await screen.findByTestId('orbit-canvas');
    const canvas = document.querySelector('canvas')!;
    await act(async () => {
      canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 1, clientY: 1, bubbles: true }));
    });
    await act(async () => {
      canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 2, clientY: 2, bubbles: true }));
    });
    raycastSpy.mockRestore();
  });

  it('rebuilds cleanly on unmount (dispose path)', async () => {
    const { unmount } = render(<OrbitScene candidates={[readyHabitable, reviewSignal]} selectedId="ready-hz" />);
    await screen.findByTestId('orbit-canvas');
    const renderer = WebGLRendererMock.instances.at(-1)!;
    unmount();
    expect(renderer.dispose).toHaveBeenCalled();
  });

  it('covers candidate-evidence, no-validation and temperature-habitable branches', async () => {
    render(
      <OrbitScene
        candidates={[candidateEvidence, noValidation, habitableNoZone]}
        selectedId="cand-1"
        onSelectCandidate={vi.fn()}
      />,
    );
    await screen.findByTestId('orbit-canvas');
    expect(screen.getByTestId('orbit-evidence-badge')).toHaveTextContent('candidate evidence');
    expect(screen.getByTestId('orbit-label-noval-1')).toBeInTheDocument();
  });

  it('handles array-valued grid material and a resize event', async () => {
    const { GridHelper } = threeMock;
    GridHelper.arrayMaterial = true;
    const { resizeObserverInstances } = await import('../test/setup');
    resizeObserverInstances.length = 0;
    render(<OrbitScene candidates={[readyHabitable]} selectedId="ready-hz" />);
    await screen.findByTestId('orbit-canvas');
    // Fire the observed resize callback to cover the camera/renderer resize body.
    act(() => resizeObserverInstances.forEach((observer) => observer.trigger()));
    GridHelper.arrayMaterial = false;
  });

  it('covers the renderer-construction failure branch', async () => {
    WebGLRendererMock.shouldThrow = true;
    render(<OrbitScene candidates={[readyHabitable]} selectedId="ready-hz" />);
    // Falls back to the static overview because the renderer threw.
    await waitFor(() => expect(screen.getByLabelText('Static orbit overview')).toBeInTheDocument());
  });
});

describe('OrbitScene fallback (no WebGL) path', () => {
  beforeEach(() => {
    webglEnabled = false;
  });

  it('renders the static fallback overview with selectable orbits', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <OrbitScene candidates={[readyHabitable, reviewSignal, blockedSignal]} selectedId="ready-hz" onSelectCandidate={onSelect} />,
    );
    await waitFor(() => expect(screen.getByLabelText('Static orbit overview')).toBeInTheDocument());
    await user.click(screen.getByTestId('fallback-orbit-review-1'));
    expect(onSelect).toHaveBeenCalledWith('review-1');
    // WebGL renderer never constructed on this path
    expect(WebGLRendererMock.instances).toHaveLength(0);
  });
});

describe('OrbitScene texture fallbacks (no 2d context)', () => {
  beforeEach(() => {
    canvas2dEnabled = false;
  });

  it('still renders when 2d canvas contexts are unavailable', async () => {
    render(<OrbitScene candidates={[readyHabitable]} selectedId="ready-hz" />);
    await screen.findByTestId('orbit-canvas');
    expect(screen.getByTestId('orbit-scene')).toBeInTheDocument();
  });
});
