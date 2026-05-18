import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * Regression coverage for the "click an old chat → WelcomeScreen opens" bug.
 *
 * Root cause was twofold:
 *   1. chatStore.setConversation set `activeMode = null` when the loaded
 *      messages array was empty, falling through to WelcomeScreen.
 *   2. handleSelect silently swallowed fetch errors and called
 *      setConversation(id) with no messages, producing the same fall-through.
 *
 * The fixes make `activeMode` follow the conversation id, harden the
 * WelcomeScreen guard with `activeConversationId === null`, and add a
 * race-condition token so a stale earlier fetch can't stomp a newer click.
 */
test.describe('Sidebar — conversation reload', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('clicking a previous chat row re-opens that chat, not WelcomeScreen', async ({ page, sidebarPage }) => {
    // Seed conversation A with a real exchange so its messages list is non-empty.
    await page.locator(S.chatInput).fill('Conversation A — hello');
    await page.locator(S.chatInput).press('Enter');
    await expect(page.locator(S.assistantMessage).first()).toBeVisible({ timeout: 90_000 });

    // Capture the conversation id of A from the sidebar row before we leave it.
    const rowA = page.locator(S.convRow).first();
    const idA = await rowA.getAttribute('data-conv-id');
    expect(idA).toBeTruthy();

    // Start a fresh conversation B (just to leave A behind).
    await sidebarPage.createNewChat();
    await page.locator(S.chatInput).fill('Conversation B — different topic');
    await page.locator(S.chatInput).press('Enter');
    await expect(page.locator(S.assistantMessage).first()).toBeVisible({ timeout: 90_000 });

    // Go back to A.
    await page.locator(S.convRowById(idA!)).click();

    // WelcomeScreen must NOT appear; A's user message must be back on screen.
    await expect(page.getByText('Choose a mode', { exact: false })).toHaveCount(0);
    await expect(page.getByText('Conversation A — hello')).toBeVisible({ timeout: 5_000 });
  });

  test('rapidly switching between two chats lands on the last clicked one', async ({ page, sidebarPage }) => {
    // Seed two chats with distinct user content.
    await page.locator(S.chatInput).fill('First chat marker — alpha');
    await page.locator(S.chatInput).press('Enter');
    await expect(page.locator(S.assistantMessage).first()).toBeVisible({ timeout: 90_000 });
    const idAlpha = await page.locator(S.convRow).first().getAttribute('data-conv-id');

    await sidebarPage.createNewChat();
    await page.locator(S.chatInput).fill('Second chat marker — beta');
    await page.locator(S.chatInput).press('Enter');
    await expect(page.locator(S.assistantMessage).first()).toBeVisible({ timeout: 90_000 });
    const idBeta = await page.locator(S.convRow).first().getAttribute('data-conv-id');

    expect(idAlpha).toBeTruthy();
    expect(idBeta).toBeTruthy();
    expect(idAlpha).not.toBe(idBeta);

    // Click alpha and then beta in rapid succession — beta's fetch may resolve
    // before alpha's. The race-guard token ensures the LAST click wins.
    await page.locator(S.convRowById(idAlpha!)).click();
    await page.locator(S.convRowById(idBeta!)).click();

    await expect(page.getByText('Second chat marker — beta')).toBeVisible({ timeout: 8_000 });
    // alpha marker should NOT be on the page.
    await expect(page.getByText('First chat marker — alpha')).toHaveCount(0);
  });

  test('conversation with an empty messages array does not fall back to WelcomeScreen', async ({ page }) => {
    // Intercept the fetch for any conversation and force-empty its messages.
    await page.route('**/api/conversations/conv_*', async (route) => {
      const original = await route.fetch();
      const body = await original.json();
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ...body, messages: [] }),
      });
    });

    // Reload the page so the active conversation re-fetches under the mock.
    await page.reload();
    await page.waitForLoadState('networkidle');

    // WelcomeScreen must not appear. Either ChatStream renders empty or the
    // composer is at least visible — both are acceptable, but WelcomeScreen is
    // the explicit failure mode we are guarding against.
    await expect(page.locator(S.chatInput)).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText('Choose a mode', { exact: false })).toHaveCount(0);
  });
});
