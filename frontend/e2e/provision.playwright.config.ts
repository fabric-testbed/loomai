import { defineConfig } from '@playwright/test';

const port = process.env.E2E_PORT || '3000';
const baseURL = `http://localhost:${port}`;

export default defineConfig({
  testDir: './tests',
  testIgnore: /.*\.contract\.spec\.ts/,
  fullyParallel: process.env.E2E_FULLY_PARALLEL === '1',
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: Number(process.env.E2E_WORKERS || '3'),
  reporter: [['html', { open: 'never', outputFolder: 'playwright-report' }]],
  outputDir: 'test-results',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: process.env.E2E_PORT ? `NEXT_DIST_DIR=.next-e2e-${port} npx next dev -p ${port}` : 'npm run dev',
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    cwd: '..',
  },
});
