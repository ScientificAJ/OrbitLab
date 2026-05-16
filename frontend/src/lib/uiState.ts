export type WorkflowState = 'idle' | 'searching' | 'product-selected' | 'running' | 'complete' | 'failed';
export type SearchStatus = 'idle' | 'searching' | 'success' | 'empty' | 'failed';
export type BlsPreviewStatus = 'idle' | 'running' | 'complete' | 'failed';

const modelDisplayNames: Record<string, string> = {
  nigraha_tess: 'Nigraha TESS',
  kepler_astronet: 'Kepler AstroNet',
  k2_exomac_kkt: 'K2 ExoMAC KKT',
  k2_astronet: 'K2 AstroNet',
};

export function formatModelDisplayName(key: string) {
  return modelDisplayNames[key] ?? key.replace(/_/g, ' ').replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

export function formatFiniteNumber(value: number | null | undefined, digits = 3) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'n/a';
}

export function buildAperturePixelLabel(row: number, column: number, value: number, selected: boolean) {
  const flux = Number.isFinite(value) ? formatFiniteNumber(value, 2) : 'not finite';
  return `Toggle aperture pixel row ${row + 1} column ${column + 1}. Flux ${flux}. ${selected ? 'Selected' : 'Not selected'}.`;
}

export function getMatchEmptyMessage(status: SearchStatus, query: string, hasSearched: boolean) {
  if (status === 'searching') return `Searching for "${query}"...`;
  if (status === 'failed') return `Search failed for "${query}".`;
  if (status === 'empty') return `No matching targets found for "${query}".`;
  return hasSearched ? 'No matching targets found.' : 'Search for a target first.';
}

export function getWorkflowMessage({
  workflow,
  searchStatus,
  productsLoading,
  blsStatus,
  jobStatus,
  hasResult,
  candidateCount,
  resultKind,
}: {
  workflow: WorkflowState;
  searchStatus: SearchStatus;
  productsLoading: boolean;
  blsStatus: BlsPreviewStatus;
  jobStatus?: string;
  hasResult?: boolean;
  candidateCount?: number;
  resultKind?: 'preview' | 'analysis';
}) {
  if (searchStatus === 'searching') return 'Resolving target in mission archive...';
  if (productsLoading) return 'Fetching target pixel products...';
  if (blsStatus === 'running') return 'Running BLS grid preview...';
  if (workflow === 'running' && jobStatus) return `Analysis job ${jobStatus}...`;
  if (workflow === 'running') return 'Submitting analysis job...';
  if (workflow === 'complete' && hasResult && candidateCount === 0) {
    return resultKind === 'preview'
      ? 'BLS preview finished with no candidates in this period range.'
      : 'Analysis finished with no candidates for this product.';
  }
  if (workflow === 'complete') {
    return resultKind === 'preview'
      ? 'BLS preview candidates are ready for review.'
      : 'Analysis candidates are ready for review.';
  }
  if (workflow === 'failed') return 'Workflow needs attention; see the error panel.';
  if (workflow === 'product-selected') return 'Product selected. Choose aperture, BLS preview, or full analysis.';
  return 'Search for a target to begin.';
}

export function getCandidateEmptyMessage(hasResult: boolean) {
  return hasResult ? 'No candidates found for this result.' : 'No candidates loaded.';
}

export function getOrbitEmptyMessage(hasResult: boolean) {
  return hasResult
    ? 'No candidate orbits were found for this result. Adjust the BLS range or try another product.'
    : 'Run BLS Search or Analysis to render candidate orbits.';
}
