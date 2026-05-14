import { Activity, Database, Download, FlaskConical, Gauge, History, Layers, Play, RefreshCw, Save, Search, SlidersHorizontal, Trash2, X } from 'lucide-react';
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { OrbitScene } from './components/OrbitScene';
import { SciencePlot } from './components/SciencePlot';
import {
  AnalysisJob,
  AnalysisResult,
  Candidate,
  Product,
  SearchResult,
  TpfPreview,
  createAnalysisJob,
  fetchAnalysisJob,
  fetchModelStatus,
  fetchProducts,
  fetchResult,
  ModelStatuses,
  searchTargets,
  saveSession,
  fetchReport,
  fetchTpfPreview,
  createApertureMask,
  fetchBlsPreview,
  createArtifactMask,
  fetchSessions,
  SavedSession,
} from './lib/api';
import './styles/app.css';

function formatNumber(value: number | null | undefined, digits = 3) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'n/a';
}

function formatTriState(value: unknown, trueLabel: string, falseLabel: string) {
  if (value === true) return trueLabel;
  if (value === false) return falseLabel;
  return 'n/a';
}

function formatScientific(value: number | null | undefined, digits = 3) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toExponential(digits) : 'n/a';
}

function CandidateCard({ candidate, active, onSelect }: { candidate: Candidate; active: boolean; onSelect: () => void }) {
  return (
    <button className={`candidate-card ${active ? 'active' : ''}`} onClick={onSelect}>
      <span>{candidate.candidate_id}</span>
      <strong>{formatNumber(candidate.period, 4)} d</strong>
      <small>SNR {formatNumber(candidate.signal_to_noise, 2)} · depth {formatNumber(candidate.depth * 1_000_000, 0)} ppm</small>
    </button>
  );
}

const setupCommands: Record<string, string> = {
  nigraha_tess: 'scripts/fetch_nigraha_weights.py',
  kepler_astronet: 'scripts/fetch_kepler_astronet.py',
  k2_exomac_kkt: 'scripts/fetch_k2_exomac_kkt.py',
  k2_astronet: 'No public K2 checkpoint registered yet.',
};

const MIN_PERIOD_FLOOR = 0.2;
const MAX_PERIOD_CEILING = 60;
const ANALYSIS_POLL_LIMIT = Number(import.meta.env.VITE_ANALYSIS_POLL_LIMIT ?? 120);
const ANALYSIS_POLL_INTERVAL_MS = Number(import.meta.env.VITE_ANALYSIS_POLL_INTERVAL_MS ?? 1000);

type Mission = 'TESS' | 'Kepler' | 'K2';

export default function App() {
  const [mission, setMission] = useState<Mission>('TESS');
  const [query, setQuery] = useState('');
  const [targets, setTargets] = useState<SearchResult[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedTarget, setSelectedTarget] = useState<SearchResult | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [productsLoading, setProductsLoading] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [model, setModel] = useState<ModelStatuses | null>(null);
  const [workflow, setWorkflow] = useState<'idle' | 'searching' | 'product-selected' | 'running' | 'complete' | 'failed'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [showApertureModal, setShowApertureModal] = useState(false);
  const [tpfPreview, setTpfPreview] = useState<TpfPreview | null>(null);
  const [apertureMask, setApertureMask] = useState<boolean[][]>([]);
  const [selectedApertureMaskId, setSelectedApertureMaskId] = useState<string | undefined>();

  const [showBlsModal, setShowBlsModal] = useState(false);
  const [minPeriod, setMinPeriod] = useState(0.5);
  const [maxPeriod, setMaxPeriod] = useState(30.0);
  const [blsRunning, setBlsRunning] = useState(false);

  const [showModelModal, setShowModelModal] = useState(false);
  const [showSessionsModal, setShowSessionsModal] = useState(false);
  const [sessions, setSessions] = useState<SavedSession[]>([]);

  const [selectedArtifactMaskId, setSelectedArtifactMaskId] = useState<string | undefined>();
  const [cadenceStart, setCadenceStart] = useState<number>(0);
  const [cadenceEnd, setCadenceEnd] = useState<number>(0);

  const analysisToken = useRef<number>(0);
  const searchToken = useRef<number>(0);
  const productToken = useRef<number>(0);
  const apertureToken = useRef<number>(0);
  const blsPreviewToken = useRef<number>(0);
  const successTimeout = useRef<number | undefined>(undefined);

  useEffect(() => {
    refreshModelStatus();
    return () => {
      if (successTimeout.current) {
        window.clearTimeout(successTimeout.current);
      }
    };
  }, []);

  async function refreshModelStatus() {
    try {
      const status = await fetchModelStatus();
      setModel(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function showSuccessMessage(message: string) {
    if (successTimeout.current) {
      window.clearTimeout(successTimeout.current);
    }
    setSuccess(message);
    successTimeout.current = window.setTimeout(() => setSuccess(null), 3000);
  }

  const selected = useMemo(() => {
    return result?.candidates.find((candidate) => candidate.candidate_id === selectedId) ?? result?.candidates[0];
  }, [result, selectedId]);

  const folded = selected && result ? result.folded_curves[selected.candidate_id] : undefined;
  const activeModel = mission === 'TESS' ? model?.nigraha_tess : mission === 'Kepler' ? model?.kepler_astronet : model?.k2_exomac_kkt;
  const activeModelStatus = typeof activeModel?.status === 'string' ? activeModel.status : 'unknown';
  const activeModelSource = typeof activeModel?.source === 'string' ? activeModel.source : typeof activeModel?.detail === 'string' ? activeModel.detail : 'n/a';

  const pixelScale = useMemo(() => {
    if (!tpfPreview) return { min: 0, span: 1 };

    const finitePixels = tpfPreview.image.flat().filter(Number.isFinite);
    const fallbackMin = finitePixels.length ? Math.min(...finitePixels) : 0;
    const fallbackMax = finitePixels.length ? Math.max(...finitePixels) : 1;

    const min = Number.isFinite(tpfPreview.finite_min) ? Number(tpfPreview.finite_min) : fallbackMin;
    const max = Number.isFinite(tpfPreview.finite_max) ? Number(tpfPreview.finite_max) : fallbackMax;

    return { min, span: max > min ? max - min : 1 };
  }, [tpfPreview]);

  function aperturePixelOpacity(value: number) {
    if (!Number.isFinite(value)) return 0.2;
    const normalized = Math.min(1, Math.max(0, (value - pixelScale.min) / pixelScale.span));
    return 0.2 + normalized * 0.8;
  }

  function changeMission(next: 'TESS' | 'Kepler' | 'K2') {
    searchToken.current += 1;
    productToken.current += 1;
    analysisToken.current += 1;
    apertureToken.current += 1;
    blsPreviewToken.current += 1;
    setMission(next);
    setTargets([]);
    setHasSearched(false);
    setSelectedTarget(null);
    setProducts([]);
    setProductsLoading(false);
    setSelectedProduct(null);
    setJob(null);
    setResult(null);
    setSelectedId(undefined);
    setJob(null);
    setWorkflow('idle');
    setError(null);
    setSuccess(null);
    setSelectedApertureMaskId(undefined);
    setSelectedArtifactMaskId(undefined);
    setTpfPreview(null);
    setApertureMask([]);
    setShowApertureModal(false);
    setShowBlsModal(false);
  }

  function updateMinPeriod(value: number) {
    const next = Math.min(Math.max(value, MIN_PERIOD_FLOOR), maxPeriod - 0.1);
    setMinPeriod(Number(next.toFixed(2)));
  }

  function updateMaxPeriod(value: number) {
    const next = Math.max(Math.min(value, MAX_PERIOD_CEILING), minPeriod + 0.1);
    setMaxPeriod(Number(next.toFixed(2)));
  }

  async function runSearch() {
    const trimmedQuery = query.trim();
    if (!trimmedQuery) return;
    const token = ++searchToken.current;
    productToken.current += 1;
    analysisToken.current += 1;
    apertureToken.current += 1;
    blsPreviewToken.current += 1;
    setError(null);
    setSuccess(null);
    setWorkflow('searching');
    setSelectedTarget(null);
    setSelectedProduct(null);
    setProducts([]);
    setProductsLoading(false);
    setResult(null);
    setSelectedId(undefined);
    setJob(null);
    setSelectedApertureMaskId(undefined);
    setSelectedArtifactMaskId(undefined);
    setTpfPreview(null);
    setApertureMask([]);
    try {
      const payload = await searchTargets(trimmedQuery, mission);
      if (token !== searchToken.current) return;
      setTargets(payload);
      setHasSearched(true);
      setWorkflow('idle');
    } catch (err) {
      if (token !== searchToken.current) return;
      setHasSearched(true);
      setError(err instanceof Error ? err.message : String(err));
      setWorkflow('failed');
    }
  }

  async function chooseTarget(target: SearchResult) {
    const token = ++productToken.current;
    analysisToken.current += 1;
    apertureToken.current += 1;
    blsPreviewToken.current += 1;
    setError(null);
    setSuccess(null);
    setSelectedTarget(target);
    setSelectedProduct(null);
    setProducts([]);
    setResult(null);
    setSelectedId(undefined);
    setJob(null);
    setSelectedApertureMaskId(undefined);
    setSelectedArtifactMaskId(undefined);
    setTpfPreview(null);
    setApertureMask([]);
    setProductsLoading(true);
    try {
      const payload = await fetchProducts(target.target_id, mission);
      if (token !== productToken.current) return;
      setProducts(payload);
      setWorkflow('idle');
    } catch (err) {
      if (token !== productToken.current) return;
      setError(err instanceof Error ? err.message : String(err));
      setWorkflow('failed');
    } finally {
      if (token === productToken.current) {
        setProductsLoading(false);
      }
    }
  }

  function chooseProduct(product: Product) {
    analysisToken.current += 1;
    apertureToken.current += 1;
    blsPreviewToken.current += 1;
    setSelectedProduct(product);
    setWorkflow('product-selected');
    setJob(null);
    setResult(null);
    setSelectedId(undefined);
    setSelectedApertureMaskId(undefined);
    setSelectedArtifactMaskId(undefined);
    setTpfPreview(null);
    setApertureMask([]);
    setCadenceStart(0);
    setCadenceEnd(0);
  }

  async function runAnalysis() {
    if (!selectedTarget || !selectedProduct?.product_uri) return;
    setError(null);
    setSuccess(null);
    setWorkflow('running');
    setResult(null);
    const token = ++analysisToken.current;
    try {
      const created = await createAnalysisJob({
        target_id: selectedTarget.target_id,
        product_uri: selectedProduct.product_uri,
        mission,
        max_candidates: 4,
        aperture_mask_id: selectedApertureMaskId,
        artifact_mask_id: selectedArtifactMaskId,
      });
      if (token !== analysisToken.current) return;
      setJob(created);
      let current = created;
      for (let index = 0; index < ANALYSIS_POLL_LIMIT && current.status !== 'complete' && current.status !== 'failed'; index += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, ANALYSIS_POLL_INTERVAL_MS));
        if (token !== analysisToken.current) return;
        current = await fetchAnalysisJob(current.job_id);
        setJob(current);
      }
      if (current.status === 'failed') {
        setError(current.error ?? 'Analysis failed');
        setWorkflow('failed');
        return;
      }
      if (!current.result_id) {
        setWorkflow('running');
        setError('Analysis is still running. Use Refresh Job Status to continue polling this job.');
        return;
      }
      const payload = await fetchResult(current.result_id);
      if (token !== analysisToken.current) return;
      setResult(payload);
      setSelectedId(payload.candidates[0]?.candidate_id);
      setWorkflow('complete');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setWorkflow('failed');
    }
  }

  async function refreshCurrentJob() {
    if (!job) return;

    const token = ++analysisToken.current;
    setError(null);

    try {
      const current = await fetchAnalysisJob(job.job_id);
      if (token !== analysisToken.current) return;

      setJob(current);

      if (current.status === 'failed') {
        setWorkflow('failed');
        setError(current.error ?? 'Analysis failed.');
        return;
      }

      if (current.status !== 'complete' || !current.result_id) {
        setWorkflow('running');
        return;
      }

      const payload = await fetchResult(current.result_id);
      if (token !== analysisToken.current) return;

      setResult(payload);
      setSelectedId(payload.candidates[0]?.candidate_id);
      setWorkflow('complete');
    } catch (err) {
      if (token !== analysisToken.current) return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleSaveSession() {
    if (!selectedTarget) return;
    setError(null);
    try {
      const name = `${mission}-${selectedTarget.target_id}-${new Date().toISOString().slice(0, 16).replace('T', ' ')}`;
      await saveSession({
        name,
        payload: {
          mission,
          query,
          products,
          selectedTarget,
          selectedProduct,
          selectedApertureMaskId,
          selectedArtifactMaskId,
          minPeriod,
          maxPeriod,
          result,
          selectedId,
          workflow,
        },
      });
      showSuccessMessage('Session saved successfully.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function openSessionsModal() {
    try {
      const payload = await fetchSessions();
      setSessions(payload);
      setShowSessionsModal(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function restoreSession(session: SavedSession) {
    const payload = session.payload as Record<string, unknown>;

    analysisToken.current += 1;
    searchToken.current += 1;
    productToken.current += 1;
    apertureToken.current += 1;
    blsPreviewToken.current += 1;

    const restoredResult = (payload.result as AnalysisResult | null | undefined) ?? null;
    const restoredProduct = (payload.selectedProduct as Product | null | undefined) ?? null;
    const restoredTarget = (payload.selectedTarget as SearchResult | null | undefined) ?? null;

    setMission((payload.mission as Mission) ?? 'TESS');
    setQuery(typeof payload.query === 'string' ? payload.query : '');
    setProducts(Array.isArray(payload.products) ? (payload.products as Product[]) : []);
    setSelectedTarget(restoredTarget);
    setTargets(restoredTarget ? [restoredTarget] : []);
    setHasSearched(Boolean(restoredTarget));
    setSelectedProduct(restoredProduct);
    setSelectedApertureMaskId(typeof payload.selectedApertureMaskId === 'string' ? payload.selectedApertureMaskId : undefined);
    setSelectedArtifactMaskId(typeof payload.selectedArtifactMaskId === 'string' ? payload.selectedArtifactMaskId : undefined);
    setMinPeriod(Number.isFinite(payload.minPeriod) ? Number(payload.minPeriod) : 0.5);
    setMaxPeriod(Number.isFinite(payload.maxPeriod) ? Number(payload.maxPeriod) : 30);
    setResult(restoredResult);
    setSelectedId(typeof payload.selectedId === 'string' ? payload.selectedId : restoredResult?.candidates[0]?.candidate_id);
    setJob(null);

    if (restoredResult) {
      setWorkflow('complete');
    } else if (restoredProduct) {
      setWorkflow('product-selected');
    } else {
      setWorkflow('idle');
    }

    setShowSessionsModal(false);
    showSuccessMessage(`Restored session ${session.name}`);
  }

  async function handleExportReport() {
    if (!result?.result_id || result.result_id === 'preview') {
      setError('Run a full analysis before exporting a report.');
      return;
    }
    setError(null);
    try {
      const report = await fetchReport(result.result_id);
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `orbitlab-report-${result.target_id}-${result.result_id.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showSuccessMessage('Report exported successfully.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function openApertureModal() {
    if (!selectedProduct || workflow === 'running') return;

    const token = ++apertureToken.current;
    const productUri = selectedProduct.product_uri;

    setError(null);

    try {
      const preview = await fetchTpfPreview(productUri);

      if (token !== apertureToken.current) return;

      setTpfPreview(preview);
      setApertureMask(Array.from({ length: preview.shape[0] }, () => Array(preview.shape[1]).fill(false)));
      setShowApertureModal(true);
    } catch (err) {
      if (token !== apertureToken.current) return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleCreateApertureMask() {
    if (!selectedTarget || !selectedProduct || !tpfPreview) return;
    setError(null);
    if (!apertureMask.flat().some(p => p)) {
      setError('Please select at least one pixel for the aperture mask.');
      return;
    }
    try {
      const created = await createApertureMask({
        target_id: selectedTarget.target_id,
        product_uri: selectedProduct.product_uri,
        mask: apertureMask,
        reason: 'User defined aperture in OrbitLab',
      });
      setSelectedApertureMaskId(created.aperture_mask_id);
      setShowApertureModal(false);
      setError(null);
      showSuccessMessage('Custom aperture mask created.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function runBlsPreview() {
    if (!selectedProduct || workflow === 'running') return;

    const token = ++blsPreviewToken.current;
    const productUri = selectedProduct.product_uri;
    const targetId = selectedTarget?.target_id ?? 'unknown';
    const missionAtRequest = mission;
    const apertureMaskId = selectedApertureMaskId;

    setError(null);
    setSuccess(null);

    if (minPeriod >= maxPeriod) {
      setError('Minimum period must be lower than maximum period.');
      return;
    }

    setBlsRunning(true);

    try {
      const payload = await fetchBlsPreview({
        product_uri: productUri,
        mission: missionAtRequest,
        aperture_mask_id: apertureMaskId,
        min_period: minPeriod,
        max_period: maxPeriod,
      });

      if (token !== blsPreviewToken.current) return;

      setResult({
        result_id: 'preview',
        target_id: targetId,
        mission: missionAtRequest,
        candidates: payload.candidates,
        periodogram: payload.periodogram,
        folded_curves: payload.folded_curves,
        light_curve: payload.bls_light_curve,
        bls_light_curve: payload.bls_light_curve,
        preprocessing: payload.preprocessing,
      });

      setSelectedId(payload.candidates[0]?.candidate_id);
      setWorkflow('complete');
      setShowBlsModal(false);
    } catch (err) {
      if (token !== blsPreviewToken.current) return;
      setError(err instanceof Error ? err.message : String(err));
      setWorkflow('failed');
    } finally {
      if (token === blsPreviewToken.current) {
        setBlsRunning(false);
      }
    }
  }

  async function handleCreateArtifactMask() {
    if (!selectedTarget || !result) return;

    setError(null);

    const cadenceCount = result.light_curve.time.length;
    const start = Math.floor(cadenceStart);
    const end = Math.floor(cadenceEnd);

    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      setError('Cadence range must contain valid numbers.');
      return;
    }

    if (end < start) {
      setError('Invalid cadence range. End cadence must be greater than or equal to start cadence.');
      return;
    }

    if (cadenceCount <= 0) {
      setError('No cadence data is available for masking.');
      return;
    }

    if (start < 0 || end >= cadenceCount) {
      setError(`Cadence range must be between 0 and ${cadenceCount - 1}.`);
      return;
    }

    try {
      const indices = Array.from({ length: end - start + 1 }, (_, i) => start + i);
      const created = await createArtifactMask({
        target_id: selectedTarget.target_id,
        indices,
        reason: 'User selected noisy cadence range',
      });

      setSelectedArtifactMaskId(created.mask_id);
      setCadenceStart(start);
      setCadenceEnd(end);
      setError(null);
      showSuccessMessage('Artifact mask created and will be applied to the next run.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <main className="shell">
      <header className="command-bar">
        <div className="brand">
          <Activity size={22} />
          <div>
            <strong>OrbitLab</strong>
            <span>Real TPF exoplanet workbench</span>
          </div>
        </div>
        <div className="search-strip">
          <Search size={16} />
          <label className="sr-only" htmlFor="target-search">Target search</label>
          <input id="target-search" name="target-search" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="target search" placeholder="Try TIC 307210830, Kepler-10, TOI-700..." />
          <button onClick={runSearch} disabled={!query.trim() || workflow === 'searching'}>
            <Search size={15} /> Search
          </button>
        </div>
        <div className="command-actions">
          <button title="Sessions" aria-label="Sessions" onClick={openSessionsModal}><History size={17} /></button>
          <button title="Save session" aria-label="Save session" onClick={handleSaveSession} disabled={!selectedTarget}><Save size={17} /></button>
          <button title="Export report" aria-label="Export report" onClick={handleExportReport} disabled={!result || result.result_id === 'preview'}><Download size={17} /></button>
        </div>
      </header>

      <section className="workspace">
        <aside className="left-rail">
          <div className="rail-section">
            <h2>Target</h2>
            <label htmlFor="mission-select">Mission</label>
            <select id="mission-select" name="mission" value={mission} onChange={(event) => changeMission(event.target.value as 'TESS' | 'Kepler' | 'K2')}>
              <option value="TESS">TESS</option>
              <option value="Kepler">Kepler</option>
              <option value="K2">K2</option>
            </select>
            <div className="field-label">Matches</div>
            <div className="selection-list">
              {targets.map((target) => (
                <button
                  key={`${target.catalog}-${target.target_id}`}
                  className={selectedTarget?.target_id === target.target_id ? 'active' : ''}
                  onClick={() => chooseTarget(target)}
                >
                  <span>{target.target_id}</span>
                  <small>{target.catalog}</small>
                </button>
              ))}
              {!targets.length && <p className="quiet">{hasSearched ? 'No matching targets found.' : 'Search for a target first.'}</p>}
            </div>
            <div className="field-label">Product</div>
            <div className="selection-list">
              {products.map((product) => (
                <button
                  key={product.product_uri}
                  className={selectedProduct?.product_uri === product.product_uri ? 'active' : ''}
                  onClick={() => chooseProduct(product)}
                >
                  <span>{product.product_id}</span>
                  <small>{product.description}</small>
                </button>
              ))}
              {productsLoading && <p className="quiet">Loading products...</p>}
              {!productsLoading && !products.length && (
                <p className="quiet">{selectedTarget ? 'No target pixel products found.' : 'Select a target first.'}</p>
              )}
            </div>
          </div>
          <div className="rail-section">
            <h2>Pipeline</h2>
            <button disabled={!selectedProduct || workflow === 'running'} onClick={openApertureModal} className={selectedApertureMaskId ? 'active-pill' : ''}>
              <SlidersHorizontal size={15} /> Aperture {selectedApertureMaskId ? '(Custom)' : ''}
            </button>
            <button disabled={!selectedProduct || workflow === 'running'} onClick={() => setShowBlsModal(true)}>
              <FlaskConical size={15} /> BLS Search
            </button>            <button disabled={!selectedProduct?.product_uri || workflow === 'running'} onClick={runAnalysis}>
              <Play size={15} /> Run Analysis
            </button>
            <button onClick={() => setShowModelModal(true)}>
              <Gauge size={15} /> ML Status {activeModelStatus}
            </button>
            {job && (
              <div className="job-status-row">
                <p className="quiet">Job {job.status}{job.result_id ? ` · ${job.result_id.slice(0, 8)}` : ''}</p>
                {job.status !== 'complete' && job.status !== 'failed' && (
                  <button className="quiet-action" onClick={refreshCurrentJob} title="Refresh Status">
                    <RefreshCw size={14} />
                  </button>
                )}
              </div>
            )}
          </div>
          <div className="rail-section">
            <h2>Candidates</h2>
            {result?.candidates.length ? (
              result.candidates.map((candidate) => (
                <CandidateCard
                  key={candidate.candidate_id}
                  candidate={candidate}
                  active={candidate.candidate_id === selected?.candidate_id}
                  onSelect={() => setSelectedId(candidate.candidate_id)}
                />
              ))
            ) : (
              <p className="quiet">No candidates loaded.</p>
            )}
          </div>
        </aside>

        <section className="center-stage">
          <div className="stage-header">
            <div>
              <span>{result?.mission ?? 'Mission'}</span>
              <strong>{result?.target_id ?? selectedTarget?.target_id ?? 'Awaiting real analysis data'}</strong>
            </div>
            <div className="sync-pill" data-testid="workflow-status">{workflow}</div>
          </div>
          <OrbitScene candidates={result?.candidates ?? []} selectedId={selected?.candidate_id} />
          <div className="timeline">
            <SciencePlot
              title="Light Curve Timeline"
              testId="light-curve-plot"
              x={result?.light_curve.time ?? []}
              y={result?.light_curve.flux ?? []}
              xLabel="time"
              yLabel="normalized flux"
            />
            {result && result.result_id !== 'preview' && (
              <div className="artifact-toolbar">
                <Layers size={14} />
                <span className="field-label">Mask Range (index):</span>
                <input type="number" value={cadenceStart} onChange={e => setCadenceStart(Number(e.target.value))} />
                <span>to</span>
                <input type="number" value={cadenceEnd} onChange={e => setCadenceEnd(Number(e.target.value))} />
                <button onClick={handleCreateArtifactMask} className={selectedArtifactMaskId ? 'active-pill' : ''}>Apply Mask</button>
                {selectedArtifactMaskId && <button className="quiet" onClick={() => setSelectedArtifactMaskId(undefined)}><Trash2 size={14}/></button>}
              </div>
            )}
          </div>
        </section>

        <aside className="right-rail">
          <div className="panel">
            <h2>Periodogram</h2>
            <SciencePlot
              title="BLS Power"
              testId="periodogram-plot"
              x={result?.periodogram.period ?? []}
              y={result?.periodogram.power ?? []}
              xLabel="period"
              yLabel="power"
            />
          </div>
          <div className="panel">
            <h2>Folded Curve</h2>
            <SciencePlot
              title={selected?.candidate_id ?? 'Candidate'}
              testId="folded-curve-plot"
              x={folded?.phase ?? []}
              y={folded?.flux ?? []}
              xLabel="phase"
              yLabel="flux"
              mode="markers"
            />
          </div>
          <div className="panel details">
            <h2>Validation</h2>
            <dl>
              <dt>Odd-even</dt><dd>{formatScientific(selected?.validation?.odd_even_depth_delta, 3)}</dd>
              <dt>Secondary</dt><dd>{formatScientific(selected?.validation?.secondary_depth, 3)}</dd>
              <dt>Duration</dt><dd>{String(selected?.validation?.duration_plausible ?? 'n/a')}</dd>
            </dl>
          </div>
          <div className="panel details">
            <h2>Physics & Habitability</h2>
            <dl>
              <dt>Rp/Rs</dt><dd>{formatNumber(selected?.physics?.radius_ratio, 4)}</dd>
              <dt>Radius</dt><dd>{formatNumber(selected?.physics?.planet_radius_earth, 2)} R⊕</dd>
              <dt>Distance</dt><dd>{formatNumber(selected?.physics?.semi_major_axis_au, 4)} AU</dd>
              <dt>T_eq</dt><dd>{formatNumber(selected?.physics?.equilibrium_temperature_k, 1)} K</dd>
              <dt>HZ Zone</dt>
              <dd className={selected?.physics?.is_in_habitable_zone ? 'status-ready' : ''}>
                {formatTriState(selected?.physics?.is_in_habitable_zone, 'Inside', 'Outside')}
              </dd>
              <dt>Habitable</dt>
              <dd className={selected?.physics?.is_temperature_habitable ? 'status-ready' : ''}>
                {formatTriState(selected?.physics?.is_temperature_habitable, 'Potential', 'Unlikely')}
              </dd>
            </dl>
          </div>
          <div className="panel details">
            <h2>Pretrained ML</h2>
            <dl>
              <dt>Readiness</dt><dd>{activeModelStatus}</dd>
              <dt>Mission</dt><dd>{mission}</dd>
              <dt>Verdict</dt><dd>{selected?.ml?.label ?? 'n/a'}</dd>
              <dt>Probability</dt><dd>{formatNumber(selected?.ml?.probability, 4)}</dd>
              {selected?.ml?.class_probabilities && Object.entries(selected.ml.class_probabilities).map(([label, probability]) => (
                <Fragment key={label}><dt>{label}</dt><dd>{formatNumber(probability, 4)}</dd></Fragment>
              ))}
              <dt>Source</dt><dd>{selected?.ml?.model_source ?? activeModelSource}</dd>
              <dt>Input</dt><dd>{selected?.ml?.input_tensor_checksum?.slice(0, 12) ?? 'n/a'}</dd>
            </dl>
          </div>
          {error && <div className="error-panel" role="alert">{error} <button aria-label="Dismiss error" onClick={() => setError(null)}><X size={14}/></button></div>}
          {success && <div className="success-panel" role="status">{success}</div>}
        </aside>
      </section>

      {showApertureModal && tpfPreview && (
        <div className="modal-overlay">
          <div className="modal">
            <header>
              <h2>Aperture Mask Editor</h2>
              <button onClick={() => setShowApertureModal(false)}><X size={20}/></button>
            </header>
            <div className="modal-content">
              <p className="quiet">Select pixels to include in the extraction aperture.</p>
              <div className="pixel-grid" style={{ gridTemplateColumns: `repeat(${tpfPreview.shape[1]}, 1fr)` }}>
                {tpfPreview.image.map((row, i) => row.map((val, j) => (
                  <button
                    key={`${i}-${j}`}
                    data-testid={`aperture-pixel-${i}-${j}`}
                    className={`pixel ${apertureMask[i][j] ? 'selected' : ''}`}
                    style={{ opacity: aperturePixelOpacity(val) }}
                    onClick={() => {
                      const next = [...apertureMask];
                      next[i] = [...next[i]];
                      next[i][j] = !next[i][j];
                      setApertureMask(next);
                    }}
                  />
                )))}
              </div>
            </div>
            <footer>
              <button onClick={handleCreateApertureMask}>Apply Mask</button>
            </footer>
          </div>
        </div>
      )}

      {showBlsModal && (
        <div className="modal-overlay">
          <div className="modal">
            <header>
              <h2>BLS Search Controls</h2>
              <button onClick={() => setShowBlsModal(false)}><X size={20}/></button>
            </header>
            <div className="modal-content">
              <div className="period-control">
                <label htmlFor="min-period">Min Period (days)</label>
                <div className="range-row">
                  <input
                    id="min-period"
                    name="min-period"
                    type="range"
                    min={MIN_PERIOD_FLOOR}
                    max={Math.max(MIN_PERIOD_FLOOR, maxPeriod - 0.1)}
                    value={minPeriod}
                    onChange={(event) => updateMinPeriod(Number(event.target.value))}
                    step="0.1"
                  />
                  <input
                    aria-label="minimum period value"
                    type="number"
                    min={MIN_PERIOD_FLOOR}
                    max={Math.max(MIN_PERIOD_FLOOR, maxPeriod - 0.1)}
                    value={minPeriod}
                    onChange={(event) => updateMinPeriod(Number(event.target.value))}
                    step="0.1"
                  />
                </div>
              </div>
              <div className="period-control">
                <label htmlFor="max-period">Max Period (days)</label>
                <div className="range-row">
                  <input
                    id="max-period"
                    name="max-period"
                    type="range"
                    min={MIN_PERIOD_FLOOR}
                    max={MAX_PERIOD_CEILING}
                    value={maxPeriod}
                    onChange={(event) => updateMaxPeriod(Number(event.target.value))}
                    step="0.1"
                  />
                  <input
                    aria-label="maximum period value"
                    type="number"
                    min={Math.min(MAX_PERIOD_CEILING, minPeriod + 0.1)}
                    max={MAX_PERIOD_CEILING}
                    value={maxPeriod}
                    onChange={(event) => updateMaxPeriod(Number(event.target.value))}
                    step="0.1"
                  />
                </div>
              </div>
              {blsRunning && <p className="quiet">Searching grid...</p>}
            </div>
            <footer>
              <button onClick={runBlsPreview} disabled={blsRunning}>Run Preview Search</button>
            </footer>
          </div>
        </div>
      )}

      {showModelModal && (
        <div className="modal-overlay">
          <div className="modal">
            <header>
              <h2>Model Status & Registry</h2>
              <button onClick={() => setShowModelModal(false)}><X size={20}/></button>
            </header>
            <div className="modal-content">
              {model ? Object.entries(model).map(([key, info]) => (
                <div key={key} className="model-info-card">
                  <h3>{key.replace('_', ' ').toUpperCase()}</h3>
                  <dl>
                    <dt>Status</dt><dd className={info.status === 'ready' ? 'status-ready' : 'status-bad'}>{info.status}</dd>
                    <dt>Source</dt><dd>{info.source ?? 'n/a'}</dd>
                    <dt>Version</dt><dd>{info.version ?? 'n/a'}</dd>
                    <dt>Checksum</dt><dd><code>{info.checksum?.slice(0, 16) ?? 'n/a'}</code></dd>
                    {info.detail && <dt>Detail</dt>}
                    {info.detail && <dd className="quiet">{info.detail}</dd>}
                  </dl>
                  {info.status !== 'ready' && (
                    <div className="setup-hint">
                      <strong>Fix:</strong> run <code>{setupCommands[key] ?? 'Check model registry setup.'}</code>
                    </div>
                  )}
                </div>
              )) : <p>Loading model registry...</p>}
            </div>
            <footer>
              <button onClick={refreshModelStatus}><RefreshCw size={14}/> Refresh Registry</button>
            </footer>
          </div>
        </div>
      )}

      {showSessionsModal && (
        <div className="modal-overlay">
          <div className="modal">
            <header>
              <h2>Saved Sessions</h2>
              <button onClick={() => setShowSessionsModal(false)}><X size={20}/></button>
            </header>
            <div className="modal-content">
              <div className="selection-list">
                {sessions.map(s => (
                  <button key={s.session_id} onClick={() => restoreSession(s)}>
                    <span>{s.name}</span>
                    <small>{new Date(s.created_at).toLocaleString()}</small>
                  </button>
                ))}
                {!sessions.length && <p className="quiet">No saved sessions found.</p>}
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
