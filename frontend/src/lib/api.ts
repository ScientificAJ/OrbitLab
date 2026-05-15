export type Candidate = {
  candidate_id: string;
  period: number;
  epoch: number;
  duration: number;
  depth: number;
  signal_to_noise: number;
  physics?: {
    radius_ratio?: number | null;
    planet_radius_earth?: number | null;
    semi_major_axis_au?: number | null;
    equilibrium_temperature_k?: number | null;
    habitable_zone_inner_au?: number | null;
    habitable_zone_outer_au?: number | null;
    is_in_habitable_zone?: boolean | null;
    is_temperature_habitable?: boolean | null;
    [key: string]: number | string | boolean | null | undefined;
  };
  validation?: {
    odd_even_depth_delta?: number | null;
    secondary_depth?: number | null;
    duration_plausible?: boolean | null;
    [key: string]: number | boolean | null | undefined;
  };
  ml?: {
    probability: number | null;
    threshold: number | null;
    label: string;
    model_version: string;
    model_source: string;
    input_tensor_checksum: string | null;
    preprocessing_compatible: boolean;
    citation: string;
    class_probabilities?: Record<string, number>;
  };
};

export type FluxSeries = {
  time: number[];
  flux: number[];
};

export type TpfPreview = {
  shape: number[];
  image: number[][];
  finite_min?: number;
  finite_max?: number;
};

export type AnalysisResult = {
  result_id: string;
  target_id: string;
  mission: string;
  candidates: Candidate[];
  periodogram: { period: number[]; power: number[]; duration?: number[] };
  folded_curves: Record<string, { phase: number[]; flux: number[] }>;
  light_curve: FluxSeries;
  bls_light_curve?: FluxSeries;
  preprocessing?: Record<string, unknown>;
};

export type ModelStatus = {
  model_id?: string;
  version?: string;
  source?: string;
  checksum?: string;
  schema_version?: string;
  status: string;
  detail?: string;
};

export type ModelStatuses = Record<string, ModelStatus>;

export type SearchResult = {
  target_id: string;
  ra?: number | null;
  dec?: number | null;
  catalog: string;
};

export type Product = {
  product_id: string;
  mission: string;
  description: string;
  size?: number | null;
  product_uri: string;
};

export type AnalysisJob = {
  job_id: string;
  status: 'queued' | 'running' | 'complete' | 'failed';
  created_at: string;
  result_id?: string | null;
  error?: string | null;
};

export type AnalysisJobCreate = {
  target_id: string;
  product_uri: string;
  mission: 'TESS' | 'Kepler' | 'K2';
  max_candidates?: number;
  stellar_radius_solar?: number;
  stellar_mass_solar?: number;
  aperture_mask_id?: string;
  artifact_mask_id?: string;
};

export type SavedSession = {
  session_id: string;
  name: string;
  payload: Record<string, unknown>;
  created_at: string;
};

const API = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, '');

function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item);
        const record = item as Record<string, unknown>;
        const location = Array.isArray(record.loc) ? record.loc.join('.') : undefined;
        const message = typeof record.msg === 'string' ? record.msg : JSON.stringify(record);
        return location ? `${location}: ${message}` : message;
      })
      .join('; ');
  }

  if (detail && typeof detail === 'object') {
    return JSON.stringify(detail);
  }

  return fallback || 'Request failed';
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();

    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new Error(text || `Request failed with status ${response.status}`);
    }

    const detail = parsed && typeof parsed === 'object' && 'detail' in parsed ? parsed.detail : undefined;
    throw new Error(formatApiErrorDetail(detail, text));
  }

  return response.json();
}

export async function fetchModelStatus(): Promise<ModelStatuses> {
  const response = await fetch(`${API}/models`);
  return readJson<ModelStatuses>(response);
}

export async function fetchResult(resultId: string): Promise<AnalysisResult> {
  const response = await fetch(`${API}/analysis-results/${encodeURIComponent(resultId)}`);
  return readJson<AnalysisResult>(response);
}

export async function searchTargets(query: string, mission: string): Promise<SearchResult[]> {
  const params = new URLSearchParams({ query, mission });
  const response = await fetch(`${API}/search?${params.toString()}`);
  return readJson<SearchResult[]>(response);
}

export async function fetchProducts(targetId: string, mission: string): Promise<Product[]> {
  const params = new URLSearchParams({ mission });
  const response = await fetch(`${API}/targets/${encodeURIComponent(targetId)}/products?${params.toString()}`);
  return readJson<Product[]>(response);
}

export async function createAnalysisJob(payload: AnalysisJobCreate): Promise<AnalysisJob> {
  const response = await fetch(`${API}/analysis-jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<AnalysisJob>(response);
}

export async function fetchAnalysisJob(jobId: string): Promise<AnalysisJob> {
  const response = await fetch(`${API}/analysis-jobs/${encodeURIComponent(jobId)}`);
  return readJson<AnalysisJob>(response);
}

export async function saveSession(payload: { name: string; payload: Record<string, unknown> }): Promise<SavedSession> {
  const response = await fetch(`${API}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<SavedSession>(response);
}

export async function fetchSessions(): Promise<SavedSession[]> {
  const response = await fetch(`${API}/sessions`);
  return readJson<SavedSession[]>(response);
}

export async function fetchReport(reportId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API}/reports/${encodeURIComponent(reportId)}`);
  return readJson<Record<string, unknown>>(response);
}

export async function fetchTpfPreview(productUri: string): Promise<TpfPreview> {
  const params = new URLSearchParams({ product_uri: productUri });
  const response = await fetch(`${API}/tpf-preview?${params.toString()}`);
  return readJson<TpfPreview>(response);
}

export async function createApertureMask(payload: {
  target_id: string;
  product_uri: string;
  mask: boolean[][];
  reason: string;
}) {
  const response = await fetch(`${API}/aperture-masks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<{
    aperture_mask_id: string;
    target_id: string;
    product_uri: string;
    mask: boolean[][];
    reason: string;
    created_at: string;
  }>(response);
}

export type BlsPreviewResult = {
  periodogram: { period: number[]; power: number[]; duration?: number[] };
  candidates: Candidate[];
  folded_curves: Record<string, { phase: number[]; flux: number[] }>;
  bls_light_curve: FluxSeries;
  preprocessing: Record<string, unknown>;
};

export async function fetchBlsPreview(payload: {
  product_uri: string;
  mission: string;
  aperture_mask_id?: string;
  min_period?: number;
  max_period?: number;
  max_candidates?: number;
}): Promise<BlsPreviewResult> {
  const response = await fetch(`${API}/bls-preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<BlsPreviewResult>(response);
}

export async function createArtifactMask(payload: { target_id: string; indices: number[]; reason: string }) {
  const response = await fetch(`${API}/artifact-masks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<{
    mask_id: string;
    target_id: string;
    indices: number[];
    reason: string;
    created_at: string;
  }>(response);
}
