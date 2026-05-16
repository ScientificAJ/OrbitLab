export type WorkflowState = 'idle' | 'searching' | 'product-selected' | 'running' | 'complete' | 'failed';
export type SearchStatus = 'idle' | 'searching' | 'success' | 'empty' | 'failed';
export type BlsPreviewStatus = 'idle' | 'running' | 'complete' | 'failed';
export type OrbitLabMode = 'beginner' | 'advanced';
export type ThemeName = 'space' | 'sakura' | 'light' | 'dark' | 'nature';

export const ORBITLAB_MODES: OrbitLabMode[] = ['beginner', 'advanced'];
export const ORBITLAB_THEMES: ThemeName[] = ['space', 'sakura', 'light', 'dark', 'nature'];

export const themeLabels: Record<ThemeName, string> = {
  space: 'Space',
  sakura: 'Sakura',
  light: 'Light',
  dark: 'Dark',
  nature: 'Nature',
};

export function normalizeOrbitLabMode(value: unknown): OrbitLabMode {
  return value === 'advanced' ? 'advanced' : 'beginner';
}

export function normalizeThemeName(value: unknown): ThemeName {
  return typeof value === 'string' && ORBITLAB_THEMES.includes(value as ThemeName) ? (value as ThemeName) : 'space';
}

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
  mode = 'advanced',
}: {
  workflow: WorkflowState;
  searchStatus: SearchStatus;
  productsLoading: boolean;
  blsStatus: BlsPreviewStatus;
  jobStatus?: string;
  hasResult?: boolean;
  candidateCount?: number;
  resultKind?: 'preview' | 'analysis';
  mode?: OrbitLabMode;
}) {
  const beginner = mode === 'beginner';
  if (searchStatus === 'searching') {
    return beginner ? 'Looking up that target in the mission archive...' : 'Resolving target in mission archive...';
  }
  if (productsLoading) {
    return beginner ? 'Finding available observation files for this target...' : 'Fetching target pixel products...';
  }
  if (blsStatus === 'running') return beginner ? 'Previewing likely transit signals...' : 'Running BLS grid preview...';
  if (workflow === 'running' && jobStatus) {
    return beginner ? `Analysis is ${jobStatus}...` : `Analysis job ${jobStatus}...`;
  }
  if (workflow === 'running') return beginner ? 'Starting the full analysis...' : 'Submitting analysis job...';
  if (workflow === 'complete' && hasResult && candidateCount === 0) {
    if (beginner) {
      return resultKind === 'preview'
        ? 'Preview finished without strong candidates. Try another product or run full analysis.'
        : 'Analysis finished without candidates for this product.';
    }
    return resultKind === 'preview'
      ? 'BLS preview finished with no candidates in this period range.'
      : 'Analysis finished with no candidates for this product.';
  }
  if (workflow === 'complete') {
    if (beginner) {
      return resultKind === 'preview'
        ? 'Preview candidates are ready. Pick one to inspect the plots.'
        : 'Analysis results are ready. Review candidates and plots.';
    }
    return resultKind === 'preview'
      ? 'BLS preview candidates are ready for review.'
      : 'Analysis candidates are ready for review.';
  }
  if (workflow === 'failed') {
    return beginner
      ? 'Something needs attention. Check the message panel for details.'
      : 'Workflow needs attention; see the error panel.';
  }
  if (workflow === 'product-selected') {
    return beginner
      ? 'Observation file selected. Preview candidates or run the full analysis.'
      : 'Product selected. Choose aperture, BLS preview, or full analysis.';
  }
  return beginner ? 'Choose a mission, then search for a target to begin.' : 'Search for a target to begin.';
}

export function getCandidateEmptyMessage(hasResult: boolean) {
  return hasResult ? 'No candidates found for this result.' : 'No candidates loaded.';
}

export function getOrbitEmptyMessage(hasResult: boolean) {
  return hasResult
    ? 'No candidate orbits were found for this result. Adjust the BLS range or try another product.'
    : 'Run BLS Search or Analysis to render candidate orbits.';
}
