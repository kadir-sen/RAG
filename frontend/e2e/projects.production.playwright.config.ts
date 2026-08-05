import { defineConfig } from '@playwright/test';

const baseURL = process.env.PROD_BASE_URL;
if (!baseURL) throw new Error('PROD_BASE_URL is required for the read-only production smoke test.');

export default defineConfig({
  testDir: './tests/production',
  fullyParallel: false,
  retries: 1,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [
    ['html', { open: 'never', outputFolder: '../playwright-report-production' }],
    process.env.CI ? ['github'] : ['list'],
  ],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    navigationTimeout: 60_000,
  },
  projects: [
    {
      name: 'production-phone-390',
      use: { viewport: { width: 390, height: 844 }, browserName: 'chromium' },
    },
    {
      name: 'production-tablet-768',
      use: { viewport: { width: 768, height: 1024 }, browserName: 'chromium' },
    },
  ],
});
