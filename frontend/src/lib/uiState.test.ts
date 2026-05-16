import { describe, expect, it } from 'vitest';
import { buildAperturePixelLabel, formatModelDisplayName, getMatchEmptyMessage, getWorkflowMessage } from './uiState';

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
});
