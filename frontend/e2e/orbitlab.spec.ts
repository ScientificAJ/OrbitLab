import { expect, Page, Route, test } from '@playwright/test';

const API = '**/api/v1';

const target = { target_id: 'TIC 307210830', ra: 123.45, dec: -54.321, catalog: 'MAST' };
const keplerTarget = { target_id: 'Kepler-10', ra: 285.67, dec: 50.24, catalog: 'MAST' };
const product = {
  product_id: 'TESS Sector 12 TPF',
  mission: 'TESS',
  description: 'Target pixel file, sector 12',
  size: 2048,
  product_uri: 'mast:tess/product-1',
};

const previewResult = {
  periodogram: { period: [0.5, 1.2, 2.4, 4.8], power: [0.1, 0.8, 0.4, 0.2], duration: [0.1, 0.1, 0.2, 0.2] },
  candidates: [
    { candidate_id: 'preview-1', period: 1.2345, epoch: 0.12, duration: 0.08, depth: 0.0021, signal_to_noise: 18.4 },
    { candidate_id: 'preview-2', period: 3.2109, epoch: 0.42, duration: 0.11, depth: 0.0012, signal_to_noise: 9.7 },
  ],
  folded_curves: {
    'preview-1': { phase: [-0.5, 0, 0.5], flux: [1.0, 0.998, 1.0] },
    'preview-2': { phase: [-0.5, 0, 0.5], flux: [1.0, 0.999, 1.0] },
  },
  bls_light_curve: { time: [1, 2, 3, 4], flux: [1, 0.998, 1.001, 1] },
  preprocessing: { finite_points: 4 },
};

const analysisResult = {
  result_id: 'result-12345678',
  target_id: target.target_id,
  mission: 'TESS',
  candidates: [
    {
      candidate_id: 'candidate-1',
      period: 1.2345,
      epoch: 0.12,
      duration: 0.08,
      depth: 0.0021,
      signal_to_noise: 18.4,
      physics: {
        radius_ratio: 0.045,
        planet_radius_earth: 1.8,
        semi_major_axis_au: 0.054,
        equilibrium_temperature_k: 285,
        is_in_habitable_zone: true,
        is_temperature_habitable: true,
      },
      validation: {
        odd_even_depth_delta: 0.00001,
        secondary_depth: 0.00002,
        duration_plausible: true,
      },
      ml: {
        probability: 0.91,
        threshold: 0.5,
        label: 'planet_candidate',
        model_version: 'test',
        model_source: 'mock fixture',
        input_tensor_checksum: 'abc123def456',
        preprocessing_compatible: true,
        citation: 'test-only fixture',
      },
    },
  ],
  periodogram: previewResult.periodogram,
  folded_curves: {
    'candidate-1': { phase: [-0.5, 0, 0.5], flux: [1.0, 0.998, 1.0] },
  },
  light_curve: previewResult.bls_light_curve,
  bls_light_curve: previewResult.bls_light_curve,
  preprocessing: { source: 'mock' },
};

const savedSession = {
  session_id: 'session-1',
  name: 'TESS-TIC 307210830-2026-05-14 17:30',
  created_at: '2026-05-14T12:00:00Z',
  payload: {
    mission: 'TESS',
    query: 'TIC 307210830',
    products: [product],
    selectedTarget: target,
    selectedProduct: product,
    result: analysisResult,
    selectedId: 'candidate-1',
    workflow: 'complete',
  },
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function installBaseMocks(page: Page) {
  await page.route(`${API}/models`, (route) =>
    json(route, {
      nigraha_tess: { status: 'ready', source: 'local test registry', version: '1.0.0', checksum: 'abcdef1234567890' },
      kepler_astronet: { status: 'unavailable', detail: 'missing checkpoint', source: 'registry' },
      k2_exomac_kkt: { status: 'unavailable', detail: 'missing K2 artifact', source: 'registry' },
      k2_astronet: { status: 'unavailable', detail: 'No public K2 checkpoint registered yet.' },
    }),
  );

  await page.route(`${API}/search?*`, (route) => {
    const url = new URL(route.request().url());
    const query = url.searchParams.get('query') ?? '';
    if (query.includes('empty')) return json(route, []);
    if (query.includes('error')) return json(route, { detail: 'MAST search unavailable' }, 502);
    if (url.searchParams.get('mission') === 'Kepler') return json(route, [keplerTarget]);
    return json(route, [target]);
  });

  await page.route(`${API}/targets/*/products?*`, (route) => json(route, [product]));
  await page.route(`${API}/tpf-preview?*`, (route) =>
    json(route, {
      shape: [2, 2],
      image: [
        [10, 20],
        [15, 25],
      ],
      finite_min: 10,
      finite_max: 25,
    }),
  );
  await page.route(`${API}/aperture-masks`, (route) =>
    json(
      route,
      {
        aperture_mask_id: 'aperture-1',
        target_id: target.target_id,
        product_uri: product.product_uri,
        mask: [
          [true, false],
          [false, false],
        ],
        reason: 'User defined aperture in OrbitLab',
        created_at: '2026-05-14T12:00:00Z',
      },
      201,
    ),
  );
  await page.route(`${API}/bls-preview`, (route) => json(route, previewResult));
  await page.route(`${API}/sessions`, async (route) => {
    if (route.request().method() === 'POST') return json(route, savedSession, 201);
    return json(route, [savedSession]);
  });
  await page.route(`${API}/reports/*`, (route) =>
    json(route, { report_id: analysisResult.result_id, generated_at: '2026-05-14T12:00:00Z', format: 'json', result: analysisResult }),
  );
}

async function openApp(page: Page) {
  await installBaseMocks(page);
  await page.goto('/');
  await expect(page.getByText('OrbitLab')).toBeVisible();
}

async function chooseProduct(page: Page) {
  await page.getByLabel('target search').fill(target.target_id);
  await page.getByRole('button', { name: /^Search$/ }).click();
  await page.getByRole('button', { name: new RegExp(target.target_id) }).click();
  await page.getByRole('button', { name: /TESS Sector 12 TPF/ }).click();
}

test('app loads without browser console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', (error) => errors.push(error.message));

  await openApp(page);

  await expect(page.getByTestId('workflow-status')).toHaveText('idle');
  expect(errors).toEqual([]);
});

test('search handles loading, success, empty, and API error states', async ({ page }) => {
  await openApp(page);

  await page.unroute(`${API}/search?*`);
  let releaseSearch: (() => void) | undefined;
  await page.route(`${API}/search?*`, async (route) => {
    const url = new URL(route.request().url());
    const query = url.searchParams.get('query') ?? '';
    if (query === target.target_id) {
      await new Promise<void>((resolve) => {
        releaseSearch = resolve;
      });
    }
    if (query.includes('empty')) return json(route, []);
    if (query.includes('error')) return json(route, { detail: 'MAST search unavailable' }, 502);
    return json(route, [target]);
  });

  await page.getByLabel('target search').fill(target.target_id);
  const searchRequest = page.waitForRequest(`${API}/search?*`);
  await page.getByRole('button', { name: /^Search$/ }).click();
  await searchRequest;
  await expect(page.getByTestId('workflow-status')).toHaveText('searching');
  releaseSearch?.();
  await expect(page.getByRole('button', { name: new RegExp(target.target_id) })).toBeVisible();

  await page.getByLabel('target search').fill('empty target');
  await page.getByRole('button', { name: /^Search$/ }).click();
  await expect(page.getByText('No matching targets found.')).toBeVisible();

  await page.getByLabel('target search').fill('error target');
  await page.getByRole('button', { name: /^Search$/ }).click();
  await expect(page.getByRole('alert')).toContainText('MAST search unavailable');
  await expect(page.getByTestId('workflow-status')).toHaveText('failed');
});

test('mission switch clears stale target, product, and result state', async ({ page }) => {
  await openApp(page);
  await chooseProduct(page);

  await page.getByRole('button', { name: /BLS Search/ }).click();
  await page.getByRole('button', { name: /Run Preview Search/ }).click();
  await expect(page.getByRole('button', { name: /preview-1/ })).toBeVisible();

  await page.getByLabel('Mission').selectOption('Kepler');

  await expect(page.getByText(target.target_id)).not.toBeVisible();
  await expect(page.getByText('Select a target first.')).toBeVisible();
  await expect(page.getByText('No candidates loaded.')).toBeVisible();
  await expect(page.getByTestId('workflow-status')).toHaveText('idle');
});

test('product selection enables aperture, BLS, and analysis controls', async ({ page }) => {
  await openApp(page);

  await expect(page.getByRole('button', { name: /Aperture/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: /BLS Search/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: /Run Analysis/ })).toBeDisabled();

  await chooseProduct(page);

  await expect(page.getByRole('button', { name: /Aperture/ })).toBeEnabled();
  await expect(page.getByRole('button', { name: /BLS Search/ })).toBeEnabled();
  await expect(page.getByRole('button', { name: /Run Analysis/ })).toBeEnabled();
});

test('aperture modal validates empty masks and saves selected pixels', async ({ page }) => {
  await openApp(page);
  await chooseProduct(page);

  await page.getByRole('button', { name: /Aperture/ }).click();
  await expect(page.getByRole('heading', { name: 'Aperture Mask Editor' })).toBeVisible();
  await page.getByRole('button', { name: 'Apply Mask' }).click();
  await expect(page.getByRole('alert')).toContainText('Please select at least one pixel');

  await page.getByTestId('aperture-pixel-0-0').click();
  await page.getByRole('button', { name: 'Apply Mask' }).click();

  await expect(page.getByRole('status')).toContainText('Custom aperture mask created.');
  await expect(page.getByRole('button', { name: /Aperture \(Custom\)/ })).toBeVisible();
});

test('BLS preview renders candidates, periodogram, folded plot, and API errors', async ({ page }) => {
  await openApp(page);
  await chooseProduct(page);

  await page.getByRole('button', { name: /BLS Search/ }).click();
  await page.getByRole('button', { name: /Run Preview Search/ }).click();

  await expect(page.getByRole('button', { name: /preview-1/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /preview-2/ })).toBeVisible();
  await expect(page.getByTestId('periodogram-plot').locator('.js-plotly-plot')).toBeVisible();
  await expect(page.getByTestId('folded-curve-plot').locator('.js-plotly-plot')).toBeVisible();

  await page.route(`${API}/bls-preview`, (route) => json(route, { detail: 'min_period must be less than max_period' }, 422));
  await page.getByRole('button', { name: /BLS Search/ }).click();
  await page.getByRole('button', { name: /Run Preview Search/ }).click();
  await expect(page.getByRole('alert')).toContainText('min_period must be less than max_period');
});

test('analysis jobs handle complete, failed, and polling timeout states', async ({ page }) => {
  await openApp(page);
  await chooseProduct(page);

  let pollCount = 0;
  await page.route(`${API}/analysis-jobs`, (route) =>
    json(route, { job_id: 'job-complete', status: 'queued', created_at: '2026-05-14T12:00:00Z' }, 201),
  );
  await page.route(`${API}/analysis-jobs/job-complete`, (route) => {
    pollCount += 1;
    return json(route, {
      job_id: 'job-complete',
      status: pollCount < 2 ? 'running' : 'complete',
      created_at: '2026-05-14T12:00:00Z',
      result_id: pollCount < 2 ? null : analysisResult.result_id,
    });
  });
  await page.route(`${API}/analysis-results/${analysisResult.result_id}`, (route) => json(route, analysisResult));

  await page.getByRole('button', { name: /Run Analysis/ }).click();
  await expect(page.getByRole('button', { name: /candidate-1/ })).toBeVisible();
  await expect(page.getByTestId('workflow-status')).toHaveText('complete');

  await page.route(`${API}/analysis-jobs`, (route) =>
    json(route, { job_id: 'job-failed', status: 'failed', created_at: '2026-05-14T12:00:00Z', error: 'BLS failed to converge' }, 201),
  );
  await page.getByRole('button', { name: /Run Analysis/ }).click();
  await expect(page.getByRole('alert')).toContainText('BLS failed to converge');
  await expect(page.getByTestId('workflow-status')).toHaveText('failed');

  await page.route(`${API}/analysis-jobs`, (route) =>
    json(route, { job_id: 'job-running', status: 'queued', created_at: '2026-05-14T12:00:00Z' }, 201),
  );
  await page.route(`${API}/analysis-jobs/job-running`, (route) =>
    json(route, { job_id: 'job-running', status: 'running', created_at: '2026-05-14T12:00:00Z' }),
  );
  await page.getByRole('button', { name: /Run Analysis/ }).click();
  await expect(page.getByRole('alert')).toContainText('Analysis is still running');
  await expect(page.getByTestId('workflow-status')).toHaveText('running');
});

test('model readiness modal shows ready and unavailable setup information', async ({ page }) => {
  await openApp(page);

  await page.getByRole('button', { name: /ML Status ready/ }).click();

  await expect(page.getByRole('heading', { name: 'Model Status & Registry' })).toBeVisible();
  await expect(page.getByText('ready').first()).toBeVisible();
  await expect(page.getByText('unavailable').first()).toBeVisible();
  await expect(page.getByText('scripts/fetch_kepler_astronet.py')).toBeVisible();
});

test('sessions save and restore expected UI state', async ({ page }) => {
  await openApp(page);
  await chooseProduct(page);

  await page.getByRole('button', { name: 'Save session' }).click();
  await expect(page.getByRole('status')).toContainText('Session saved successfully.');

  await page.getByRole('button', { name: 'Sessions' }).click();
  await page.getByRole('button', { name: /TESS-TIC 307210830/ }).click();

  await expect(page.getByRole('status')).toContainText('Restored session');
  await expect(page.getByText(target.target_id).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /candidate-1/ })).toBeVisible();
  await expect(page.getByTestId('workflow-status')).toHaveText('complete');
});

test('report export is disabled without full results and downloads valid reports', async ({ page }) => {
  await openApp(page);

  await expect(page.getByRole('button', { name: 'Export report' })).toBeDisabled();

  await chooseProduct(page);
  await page.route(`${API}/analysis-jobs`, (route) =>
    json(route, {
      job_id: 'job-complete',
      status: 'complete',
      created_at: '2026-05-14T12:00:00Z',
      result_id: analysisResult.result_id,
    }, 201),
  );
  await page.route(`${API}/analysis-results/${analysisResult.result_id}`, (route) => json(route, analysisResult));
  await page.getByRole('button', { name: /Run Analysis/ }).click();
  await expect(page.getByRole('button', { name: /candidate-1/ })).toBeVisible();

  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export report' }).click();
  expect((await download).suggestedFilename()).toBe('orbitlab-report-TIC 307210830-result-1.json');
});
