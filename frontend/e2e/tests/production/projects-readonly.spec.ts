import { expect, test } from '@playwright/test';

const username = process.env.PROD_E2E_USERNAME ?? '';
const password = process.env.PROD_E2E_PASSWORD ?? '';
const projectId = process.env.PROD_E2E_PROJECT_ID ?? '';

test('production Projects and module routes are healthy without mutating project data', async ({
  page,
}) => {
  expect(username, 'PROD_E2E_USERNAME must be configured').not.toBe('');
  expect(password, 'PROD_E2E_PASSWORD must be configured').not.toBe('');
  expect(projectId, 'PROD_E2E_PROJECT_ID must be configured').not.toBe('');

  const forbiddenRequests: string[] = [];
  page.on('request', (request) => {
    const method = request.method();
    const path = new URL(request.url()).pathname;
    const isLogin = method === 'POST' && path === '/api/auth/login';
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !isLogin) {
      forbiddenRequests.push(`${method} ${path}`);
    }
  });

  await page.goto('/login');
  await page.locator('#login-username').fill(username);
  await page.locator('#login-password').fill(password);
  await page.getByRole('button', { name: /Enter/ }).click();
  await expect(page).toHaveURL(/\/projects$/);

  await page.getByRole('combobox', { name: 'Switch active project' }).selectOption(projectId);
  await expect(page.locator('[data-testid="project-modules"]')).toBeVisible();
  await expect(page.locator('[data-testid="project-modules"] a[data-module]')).toHaveCount(3);

  const width = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(width.document).toBeLessThanOrEqual(width.viewport);

  await page.goto('/chat');
  await expect(page).toHaveURL(/\/chat$/);
  await page.goto('/chronology');
  await expect(page).toHaveURL(/\/chronology$/);
  await page.goto('/forensic/intake');
  await expect(page).toHaveURL(/\/forensic\/intake$/);

  expect(forbiddenRequests, 'Production smoke must remain read-only after login').toEqual([]);
});
