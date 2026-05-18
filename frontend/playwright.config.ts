import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';

const chromeExecutablePath = process.env.PLAYWRIGHT_CHROME_EXECUTABLE_PATH ?? '/opt/google/chrome/chrome';
const launchOptions = existsSync(chromeExecutablePath) ? { executablePath: chromeExecutablePath } : undefined;

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [['html', { open: 'never' }], ['list']],
  outputDir: './test-results',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    launchOptions,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-chromium',
      grep: /app loads|product selection/,
      use: { ...devices['Pixel 5'] },
    },
  ],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
    env: {
      VITE_ANALYSIS_POLL_LIMIT: '2',
      VITE_ANALYSIS_POLL_INTERVAL_MS: '25',
    },
  },
});
