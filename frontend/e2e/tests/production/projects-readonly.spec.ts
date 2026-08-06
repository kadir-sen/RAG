import { expect, test } from '@playwright/test';

const username = process.env.PROD_E2E_USERNAME ?? '';
const password = process.env.PROD_E2E_PASSWORD ?? '';
const projectId = process.env.PROD_E2E_PROJECT_ID ?? '';

async function expectNoPageOverflow(page: import('@playwright/test').Page) {
  await expect.poll(() => page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }))).toMatchObject({ viewport: page.viewportSize()?.width });
  const geometry = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(geometry.document).toBeLessThanOrEqual(geometry.viewport + 1);
}

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

  await expectNoPageOverflow(page);

  await page.goto('/chat');
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.locator('#chat-input')).toBeVisible();
  await expectNoPageOverflow(page);

  const sidebar = page.getByRole('complementary', { name: 'Sidebar' });
  if ((await sidebar.getAttribute('aria-hidden')) === 'true') {
    await page.getByRole('button', { name: 'Open sidebar' }).click();
  }
  await page.getByRole('button', { name: /Documents/ }).click();
  const pdf = sidebar.getByRole('button').filter({ hasText: /\.pdf$/i }).first();
  await expect(pdf, 'The dedicated smoke project must contain a harmless PDF fixture.').toBeVisible();
  await pdf.click();
  await expect(page.getByTestId('document-viewer')).toBeVisible();
  await expect(page.getByTestId('document-viewer')).not.toContainText(/not found|preview not available/i);
  await page.getByRole('button', { name: 'Close viewer' }).click();

  await page.getByRole('button', { name: /Spreadsheets/ }).click();
  const spreadsheet = sidebar.getByRole('button').filter({ hasText: /\.(xlsx?|csv)$/i }).first();
  await expect(spreadsheet, 'The dedicated smoke project must contain a harmless spreadsheet fixture.').toBeVisible();
  await spreadsheet.click();
  await expect(page.getByTestId('document-table-scroll')).toBeVisible();
  await page.getByRole('button', { name: 'Close viewer' }).click();

  await page.goto('/chronology');
  await expect(page).toHaveURL(/\/chronology$/);
  await expect(page.getByRole('heading', { name: 'Build a new chronology' })).toBeVisible();
  await expectNoPageOverflow(page);
  await page.goto('/forensic/intake');
  await expect(page).toHaveURL(/\/forensic\/intake$/);
  await expect(page.getByRole('combobox', { name: 'Analysis module' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Analysis module' }).locator('option')).toHaveCount(20);
  await expectNoPageOverflow(page);

  expect(forbiddenRequests, 'Production smoke must remain read-only after login').toEqual([]);
});
