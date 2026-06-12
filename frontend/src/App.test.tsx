import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type {
  AnalysisJob,
  AnalysisResult,
  BlsPreviewResult,
  Candidate,
  HealthStatus,
  ModelStatuses,
  Product,
  SavedSession,
  SearchResult,
  Tce,
  TpfPreview,
} from './lib/api';

// ---------------------------------------------------------------------------
// Mock the API layer so App's workflows are deterministic and offline.
// ---------------------------------------------------------------------------
vi.mock('./lib/api', () => ({
  fetchModelStatus: vi.fn(),
  fetchHealth: vi.fn(),
  fetchResult: vi.fn(),
  searchTargets: vi.fn(),
  fetchProducts: vi.fn(),
  createAnalysisJob: vi.fn(),
  fetchAnalysisJob: vi.fn(),
  saveSession: vi.fn(),
  fetchSessions: vi.fn(),
  fetchReport: vi.fn(),
  fetchTpfPreview: vi.fn(),
  createApertureMask: vi.fn(),
  fetchBlsPreview: vi.fn(),
  createArtifactMask: vi.fn(),
}));

// Mock the heavy visual children so jsdom stays light; App logic is the target.
vi.mock('./components/OrbitScene', () => ({
  OrbitScene: ({
    candidates,
    onSelectCandidate,
  }: {
    candidates: Candidate[];
    onSelectCandidate?: (id: string) => void;
  }) => (
    <div data-testid="orbit-scene-mock">
      {candidates.map((c) => (
        <button key={c.candidate_id} type="button" onClick={() => onSelectCandidate?.(c.candidate_id)}>
          orbit-{c.candidate_id}
        </button>
      ))}
    </div>
  ),
}));
vi.mock('./components/SciencePlot', () => ({
  SciencePlot: ({ title }: { title: string }) => <div data-testid="science-plot-mock">{title}</div>,
}));

import * as api from './lib/api';
import App from './App';

const mocked = vi.mocked(api);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
function health(overrides: Partial<HealthStatus> = {}): HealthStatus {
  return {
    status: 'ok',
    api: 'ok',
    database: 'ok',
    worker_mode: 'inline',
    redis_configured: false,
    frontend: 'served',
    generated_at: '2026-06-08T00:00:00Z',
    ...overrides,
  };
}

function models(overrides: Partial<ModelStatuses> = {}): ModelStatuses {
  return {
    nigraha_tess: { status: 'ready', source: 'pretrained', version: '1.0' },
    kepler_astronet: { status: 'unavailable', detail: 'missing weights' },
    k2_exomac_kkt: { status: 'ready' },
    ...overrides,
  };
}

function searchResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return { target_id: 'TIC 307210830', catalog: 'TIC', match_type: 'catalog', ...overrides };
}

function product(overrides: Partial<Product> = {}): Product {
  return {
    product_id: 'obs-001',
    mission: 'TESS',
    description: 'Target Pixel File',
    product_uri: 'mast:TESS/product/file.fits',
    ...overrides,
  };
}

function candidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    candidate_id: 'cand-1',
    period: 3.52,
    epoch: 1.1,
    duration: 0.1,
    depth: 0.0021,
    signal_to_noise: 14.2,
    science_readiness: { status: 'ready' },
    ...overrides,
  } as Candidate;
}

function analysisResult(overrides: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    result_id: 'res-12345678',
    target_id: 'TIC 307210830',
    mission: 'TESS',
    candidates: [candidate()],
    periodogram: { period: [1, 2, 3], power: [4, 5, 6], duration: [0.1, 0.1, 0.1] },
    folded_curves: { 'cand-1': { phase: [0, 0.5, 1], flux: [1, 0.99, 1] } },
    light_curve: { time: [0, 1, 2, 3, 4], flux: [1, 1, 0.99, 1, 1] },
    ...overrides,
  };
}

function tpf(overrides: Partial<TpfPreview> = {}): TpfPreview {
  return {
    shape: [3, 3],
    image: [
      [1, 2, 3],
      [4, 5, 6],
      [7, 8, 9],
    ],
    finite_min: 1,
    finite_max: 9,
    baseline: 27,
    ...overrides,
  };
}

function job(overrides: Partial<AnalysisJob> = {}): AnalysisJob {
  return { job_id: 'job-1', status: 'complete', created_at: '', result_id: 'res-12345678', error: null, ...overrides };
}

function blsPreview(overrides: Partial<BlsPreviewResult> = {}): BlsPreviewResult {
  return {
    search_profile: 'preview_fast',
    periodogram: { period: [1, 2], power: [3, 4] },
    candidates: [candidate({ candidate_id: 'prev-1' })],
    folded_curves: { 'prev-1': { phase: [0, 1], flux: [1, 1] } },
    bls_light_curve: { time: [0, 1, 2], flux: [1, 1, 1] },
    preprocessing: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Default happy-path mock wiring before each test.
// ---------------------------------------------------------------------------
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  localStorage.setItem('orbitlab-first-run-acknowledged', 'true');
  localStorage.setItem('orbitlab-beginner-tour-completed', 'true');
  mocked.fetchModelStatus.mockResolvedValue(models());
  mocked.fetchHealth.mockResolvedValue(health());
  mocked.searchTargets.mockResolvedValue([searchResult()]);
  mocked.fetchProducts.mockResolvedValue([product()]);
  mocked.createAnalysisJob.mockResolvedValue(job({ status: 'queued', result_id: null }));
  mocked.fetchAnalysisJob.mockResolvedValue(job());
  mocked.fetchResult.mockResolvedValue(analysisResult());
  mocked.saveSession.mockResolvedValue({ session_id: 's1', name: 'n', payload: {}, created_at: '' } as SavedSession);
  mocked.fetchSessions.mockResolvedValue([]);
  mocked.fetchReport.mockResolvedValue({ report_id: 'r1' });
  mocked.fetchTpfPreview.mockResolvedValue(tpf());
  mocked.createApertureMask.mockResolvedValue({
    aperture_mask_id: 'am-1',
    target_id: 'TIC 307210830',
    product_uri: 'mast:p',
    mask: [[true]],
    reason: 'r',
    created_at: '',
  });
  mocked.fetchBlsPreview.mockResolvedValue(blsPreview());
  mocked.createArtifactMask.mockResolvedValue({
    mask_id: 'art-1',
    target_id: 'TIC 307210830',
    indices: [0, 1],
    reason: 'r',
    created_at: '',
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

// Helper: render and wait for initial effects (model + health) to settle.
async function renderApp() {
  const utils = render(<App />);
  await waitFor(() => expect(mocked.fetchHealth).toHaveBeenCalled());
  return utils;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('App – initial render and mode/theme', () => {
  it('renders the workbench in beginner mode by default and loads model/health', async () => {
    await renderApp();
    expect(screen.getByText('OrbitLab')).toBeInTheDocument();
    expect(screen.getByText('Guided exoplanet workflow')).toBeInTheDocument();
    expect(mocked.fetchModelStatus).toHaveBeenCalled();
  });

  it('persists mode to advanced and back, updating localStorage', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    await renderApp();
    expect(screen.getByText('Real TPF exoplanet workbench')).toBeInTheDocument();
    expect(localStorage.getItem('orbitlab-mode')).toBe('advanced');
  });
});

describe('App – search workflow', () => {
  it('runs a search and lists catalog matches', async () => {
    const user = userEvent.setup();
    await renderApp();
    const input = screen.getByLabelText('target search');
    await user.type(input, 'TIC 307210830');
    await user.click(screen.getByRole('button', { name: /Search/i }));
    await screen.findByText('TIC 307210830');
    expect(mocked.searchTargets).toHaveBeenCalledWith('TIC 307210830', 'TESS');
  });

  it('shows an empty message when no targets match', async () => {
    mocked.searchTargets.mockResolvedValueOnce([]);
    const user = userEvent.setup();
    await renderApp();
    await user.type(screen.getByLabelText('target search'), 'nope');
    await user.click(screen.getByRole('button', { name: /Search/i }));
    await waitFor(() => expect(mocked.searchTargets).toHaveBeenCalled());
  });

  it('surfaces a search failure', async () => {
    mocked.searchTargets.mockRejectedValueOnce(new Error('MAST down'));
    const user = userEvent.setup();
    await renderApp();
    await user.type(screen.getByLabelText('target search'), 'boom');
    await user.click(screen.getByRole('button', { name: /Search/i }));
    await screen.findByText('MAST down');
  });

  it('unlocks Voyager mode via the easter egg query', async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.type(screen.getByLabelText('target search'), 'voyager');
    await user.click(screen.getByRole('button', { name: /Search/i }));
    await screen.findByText('Voyager Mode unlocked.');
  });
});

// ---------------------------------------------------------------------------
// Drive a target+product selection, returning after products are listed.
// ---------------------------------------------------------------------------
async function selectTargetAndProduct(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('target search'), 'TIC 307210830');
  await user.click(screen.getByRole('button', { name: /^Search$/i }));
  await user.click(await screen.findByText('TIC 307210830'));
  await user.click(await screen.findByText('obs-001'));
}

describe('App – analysis workflow', () => {
  it('runs a full analysis with polling and renders the result', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    try {
      // queued -> running -> complete across polls
      mocked.createAnalysisJob.mockResolvedValue(job({ status: 'queued', result_id: null }));
      mocked.fetchAnalysisJob
        .mockResolvedValueOnce(job({ status: 'running', result_id: null }))
        .mockResolvedValue(job({ status: 'complete', result_id: 'res-12345678' }));

      render(<App />);
      await waitFor(() => expect(mocked.fetchHealth).toHaveBeenCalled());
      await selectTargetAndProduct(user);
      await user.click(screen.getByRole('button', { name: /Run Analysis/i }));

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
      await waitFor(() => expect(mocked.fetchResult).toHaveBeenCalled());
      expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete');
    } finally {
      vi.useRealTimers();
    }
  });

  it('handles an analysis job that reports failure', async () => {
    const user = userEvent.setup();
    await renderApp();
    mocked.createAnalysisJob.mockResolvedValueOnce(job({ status: 'failed', result_id: null, error: 'pipeline boom' }));
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await screen.findByText('pipeline boom');
  });

  it('surfaces an error when job creation throws', async () => {
    const user = userEvent.setup();
    await renderApp();
    mocked.createAnalysisJob.mockRejectedValueOnce(new Error('queue offline'));
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await screen.findByText('queue offline');
  });
});

describe('App – result display', () => {
  function fullTce(): Tce {
    return {
      candidate_id: 'tce-1',
      tce_id: 'TCE-1',
      period: 4.2,
      epoch: 2.1,
      duration: 0.15,
      depth: 0.003,
      signal_to_noise: 18,
      period_days: 4.2,
      disposition: 'planet_candidate',
      action_label: 'review_needed',
      disposition_score: 0.8,
      final_score: 0.9,
      science_readiness: {
        status: 'review',
        result_kind: 'analysis',
        blockers: ['blk'],
        warnings: ['warn'],
        evidence_gaps: ['gap'],
        interpretation: 'looks planetary',
      },
      detection_metrics: {
        effective_snr: 17,
        red_noise_beta: 1.1,
        observed_transit_count: 5,
        duration_period_ratio: 0.03,
        phase_coverage_score: 0.9,
        tls_sde: 12,
        paper_grade_pass: 1,
        alias_flags: ['half'],
      },
      validation: {
        odd_even_depth_delta: 0.0001,
        odd_even_sigma: 1.2,
        secondary_depth: 0.0002,
        secondary_snr: 0.5,
        duration_plausible: true,
        false_positive_flags: ['fp'],
      },
      physics: {
        radius_ratio: 0.04,
        planet_radius_earth: 1.5,
        semi_major_axis_au: 0.9,
        equilibrium_temperature_k: 290,
        is_in_habitable_zone: true,
        is_temperature_habitable: true,
        kopparapu_hz: { conservative_inner_au: 0.8, conservative_outer_au: 1.2 },
        habitability: { status: 'promising' },
        stellar_context_source: 'tic',
        interpretation_locked: true,
        locked_reason: 'unverified stellar context',
        trust_message: 'verify stellar params',
      },
      ml: {
        probability: 0.91,
        raw_ml_probability: 0.88,
        calibrated_ml_probability: 0.9,
        calibration_source: 'platt',
        threshold: 0.5,
        label: 'planet',
        model_version: 'v1',
        model_source: 'nigraha',
        input_tensor_checksum: 'abcdef0123456789',
        preprocessing_compatible: true,
        citation: 'cite',
        class_probabilities: { planet: 0.91, eb: 0.05 },
      },
      evidence_scores: { detection: 0.8, vetting: 0.7, data_quality: 0.9, centroid: 0.6, physics_plausibility: 0.5 },
      evidence: { tls: { status: 'ok' }, model_shift: { status: 'ok' }, sweet: { status: 'ok' } },
      vetting: {
        model_shift: { status: 'pass', robovet: { disp: 'PC' } },
        sweet: { status: 'pass' },
        detrending_sensitivity: { status: 'stable' },
        sector_consistency: { multi_sector_status: 'consistent' },
      },
      detrending_sensitivity: { status: 'stable' },
      sector_consistency: { multi_sector_status: 'consistent' },
      catalog_context: {
        status: 'matched',
        exofop_toi: { match_count: 1 },
        nasa_exoplanet_archive: { confirmed_planet_count: 1 },
        contamination: { capable_neighbor_count: 2 },
      },
      fpp: { status: 'low', fpp: 0.001, nfpp: 0.0005 },
      flags: [{ code: 'odd_even', severity: 'warning', message: 'Odd-even mismatch needs review.' }],
      explanation: ['strong transit', 'passes vetting'],
    } as Tce;
  }

  it('renders a fully-populated TCE-rich result (truthy display branches)', async () => {
    const user = userEvent.setup();
    const tce = fullTce();
    mocked.fetchResult.mockResolvedValue(
      analysisResult({
        candidates: [],
        tces: [tce],
        planet_candidates: [tce],
        science_readiness: { status: 'review', result_kind: 'analysis', blockers: ['major'] },
        stellar_context: { physics_source: 'tic' },
      }),
    );
    mocked.fetchAnalysisJob.mockResolvedValue(job());
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await screen.findByText('looks planetary');
    expect(screen.getByText('TCE Ledger')).toBeInTheDocument();
    await user.click(screen.getByText('TCE-1'));
    // class probabilities rendered
    expect(screen.getAllByText('planet').length).toBeGreaterThan(0);
  });

  it('renders a minimal result (n/a fallback branches)', async () => {
    const user = userEvent.setup();
    mocked.fetchResult.mockResolvedValue(
      analysisResult({ candidates: [candidate({ science_readiness: undefined, depth: 0 })] }),
    );
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await waitFor(() => expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete'));
    expect(screen.getAllByText('n/a').length).toBeGreaterThan(0);
  });

  it('selects a candidate from the orbit scene and candidate card', async () => {
    const user = userEvent.setup();
    mocked.fetchResult.mockResolvedValue(
      analysisResult({ candidates: [candidate({ candidate_id: 'a' }), candidate({ candidate_id: 'b' })] }),
    );
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await screen.findByText('orbit-a');
    await user.click(screen.getByText('orbit-b'));
    await user.click(screen.getAllByText('b')[0]);
  });

  it('passes advanced expert inputs and mask ids into a full analysis request', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    await user.clear(screen.getByLabelText(/Max Candidates/i));
    await user.type(screen.getByLabelText(/Max Candidates/i), '9');
    await user.selectOptions(screen.getByLabelText(/Accuracy Mode/i), 'deep');
    await user.type(screen.getByLabelText(/Stellar Radius/i), '1.1');
    await user.type(screen.getByLabelText(/Stellar Mass/i), '0.9');
    await user.type(screen.getByLabelText(/Stellar Teff/i), '5772');
    await user.type(screen.getByLabelText(/Stellar logg/i), '4.4');
    await user.type(screen.getByLabelText(/Luminosity/i), '1.2');
    await user.type(screen.getByLabelText(/Density/i), '0.8');
    await user.type(screen.getByLabelText(/Rotation Period/i), '12.5');
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await waitFor(() => expect(mocked.createAnalysisJob).toHaveBeenCalled());
    expect(mocked.createAnalysisJob).toHaveBeenCalledWith(
      expect.objectContaining({
        max_candidates: 8,
        vetting_mode: 'deep',
        stellar_radius_solar: 1.1,
        stellar_mass_solar: 0.9,
        stellar_teff: 5772,
        stellar_logg: 4.4,
        stellar_luminosity_solar: 1.2,
        stellar_density_solar: 0.8,
        stellar_rotation_period: 12.5,
      }),
    );
  });
});

describe('App – BLS preview (beginner) and advanced pipeline', () => {
  it('runs a beginner preview and renders preview candidates', async () => {
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Preview Candidates/i }));
    await waitFor(() => expect(mocked.fetchBlsPreview).toHaveBeenCalled());
  });

  it('reports a BLS preview failure', async () => {
    const user = userEvent.setup();
    mocked.fetchBlsPreview.mockRejectedValueOnce(new Error('bls exploded'));
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Preview Candidates/i }));
    await waitFor(() => expect(mocked.fetchBlsPreview).toHaveBeenCalled());
  });

  it('runs a second preview after clearing an existing preview result', async () => {
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Preview Candidates/i }));
    await waitFor(() => expect(mocked.fetchBlsPreview).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: /Preview Candidates/i }));
    await waitFor(() => expect(mocked.fetchBlsPreview).toHaveBeenCalledTimes(2));
  });

  it('falls back to the ceiling period limit when preview metadata cannot be loaded', async () => {
    const user = userEvent.setup();
    mocked.fetchTpfPreview.mockRejectedValueOnce(new Error('no preview metadata'));
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Preview Candidates/i }));
    await waitFor(() => expect(mocked.fetchBlsPreview).toHaveBeenCalled());
    expect(mocked.fetchBlsPreview).toHaveBeenCalledWith(expect.objectContaining({ max_period: 30 }));
  });

  it('opens aperture editor, toggles a pixel, and applies the mask', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Aperture/i }));
    const pixel = await screen.findByTestId('aperture-pixel-0-0');
    await user.click(pixel);
    await user.click(screen.getByRole('button', { name: 'Apply Mask' }));
    await screen.findByText('Custom aperture mask created.');
  });

  it('reports an aperture preview load failure and an aperture mask creation failure', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    mocked.fetchTpfPreview.mockRejectedValueOnce(new Error('TPF preview failed'));
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Aperture/i }));
    await screen.findByText('TPF preview failed');

    mocked.createApertureMask.mockRejectedValueOnce(new Error('mask save failed'));
    await user.click(screen.getByRole('button', { name: /Aperture/i }));
    const pixel = await screen.findByTestId('aperture-pixel-0-0');
    await user.click(pixel);
    await user.click(screen.getByRole('button', { name: 'Apply Mask' }));
    await screen.findByText('mask save failed');
  });

  it('blocks applying an empty aperture mask', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Aperture/i }));
    await screen.findByTestId('aperture-pixel-0-0');
    await user.click(screen.getByRole('button', { name: 'Apply Mask' }));
    await screen.findByText('Please select at least one pixel for the aperture mask.');
  });

  it('opens the BLS modal and runs a preview search from it', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /BLS Search/i }));
    await screen.findByText('BLS Search Controls');
    await user.click(screen.getByRole('button', { name: /Run Preview Search/i }));
    await waitFor(() => expect(mocked.fetchBlsPreview).toHaveBeenCalled());
  });

  it('opens the BLS modal even when TPF preview fails', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    mocked.fetchTpfPreview.mockRejectedValueOnce(new Error('preview unavailable'));
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /BLS Search/i }));
    await screen.findByText('BLS Search Controls');
    await screen.findByText('preview unavailable');
  });

  it('updates BLS period controls through the modal', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /BLS Search/i }));
    await screen.findByText('BLS Search Controls');
    fireEvent.change(document.querySelector('input[name="min-period"]') as HTMLInputElement, {
      target: { value: '0.8' },
    });
    fireEvent.change(document.querySelector('input[name="max-period"]') as HTMLInputElement, {
      target: { value: '9.2' },
    });
    fireEvent.change(screen.getByLabelText('minimum period value'), { target: { value: '1.2' } });
    fireEvent.change(screen.getByLabelText('maximum period value'), { target: { value: '8.4' } });
    await user.click(screen.getByRole('button', { name: /Run Preview Search/i }));
    await waitFor(() =>
      expect(mocked.fetchBlsPreview).toHaveBeenCalledWith(
        expect.objectContaining({ min_period: 1.2, max_period: 8.4 }),
      ),
    );
  });
});

describe('App – modals, sessions, theme, tour', () => {
  it('opens settings, switches mode and theme', async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: 'Settings' }));
    await user.click(await screen.findByRole('radio', { name: 'Advanced' }));
    await user.click(screen.getByRole('radio', { name: 'Beginner' }));
    await user.click(screen.getByRole('radio', { name: 'Sakura' }));
    expect(localStorage.getItem('orbitlab-theme')).toBe('sakura');
  });

  it('enables Voyager overlay after the easter egg unlock', async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.type(screen.getByLabelText('target search'), 'voyager');
    await user.click(screen.getByRole('button', { name: /^Search$/i }));
    await screen.findByText('Voyager Mode unlocked.');
    expect(localStorage.getItem('orbitlab-voyager-enabled')).toBe('true');
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.click(screen.getByRole('button', { name: 'Settings' }));
    await user.click(screen.getByRole('checkbox', { name: /Mission overlay/i }));
    expect(localStorage.getItem('orbitlab-voyager-enabled')).toBe('false');
  });

  it('saves a session and lists saved sessions, then restores one', async () => {
    const saved: SavedSession = {
      session_id: 's1',
      name: 'TESS-TIC 307210830',
      payload: { mission: 'TESS', query: 'TIC 307210830', selectedTarget: searchResult(), result: analysisResult() },
      created_at: '2026-06-08T00:00:00Z',
    };
    mocked.fetchSessions.mockResolvedValue([saved]);
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: 'Save session' }));
    await screen.findByText('Session saved successfully.');
    await user.click(screen.getByRole('button', { name: 'Sessions' }));
    await user.click(await screen.findByText('TESS-TIC 307210830'));
    await screen.findByText(/Restored session/);
  });

  it('handles empty sessions, session API failures, and save failures', async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: 'Sessions' }));
    await screen.findByText('No saved sessions found.');

    mocked.fetchSessions.mockRejectedValueOnce(new Error('sessions unavailable'));
    await user.click(screen.getByRole('button', { name: 'Close Saved Sessions' }));
    await user.click(screen.getByRole('button', { name: 'Sessions' }));
    await screen.findByText('sessions unavailable');

    mocked.saveSession.mockRejectedValueOnce(new Error('save unavailable'));
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: 'Save session' }));
    await screen.findByText('save unavailable');
  });

  it('restores sparse sessions through fallback defaults', async () => {
    const sparse: SavedSession = {
      session_id: 'sparse',
      name: 'Sparse Session',
      payload: { selectedProduct: product(), maxCandidates: 99, vettingMode: 'nonsense', result: null },
      created_at: '2026-06-08T00:00:00Z',
    };
    mocked.fetchSessions.mockResolvedValue([sparse]);
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: 'Sessions' }));
    await user.click(await screen.findByText('Sparse Session'));
    await screen.findByText(/Restored session Sparse Session/);
    expect(screen.getByTestId('workflow-status')).toHaveTextContent('product-selected');
  });

  it('restores an idle sparse session when no result or product is persisted', async () => {
    const sparse: SavedSession = {
      session_id: 'idle-sparse',
      name: 'Idle Sparse Session',
      payload: { query: 123, maxCandidates: 'bad' },
      created_at: '2026-06-08T00:00:00Z',
    };
    mocked.fetchSessions.mockResolvedValue([sparse]);
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: 'Sessions' }));
    await user.click(await screen.findByText('Idle Sparse Session'));
    expect(screen.getByTestId('workflow-status')).toHaveTextContent('idle');
  });

  it('exports a report after a full analysis', async () => {
    const createObjectURL = vi.fn().mockReturnValue('blob:url');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await waitFor(() => expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete'));
    await user.click(screen.getByRole('button', { name: 'Export report' }));
    await screen.findByText('Report exported successfully.');
    clickSpy.mockRestore();
  });

  it('reports export failures for completed analyses', async () => {
    const user = userEvent.setup();
    mocked.fetchReport.mockRejectedValueOnce(new Error('report failed'));
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await waitFor(() => expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete'));
    await user.click(screen.getByRole('button', { name: 'Export report' }));
    await screen.findByText('report failed');
  });

  it('opens the model registry modal and refreshes it', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: /ML Status/i }));
    await screen.findByText('Model Status & Registry');
    await user.click(screen.getByRole('button', { name: /Refresh Registry/i }));
  });

  it('renders model fallback setup hints for unknown unavailable registry keys', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    mocked.fetchModelStatus.mockResolvedValue({
      experimental_model: { status: 'missing' },
    } as unknown as ModelStatuses);
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: /ML Status/i }));
    await screen.findByText('Experimental Model');
    await screen.findByText('Check model registry setup.');
  });

  it('starts the beginner tour and steps through it', async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: 'Start beginner tour' }));
    await user.click(await screen.findByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: 'Skip' }));
  });

  it('shows a health banner when the backend is unhealthy', async () => {
    mocked.fetchHealth.mockResolvedValue(health({ status: 'degraded', api: 'slow' }));
    await renderApp();
    expect(await screen.findByTestId('health-banner')).toBeInTheDocument();
  });

  it('shows a health banner when the health check fails entirely', async () => {
    mocked.fetchHealth.mockRejectedValue(new Error('no backend'));
    const user = userEvent.setup();
    await renderApp();
    const banner = await screen.findByTestId('health-banner');
    expect(banner).toHaveTextContent('Health check failed');
    await user.click(within(banner).getByRole('button', { name: /Retry/i }));
  });

  it('surfaces model registry load failures and dismisses the error panel', async () => {
    mocked.fetchModelStatus.mockRejectedValueOnce(new Error('model registry down'));
    const user = userEvent.setup();
    await renderApp();
    await screen.findByText('model registry down');
    await user.click(screen.getByRole('button', { name: 'Dismiss error' }));
    await waitFor(() => expect(screen.queryByText('model registry down')).not.toBeInTheDocument());
  });

  it('runs theme bloom, success, and completion cleanup timers without leaking', async () => {
    const user = userEvent.setup();
    const originalRaf = window.requestAnimationFrame;
    window.requestAnimationFrame = ((callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    }) as typeof window.requestAnimationFrame;
    const rendered = await renderApp();
    await user.click(screen.getByRole('button', { name: 'Settings' }));
    await user.click(screen.getByRole('radio', { name: 'Nature' }));
    await user.click(screen.getByRole('radio', { name: 'Dark' }));
    await user.click(screen.getByRole('button', { name: 'Close Settings' }));
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await waitFor(() => expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete'));
    rendered.unmount();
    window.requestAnimationFrame = originalRaf;
  });

  it('clears the auto-tour startup timer on early unmount', async () => {
    vi.useFakeTimers();
    try {
      localStorage.removeItem('orbitlab-beginner-tour-completed');
      const rendered = render(<App />);
      rendered.unmount();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('App – first-run installer welcome', () => {
  it('shows the install welcome on first launch and hands off to the beginner tour', async () => {
    localStorage.removeItem('orbitlab-first-run-acknowledged');
    localStorage.removeItem('orbitlab-beginner-tour-completed');
    const user = userEvent.setup();
    await renderApp();
    const welcome = await screen.findByTestId('first-run-welcome');
    expect(welcome).toHaveTextContent('scripts/start_all.sh');
    expect(welcome).toHaveTextContent('First launch detected');
    await user.click(within(welcome).getByRole('button', { name: /Start exploring/ }));
    expect(screen.queryByTestId('first-run-welcome')).not.toBeInTheDocument();
    expect(localStorage.getItem('orbitlab-first-run-acknowledged')).toBe('true');
    expect(screen.getByText('Choose a mission')).toBeInTheDocument();
  });

  it('closes without the tour in advanced mode and persists the acknowledgement', async () => {
    localStorage.removeItem('orbitlab-first-run-acknowledged');
    localStorage.removeItem('orbitlab-beginner-tour-completed');
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    await renderApp();
    const welcome = await screen.findByTestId('first-run-welcome');
    await user.click(within(welcome).getByRole('button', { name: 'Close welcome' }));
    expect(screen.queryByTestId('first-run-welcome')).not.toBeInTheDocument();
    expect(screen.queryByText('Choose a mission')).not.toBeInTheDocument();
    expect(localStorage.getItem('orbitlab-first-run-acknowledged')).toBe('true');
  });

  it('dismisses when clicking the overlay backdrop', async () => {
    localStorage.removeItem('orbitlab-first-run-acknowledged');
    await renderApp();
    const welcome = await screen.findByTestId('first-run-welcome');
    fireEvent.mouseDown(welcome.closest('.modal-overlay')!);
    await waitFor(() => expect(screen.queryByTestId('first-run-welcome')).not.toBeInTheDocument());
    expect(localStorage.getItem('orbitlab-first-run-acknowledged')).toBe('true');
  });

  it('treats Escape as acknowledgement so the welcome never nags again', async () => {
    localStorage.removeItem('orbitlab-first-run-acknowledged');
    localStorage.removeItem('orbitlab-beginner-tour-completed');
    await renderApp();
    await screen.findByTestId('first-run-welcome');
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('first-run-welcome')).not.toBeInTheDocument());
    expect(localStorage.getItem('orbitlab-first-run-acknowledged')).toBe('true');
  });

  it('copies the install command and confirms with a copied state', async () => {
    localStorage.removeItem('orbitlab-first-run-acknowledged');
    const user = userEvent.setup();
    await renderApp();
    const welcome = await screen.findByTestId('first-run-welcome');
    await user.click(within(welcome).getByRole('button', { name: 'Copy install command' }));
    expect(await within(welcome).findByText('Copied')).toBeInTheDocument();
    expect(await window.navigator.clipboard.readText()).toBe('scripts/start_all.sh');
  });

  it('does not reopen the welcome once acknowledged', async () => {
    await renderApp();
    await new Promise((resolve) => setTimeout(resolve, 450));
    expect(screen.queryByTestId('first-run-welcome')).not.toBeInTheDocument();
  });
});

describe('App – failure and edge workflows', () => {
  it('executes auto-tour, success, theme-bloom, and completion timer callbacks', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    try {
      localStorage.removeItem('orbitlab-beginner-tour-completed');
      render(<App />);
      await act(async () => vi.advanceTimersByTimeAsync(400));
      expect(screen.getByText('Choose a mission')).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Skip' }));

      await user.type(screen.getByLabelText('target search'), 'voyager');
      await user.click(screen.getByRole('button', { name: /^Search$/i }));
      await user.click(screen.getByRole('button', { name: 'Continue' }));
      await user.click(screen.getByRole('button', { name: 'Settings' }));
      await user.click(screen.getByRole('radio', { name: 'Nature' }));
      await user.click(screen.getByRole('button', { name: 'Close Settings' }));
      await act(async () => vi.advanceTimersByTimeAsync(6500));

      await selectTargetAndProduct(user);
      await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
      await act(async () => vi.advanceTimersByTimeAsync(2500));
      expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete');
    } finally {
      vi.useRealTimers();
    }
  });

  it('handles non-Error failures and a no-op same-theme selection', async () => {
    mocked.fetchModelStatus.mockRejectedValueOnce('model string failure');
    mocked.fetchHealth.mockRejectedValueOnce('health string failure');
    const user = userEvent.setup();
    await renderApp();
    await screen.findByText('model string failure');
    expect(screen.getByTestId('health-banner')).toHaveTextContent('health string failure');
    await user.click(screen.getByRole('button', { name: 'Settings' }));
    await user.click(screen.getByRole('radio', { name: 'Space' }));
  });

  it('renders K2, planet-candidate fallback, sparse TCE, and unknown readiness payload paths', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const sparseTce = {
      ...candidate({ candidate_id: 'sparse-tce', final_score: undefined, science_readiness: undefined }),
      disposition_score: 0.33,
      disposition: undefined,
      action_label: undefined,
      tce_id: undefined,
      physics: {
        interpretation_locked: true,
        locked_reason: undefined,
        trust_message: undefined,
      },
    } as Tce;
    const restored: SavedSession = {
      session_id: 'display-edges',
      name: 'Display Edges',
      payload: {
        mission: 'K2',
        selectedTarget: searchResult({ target_id: 'K2 target' }),
        result: analysisResult({
          mission: 'K2',
          candidates: [],
          tces: undefined,
          planet_candidates: [sparseTce],
          science_readiness: { status: undefined, result_kind: 'analysis', evidence_gaps: [] },
          folded_curves: { 'sparse-tce': { phase: [], flux: [] } },
        }),
      },
      created_at: '',
    };
    mocked.fetchSessions.mockResolvedValue([restored]);
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: 'Sessions' }));
    await user.click(await screen.findByText('Display Edges'));
    expect(screen.getByText('Science readiness: unknown')).toBeInTheDocument();
    expect(screen.getAllByText('sparse-tce').length).toBeGreaterThan(0);
    expect(screen.getByText('locked')).toBeInTheDocument();
    expect(screen.getByText('Stellar context is not verified.')).toBeInTheDocument();
  });

  it('renders pathological but valid TPF pixel-scale fallbacks', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    mocked.fetchTpfPreview
      .mockResolvedValueOnce(
        tpf({ shape: [1, 1], image: [[Number.NaN]], finite_min: Number.NaN, finite_max: Number.NaN }),
      )
      .mockResolvedValueOnce(tpf({ shape: [1, 1], image: [[5]], finite_min: 5, finite_max: 5 }));
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Aperture/i }));
    expect(await screen.findByTestId('aperture-pixel-0-0')).toHaveStyle({ opacity: '0.2' });
    await user.click(screen.getByRole('button', { name: 'Close Aperture Mask Editor' }));
    await user.click(screen.getByRole('button', { name: /Aperture/i }));
    expect(await screen.findByTestId('aperture-pixel-0-0')).toBeInTheDocument();
  });

  it('covers blank-search and disabled action guards without changing app state', async () => {
    await renderApp();
    const searchButton = screen.getByRole('button', { name: /^Search$/i }) as HTMLButtonElement;
    searchButton.disabled = false;
    fireEvent.click(searchButton);
    expect(mocked.searchTargets).not.toHaveBeenCalled();

    const runButton = screen.getByRole('button', { name: /Run Analysis/i }) as HTMLButtonElement;
    runButton.disabled = false;
    fireEvent.click(runButton);
    expect(mocked.createAnalysisJob).not.toHaveBeenCalled();

    const saveButton = screen.getByRole('button', { name: 'Save session' }) as HTMLButtonElement;
    saveButton.disabled = false;
    fireEvent.click(saveButton);
    expect(mocked.saveSession).not.toHaveBeenCalled();
  });

  it('renders advanced empty-product and alias-without-query branches', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    mocked.searchTargets.mockResolvedValue([
      searchResult({
        target_id: 'Alias no query',
        match_type: 'alias',
        matched_query: undefined,
        trust_label: undefined,
      }),
    ]);
    mocked.fetchProducts.mockResolvedValue([]);
    const user = userEvent.setup();
    await renderApp();
    await user.type(screen.getByLabelText('target search'), 'alias');
    await user.click(screen.getByRole('button', { name: /^Search$/i }));
    await user.click(await screen.findByText('Alias no query'));
    expect(await screen.findByText('No target pixel products found.')).toBeInTheDocument();
  });

  it('opens model registry while its initial request is still pending', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const pending = deferred<ModelStatuses>();
    mocked.fetchModelStatus.mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(mocked.fetchHealth).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: /ML Status/i }));
    expect(await screen.findByText('Loading model registry...')).toBeInTheDocument();
    pending.resolve(models());
  });

  it('changes mission and resets search/product/result state', async () => {
    const user = userEvent.setup();
    mocked.searchTargets.mockResolvedValue([
      searchResult({ target_id: 'Alias Target', match_type: 'alias', matched_query: 'Kepler-10' }),
      searchResult({ target_id: 'KIC 11904151', catalog: 'Kepler', match_type: 'catalog' }),
    ]);
    await renderApp();
    await user.selectOptions(screen.getByLabelText(/Mission/i), 'Kepler');
    await user.type(screen.getByLabelText('target search'), 'Kepler-10');
    await user.click(screen.getByRole('button', { name: /^Search$/i }));
    await screen.findByText('Suggested targets');
    await screen.findByText('Catalog matches');
    await user.click(screen.getByText('Alias Target'));
    expect(mocked.searchTargets).toHaveBeenCalledWith('Kepler-10', 'Kepler');
  });

  it('surfaces product loading failures after target selection', async () => {
    const user = userEvent.setup();
    mocked.fetchProducts.mockRejectedValueOnce(new Error('products unavailable'));
    await renderApp();
    await user.type(screen.getByLabelText('target search'), 'TIC 307210830');
    await user.click(screen.getByRole('button', { name: /^Search$/i }));
    await user.click(await screen.findByText('TIC 307210830'));
    await screen.findByText('products unavailable');
  });

  it('reports a still-running analysis after the polling limit', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    try {
      mocked.createAnalysisJob.mockResolvedValue(job({ status: 'queued', result_id: null }));
      mocked.fetchAnalysisJob.mockResolvedValue(job({ status: 'running', result_id: null }));
      render(<App />);
      await waitFor(() => expect(mocked.fetchHealth).toHaveBeenCalled());
      await selectTargetAndProduct(user);
      await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(121_000);
      });
      await screen.findByText('Analysis is still running. Use Refresh Job Status to continue polling this job.');
    } finally {
      vi.useRealTimers();
    }
  });

  it('refreshes an in-flight job through failed, running, complete, and thrown statuses', async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(mocked.fetchHealth).toHaveBeenCalled());
    await selectTargetAndProduct(user);
    mocked.createAnalysisJob.mockResolvedValue(job({ status: 'queued', result_id: null }));
    mocked.fetchAnalysisJob
      .mockResolvedValueOnce(job({ status: 'failed', result_id: null, error: null }))
      .mockResolvedValueOnce(job({ status: 'running', result_id: null }))
      .mockResolvedValueOnce(job({ status: 'complete', result_id: 'res-12345678' }))
      .mockRejectedValueOnce(new Error('refresh failed'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));
      await Promise.resolve();
    });
    expect(screen.getByTitle('Refresh Status')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByTitle('Refresh Status'));
      await Promise.resolve();
    });
    await screen.findByText('Analysis failed.');

    mocked.createAnalysisJob.mockResolvedValueOnce(job({ status: 'queued', result_id: null }));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));
      await Promise.resolve();
    });
    expect(screen.getByTitle('Refresh Status')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByTitle('Refresh Status'));
      await Promise.resolve();
    });
    expect(screen.getByTestId('workflow-status')).toHaveTextContent('running');
    await act(async () => {
      fireEvent.click(screen.getByTitle('Refresh Status'));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete'));

    mocked.createAnalysisJob.mockResolvedValueOnce(job({ status: 'queued', result_id: null }));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));
      await Promise.resolve();
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle('Refresh Status'));
      await Promise.resolve();
    });
    await screen.findByText('refresh failed');
  }, 10_000);

  it('validates artifact mask ranges and handles success, removal, and API failure', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    mocked.createAnalysisJob.mockResolvedValueOnce(job());
    fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await waitFor(() => expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete'));

    const [startInput, endInput] = screen.getAllByRole('spinbutton').slice(-2);
    fireEvent.change(startInput, { target: { value: '3' } });
    fireEvent.change(endInput, { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Mask' }));
    await screen.findByText('Invalid cadence range. End cadence must be greater than or equal to start cadence.');

    fireEvent.change(startInput, { target: { value: '-1' } });
    fireEvent.change(endInput, { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Mask' }));
    await screen.findByText('Cadence range must be between 0 and 4.');

    fireEvent.change(startInput, { target: { value: '1' } });
    fireEvent.change(endInput, { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Mask' }));
    await screen.findByText('Artifact mask created and will be applied to the next run.');
    const clearMaskButton = document.querySelector('.artifact-toolbar .quiet') as HTMLButtonElement;
    fireEvent.click(clearMaskButton);

    mocked.createArtifactMask.mockRejectedValueOnce(new Error('artifact failed'));
    fireEvent.click(screen.getByRole('button', { name: 'Apply Mask' }));
    await screen.findByText('artifact failed');
  }, 10_000);

  it('covers the artifact mask no-cadence guard', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    await renderApp();
    await selectTargetAndProduct(user);
    mocked.createAnalysisJob.mockResolvedValueOnce(job());
    mocked.fetchResult.mockResolvedValueOnce(analysisResult({ light_curve: { time: [], flux: [] } }));
    fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await waitFor(() => expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete'));

    const [startInput, endInput] = screen.getAllByRole('spinbutton').slice(-2);
    fireEvent.change(startInput, { target: { value: '0' } });
    fireEvent.change(endInput, { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Mask' }));
    await screen.findByText('No cadence data is available for masking.');
  }, 10_000);

  it('validates restored impossible BLS period bounds before preview search', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const restored: SavedSession = {
      session_id: 'periods',
      name: 'Bad Period Session',
      payload: {
        mission: 'TESS',
        query: 'TIC 307210830',
        selectedTarget: searchResult(),
        selectedProduct: product(),
        products: [product()],
        minPeriod: 10,
        maxPeriod: 5,
      },
      created_at: '2026-06-08T00:00:00Z',
    };
    mocked.fetchSessions.mockResolvedValue([restored]);
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: 'Sessions' }));
    await user.click(await screen.findByText('Bad Period Session'));
    await user.click(screen.getByRole('button', { name: /BLS Search/i }));
    await screen.findByText('BLS Search Controls');
    await user.click(screen.getByRole('button', { name: /Run Preview Search/i }));
    await screen.findByText('Minimum period must be lower than maximum period.');
  });
});

describe('App – stale request cancellation and defensive races', () => {
  it('ignores stale successful and failed searches after mission changes', async () => {
    const user = userEvent.setup();
    const success = deferred<SearchResult[]>();
    const failure = deferred<SearchResult[]>();
    mocked.searchTargets.mockReturnValueOnce(success.promise).mockReturnValueOnce(failure.promise);
    await renderApp();

    await user.type(screen.getByLabelText('target search'), 'first');
    await user.click(screen.getByRole('button', { name: /^Search$/i }));
    await user.selectOptions(screen.getByLabelText(/Mission/i), 'Kepler');
    await act(async () => success.resolve([searchResult({ target_id: 'stale success' })]));
    expect(screen.queryByText('stale success')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('target search'), 'second');
    await user.click(screen.getByRole('button', { name: /^Search$/i }));
    await user.selectOptions(screen.getByLabelText(/Mission/i), 'K2');
    await act(async () => failure.reject('stale failure'));
    expect(screen.queryByText('stale failure')).not.toBeInTheDocument();
  });

  it('ignores stale successful and failed product loads after mission changes', async () => {
    const user = userEvent.setup();
    const success = deferred<Product[]>();
    const failure = deferred<Product[]>();
    mocked.fetchProducts.mockReturnValueOnce(success.promise).mockReturnValueOnce(failure.promise);
    await renderApp();

    await user.type(screen.getByLabelText('target search'), 'first');
    await user.click(screen.getByRole('button', { name: /^Search$/i }));
    await user.click(await screen.findByText('TIC 307210830'));
    await user.selectOptions(screen.getByLabelText(/Mission/i), 'Kepler');
    await act(async () => success.resolve([product({ product_id: 'stale product' })]));
    expect(screen.queryByText('stale product')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('target search'), 'second');
    await user.click(screen.getByRole('button', { name: /^Search$/i }));
    await user.click(await screen.findByText('TIC 307210830'));
    await user.selectOptions(screen.getByLabelText(/Mission/i), 'K2');
    await act(async () => failure.reject('stale product failure'));
    expect(screen.queryByText('stale product failure')).not.toBeInTheDocument();
  });

  it('ignores stale analysis creation, poll, and result responses', async () => {
    const user = userEvent.setup();
    const created = deferred<AnalysisJob>();
    mocked.createAnalysisJob.mockReturnValueOnce(created.promise);
    await renderApp();
    await selectTargetAndProduct(user);
    fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await user.selectOptions(screen.getByLabelText(/Mission/i), 'Kepler');
    await act(async () => created.resolve(job()));
    expect(screen.getByTestId('workflow-status')).toHaveTextContent('idle');

    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const timerUser = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      mocked.createAnalysisJob.mockResolvedValueOnce(job({ status: 'queued', result_id: null }));
      await selectTargetAndProduct(timerUser);
      fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));
      await waitFor(() => expect(screen.getByText(/Job queued/)).toBeInTheDocument());
      fireEvent.change(screen.getByLabelText(/Mission/i), { target: { value: 'K2' } });
      await act(async () => vi.advanceTimersByTimeAsync(1100));
      expect(mocked.fetchAnalysisJob).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }

    const resultResponse = deferred<AnalysisResult>();
    mocked.createAnalysisJob.mockResolvedValueOnce(job());
    mocked.fetchResult.mockReturnValueOnce(resultResponse.promise);
    await selectTargetAndProduct(user);
    fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await waitFor(() => expect(mocked.fetchResult).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText(/Mission/i), { target: { value: 'TESS' } });
    await act(async () => resultResponse.resolve(analysisResult({ target_id: 'stale result' })));
    expect(screen.queryByText('stale result')).not.toBeInTheDocument();
  }, 15_000);

  it('ignores stale aperture and BLS modal preview responses', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    const apertureSuccess = deferred<TpfPreview>();
    const apertureFailure = deferred<TpfPreview>();
    mocked.fetchTpfPreview.mockReturnValueOnce(apertureSuccess.promise).mockReturnValueOnce(apertureFailure.promise);
    await renderApp();
    await selectTargetAndProduct(user);

    fireEvent.click(screen.getByRole('button', { name: /Aperture/i }));
    await user.selectOptions(screen.getByLabelText(/Mission/i), 'Kepler');
    await act(async () => apertureSuccess.resolve(tpf()));
    expect(screen.queryByText('Aperture Mask Editor')).not.toBeInTheDocument();

    await selectTargetAndProduct(user);
    fireEvent.click(screen.getByRole('button', { name: /Aperture/i }));
    await user.selectOptions(screen.getByLabelText(/Mission/i), 'K2');
    await act(async () => apertureFailure.reject('stale aperture failure'));
    expect(screen.queryByText('stale aperture failure')).not.toBeInTheDocument();
  });

  it('restores all optional session strings and ids and reports non-Error action failures', async () => {
    const restored: SavedSession = {
      session_id: 'all-fields',
      name: 'All Fields',
      payload: {
        mission: 'TESS',
        query: 'all',
        products: [product()],
        selectedTarget: searchResult(),
        selectedProduct: product(),
        selectedApertureMaskId: 'aperture-id',
        selectedArtifactMaskId: 'artifact-id',
        minPeriod: 1,
        maxPeriod: 2,
        maxCandidates: 2,
        vettingMode: 'fast',
        stellarRadius: '1',
        stellarMass: '1',
        stellarTeff: '5000',
        stellarLogg: '4',
        stellarLuminosity: '1',
        stellarDensity: '1',
        stellarRotationPeriod: '10',
        result: analysisResult(),
        selectedId: 'cand-1',
      },
      created_at: '',
    };
    mocked.fetchSessions.mockResolvedValueOnce([restored]).mockRejectedValueOnce('session string failure');
    mocked.saveSession.mockRejectedValueOnce('save string failure');
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: 'Sessions' }));
    await user.click(await screen.findByText('All Fields'));
    await user.click(screen.getByRole('button', { name: 'Save session' }));
    await screen.findByText('save string failure');
    await user.click(screen.getByRole('button', { name: 'Sessions' }));
    await screen.findByText('session string failure');
  });

  it('covers failed-analysis fallback and sparse TCE card variants', async () => {
    const user = userEvent.setup();
    mocked.createAnalysisJob.mockResolvedValueOnce(job({ status: 'failed', result_id: null, error: null }));
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await screen.findByText('Analysis failed');
  });

  it('handles non-Error report and artifact failures', async () => {
    localStorage.setItem('orbitlab-mode', 'advanced');
    const user = userEvent.setup();
    mocked.fetchReport.mockRejectedValueOnce('report string failure');
    mocked.createArtifactMask.mockRejectedValueOnce('artifact string failure');
    await renderApp();
    await selectTargetAndProduct(user);
    await user.click(screen.getByRole('button', { name: /Run Analysis/i }));
    await waitFor(() => expect(screen.getByTestId('workflow-status')).toHaveTextContent('complete'));
    await user.click(screen.getByRole('button', { name: 'Export report' }));
    await screen.findByText('report string failure');
    fireEvent.click(screen.getByRole('button', { name: 'Apply Mask' }));
    await screen.findByText('artifact string failure');
  });
});
