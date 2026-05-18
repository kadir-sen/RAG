import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * Document Analysis regression for the duplicate-row + click bug from the
 * user's screenshots:
 *
 *   1. The timeline must never list the same filename twice — Pinecone
 *      holds two ingestions of every source file (Windows path + container
 *      path), so the response_builder now dedupes by file_name and remaps
 *      every doc_id to the registry's canonical id.
 *   2. Each row must be clickable and open its document in the right-side
 *      viewer without "Document not found" / "preview not available" /
 *      "Cannot parse" banners.
 *
 * The test exercises Document Analysis mode end-to-end and additionally
 * verifies the backend contract directly (so a flaky intro wrap won't mask
 * a regression).
 */

const TIMELINE_QUERY = 'What are the contract terms about delay penalties?';

test.describe('Document Analysis — timeline has no duplicates and every row opens', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('backend dedupe contract: no duplicate doc_name and every doc_id resolves', async ({
    request,
    baseURL,
  }) => {
    const apiBase = baseURL?.replace(/\/$/, '') ?? '';
    const conv = await (
      await request.post(`${apiBase}/api/conversations`, { data: {} })
    ).json();
    const conversation_id = conv.conversation_id;

    const chatResp = await request.post(`${apiBase}/api/chat`, {
      data: {
        message: TIMELINE_QUERY,
        conversation_id,
        mode: 'document_analysis',
      },
      timeout: 120_000,
    });
    expect(chatResp.ok()).toBeTruthy();
    const body = await chatResp.json();
    const related: Array<{ doc_name: string; doc_id: string }> =
      body.related_docs ?? [];
    expect(
      related.length,
      `Backend returned no related_docs — payload: ${JSON.stringify(body).slice(0, 300)}`,
    ).toBeGreaterThan(0);

    // No duplicate doc_name in the API payload.
    const names = related.map((r) => r.doc_name);
    const dupes = names.filter((n, i) => names.indexOf(n) !== i);
    expect(
      dupes,
      `Backend related_docs have duplicate doc_names: ${[...new Set(dupes)].join(', ')}`,
    ).toEqual([]);

    // Every doc_id must resolve through /api/docs/{id}/content without an
    // error banner. Spot-check the first six.
    for (const rd of related.slice(0, 6)) {
      const docResp = await request.get(
        `${apiBase}/api/docs/${encodeURIComponent(rd.doc_id)}/content?anchor=page_1`,
        { timeout: 15_000 },
      );
      expect(docResp.ok(), `viewer fetch failed for ${rd.doc_name}`).toBeTruthy();
      const docBody = await docResp.json();
      expect(
        docBody.error,
        `viewer surfaced an error for ${rd.doc_name}: ${docBody.error}`,
      ).toBeFalsy();
    }
  });

  test('document analysis UI: timeline rows are unique and every row opens', async ({
    page,
    viewerPage,
  }) => {
    test.setTimeout(240_000);

    // Enter Document Analysis mode via the sidebar toggle.
    await page.locator(S.chipDocumentAnalysis).click();
    await expect(page.locator(S.chipDocumentAnalysis)).toHaveAttribute(
      'aria-pressed', 'true',
    );

    // The intro screen wraps anything typed into "Show me all documents
    // related to <X>, chronologically." which on some builds routes to SQL
    // instead of FILE_LIST. The standard ChatInput is always rendered at
    // the bottom of ChatPage (even while the intro is on screen), so we
    // send the query directly through it to keep the routing clean.
    const realResp = page.waitForResponse(
      (r) => r.url().endsWith('/api/chat') && r.request().method() === 'POST',
      { timeout: 120_000 },
    );
    await page.locator(S.chatInput).fill(TIMELINE_QUERY);
    await page.locator(S.chatInput).press('Enter');

    const apiResp = await realResp;
    const body = await apiResp.json();
    console.log(
      `[timeline-spec] real query intent=${body.ui_intent} related=${(body.related_docs ?? []).length}`,
    );
    const related = body.related_docs ?? [];
    expect(
      related.length,
      `No related_docs returned — payload: ${JSON.stringify(body).slice(0, 300)}`,
    ).toBeGreaterThan(0);
    const apiNames = related.map((r: { doc_name: string }) => r.doc_name);
    const apiDupes = apiNames.filter((n: string, i: number) => apiNames.indexOf(n) !== i);
    expect(apiDupes).toEqual([]);

    // Find the rendered timeline rows. Each row's clickable surface is a
    // button.text-left inside an <li> element.
    const timelineRows = page
      .locator('.prose')
      .last()
      .locator('xpath=..')
      .locator('li')
      .filter({ has: page.locator('button.text-left') });

    await expect(timelineRows.first()).toBeVisible({ timeout: 15_000 });
    const rowCount = await timelineRows.count();
    expect(rowCount).toBeGreaterThan(0);

    // Collect visible filenames and assert uniqueness.
    const titles: string[] = [];
    for (let i = 0; i < rowCount; i++) {
      const titleEl = timelineRows.nth(i).locator('span.font-semibold').first();
      const text = (await titleEl.innerText().catch(() => '')).trim();
      if (text) titles.push(text);
    }
    const dupes = titles.filter((t, idx) => titles.indexOf(t) !== idx);
    expect(
      dupes,
      `UI timeline has duplicate rows: ${[...new Set(dupes)].join(', ')}`,
    ).toEqual([]);

    // Each unique row must open without a viewer error.
    const maxCheck = Math.min(rowCount, 6);
    for (let i = 0; i < maxCheck; i++) {
      const row = timelineRows.nth(i);
      const button = row.locator('button.text-left').first();
      const label = (await button.innerText().catch(() => '')).trim() || `row ${i}`;

      await button.click();
      try {
        await viewerPage.waitForOpen(8_000);
      } catch {
        throw new Error(`Row ${i} ("${label}") did not open the viewer`);
      }

      const viewerBody = await page.locator(S.mainContent).innerText();
      for (const err of ['Document not found', 'preview not available', 'Cannot parse']) {
        expect(
          viewerBody.includes(err),
          `Row ${i} ("${label}") surfaced viewer error: ${err}`,
        ).toBe(false);
      }
      await viewerPage.close().catch(() => {});
    }
  });
});
