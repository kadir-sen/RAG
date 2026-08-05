import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.FORENSIC_E2E_BASE_URL || 'http://127.0.0.1:4174';
const externalServer = Boolean(process.env.FORENSIC_E2E_BASE_URL);

export default defineConfig({
  testDir: './tests/forensic',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [
    ['html', { open: 'never', outputFolder: '../playwright-report-forensic' }],
    process.env.CI ? ['github'] : ['list'],
  ],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: externalServer
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1 --port 4174',
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
