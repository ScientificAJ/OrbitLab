import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createAnalysisJob,
  createApertureMask,
  createArtifactMask,
  fetchAnalysisJob,
  fetchBlsPreview,
  fetchHealth,
  fetchModelStatus,
  fetchProducts,
  fetchReport,
  fetchResult,
  fetchSessions,
  fetchTpfPreview,
  saveSession,
  searchTargets,
} from './api';

// ---------------------------------------------------------------------------
// fetch mock setup
// ---------------------------------------------------------------------------
const mockFetch = vi.fn();
beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
});
afterEach(() => {
  mockFetch.mockClear();
  vi.restoreAllMocks();
});

function okJson(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function errorJson(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function errorText(status: number, text: string): Response {
  return new Response(text, { status });
}

// ---------------------------------------------------------------------------
// fetchHealth
// ---------------------------------------------------------------------------
describe('fetchHealth', () => {
  it('returns parsed health response on success', async () => {
    const payload = {
      status: 'ok',
      api: 'ok',
      database: 'ok',
      worker_mode: 'inline',
      redis_configured: false,
      frontend: 'served separately',
      generated_at: '2026-06-04T00:00:00Z',
    };
    mockFetch.mockResolvedValueOnce(okJson(payload));
    const result = await fetchHealth();
    expect(result.status).toBe('ok');
    expect(result.worker_mode).toBe('inline');
  });

  it('throws with detail message on 503', async () => {
    mockFetch.mockResolvedValueOnce(errorJson(503, 'service unavailable'));
    await expect(fetchHealth()).rejects.toThrow('service unavailable');
  });
});

// ---------------------------------------------------------------------------
// fetchModelStatus
// ---------------------------------------------------------------------------
describe('fetchModelStatus', () => {
  it('returns model statuses dict', async () => {
    const payload = { nigraha_tess: { status: 'ready' }, k2_exomac_kkt: { status: 'unavailable' } };
    mockFetch.mockResolvedValueOnce(okJson(payload));
    const result = await fetchModelStatus();
    expect(result['nigraha_tess'].status).toBe('ready');
    expect(result['k2_exomac_kkt'].status).toBe('unavailable');
  });
});

// ---------------------------------------------------------------------------
// searchTargets
// ---------------------------------------------------------------------------
describe('searchTargets', () => {
  it('sends query and mission as URL params', async () => {
    mockFetch.mockResolvedValueOnce(okJson([]));
    await searchTargets('TIC 307210830', 'TESS');
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('query=TIC+307210830');
    expect(url).toContain('mission=TESS');
  });

  it('returns list of search results', async () => {
    const results = [
      { target_id: '307210830', catalog: 'TIC', match_type: 'catalog', ra: 12.0, dec: -5.0 },
    ];
    mockFetch.mockResolvedValueOnce(okJson(results));
    const out = await searchTargets('307210830', 'TESS');
    expect(out).toHaveLength(1);
    expect(out[0].target_id).toBe('307210830');
  });

  it('throws on 502 with detail', async () => {
    mockFetch.mockResolvedValueOnce(errorJson(502, 'MAST unreachable'));
    await expect(searchTargets('bad', 'TESS')).rejects.toThrow('MAST unreachable');
  });
});

// ---------------------------------------------------------------------------
// fetchProducts
// ---------------------------------------------------------------------------
describe('fetchProducts', () => {
  it('encodes target_id in URL path', async () => {
    mockFetch.mockResolvedValueOnce(okJson([]));
    await fetchProducts('TIC 307210830', 'TESS');
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('TIC%20307210830');
    expect(url).toContain('mission=TESS');
  });

  it('returns product list', async () => {
    const products = [
      {
        product_id: 'obs-001',
        mission: 'TESS',
        description: 'Target Pixel File',
        size: 2048,
        product_uri: 'mast:TESS/product/file.fits',
      },
    ];
    mockFetch.mockResolvedValueOnce(okJson(products));
    const result = await fetchProducts('TIC 100', 'TESS');
    expect(result[0].product_id).toBe('obs-001');
  });
});

// ---------------------------------------------------------------------------
// fetchResult
// ---------------------------------------------------------------------------
describe('fetchResult', () => {
  it('encodes result_id in URL', async () => {
    const payload = {
      result_id: 'abc-123',
      target_id: 'TIC 100',
      mission: 'TESS',
      candidates: [],
      periodogram: { period: [], power: [] },
      folded_curves: {},
      light_curve: { time: [], flux: [] },
    };
    mockFetch.mockResolvedValueOnce(okJson(payload));
    const result = await fetchResult('abc-123');
    expect(result.result_id).toBe('abc-123');
    expect(result.target_id).toBe('TIC 100');
  });

  it('throws 404 detail when result not found', async () => {
    mockFetch.mockResolvedValueOnce(errorJson(404, 'result not found'));
    await expect(fetchResult('missing')).rejects.toThrow('result not found');
  });
});

// ---------------------------------------------------------------------------
// createAnalysisJob
// ---------------------------------------------------------------------------
describe('createAnalysisJob', () => {
  it('POSTs JSON and returns created job', async () => {
    const job = {
      job_id: 'job-001',
      status: 'queued',
      created_at: '2026-06-04T00:00:00Z',
      result_id: null,
      error: null,
    };
    mockFetch.mockResolvedValueOnce(okJson(job));
    const result = await createAnalysisJob({
      target_id: 'TIC 100',
      product_uri: 'mast:product',
      mission: 'TESS',
    });
    expect(result.status).toBe('queued');
    expect(result.job_id).toBe('job-001');

    const call = mockFetch.mock.calls[0];
    expect(call[1].method).toBe('POST');
    const body = JSON.parse(call[1].body as string);
    expect(body.target_id).toBe('TIC 100');
    expect(body.mission).toBe('TESS');
  });

  it('includes optional stellar context when provided', async () => {
    mockFetch.mockResolvedValueOnce(
      okJson({ job_id: 'j2', status: 'queued', created_at: '', result_id: null, error: null }),
    );
    await createAnalysisJob({
      target_id: 'TIC 200',
      product_uri: 'mast:p2',
      mission: 'TESS',
      stellar_radius_solar: 1.2,
      stellar_teff: 5500,
      vetting_mode: 'paper',
    });
    const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(body.stellar_radius_solar).toBe(1.2);
    expect(body.stellar_teff).toBe(5500);
    expect(body.vetting_mode).toBe('paper');
  });

  it('throws with API error detail on 404', async () => {
    mockFetch.mockResolvedValueOnce(errorJson(404, 'aperture mask not found'));
    await expect(
      createAnalysisJob({ target_id: 'X', product_uri: 'p', mission: 'TESS', aperture_mask_id: 'bad' }),
    ).rejects.toThrow('aperture mask not found');
  });
});

// ---------------------------------------------------------------------------
// fetchAnalysisJob
// ---------------------------------------------------------------------------
describe('fetchAnalysisJob', () => {
  it('returns job status', async () => {
    mockFetch.mockResolvedValueOnce(
      okJson({ job_id: 'j3', status: 'running', created_at: '', result_id: null, error: null }),
    );
    const job = await fetchAnalysisJob('j3');
    expect(job.status).toBe('running');
  });

  it('encodes job_id in URL', async () => {
    mockFetch.mockResolvedValueOnce(
      okJson({ job_id: 'j4', status: 'complete', created_at: '', result_id: 'r1', error: null }),
    );
    await fetchAnalysisJob('special/id');
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('special%2Fid');
  });
});

// ---------------------------------------------------------------------------
// createApertureMask
// ---------------------------------------------------------------------------
describe('createApertureMask', () => {
  it('POSTs mask and returns aperture mask id', async () => {
    const resp = {
      aperture_mask_id: 'am-001',
      target_id: 'TIC 300',
      product_uri: 'mast:p',
      mask: [[true, false]],
      reason: 'test',
      created_at: '',
    };
    mockFetch.mockResolvedValueOnce(okJson(resp));
    const result = await createApertureMask({
      target_id: 'TIC 300',
      product_uri: 'mast:p',
      mask: [[true, false]],
      reason: 'test',
    });
    expect(result.aperture_mask_id).toBe('am-001');
    expect(mockFetch.mock.calls[0][1].method).toBe('POST');
  });

  it('throws 422 with validation error detail', async () => {
    mockFetch.mockResolvedValueOnce(errorJson(422, 'aperture mask must select at least one pixel'));
    await expect(
      createApertureMask({ target_id: 'TIC 300', product_uri: 'p', mask: [[false]], reason: 'r' }),
    ).rejects.toThrow('aperture mask must select at least one pixel');
  });
});

// ---------------------------------------------------------------------------
// createArtifactMask
// ---------------------------------------------------------------------------
describe('createArtifactMask', () => {
  it('POSTs artifact mask and returns mask_id', async () => {
    const resp = { mask_id: 'art-001', target_id: 'TIC 400', indices: [0, 5], reason: 'cr', created_at: '' };
    mockFetch.mockResolvedValueOnce(okJson(resp));
    const result = await createArtifactMask({ target_id: 'TIC 400', indices: [0, 5], reason: 'cr' });
    expect(result.mask_id).toBe('art-001');
    expect(result.indices).toEqual([0, 5]);
  });
});

// ---------------------------------------------------------------------------
// fetchBlsPreview
// ---------------------------------------------------------------------------
describe('fetchBlsPreview', () => {
  it('POSTs and returns preview result', async () => {
    const resp = {
      search_profile: 'preview_fast',
      periodogram: { period: [1.0], power: [9.0], duration: [0.08] },
      candidates: [],
      tces: [],
      folded_curves: {},
      bls_light_curve: { time: [0, 1], flux: [1, 1] },
      preprocessing: {},
    };
    mockFetch.mockResolvedValueOnce(okJson(resp));
    const result = await fetchBlsPreview({ product_uri: 'mast:p', mission: 'TESS' });
    expect(result.search_profile).toBe('preview_fast');
    expect(result.periodogram.period).toEqual([1.0]);
  });

  it('passes optional fields in body', async () => {
    mockFetch.mockResolvedValueOnce(
      okJson({
        periodogram: { period: [], power: [] },
        candidates: [],
        folded_curves: {},
        bls_light_curve: { time: [], flux: [] },
        preprocessing: {},
      }),
    );
    await fetchBlsPreview({
      product_uri: 'mast:p',
      mission: 'TESS',
      target_id: 'TIC 100',
      min_period: 0.5,
      max_period: 10.0,
      max_candidates: 4,
    });
    const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(body.target_id).toBe('TIC 100');
    expect(body.min_period).toBe(0.5);
    expect(body.max_candidates).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// fetchTpfPreview
// ---------------------------------------------------------------------------
describe('fetchTpfPreview', () => {
  it('sends product_uri as query param', async () => {
    mockFetch.mockResolvedValueOnce(
      okJson({ shape: [5, 5], image: [[0]], finite_min: 0, finite_max: 100, baseline: 27.0 }),
    );
    await fetchTpfPreview('mast:some/product.fits');
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('product_uri=');
    expect(url).toContain('tpf-preview');
  });
});

// ---------------------------------------------------------------------------
// saveSession / fetchSessions
// ---------------------------------------------------------------------------
describe('sessions', () => {
  it('saveSession POSTs and returns saved session', async () => {
    const resp = {
      session_id: 's-001',
      name: 'My Analysis',
      payload: { target: 'TIC 100' },
      created_at: '',
    };
    mockFetch.mockResolvedValueOnce(okJson(resp));
    const result = await saveSession({ name: 'My Analysis', payload: { target: 'TIC 100' } });
    expect(result.session_id).toBe('s-001');
    expect(result.name).toBe('My Analysis');
  });

  it('fetchSessions returns array of sessions', async () => {
    const sessions = [
      { session_id: 's-1', name: 'A', payload: {}, created_at: '' },
      { session_id: 's-2', name: 'B', payload: {}, created_at: '' },
    ];
    mockFetch.mockResolvedValueOnce(okJson(sessions));
    const result = await fetchSessions();
    expect(result).toHaveLength(2);
    expect(result[0].session_id).toBe('s-1');
  });
});

// ---------------------------------------------------------------------------
// fetchReport
// ---------------------------------------------------------------------------
describe('fetchReport', () => {
  it('encodes report_id and returns report payload', async () => {
    const report = { report_id: 'r-001', generated_at: '', format: 'json', result: { target_id: 'TIC 100' } };
    mockFetch.mockResolvedValueOnce(okJson(report));
    const result = await fetchReport('r-001');
    expect(result['report_id']).toBe('r-001');
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('r-001');
  });

  it('throws 404 when report not found', async () => {
    mockFetch.mockResolvedValueOnce(errorJson(404, 'report not found'));
    await expect(fetchReport('missing')).rejects.toThrow('report not found');
  });
});

// ---------------------------------------------------------------------------
// formatApiErrorDetail — exercises the error parsing inside readJson
// ---------------------------------------------------------------------------
describe('error detail parsing', () => {
  it('surfaces FastAPI validation error array as joined string', async () => {
    const detail = [
      { loc: ['body', 'target_id'], msg: 'field required', type: 'missing' },
      { loc: ['body', 'mission'], msg: 'field required', type: 'missing' },
    ];
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail }), {
        status: 422,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    await expect(fetchHealth()).rejects.toThrow(/field required/);
  });

  it('surfaces plain text error when body is not JSON', async () => {
    mockFetch.mockResolvedValueOnce(errorText(500, 'Internal Server Error'));
    await expect(fetchHealth()).rejects.toThrow('Internal Server Error');
  });
});
