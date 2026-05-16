import {
  Activity,
  Download,
  FlaskConical,
  Gauge,
  History,
  Layers,
  Play,
  RefreshCw,
  Save,
  Search,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-react';
import { Fragment, type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { OrbitScene } from './components/OrbitScene';
import { SciencePlot } from './components/SciencePlot';
import { useModalState } from './hooks/useModalState';
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
import {
  BlsPreviewStatus,
  SearchStatus,
  WorkflowState,
  buildAperturePixelLabel,
  formatFiniteNumber,
  formatModelDisplayName,
  getMatchEmptyMessage,
  getWorkflowMessage,
} from './lib/uiState';
import './styles/app.css';

function formatNumber(value: number | null | undefined, digits = 3) {
  return formatFiniteNumber(value, digits);
}

function formatTriState(value: unknown, trueLabel: string, falseLabel: string) {
  if (value === true) return trueLabel;
  if (value === false) return falseLabel;
  return 'n/a';
}

function formatScientific(value: number | null | undefined, digits = 3) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toExponential(digits) : 'n/a';
}

function CandidateCard({
  candidate,
  active,
  onSelect,
}: {
  candidate: Candidate;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" className={`candidate-card ${active ? 'active' : ''}`} onClick={onSelect}>
      <span>{candidate.candidate_id}</span>
      <strong>{formatNumber(candidate.period, 4)} d</strong>
      <small>
        SNR {formatNumber(candidate.signal_to_noise, 2)} · depth {formatNumber(candidate.depth * 1_000_000, 0)} ppm
      </small>
    </button>
  );
}

function ModalShell({
  title,
  titleId,
  children,
  footer,
  onClose,
  closeDisabled = false,
}: {
  title: string;
  titleId: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  closeDisabled?: boolean;
}) {
  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !closeDisabled) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header>
          <h2 id={titleId}>{title}</h2>
          <button type="button" aria-label={`Close ${title}`} onClick={onClose} disabled={closeDisabled}>
            <X size={20} />
          </button>
        </header>
        <div className="modal-content">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

const setupHints: Record<string, { label: string; command?: string }> = {
  nigraha_tess: { label: 'Fetch and register the TESS weights.', command: 'scripts/fetch_nigraha_weights.py' },
  kepler_astronet: { label: 'Fetch and register the Kepler checkpoint.', command: 'scripts/fetch_kepler_astronet.py' },
  k2_exomac_kkt: { label: 'Fetch and register the K2 ExoMAC bundle.', command: 'scripts/fetch_k2_exomac_kkt.py' },
  k2_astronet: { label: 'No public downloadable K2 AstroNet checkpoint is registered for OrbitLab.' },
};

function ModelSetupHint({ modelKey }: { modelKey: string }) {
  const hint = setupHints[modelKey];
  if (!hint) {
    return (
      <div className="setup-hint">
        <strong>Note:</strong> Check model registry setup.
      </div>
    );
  }

  return (
    <div className="setup-hint">
      <strong>{hint.command ? 'Fix:' : 'Note:'}</strong> {hint.label}
      {hint.command && (
        <>
          {' '}
          Run <code>{hint.command}</code>
        </>
      )}
    </div>
  );
}

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
  const [searchStatus, setSearchStatus] = useState<SearchStatus>('idle');
  const [searchStatusQuery, setSearchStatusQuery] = useState('');
  const [selectedTarget, setSelectedTarget] = useState<SearchResult | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [productsLoading, setProductsLoading] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [model, setModel] = useState<ModelStatuses | null>(null);
  const [workflow, setWorkflow] = useState<WorkflowState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [tpfPreview, setTpfPreview] = useState<TpfPreview | null>(null);
  const [apertureMask, setApertureMask] = useState<boolean[][]>([]);
  const [selectedApertureMaskId, setSelectedApertureMaskId] = useState<string | undefined>();

  const [minPeriod, setMinPeriod] = useState(0.5);
  const [maxPeriod, setMaxPeriod] = useState(30.0);
  const [blsRunning, setBlsRunning] = useState(false);
  const [blsPreviewStatus, setBlsPreviewStatus] = useState<BlsPreviewStatus>('idle');
  const [blsPreviewError, setBlsPreviewError] = useState<string | null>(null);

  const [sessions, setSessions] = useState<SavedSession[]>([]);

  const [selectedArtifactMaskId, setSelectedArtifactMaskId] = useState<string | undefined>();
  const [cadenceStart, setCadenceStart] = useState<number>(0);
  const [cadenceEnd, setCadenceEnd] = useState<number>(0);
  const { activeModal, openModal, closeActiveModal, setActiveModal } = useModalState(
    (modal) => modal === 'bls' && blsRunning,
  );

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
  const activeModel =
    mission === 'TESS' ? model?.nigraha_tess : mission === 'Kepler' ? model?.kepler_astronet : model?.k2_exomac_kkt;
  const activeModelStatus = typeof activeModel?.status === 'string' ? activeModel.status : 'unknown';
  const activeModelSource =
    typeof activeModel?.source === 'string'
      ? activeModel.source
      : typeof activeModel?.detail === 'string'
        ? activeModel.detail
        : 'n/a';
  const selectedAperturePixelCount = useMemo(() => apertureMask.flat().filter(Boolean).length, [apertureMask]);
  const matchEmptyMessage = useMemo(() => {
    return getMatchEmptyMessage(searchStatus, searchStatusQuery, hasSearched);
  }, [hasSearched, searchStatus, searchStatusQuery]);
  const suggestedTargets = useMemo(() => targets.filter((target) => target.match_type === 'alias'), [targets]);
  const catalogTargets = useMemo(() => targets.filter((target) => target.match_type !== 'alias'), [targets]);
  const workflowMessage = useMemo(() => {
    return getWorkflowMessage({
      workflow,
      searchStatus,
      productsLoading,
      blsStatus: blsPreviewStatus,
      jobStatus: job?.status,
    });
  }, [blsPreviewStatus, job?.status, productsLoading, searchStatus, workflow]);

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

  function aperturePixelLabel(row: number, column: number, value: number, selected: boolean) {
    return buildAperturePixelLabel(row, column, value, selected);
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
    setSearchStatus('idle');
    setSearchStatusQuery('');
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
    setBlsPreviewStatus('idle');
    setBlsPreviewError(null);
    setActiveModal(null);
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
    setTargets([]);
    setHasSearched(true);
    setSearchStatus('searching');
    setSearchStatusQuery(trimmedQuery);
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
      setSearchStatus(payload.length ? 'success' : 'empty');
      setWorkflow('idle');
    } catch (err) {
      if (token !== searchToken.current) return;
      setHasSearched(true);
      setTargets([]);
      setSearchStatus('failed');
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
    setBlsPreviewStatus('idle');
    setBlsPreviewError(null);
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
    setBlsPreviewStatus('idle');
    setBlsPreviewError(null);
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
      for (
        let index = 0;
        index < ANALYSIS_POLL_LIMIT && current.status !== 'complete' && current.status !== 'failed';
        index += 1
      ) {
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
      openModal('sessions');
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
    setSearchStatus(restoredTarget ? 'success' : 'idle');
    setSearchStatusQuery(typeof payload.query === 'string' ? payload.query : '');
    setSelectedProduct(restoredProduct);
    setSelectedApertureMaskId(
      typeof payload.selectedApertureMaskId === 'string' ? payload.selectedApertureMaskId : undefined,
    );
    setSelectedArtifactMaskId(
      typeof payload.selectedArtifactMaskId === 'string' ? payload.selectedArtifactMaskId : undefined,
    );
    setMinPeriod(Number.isFinite(payload.minPeriod) ? Number(payload.minPeriod) : 0.5);
    setMaxPeriod(Number.isFinite(payload.maxPeriod) ? Number(payload.maxPeriod) : 30);
    setResult(restoredResult);
    setSelectedId(
      typeof payload.selectedId === 'string' ? payload.selectedId : restoredResult?.candidates[0]?.candidate_id,
    );
    setJob(null);

    if (restoredResult) {
      setWorkflow('complete');
    } else if (restoredProduct) {
      setWorkflow('product-selected');
    } else {
      setWorkflow('idle');
    }

    setActiveModal(null);
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
      openModal('aperture');
    } catch (err) {
      if (token !== apertureToken.current) return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleCreateApertureMask() {
    if (!selectedTarget || !selectedProduct || !tpfPreview) return;
    setError(null);
    if (!apertureMask.flat().some((p) => p)) {
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
      setActiveModal(null);
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
    setBlsPreviewError(null);
    setBlsPreviewStatus('running');

    if (result?.result_id === 'preview') {
      setResult(null);
      setSelectedId(undefined);
      setWorkflow('product-selected');
    }

    if (minPeriod >= maxPeriod) {
      setBlsPreviewStatus('failed');
      setBlsPreviewError('Minimum period must be lower than maximum period.');
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
      setBlsPreviewStatus('complete');
      setActiveModal(null);
    } catch (err) {
      if (token !== blsPreviewToken.current) return;
      setBlsPreviewStatus('failed');
      setBlsPreviewError(err instanceof Error ? err.message : String(err));
      setWorkflow(result && result.result_id !== 'preview' ? 'complete' : 'product-selected');
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
          <label className="sr-only" htmlFor="target-search">
            Target search
          </label>
          <input
            id="target-search"
            name="target-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="target search"
            placeholder="Try TIC 307210830, Kepler-10, TOI-700..."
          />
          <button type="button" onClick={runSearch} disabled={!query.trim() || workflow === 'searching'}>
            <Search size={15} /> Search
          </button>
        </div>
        <div className="command-actions">
          <button type="button" title="Sessions" aria-label="Sessions" onClick={openSessionsModal}>
            <History size={17} />
          </button>
          <button
            type="button"
            title="Save session"
            aria-label="Save session"
            onClick={handleSaveSession}
            disabled={!selectedTarget}
          >
            <Save size={17} />
          </button>
          <button
            type="button"
            title="Export report"
            aria-label="Export report"
            onClick={handleExportReport}
            disabled={!result || result.result_id === 'preview'}
          >
            <Download size={17} />
          </button>
        </div>
      </header>

      <section className="workspace">
        <aside className="left-rail">
          <div className="rail-section">
            <h2>Target</h2>
            <label htmlFor="mission-select">Mission</label>
            <select
              id="mission-select"
              name="mission"
              value={mission}
              onChange={(event) => changeMission(event.target.value as 'TESS' | 'Kepler' | 'K2')}
            >
              <option value="TESS">TESS</option>
              <option value="Kepler">Kepler</option>
              <option value="K2">K2</option>
            </select>
            <div className="field-label">Matches</div>
            <div className="selection-list">
              {suggestedTargets.length > 0 && <div className="selection-group-label">Suggested targets</div>}
              {suggestedTargets.map((target) => (
                <button
                  type="button"
                  key={`${target.catalog}-${target.target_id}-${target.matched_query ?? ''}`}
                  className={selectedTarget?.target_id === target.target_id ? 'active' : ''}
                  onClick={() => chooseTarget(target)}
                >
                  <span>{target.target_id}</span>
                  <small>{target.matched_query ? `Alias for "${target.matched_query}"` : target.catalog}</small>
                </button>
              ))}
              {suggestedTargets.length > 0 && catalogTargets.length > 0 && (
                <div className="selection-group-label">Catalog matches</div>
              )}
              {catalogTargets.map((target) => (
                <button
                  type="button"
                  key={`${target.catalog}-${target.target_id}`}
                  className={selectedTarget?.target_id === target.target_id ? 'active' : ''}
                  onClick={() => chooseTarget(target)}
                >
                  <span>{target.target_id}</span>
                  <small>{target.catalog}</small>
                </button>
              ))}
              {!targets.length && <p className="quiet">{matchEmptyMessage}</p>}
            </div>
            <div className="field-label">Product</div>
            <div className="selection-list">
              {products.map((product) => (
                <button
                  type="button"
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
            <button
              type="button"
              disabled={!selectedProduct || workflow === 'running'}
              onClick={openApertureModal}
              className={selectedApertureMaskId ? 'active-pill' : ''}
            >
              <SlidersHorizontal size={15} /> Aperture {selectedApertureMaskId ? '(Custom)' : ''}
            </button>
            <button
              type="button"
              disabled={!selectedProduct || workflow === 'running'}
              onClick={() => openModal('bls')}
            >
              <FlaskConical size={15} /> BLS Search
            </button>
            <button
              type="button"
              disabled={!selectedProduct?.product_uri || workflow === 'running'}
              onClick={runAnalysis}
            >
              <Play size={15} /> Run Analysis
            </button>
            <button type="button" onClick={() => openModal('models')}>
              <Gauge size={15} /> ML Status {activeModelStatus}
            </button>
            {job && (
              <div className="job-status-row">
                <p className="quiet">
                  Job {job.status}
                  {job.result_id ? ` · ${job.result_id.slice(0, 8)}` : ''}
                </p>
                {job.status !== 'complete' && job.status !== 'failed' && (
                  <button type="button" className="quiet-action" onClick={refreshCurrentJob} title="Refresh Status">
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
              <small className="stage-message" data-testid="workflow-message">
                {workflowMessage}
              </small>
            </div>
            <div className="sync-pill" data-testid="workflow-status">
              {workflow}
            </div>
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
                <input type="number" value={cadenceStart} onChange={(e) => setCadenceStart(Number(e.target.value))} />
                <span>to</span>
                <input type="number" value={cadenceEnd} onChange={(e) => setCadenceEnd(Number(e.target.value))} />
                <button
                  type="button"
                  onClick={handleCreateArtifactMask}
                  className={selectedArtifactMaskId ? 'active-pill' : ''}
                >
                  Apply Mask
                </button>
                {selectedArtifactMaskId && (
                  <button type="button" className="quiet" onClick={() => setSelectedArtifactMaskId(undefined)}>
                    <Trash2 size={14} />
                  </button>
                )}
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
              <dt>Odd-even</dt>
              <dd>{formatScientific(selected?.validation?.odd_even_depth_delta, 3)}</dd>
              <dt>Secondary</dt>
              <dd>{formatScientific(selected?.validation?.secondary_depth, 3)}</dd>
              <dt>Duration</dt>
              <dd>{String(selected?.validation?.duration_plausible ?? 'n/a')}</dd>
            </dl>
          </div>
          <div className="panel details">
            <h2>Physics & Habitability</h2>
            <dl>
              <dt>Rp/Rs</dt>
              <dd>{formatNumber(selected?.physics?.radius_ratio, 4)}</dd>
              <dt>Radius</dt>
              <dd>{formatNumber(selected?.physics?.planet_radius_earth, 2)} R⊕</dd>
              <dt>Distance</dt>
              <dd>{formatNumber(selected?.physics?.semi_major_axis_au, 4)} AU</dd>
              <dt>T_eq</dt>
              <dd>{formatNumber(selected?.physics?.equilibrium_temperature_k, 1)} K</dd>
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
              <dt>Readiness</dt>
              <dd>{activeModelStatus}</dd>
              <dt>Mission</dt>
              <dd>{mission}</dd>
              <dt>Verdict</dt>
              <dd>{selected?.ml?.label ?? 'n/a'}</dd>
              <dt>Probability</dt>
              <dd>{formatNumber(selected?.ml?.probability, 4)}</dd>
              {selected?.ml?.class_probabilities &&
                Object.entries(selected.ml.class_probabilities).map(([label, probability]) => (
                  <Fragment key={label}>
                    <dt>{label}</dt>
                    <dd>{formatNumber(probability, 4)}</dd>
                  </Fragment>
                ))}
              <dt>Source</dt>
              <dd>{selected?.ml?.model_source ?? activeModelSource}</dd>
              <dt>Input</dt>
              <dd>{selected?.ml?.input_tensor_checksum?.slice(0, 12) ?? 'n/a'}</dd>
            </dl>
          </div>
          {error && (
            <div className="error-panel" role="alert">
              {error}{' '}
              <button type="button" aria-label="Dismiss error" onClick={() => setError(null)}>
                <X size={14} />
              </button>
            </div>
          )}
          {success && (
            <div className="success-panel" role="status">
              {success}
            </div>
          )}
        </aside>
      </section>

      {activeModal === 'aperture' && tpfPreview && (
        <ModalShell
          title="Aperture Mask Editor"
          titleId="aperture-modal-title"
          onClose={closeActiveModal}
          footer={
            <button type="button" onClick={handleCreateApertureMask}>
              Apply Mask
            </button>
          }
        >
          <p className="quiet">Select pixels to include in the extraction aperture.</p>
          <p className="quiet aperture-summary" data-testid="aperture-selection-summary">
            {selectedAperturePixelCount} {selectedAperturePixelCount === 1 ? 'pixel' : 'pixels'} selected.
          </p>
          <div className="pixel-grid" style={{ gridTemplateColumns: `repeat(${tpfPreview.shape[1]}, 1fr)` }}>
            {tpfPreview.image.map((row, i) =>
              row.map((val, j) => {
                const selectedPixel = Boolean(apertureMask[i][j]);
                const label = aperturePixelLabel(i, j, val, selectedPixel);

                return (
                  <button
                    type="button"
                    key={`${i}-${j}`}
                    data-testid={`aperture-pixel-${i}-${j}`}
                    aria-label={label}
                    aria-pressed={selectedPixel}
                    title={label}
                    className={`pixel ${selectedPixel ? 'selected' : ''}`}
                    style={{ opacity: aperturePixelOpacity(val) }}
                    onClick={() => {
                      const next = [...apertureMask];
                      next[i] = [...next[i]];
                      next[i][j] = !next[i][j];
                      setApertureMask(next);
                    }}
                  />
                );
              }),
            )}
          </div>
        </ModalShell>
      )}

      {activeModal === 'bls' && (
        <ModalShell
          title="BLS Search Controls"
          titleId="bls-modal-title"
          onClose={closeActiveModal}
          closeDisabled={blsRunning}
          footer={
            <button type="button" onClick={runBlsPreview} disabled={blsRunning}>
              {blsPreviewStatus === 'failed' ? 'Retry Preview Search' : 'Run Preview Search'}
            </button>
          }
        >
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
          <div className={`modal-status bls-status-${blsPreviewStatus}`}>
            BLS preview status: <strong>{blsPreviewStatus}</strong>
          </div>
          {blsRunning && <p className="quiet">Searching grid...</p>}
          {blsPreviewStatus === 'failed' && blsPreviewError && (
            <div className="modal-error" role="alert">
              <strong>Preview search failed</strong>
              <p>{blsPreviewError}</p>
            </div>
          )}
        </ModalShell>
      )}

      {activeModal === 'models' && (
        <ModalShell
          title="Model Status & Registry"
          titleId="models-modal-title"
          onClose={closeActiveModal}
          footer={
            <button type="button" onClick={refreshModelStatus}>
              <RefreshCw size={14} /> Refresh Registry
            </button>
          }
        >
          {model ? (
            Object.entries(model).map(([key, info]) => (
              <div key={key} className="model-info-card">
                <h3>{formatModelDisplayName(key)}</h3>
                <dl>
                  <dt>Status</dt>
                  <dd className={info.status === 'ready' ? 'status-ready' : 'status-bad'}>{info.status}</dd>
                  <dt>Source</dt>
                  <dd>{info.source ?? 'n/a'}</dd>
                  <dt>Version</dt>
                  <dd>{info.version ?? 'n/a'}</dd>
                  <dt>Checksum</dt>
                  <dd>
                    <code>{info.checksum?.slice(0, 16) ?? 'n/a'}</code>
                  </dd>
                  {info.detail && <dt>Detail</dt>}
                  {info.detail && <dd className="quiet">{info.detail}</dd>}
                </dl>
                {info.status !== 'ready' && <ModelSetupHint modelKey={key} />}
              </div>
            ))
          ) : (
            <p>Loading model registry...</p>
          )}
        </ModalShell>
      )}

      {activeModal === 'sessions' && (
        <ModalShell title="Saved Sessions" titleId="sessions-modal-title" onClose={closeActiveModal}>
          <div className="selection-list">
            {sessions.map((s) => (
              <button type="button" key={s.session_id} onClick={() => restoreSession(s)}>
                <span>{s.name}</span>
                <small>{new Date(s.created_at).toLocaleString()}</small>
              </button>
            ))}
            {!sessions.length && <p className="quiet">No saved sessions found.</p>}
          </div>
        </ModalShell>
      )}
    </main>
  );
}
