import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

/**
 * Walks the production library: expands every Knowledge Base folder in the
 * sidebar and clicks each file. The right-side viewer must open and must NOT
 * show "Document not found" / "preview not available". Caps at 12 files per
 * folder so the suite stays within Playwright's per-test timeout.
 */
test.describe('Library tour — every file opens', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  for (const folder of [
    { selector: S.folderDocuments, label: 'Documents' },
    { selector: S.folderCorrespondence, label: 'Communications' },
    { selector: S.folderSpreadsheet, label: 'Spreadsheets' },
  ]) {
    test(`${folder.label}: every file opens cleanly in the viewer`, async ({
      page,
      viewerPage,
    }) => {
      const header = page.locator(folder.selector);
      await expect(header).toBeVisible({ timeout: 5_000 });

      // Expand the folder if it isn't already.
      const expanded = await header.getAttribute('aria-expanded');
      if (expanded !== 'true') {
        await header.click();
      }

      const items = header.locator('xpath=following-sibling::div[1]').locator('button');
      const count = await items.count();
      test.skip(count === 0, `No files indexed under ${folder.label}`);

      const maxCheck = Math.min(count, 12);
      const failures: string[] = [];
      for (let i = 0; i < maxCheck; i++) {
        const fileBtn = items.nth(i);
        const fileName = (await fileBtn.innerText().catch(() => '')).trim() || `file ${i}`;
        await fileBtn.click();
        try {
          await viewerPage.waitForOpen(8_000);
        } catch {
          failures.push(`${fileName}: viewer never opened`);
          continue;
        }
        const body = await page.locator(S.mainContent).innerText();
        for (const marker of ['Document not found', 'preview not available', 'Cannot parse']) {
          if (body.includes(marker)) {
            failures.push(`${fileName}: viewer surfaced "${marker}"`);
            break;
          }
        }
        await viewerPage.close().catch(() => {});
      }
      expect(failures, failures.join('\n')).toEqual([]);
    });
  }
});
