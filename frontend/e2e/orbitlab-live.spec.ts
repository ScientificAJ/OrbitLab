import { expect, test } from '@playwright/test';

test.describe('live OrbitLab smoke', () => {
  test.skip(process.env.LIVE_ORBITLAB !== '1', 'Set LIVE_ORBITLAB=1 and start the backend/frontend stack to run.');

  test('loads the real UI and reaches backend model API', async ({ page, request, baseURL }) => {
    const apiBase = process.env.VITE_API_BASE_URL ?? '/api/v1';
    const modelsUrl = apiBase.startsWith('http')
      ? `${apiBase.replace(/\/$/, '')}/models`
      : new URL(`${apiBase.replace(/\/$/, '')}/models`, baseURL).toString();

    const response = await request.get(modelsUrl);
    expect(response.ok()).toBeTruthy();
    const models = await response.json();
    expect(models).toHaveProperty('nigraha_tess');

    // Live smoke targets the running stack, not the one-time install welcome.
    await page.addInitScript(() => window.localStorage.setItem('orbitlab-first-run-acknowledged', 'true'));
    await page.goto('/');
    await expect(page.getByText('OrbitLab')).toBeVisible();
    await expect(page.getByRole('button', { name: /Search/ })).toBeVisible();
    await expect(page.getByRole('combobox', { name: /Mission/ })).toBeVisible();
  });
});
