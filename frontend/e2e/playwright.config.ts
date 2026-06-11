import { defineConfig } from '@playwright/test';

const port = process.env.E2E_PORT || '3000';
const baseURL = `http://localhost:${port}`;
const backendContract = process.env.E2E_BACKEND_CONTRACT === '1';
const backendPort = process.env.E2E_BACKEND_PORT || '8010';
const backendURL = `http://127.0.0.1:${backendPort}`;
const frontendWebServer = {
  command: process.env.E2E_PORT ? `NEXT_DIST_DIR=.next-e2e-${port} npx next dev -p ${port}` : 'npm run dev',
  url: baseURL,
  reuseExistingServer: !process.env.CI,
  timeout: 60_000,
  cwd: '..',
};
const backendWebServer = {
  command: [
    'LOOMAI_CONTRACT_MODE=1',
    'LOOMAI_NO_AUTH=1',
    'LOOMAI_DISABLE_BACKGROUND_JOBS=1',
    'FABRIC_STORAGE_DIR=/tmp/loomai-contract',
    'FABRIC_CONFIG_DIR=/tmp/loomai-contract/fabric_config',
    'FABRIC_TOKEN_FILE=/tmp/loomai-contract/fabric_config/id_token.json',
    'FABRIC_PROJECT_ID=contract-project',
    'MPLCONFIGDIR=/tmp/loomai-contract/matplotlib',
    `sh -c 'if .venv/bin/python -c "import uvicorn" >/dev/null 2>&1; then exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}; else exec python -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}; fi'`,
  ].join(' '),
  url: `${backendURL}/api/health`,
  reuseExistingServer: !process.env.CI,
  timeout: 60_000,
  cwd: '../../backend',
};
const webServer = backendContract ? [backendWebServer, frontendWebServer] : frontendWebServer;

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['html', { open: 'never', outputFolder: 'playwright-report' }]],
  outputDir: 'test-results',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  webServer,
  projects: [
    {
      name: 'mocked-e2e',
      testMatch: /.*\.mock\.spec\.ts/,
      use: { browserName: 'chromium' },
    },
    {
      name: 'backend-contract',
      testMatch: /.*\.contract\.spec\.ts/,
      use: { browserName: 'chromium' },
    },
    {
      name: 'live-e2e',
      testMatch: /.*\.live\.spec\.ts/,
      use: { browserName: 'chromium' },
    },
  ],
});
