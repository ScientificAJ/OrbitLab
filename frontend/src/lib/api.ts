export type Candidate = {
  candidate_id: string;
  period: number;
  epoch: number;
  duration: number;
  depth: number;
  signal_to_noise: number;
  raw_snr?: number | null;
  red_noise_beta?: number | null;
  effective_snr?: number | null;
  final_score?: number | null;
  evidence?: Record<string, unknown>;
  evidence_scores?: Record<string, unknown>;
  explanation?: string[];
  physics?: {
    radius_ratio?: number | null;
    planet_radius_earth?: number | null;
    semi_major_axis_au?: number | null;
    equilibrium_temperature_k?: number | null;
    habitable_zone_inner_au?: number | null;
    habitable_zone_outer_au?: number | null;
    is_in_habitable_zone?: boolean | null;
    is_temperature_habitable?: boolean | null;
    habitability?: Record<string, unknown>;
    [key: string]: number | string | boolean | Record<string, unknown> | null | undefined;
  };
  validation?: {
    odd_even_depth_delta?: number | null;
    secondary_depth?: number | null;
    duration_plausible?: boolean | null;
    false_positive_flags?: string[];
    [key: string]: number | boolean | string[] | null | undefined;
  };
  period_source?: string | null;
  signal_origin?: string | null;
  catalog_match?: Record<string, unknown> | null;
  is_residual?: boolean | null;
  display_priority?: number | null;
  secondary_context?: Record<string, unknown> | null;
  period_days?: number | null;
  epoch_days?: number | null;
  duration_days?: number | null;
  depth_fraction?: number | null;
  depth_ppm?: number | null;
  detection_metrics?: Record<string, unknown>;
  vetting?: Record<string, unknown>;
  flags?: Array<{ code: string; severity: 'info' | 'warning' | 'hard_fail'; message: string }>;
  ml?: {
    probability: number | null;
    raw_ml_probability?: number | null;
    calibrated_ml_probability?: number | null;
    calibration_source?: string | null;
    calibration_method?: string | null;
    calibration_checksum?: string | null;
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

export type Tce = Candidate & {
  tce_id?: string | null;
  period_days?: number | null;
  epoch_days?: number | null;
  duration_days?: number | null;
  depth_fraction?: number | null;
  depth_ppm?: number | null;
  disposition?: 'planet_candidate' | 'borderline_tce' | 'rejected_signal' | null;
  action_label?: 'none' | 'review_needed' | 'follow_up_needed' | null;
  disposition_score?: number | null;
  final_score?: number | null;
  confidence_band?: string | null;
  flags?: Array<{ code: string; severity: 'info' | 'warning' | 'hard_fail'; message: string }>;
  detection_metrics?: Record<string, unknown>;
  aperture_stability?: Record<string, unknown>;
  vetting?: Record<string, unknown>;
  catalog_context?: Record<string, unknown>;
  fpp?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  evidence_scores?: Record<string, unknown>;
  explanation?: string[];
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
  baseline?: number;
};

export type VettingMode = 'fast' | 'deep' | 'paper';

export type AnalysisResult = {
  result_id: string;
  target_id: string;
  mission: string;
  candidates: Candidate[];
  schema_version?: string;
  pipeline_version?: string;
  science_config_hash?: string;
  search_profile?: string;
  active_science_config_keys?: string[];
  inactive_science_config_keys?: string[];
  missing_science_config_keys?: string[];
  injection_recovery?: Record<string, unknown>;
  vetting_mode?: VettingMode;
  data_quality?: Record<string, unknown>;
  tces?: Tce[];
  planet_candidates?: Tce[];
  validation_status?: string;
  engine_status?: Record<string, unknown>;
  deep_mode_progress?: Record<string, unknown>;
  periodogram: { period: number[]; power: number[]; duration?: number[] };
  folded_curves: Record<string, { phase: number[]; flux: number[] }>;
  light_curve: FluxSeries;
  bls_light_curve?: FluxSeries;
  stellar_context?: Record<string, number | string | null | undefined>;
  preprocessing?: Record<string, unknown>;
};

export type HealthStatus = {
  status: string;
  api: string;
  database: string;
  worker_mode: string;
  redis_configured: boolean;
  frontend: string;
  generated_at: string;
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
  match_type?: 'catalog' | 'alias';
  matched_query?: string | null;
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
  vetting_mode?: VettingMode;
  stellar_radius_solar?: number;
  stellar_mass_solar?: number;
  stellar_teff?: number;
  stellar_logg?: number;
  stellar_luminosity_solar?: number;
  stellar_density_solar?: number;
  stellar_rotation_period?: number;
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

export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch(`${API}/health`);
  return readJson<HealthStatus>(response);
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
  search_profile?: string;
  periodogram: { period: number[]; power: number[]; duration?: number[] };
  candidates: Candidate[];
  planet_candidates?: Tce[];
  tces?: Tce[];
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
