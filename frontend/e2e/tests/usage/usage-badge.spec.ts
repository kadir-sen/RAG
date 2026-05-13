import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

const STUB_BODY = {
  used_usd: 12.34,
  limit_usd: 100,
  remaining_usd: 87.66,
  remaining_pct: 0.8766,
  over_budget: false,
  prompt_tokens: 1234,
  completion_tokens: 567,
  total_tokens: 1801,
  total_calls: 7,
};

test.describe('Usage endpoint + badge', () => {
  test('GET /api/usage returns the expected schema', async ({ page }) => {
    const resp = await page.request.get('/api/usage');
    expect(resp.ok(), `status ${resp.status()}`).toBe(true);
    const body = await resp.json();
    for (const key of [
      'used_usd', 'limit_usd', 'remaining_usd', 'remaining_pct',
      'over_budget', 'prompt_tokens', 'completion_tokens',
      'total_tokens', 'total_calls',
    ]) {
      expect(body, `missing field "${key}"`).toHaveProperty(key);
    }
    expect(typeof body.used_usd).toBe('number');
    expect(typeof body.limit_usd).toBe('number');
    expect(typeof body.over_budget).toBe('boolean');
    expect(Number.isInteger(body.total_calls)).toBe(true);
  });

  test('UsageBadge renders the $used / $limit chip (stubbed)', async ({ page }) => {
    await page.route('**/api/usage', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(STUB_BODY),
      }),
    );

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const badge = page.locator(S.usageBadge);
    await expect(badge).toBeVisible();
    await expect(badge).toContainText('$12');
    await expect(badge).toContainText('$100');
  });

  test('amber colour ramp kicks in around 70-90%', async ({ page }) => {
    await page.route('**/api/usage', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...STUB_BODY, used_usd: 75, remaining_usd: 25, remaining_pct: 0.25 }),
      }),
    );

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const badge = page.locator(S.usageBadge);
    await expect(badge).toBeVisible();
    // The progress fill carries the colour class.
    await expect(badge.locator('div').last()).toHaveClass(/amber/);
  });

  test('red colour ramp + danger text when budget is exceeded', async ({ page }) => {
    await page.route('**/api/usage', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...STUB_BODY, used_usd: 110, remaining_usd: 0, remaining_pct: 0, over_budget: true }),
      }),
    );

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const badge = page.locator(S.usageBadge);
    await expect(badge).toBeVisible();
    // Span carrying the dollar amounts switches to text-[var(--danger)] class.
    const textSpan = badge.locator('span').first();
    await expect(textSpan).toHaveClass(/danger/);
  });
});
