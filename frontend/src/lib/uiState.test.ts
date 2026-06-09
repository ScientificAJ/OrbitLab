import { describe, expect, it } from 'vitest';
import {
  buildAperturePixelLabel,
  formatFiniteNumber,
  formatModelDisplayName,
  getCandidateEmptyMessage,
  getMatchEmptyMessage,
  getOrbitEmptyMessage,
  getWorkflowMessage,
  isVoyagerEasterEggQuery,
  normalizeOrbitLabMode,
  normalizeThemeName,
} from './uiState';

describe('uiState helpers', () => {
  it('formats known and fallback model ids for humans', () => {
    expect(formatModelDisplayName('k2_exomac_kkt')).toBe('K2 ExoMAC KKT');
    expect(formatModelDisplayName('future_model_adapter')).toBe('Future Model Adapter');
  });

  it('builds aperture pixel labels with state and flux', () => {
    expect(buildAperturePixelLabel(1, 2, 24.567, true)).toBe(
      'Toggle aperture pixel row 2 column 3. Flux 24.57. Selected.',
    );
    expect(buildAperturePixelLabel(0, 0, Number.NaN, false)).toBe(
      'Toggle aperture pixel row 1 column 1. Flux not finite. Not selected.',
    );
  });

  it('describes search empty states without stale wording', () => {
    expect(getMatchEmptyMessage('idle', '', false)).toBe('Search for a target first.');
    expect(getMatchEmptyMessage('idle', '', true)).toBe('No matching targets found.');
    expect(getMatchEmptyMessage('success', '', true)).toBe('No matching targets found.');
    expect(getMatchEmptyMessage('searching', 'TOI-700', true)).toBe('Searching for "TOI-700"...');
    expect(getMatchEmptyMessage('failed', 'bad target', true)).toBe('Search failed for "bad target".');
    expect(getMatchEmptyMessage('empty', 'empty target', true)).toBe('No matching targets found for "empty target".');
  });

  it('formats finite numbers and falls back for non-finite or non-number values', () => {
    expect(formatFiniteNumber(3.14159, 2)).toBe('3.14');
    expect(formatFiniteNumber(42)).toBe('42.000');
    expect(formatFiniteNumber(Number.NaN)).toBe('n/a');
    expect(formatFiniteNumber(Number.POSITIVE_INFINITY)).toBe('n/a');
    expect(formatFiniteNumber(null)).toBe('n/a');
    expect(formatFiniteNumber(undefined)).toBe('n/a');
  });

  it('summarizes long-running workflow states', () => {
    expect(
      getWorkflowMessage({
        workflow: 'running',
        searchStatus: 'success',
        productsLoading: false,
        blsStatus: 'idle',
        jobStatus: 'queued',
      }),
    ).toBe('Analysis job queued...');

    expect(
      getWorkflowMessage({
        workflow: 'product-selected',
        searchStatus: 'success',
        productsLoading: false,
        blsStatus: 'idle',
      }),
    ).toBe('Product selected. Choose aperture, BLS preview, or full analysis.');
  });

  it('falls back safely for invalid saved mode and theme values', () => {
    expect(normalizeOrbitLabMode('advanced')).toBe('advanced');
    expect(normalizeOrbitLabMode('expert')).toBe('beginner');
    expect(normalizeOrbitLabMode(null)).toBe('beginner');

    expect(normalizeThemeName('nature')).toBe('nature');
    expect(normalizeThemeName('solarized')).toBe('space');
    expect(normalizeThemeName(undefined)).toBe('space');
  });

  it('recognizes only the Voyager Mode easter egg trigger phrases', () => {
    expect(isVoyagerEasterEggQuery('voyager')).toBe(true);
    expect(isVoyagerEasterEggQuery(' Voyager Mode ')).toBe(true);
    expect(isVoyagerEasterEggQuery('\tGOLDEN RECORD\n')).toBe(true);

    expect(isVoyagerEasterEggQuery('voyager 1')).toBe(false);
    expect(isVoyagerEasterEggQuery('gold record')).toBe(false);
    expect(isVoyagerEasterEggQuery('TIC 307210830')).toBe(false);
  });

  it('keeps workflow guidance distinct for beginner and advanced modes', () => {
    const base = {
      workflow: 'product-selected' as const,
      searchStatus: 'success' as const,
      productsLoading: false,
      blsStatus: 'idle' as const,
    };

    expect(getWorkflowMessage({ ...base, mode: 'beginner' })).toBe(
      'Observation file selected. Preview candidates or run the full analysis.',
    );
    expect(getWorkflowMessage({ ...base, mode: 'advanced' })).toBe(
      'Product selected. Choose aperture, BLS preview, or full analysis.',
    );
  });

  it('separates pre-run and post-result empty candidate messages', () => {
    expect(getCandidateEmptyMessage(false)).toBe('No candidates loaded.');
    expect(getCandidateEmptyMessage(true)).toBe('No candidates found for this result.');
    expect(getOrbitEmptyMessage(false)).toBe('Run BLS Search or Analysis to render candidate orbits.');
    expect(getOrbitEmptyMessage(true)).toContain('No candidate orbits were found');
    expect(
      getWorkflowMessage({
        workflow: 'complete',
        searchStatus: 'success',
        productsLoading: false,
        blsStatus: 'complete',
        hasResult: true,
        candidateCount: 0,
        resultKind: 'preview',
      }),
    ).toBe('BLS preview finished with no candidates in this period range.');
  });

  // Exhaustive branch coverage for getWorkflowMessage: every state x every mode.
  const base = {
    workflow: 'idle' as const,
    searchStatus: 'idle' as const,
    productsLoading: false,
    blsStatus: 'idle' as const,
  };

  it('covers searching status in both modes', () => {
    expect(getWorkflowMessage({ ...base, searchStatus: 'searching', mode: 'advanced' })).toBe(
      'Resolving target in mission archive...',
    );
    expect(getWorkflowMessage({ ...base, searchStatus: 'searching', mode: 'beginner' })).toBe(
      'Looking up that target in the mission archive...',
    );
  });

  it('covers products loading in both modes', () => {
    expect(getWorkflowMessage({ ...base, productsLoading: true, mode: 'advanced' })).toBe(
      'Fetching target pixel products...',
    );
    expect(getWorkflowMessage({ ...base, productsLoading: true, mode: 'beginner' })).toBe(
      'Finding available observation files for this target...',
    );
  });

  it('covers BLS running in both modes', () => {
    expect(getWorkflowMessage({ ...base, blsStatus: 'running', mode: 'advanced' })).toBe('Running BLS grid preview...');
    expect(getWorkflowMessage({ ...base, blsStatus: 'running', mode: 'beginner' })).toBe(
      'Previewing likely transit signals...',
    );
  });

  it('covers running workflow with and without a job status, both modes', () => {
    expect(getWorkflowMessage({ ...base, workflow: 'running', jobStatus: 'started', mode: 'beginner' })).toBe(
      'Analysis is started...',
    );
    expect(getWorkflowMessage({ ...base, workflow: 'running', jobStatus: 'started', mode: 'advanced' })).toBe(
      'Analysis job started...',
    );
    expect(getWorkflowMessage({ ...base, workflow: 'running', mode: 'beginner' })).toBe(
      'Starting the full analysis...',
    );
    expect(getWorkflowMessage({ ...base, workflow: 'running', mode: 'advanced' })).toBe('Submitting analysis job...');
  });

  it('covers complete-with-zero-candidates for preview and analysis, both modes', () => {
    const zero = { ...base, workflow: 'complete' as const, hasResult: true, candidateCount: 0 };
    expect(getWorkflowMessage({ ...zero, resultKind: 'preview', mode: 'beginner' })).toBe(
      'Preview finished without strong candidates. Try another product or run full analysis.',
    );
    expect(getWorkflowMessage({ ...zero, resultKind: 'analysis', mode: 'beginner' })).toBe(
      'Analysis finished without candidates for this product.',
    );
    expect(getWorkflowMessage({ ...zero, resultKind: 'preview', mode: 'advanced' })).toBe(
      'BLS preview finished with no candidates in this period range.',
    );
    expect(getWorkflowMessage({ ...zero, resultKind: 'analysis', mode: 'advanced' })).toBe(
      'Analysis finished with no candidates for this product.',
    );
  });

  it('covers complete-with-candidates for preview and analysis, both modes', () => {
    const done = { ...base, workflow: 'complete' as const, hasResult: true, candidateCount: 2 };
    expect(getWorkflowMessage({ ...done, resultKind: 'preview', mode: 'beginner' })).toBe(
      'Preview candidates are ready. Pick one to inspect the plots.',
    );
    expect(getWorkflowMessage({ ...done, resultKind: 'analysis', mode: 'beginner' })).toBe(
      'Analysis results are ready. Review candidates and plots.',
    );
    expect(getWorkflowMessage({ ...done, resultKind: 'preview', mode: 'advanced' })).toBe(
      'BLS preview candidates are ready for review.',
    );
    expect(getWorkflowMessage({ ...done, resultKind: 'analysis', mode: 'advanced' })).toBe(
      'Analysis candidates are ready for review.',
    );
  });

  it('covers failed workflow in both modes', () => {
    expect(getWorkflowMessage({ ...base, workflow: 'failed', mode: 'beginner' })).toBe(
      'Something needs attention. Check the message panel for details.',
    );
    expect(getWorkflowMessage({ ...base, workflow: 'failed', mode: 'advanced' })).toBe(
      'Workflow needs attention; see the error panel.',
    );
  });

  it('covers product-selected beginner mode and the idle fallback in both modes', () => {
    expect(getWorkflowMessage({ ...base, workflow: 'product-selected', mode: 'beginner' })).toBe(
      'Observation file selected. Preview candidates or run the full analysis.',
    );
    expect(getWorkflowMessage({ ...base, mode: 'beginner' })).toBe(
      'Choose a mission, then search for a target to begin.',
    );
    expect(getWorkflowMessage({ ...base, mode: 'advanced' })).toBe('Search for a target to begin.');
    // default mode (omitted) should behave as advanced
    expect(getWorkflowMessage({ ...base })).toBe('Search for a target to begin.');
  });

  it('handles complete workflow without hasResult (skips zero-candidate branch)', () => {
    expect(
      getWorkflowMessage({
        ...base,
        workflow: 'complete',
        hasResult: false,
        candidateCount: 0,
        resultKind: 'analysis',
      }),
    ).toBe('Analysis candidates are ready for review.');
  });
});
