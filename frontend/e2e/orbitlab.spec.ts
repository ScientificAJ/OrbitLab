import { expect, Page, Route, test } from '@playwright/test';
import { inflateSync } from 'node:zlib';

const API = '**/api/v1';

const target = { target_id: 'TIC 307210830', ra: 123.45, dec: -54.321, catalog: 'MAST' };
const keplerTarget = { target_id: 'Kepler-10', ra: 285.67, dec: 50.24, catalog: 'MAST' };
const trappistAlias = {
  target_id: 'TRAPPIST-1',
  ra: null,
  dec: null,
  catalog: 'ALIAS',
  match_type: 'alias',
  matched_query: 'trappist',
};
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
        label: 'planet-candidate',
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

function pngHasColorVariance(png: Buffer) {
  const signatureLength = 8;
  let offset = signatureLength;
  let width = 0;
  let height = 0;
  let colorType = 0;
  const idatChunks: Buffer[] = [];

  while (offset < png.length) {
    const length = png.readUInt32BE(offset);
    const type = png.toString('ascii', offset + 4, offset + 8);
    const data = png.subarray(offset + 8, offset + 8 + length);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      colorType = data[9];
    }
    if (type === 'IDAT') idatChunks.push(data);
    if (type === 'IEND') break;
    offset += length + 12;
  }

  if (!width || !height || ![2, 6].includes(colorType)) return false;

  const bytesPerPixel = colorType === 6 ? 4 : 3;
  const stride = width * bytesPerPixel;
  const inflated = inflateSync(Buffer.concat(idatChunks));
  const rows: number[][] = [];
  let cursor = 0;

  for (let y = 0; y < height; y += 1) {
    const filter = inflated[cursor];
    cursor += 1;
    const row = Array.from(inflated.subarray(cursor, cursor + stride));
    cursor += stride;
    const previous = rows[y - 1] ?? Array(stride).fill(0);

    for (let x = 0; x < stride; x += 1) {
      const left = x >= bytesPerPixel ? row[x - bytesPerPixel] : 0;
      const up = previous[x];
      const upLeft = x >= bytesPerPixel ? previous[x - bytesPerPixel] : 0;
      if (filter === 1) row[x] = (row[x] + left) & 255;
      if (filter === 2) row[x] = (row[x] + up) & 255;
      if (filter === 3) row[x] = (row[x] + Math.floor((left + up) / 2)) & 255;
      if (filter === 4) {
        const p = left + up - upLeft;
        const pa = Math.abs(p - left);
        const pb = Math.abs(p - up);
        const pc = Math.abs(p - upLeft);
        row[x] = (row[x] + (pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft)) & 255;
      }
    }
    rows.push(row);
  }

  const first = rows[0].slice(0, 3);
  return rows.some((row) => {
    for (let index = 0; index < row.length; index += 160) {
      if (
        Math.abs(row[index] - first[0]) > 8 ||
        Math.abs(row[index + 1] - first[1]) > 8 ||
        Math.abs(row[index + 2] - first[2]) > 8
      ) {
        return true;
      }
    }
    return false;
  });
}

async function installBaseMocks(page: Page) {
  await page.route(`${API}/models`, (route) =>
    json(route, {
      nigraha_tess: {
        model_id: 'nigraha-tess-global-nodropout-binary-ensemble',
        status: 'ready',
        source:
          'ExoplanetML/Nigraha models/weights/global_nodropout/binary at c4365b41dd02b187c3210189ffe8e3ead584f4f5',
        version: 'c4365b41dd02b187c3210189ffe8e3ead584f4f5',
        checksum: '1ff146fb1cd3f9bfd354c3c71a95b93adfee53edaf494cc5507bd5865d850f93',
        schema_version: 'orbitlab.nigraha.v1',
      },
      kepler_astronet: {
        model_id: 'kepler-astronet-cnn-bilstm-attention',
        status: 'ready',
        source: 'bibinthomas123/Astronet TensorFlow checkpoint at 9809ce92306f11fbdc96f9830b522026710a3883',
        version: '9809ce92306f11fbdc96f9830b522026710a3883',
        checksum: '68dee983c65e9e4cd67748906e8a6796ce1810f7cbe66bf9a34938af9b61b9a3',
        schema_version: 'orbitlab.astronet.v1',
      },
      k2_exomac_kkt: {
        model_id: 'k2-exomac-kkt-randomforest',
        status: 'ready',
        source: 'ZapatoProgramming/ExoMAC-KKT pretrained NASA Kepler/K2/TESS catalog classifier',
        version: '5cda5310d5a163679c6915f9463a4d6afc312483',
        checksum: 'd8a28d99cb29be8cfd0870d964bdde0bb3e97ee8d0aee9fded946ad5a54b2c2c',
        schema_version: 'orbitlab.exomac-kkt.v1',
      },
      k2_astronet: {
        model_id: 'k2-astronet-family',
        mission: 'K2',
        status: 'unavailable',
        detail: 'Published AstroNet-K2 paper found; no public downloadable checkpoint is registered.',
      },
    }),
  );

  await page.route(`${API}/search?*`, (route) => {
    const url = new URL(route.request().url());
    const query = url.searchParams.get('query') ?? '';
    if (query.includes('empty')) return json(route, []);
    if (query.includes('error')) return json(route, { detail: 'MAST search unavailable' }, 502);
    if (query.toLowerCase() === 'trappist') return json(route, [trappistAlias, target]);
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
    json(route, {
      report_id: analysisResult.result_id,
      generated_at: '2026-05-14T12:00:00Z',
      format: 'json',
      result: analysisResult,
    }),
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
  await expect(page.getByTestId('orbit-empty-state')).toContainText('Run BLS Search or Analysis');
  await expect(page.getByTestId('orbit-scene').getByTestId(/orbit-label-/)).toHaveCount(0);
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
  await expect(page.getByText('No matching targets found for "empty target".')).toBeVisible();

  await page.getByLabel('target search').fill('error target');
  await page.getByRole('button', { name: /^Search$/ }).click();
  await expect(page.getByRole('alert')).toContainText('MAST search unavailable');
  await expect(page.getByText('Search failed for "error target".')).toBeVisible();
  await expect(page.getByTestId('workflow-status')).toHaveText('failed');
});

test('trappist search shows a suggested canonical target before product lookup', async ({ page }) => {
  await openApp(page);

  await page.getByLabel('target search').fill('trappist');
  await page.getByRole('button', { name: /^Search$/ }).click();

  await expect(page.getByText('Suggested targets')).toBeVisible();
  await expect(page.getByRole('button', { name: /TRAPPIST-1/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /TESS Sector 12 TPF/ })).not.toBeVisible();

  const productsRequest = page.waitForRequest((request) => request.url().includes('/targets/TRAPPIST-1/products'));
  await page.getByRole('button', { name: /TRAPPIST-1/ }).click();
  await productsRequest;
  await expect(page.getByRole('button', { name: /TESS Sector 12 TPF/ })).toBeVisible();
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
  await expect(page.getByTestId('orbit-empty-state')).toContainText('Run BLS Search or Analysis');
  await expect(page.getByTestId('orbit-scene').getByTestId(/orbit-label-/)).toHaveCount(0);
  await expect(page.getByTestId('workflow-status')).toHaveText('idle');
});

test('search API failures clear stale matches and selected product state', async ({ page }) => {
  await openApp(page);
  await chooseProduct(page);
  await expect(page.getByRole('button', { name: /TESS Sector 12 TPF/ })).toBeVisible();

  await page.getByLabel('target search').fill('error target');
  await page.getByRole('button', { name: /^Search$/ }).click();

  await expect(page.getByRole('alert')).toContainText('MAST search unavailable');
  await expect(page.getByText('Search failed for "error target".')).toBeVisible();
  await expect(page.getByRole('button', { name: new RegExp(target.target_id) })).not.toBeVisible();
  await expect(page.getByRole('button', { name: /TESS Sector 12 TPF/ })).not.toBeVisible();
  await expect(page.getByText('Select a target first.')).toBeVisible();
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
  await expect(page.getByRole('dialog', { name: 'Aperture Mask Editor' })).toBeVisible();
  await expect(page.getByTestId('aperture-selection-summary')).toHaveText('0 pixels selected.');
  await page.getByRole('button', { name: 'Apply Mask' }).click();
  await expect(page.getByRole('alert')).toContainText('Please select at least one pixel');

  const pixel = page.getByTestId('aperture-pixel-0-0');
  await expect(pixel).toHaveAttribute('aria-label', /Toggle aperture pixel row 1 column 1/);
  await expect(pixel).toHaveAttribute('aria-pressed', 'false');
  await pixel.focus();
  await page.keyboard.press('Enter');
  await expect(pixel).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('aperture-selection-summary')).toHaveText('1 pixel selected.');
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
  await expect(page.getByTestId('orbit-label-preview-1')).toBeVisible();
  await expect(page.getByTestId('orbit-label-preview-1')).toHaveClass(/active/);
  await page.getByRole('button', { name: /preview-2/ }).click();
  await expect(page.getByTestId('orbit-label-preview-2')).toHaveClass(/active/);
  const orbitCanvas = page.getByTestId('orbit-canvas');
  await expect(orbitCanvas).toBeVisible();
  expect(pngHasColorVariance(await orbitCanvas.screenshot())).toBe(true);
  await expect(page.getByTestId('periodogram-plot').locator('.js-plotly-plot')).toBeVisible();
  await expect(page.getByTestId('folded-curve-plot').locator('.js-plotly-plot')).toBeVisible();

  await page.route(`${API}/bls-preview`, (route) =>
    json(route, { detail: 'min_period must be less than max_period' }, 422),
  );
  await page.getByRole('button', { name: /BLS Search/ }).click();
  await page.getByRole('button', { name: /Run Preview Search/ }).click();
  await expect(page.getByRole('alert')).toContainText('min_period must be less than max_period');
  await expect(page.getByRole('dialog', { name: 'BLS Search Controls' })).toBeVisible();
  await expect(page.getByRole('button', { name: /preview-1/ })).not.toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(1);
});

test('failed BLS preview clears stale preview data but preserves full analysis results', async ({ page }) => {
  await openApp(page);
  await chooseProduct(page);

  await page.getByRole('button', { name: /BLS Search/ }).click();
  await page.getByRole('button', { name: /Run Preview Search/ }).click();
  await expect(page.getByRole('button', { name: /preview-1/ })).toBeVisible();

  await page.route(`${API}/bls-preview`, (route) => json(route, { detail: 'BLS preview unavailable' }, 500));
  await page.getByRole('button', { name: /BLS Search/ }).click();
  await page.getByRole('button', { name: /Run Preview Search/ }).click();
  await expect(page.getByRole('alert')).toContainText('BLS preview unavailable');
  await expect(page.getByRole('button', { name: /preview-1/ })).not.toBeVisible();
  await expect(page.getByText('No candidates loaded.')).toBeVisible();

  await page.getByRole('button', { name: /Close BLS Search Controls/ }).click();
  await page.route(`${API}/analysis-jobs`, (route) =>
    json(
      route,
      {
        job_id: 'job-complete',
        status: 'complete',
        created_at: '2026-05-14T12:00:00Z',
        result_id: analysisResult.result_id,
      },
      201,
    ),
  );
  await page.route(`${API}/analysis-results/${analysisResult.result_id}`, (route) => json(route, analysisResult));
  await page.getByRole('button', { name: /Run Analysis/ }).click();
  await expect(page.getByRole('button', { name: /candidate-1/ })).toBeVisible();
  await expect(page.getByTestId('orbit-label-candidate-1')).toBeVisible();

  await page.getByRole('button', { name: /BLS Search/ }).click();
  await page.getByRole('button', { name: /Retry Preview Search|Run Preview Search/ }).click();
  await expect(page.getByRole('alert')).toContainText('BLS preview unavailable');
  await expect(page.getByRole('button', { name: /candidate-1/ })).toBeVisible();
  await expect(page.getByTestId('workflow-status')).toHaveText('complete');
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
    json(
      route,
      { job_id: 'job-failed', status: 'failed', created_at: '2026-05-14T12:00:00Z', error: 'BLS failed to converge' },
      201,
    ),
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

  await expect(page.getByRole('dialog', { name: 'Model Status & Registry' })).toBeVisible();
  await expect(page.getByText('ready').first()).toBeVisible();
  await expect(page.getByText('unavailable').first()).toBeVisible();
  await expect(
    page.getByText('No public downloadable K2 AstroNet checkpoint is registered for OrbitLab.'),
  ).toBeVisible();
  await expect(page.getByRole('heading', { name: 'K2 ExoMAC KKT' })).toBeVisible();
  await expect(page.locator('.model-info-card h3').filter({ hasText: '_' })).toHaveCount(0);
});

test('modal dialogs are single, labelled, and dismissible', async ({ page }) => {
  await openApp(page);

  await page.getByRole('button', { name: /ML Status ready/ }).click();
  await expect(page.getByRole('dialog', { name: 'Model Status & Registry' })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(1);

  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);

  await page.getByRole('button', { name: 'Sessions' }).click();
  await expect(page.getByRole('dialog', { name: 'Saved Sessions' })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(1);
  await page.getByRole('button', { name: /Close Saved Sessions/ }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
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
    json(
      route,
      {
        job_id: 'job-complete',
        status: 'complete',
        created_at: '2026-05-14T12:00:00Z',
        result_id: analysisResult.result_id,
      },
      201,
    ),
  );
  await page.route(`${API}/analysis-results/${analysisResult.result_id}`, (route) => json(route, analysisResult));
  await page.getByRole('button', { name: /Run Analysis/ }).click();
  await expect(page.getByRole('button', { name: /candidate-1/ })).toBeVisible();

  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export report' }).click();
  expect((await download).suggestedFilename()).toBe('orbitlab-report-TIC 307210830-result-1.json');
});
