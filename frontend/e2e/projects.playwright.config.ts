import { defineConfig } from '@playwright/test';

const baseURL = process.env.PROJECTS_E2E_BASE_URL || 'http://127.0.0.1:4173';
const externalServer = Boolean(process.env.PROJECTS_E2E_BASE_URL);

export default defineConfig({
  testDir: './tests/projects',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['html', { open: 'never', outputFolder: '../playwright-report-projects' }],
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
        command: 'npm run dev -- --host 127.0.0.1 --port 4173',
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  projects: [
    { name: 'phone-360', use: { viewport: { width: 360, height: 800 }, browserName: 'chromium' } },
    { name: 'phone-390', use: { viewport: { width: 390, height: 844 }, browserName: 'chromium' } },
    { name: 'phone-430', use: { viewport: { width: 430, height: 932 }, browserName: 'chromium' } },
    {
      name: 'tablet-768',
      use: { viewport: { width: 768, height: 1024 }, browserName: 'chromium' },
    },
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 }, browserName: 'chromium' } },
  ],
});
