import { describe, expect, it } from 'vitest';
import {
  buildAperturePixelLabel,
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
    expect(getMatchEmptyMessage('searching', 'TOI-700', true)).toBe('Searching for "TOI-700"...');
    expect(getMatchEmptyMessage('failed', 'bad target', true)).toBe('Search failed for "bad target".');
    expect(getMatchEmptyMessage('empty', 'empty target', true)).toBe('No matching targets found for "empty target".');
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
});
