/**
 * Demo-readiness capability suite.
 *
 * Exercises the AI decision surface end-to-end through the real UI against a
 * live server: authentication, then the four capabilities the demo leans on —
 * direct RAG (document answer + related-doc bubbles), SQL/data analysis,
 * correspondence reasoning (parties + late replies), and reply drafting.
 *
 * Assertions are split in two tiers so the run produces a capability *matrix*
 * rather than aborting on the first soft gap:
 *   - HARD expect: a non-error assistant answer must arrive (the floor).
 *   - expect.soft: capability markers (table, "Related Documents", citations,
 *     clickable bubbles). Soft failures are reported but let the suite finish,
 *     so one run tells you exactly which capabilities are demo-ready.
 *
 * Credentials/target come from env (never hard-code secrets or a production
 * host in the suite): E2E_USER, E2E_PASS and BASE_URL.
 *
 * Run:
 *   BASE_URL=http://127.0.0.1:4173 E2E_USER=test-user E2E_PASS=... \
 *     npm run e2e -- tests/chat/capability-suite.spec.ts
 */
import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { S } from '../../helpers/selectors';

const USER = process.env.E2E_USER ?? '';
const PASS = process.env.E2E_PASS ?? '';
const SHOTS = '/tmp/coair-e2e-shots';

// Phrases the backend emits when routing/execution degrades — used to fail a
// capability even when the request technically returned 200 with prose.
const FAILURE_MARKERS = [
  'having trouble processing',
  'try rephrasing your question',
  'cannot reach',
  'something went wrong',
];

async function login(page: Page) {
  // Root is always served; ProtectedRoute redirects to /login client-side when
  // unauthenticated. Handle both "already authed" and "needs login" landings.
  await page.goto('/');
  const usernameField = page.locator('#login-username');
  const chatInput = page.locator(S.chatInput);

  await Promise.race([
    usernameField.waitFor({ state: 'visible', timeout: 30_000 }).catch(() => {}),
    chatInput.waitFor({ state: 'visible', timeout: 30_000 }).catch(() => {}),
  ]);

  if (await usernameField.isVisible().catch(() => false)) {
    await usernameField.fill(USER);
    await page.locator('#login-password').fill(PASS);
    await page.locator('button[type="submit"]').click();
  }
  // Success signal: the composer is reachable.
  await expect(chatInput).toBeVisible({ timeout: 30_000 });
}

/** Type a question into the composer, wait for the answer to settle, return the
 *  latest assistant message card (Locator) + its text. */
async function ask(page: Page, text: string): Promise<{ card: ReturnType<Page['locator']>; body: string }> {
  const input = page.locator(S.chatInput);
  await expect(input).toBeVisible({ timeout: 15_000 });
  await input.fill(text);
  await input.press('Enter');

  const typing = page.locator(S.typingIndicator);
  // Indicator may flash quickly; tolerate it never being caught visible.
  await typing.waitFor({ state: 'visible', timeout: 15_000 }).catch(() => {});
  await expect(typing).toBeHidden({ timeout: 150_000 });

  const cards = page.locator('.assistant-card');
  await expect(cards.first()).toBeVisible({ timeout: 15_000 });
  const card = cards.last();
  const body = (await card.innerText()).trim();
  return { card, body };
}

function assertRealAnswer(body: string, label: string) {
  expect(body.length, `${label}: answer should be non-trivial`).toBeGreaterThan(25);
  const lower = body.toLowerCase();
  for (const marker of FAILURE_MARKERS) {
    expect(lower.includes(marker), `${label}: answer must not contain failure marker "${marker}"`).toBeFalsy();
  }
}

test.describe('COAir — demo-readiness capability suite', () => {
  test.skip(!USER || !PASS, 'E2E_USER and E2E_PASS are required for the live capability suite.');

  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('AUTH — login reaches the chat composer', async ({ page }) => {
    await expect(page.locator(S.chatInput)).toBeVisible();
  });

  test('RAG — document answer with related-doc bubbles', async ({ page }) => {
    const { card, body } = await ask(
      page,
      'Summarize the server room correspondence and tell me what it is about.',
    );
    assertRealAnswer(body, 'RAG');

    // Capability markers (soft): clickable related-doc bubbles OR inline citations.
    const relatedHeader = card.getByText(/Related Documents/i);
    const hasRelated = await relatedHeader.isVisible().catch(() => false);
    const chipCount = await card.locator('button').count();
    expect.soft(hasRelated || chipCount > 0, 'RAG: should surface related docs or citations').toBeTruthy();

    // A related-doc bubble must be clickable and open the document viewer.
    // Target a bubble by its filename (citation chips above don't carry an
    // extension), and wait for the lazily-loaded RightDocViewer chunk to mount.
    if (hasRelated) {
      const bubble = card.getByRole('button', { name: /\.(pdf|msg|docx|xlsx)/i }).first();
      await bubble.click();
      await expect
        .soft(page.locator(S.viewerClose), 'RAG: bubble should open the document viewer')
        .toBeVisible({ timeout: 15_000 });
      await page.locator(S.viewerClose).click().catch(() => {});
    }
    await page.screenshot({ path: `${SHOTS}/01-rag.png`, fullPage: true });
  });

  test('SQL — data question returns a result table', async ({ page }) => {
    const { card, body } = await ask(
      page,
      'What is the total number of workers by trade across the manpower logs?',
    );
    assertRealAnswer(body, 'SQL');

    const tableCount = await card.locator('table').count();
    const hasSqlMarker = await card.getByText(/\bSQL\b|Source:/).first().isVisible().catch(() => false);
    expect.soft(tableCount > 0 || hasSqlMarker, 'SQL: should render a result table or SQL artifact').toBeTruthy();
    await page.screenshot({ path: `${SHOTS}/02-sql.png`, fullPage: true });
  });

  test('CORRESPONDENCE — identify the parties', async ({ page }) => {
    const { body } = await ask(
      page,
      'Who are the main parties exchanging emails about the server room and access cards?',
    );
    assertRealAnswer(body, 'PARTIES');
    await page.screenshot({ path: `${SHOTS}/03-parties.png`, fullPage: true });
  });

  test('CORRESPONDENCE — late / delayed replies', async ({ page }) => {
    const { body } = await ask(
      page,
      'Which letters or emails were about delays or late responses, and when were they sent?',
    );
    assertRealAnswer(body, 'DELAYS');
    await page.screenshot({ path: `${SHOTS}/04-delays.png`, fullPage: true });
  });

  test('DRAFT — generate a reply', async ({ page }) => {
    const { body } = await ask(
      page,
      'Draft a short, professional reply acknowledging the delay notification and proposing a recovery plan.',
    );
    assertRealAnswer(body, 'DRAFT');
    expect.soft(body.length, 'DRAFT: a drafted reply should be substantial').toBeGreaterThan(120);
    await page.screenshot({ path: `${SHOTS}/05-draft.png`, fullPage: true });
  });
});
