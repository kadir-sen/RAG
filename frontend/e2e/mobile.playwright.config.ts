import { defineConfig } from '@playwright/test';

const baseURL = process.env.MOBILE_E2E_BASE_URL || 'http://127.0.0.1:4175';
const externalServer = Boolean(process.env.MOBILE_E2E_BASE_URL);

export default defineConfig({
  testDir: './tests/mobile',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [
    ['html', { open: 'never', outputFolder: '../playwright-report-mobile' }],
    process.env.CI ? ['github'] : ['list'],
  ],
  snapshotPathTemplate: '{testDir}/{testFilePath}-snapshots/{arg}-{projectName}{ext}',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: externalServer
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1 --port 4175',
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  projects: [
    { name: 'chromium-phone-360', use: { browserName: 'chromium', viewport: { width: 360, height: 800 } } },
    { name: 'chromium-phone-390', use: { browserName: 'chromium', viewport: { width: 390, height: 844 } } },
    { name: 'chromium-phone-430', use: { browserName: 'chromium', viewport: { width: 430, height: 932 } } },
    { name: 'chromium-tablet-768', use: { browserName: 'chromium', viewport: { width: 768, height: 1024 } } },
    { name: 'chromium-desktop-1440', use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-phone-390', use: { browserName: 'webkit', viewport: { width: 390, height: 844 } } },
    { name: 'webkit-tablet-768', use: { browserName: 'webkit', viewport: { width: 768, height: 1024 } } },
  ],
});
