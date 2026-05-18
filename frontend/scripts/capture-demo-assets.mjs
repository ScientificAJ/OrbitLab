import { chromium } from '@playwright/test';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(__dirname, '..');
const repoRoot = resolve(frontendRoot, '..');
const screenshotDir = resolve(repoRoot, 'docs/assets/screenshots');
const demoDir = resolve(repoRoot, 'docs/assets/demo');
const API = '**/api/v1';

const target = { target_id: 'TIC 307210830', ra: 123.45, dec: -54.321, catalog: 'MAST' };
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

function json(route, body, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function installMocks(page) {
  await page.route(`${API}/health`, (route) =>
    json(route, {
      status: 'ok',
      api: 'ok',
      database: 'ok',
      worker_mode: 'inline',
      redis_configured: true,
      frontend: 'served separately',
      generated_at: '2026-05-16T00:00:00Z',
    }),
  );

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
    }),
  );

  await page.route(`${API}/search?*`, (route) => json(route, [target]));
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
}

function startServer() {
  const child = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1'], {
    cwd: frontendRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      VITE_ANALYSIS_POLL_LIMIT: '2',
      VITE_ANALYSIS_POLL_INTERVAL_MS: '25',
    },
    detached: true,
  });

  let output = '';
  child.stdout.on('data', (chunk) => {
    output += chunk.toString();
  });
  child.stderr.on('data', (chunk) => {
    output += chunk.toString();
  });

  return { child, getOutput: () => output };
}

async function waitForServer(url) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Vite is still booting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function capture(page, name) {
  await page.screenshot({ path: resolve(screenshotDir, name), fullPage: true });
}

function runChecked(command, args) {
  const result = spawnSync(command, args, { cwd: repoRoot, stdio: 'inherit' });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed with exit code ${result.status}`);
  }
}

function buildDemoGif() {
  const frames = [
    '01-search-start.png',
    '02-product-selected.png',
    '03-aperture-editor.png',
    '05-bls-preview.png',
    '06-analysis-workbench.png',
    '07-model-status.png',
    '08-voyager-mode.png',
  ];

  for (const [index, frame] of frames.entries()) {
    runChecked('ffmpeg', [
      '-y',
      '-hide_banner',
      '-loglevel',
      'error',
      '-i',
      resolve(screenshotDir, frame),
      '-vf',
      'scale=960:-1,crop=960:620:0:0',
      '-frames:v',
      '1',
      '-update',
      '1',
      resolve(demoDir, `frame-${String(index + 1).padStart(2, '0')}.png`),
    ]);
  }

  runChecked('ffmpeg', [
    '-y',
    '-hide_banner',
    '-loglevel',
    'error',
    '-framerate',
    '1',
    '-i',
    resolve(demoDir, 'frame-%02d.png'),
    '-vf',
    'fps=8,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5',
    '-loop',
    '0',
    resolve(demoDir, 'orbitlab-demo.gif'),
  ]);
}

async function main() {
  await mkdir(screenshotDir, { recursive: true });
  await mkdir(demoDir, { recursive: true });

  const server = startServer();
  try {
    await waitForServer('http://127.0.0.1:5173');

    const executablePath = process.env.PLAYWRIGHT_CHROME_EXECUTABLE_PATH ?? '/opt/google/chrome/chrome';
    const browser = await chromium.launch({
      executablePath: existsSync(executablePath) ? executablePath : undefined,
    });
    const page = await browser.newPage({ viewport: { width: 1440, height: 920 }, deviceScaleFactor: 1 });

    await installMocks(page);
    await page.addInitScript(() => {
      window.localStorage.setItem('orbitlab-mode', 'advanced');
      window.localStorage.setItem('orbitlab-theme', 'space');
      window.localStorage.setItem('orbitlab-beginner-tour-completed', 'true');
    });

    await page.goto('http://127.0.0.1:5173');
    await page.getByText('OrbitLab', { exact: true }).waitFor();
    await capture(page, '01-search-start.png');

    await page.getByLabel('target search').fill(target.target_id);
    await page.getByRole('button', { name: /^Search$/ }).click();
    await page.getByRole('button', { name: new RegExp(target.target_id) }).click();
    await page.getByRole('button', { name: /TESS Sector 12 TPF/ }).click();
    await capture(page, '02-product-selected.png');

    await page.getByRole('button', { name: /Aperture/ }).click();
    await page.getByRole('button', { name: /Toggle aperture pixel row 1 column 1/ }).click();
    await capture(page, '03-aperture-editor.png');
    await page.getByRole('button', { name: 'Apply Mask' }).click();

    await page.getByRole('button', { name: /BLS Search/ }).click();
    await capture(page, '04-bls-controls.png');
    await page.getByRole('button', { name: /Run Preview Search/ }).click();
    await page.getByRole('button', { name: /preview-1/ }).waitFor();
    await capture(page, '05-bls-preview.png');

    await page.getByRole('button', { name: /Run Analysis/ }).click();
    await page.getByRole('button', { name: /candidate-1/ }).waitFor();
    await capture(page, '06-analysis-workbench.png');

    await page.getByRole('button', { name: /ML Status/ }).click();
    await capture(page, '07-model-status.png');
    await page.keyboard.press('Escape');

    await page.getByLabel('target search').fill('voyager');
    await page.getByRole('button', { name: /^Search$/ }).click();
    await page.getByRole('dialog', { name: 'Voyager Mode Unlocked' }).waitFor();
    await capture(page, '08-voyager-mode.png');

    await browser.close();
    buildDemoGif();
  } catch (error) {
    console.error(server.getOutput());
    throw error;
  } finally {
    if (server.child.pid) {
      try {
        process.kill(-server.child.pid, 'SIGTERM');
      } catch {
        server.child.kill('SIGTERM');
      }
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
