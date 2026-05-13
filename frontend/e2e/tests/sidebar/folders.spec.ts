import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

const FOLDERS = ['Documents', 'Correspondence', 'Spreadsheet'] as const;

test.describe('Sidebar library folders', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('AI Assistant section header is rendered', async ({ page }) => {
    await expect(page.locator(S.sidebarAiAssistantHeading)).toBeVisible();
  });

  test('all three folders render with a numeric count', async ({ sidebarPage }) => {
    for (const name of FOLDERS) {
      await expect(sidebarPage.folderHeader(name)).toBeVisible();
      const count = await sidebarPage.folderCount(name);
      expect(count, `${name} folder count`).toBeGreaterThanOrEqual(0);
    }
  });

  test('folders start collapsed and toggle on click', async ({ sidebarPage }) => {
    for (const name of FOLDERS) {
      expect(await sidebarPage.folderIsExpanded(name)).toBe(false);
      await sidebarPage.openFolder(name);
      expect(await sidebarPage.folderIsExpanded(name)).toBe(true);
      await sidebarPage.closeFolder(name);
      expect(await sidebarPage.folderIsExpanded(name)).toBe(false);
    }
  });

  test('folder counts match /api/files (the sidebar source of truth)', async ({ page, sidebarPage }) => {
    // The sidebar reads from `/api/files` (not `/api/library`), so we compare
    // against the same endpoint. /api/library aggregates more than the file
    // list (e.g. data-table duplicates), and would not match.
    const resp = await page.request.get('/api/files');
    expect(resp.ok()).toBe(true);
    const docs: Array<{ file_type?: string; extension?: string }> = await resp.json();

    const isDoc = (d: { file_type?: string; extension?: string }) => {
      const t = (d.file_type || '').toLowerCase();
      return ['document', 'pdf', 'doc', 'docx', 'text', 'txt'].includes(t);
    };
    const isData = (d: { file_type?: string; extension?: string }) => {
      const t = (d.file_type || '').toLowerCase();
      return ['data', 'excel', 'xls', 'xlsx', 'csv'].includes(t);
    };
    const isEmail = (d: { file_type?: string; extension?: string }) => {
      const t = (d.file_type || '').toLowerCase();
      return ['email', 'eml', 'msg'].includes(t);
    };

    const docCount = docs.filter(isDoc).length;
    const dataCount = docs.filter(isData).length;
    const emailCount = docs.filter(isEmail).length;

    expect(await sidebarPage.folderCount('Documents')).toBe(docCount);
    expect(await sidebarPage.folderCount('Spreadsheet')).toBe(dataCount);
    expect(await sidebarPage.folderCount('Correspondence')).toBe(emailCount);
  });

  test('entering Correspondence mode auto-opens the Correspondence folder', async ({ page, sidebarPage, welcomePage }) => {
    expect(await sidebarPage.folderIsExpanded('Correspondence')).toBe(false);
    await welcomePage.selectCorrespondenceMode();
    await expect(page.getByText('CORRESPONDENCE MODE')).toBeVisible({ timeout: 5_000 });
    // The effect inside ConversationSidebar opens the folder.
    await expect(sidebarPage.folderHeader('Correspondence')).toHaveAttribute('aria-expanded', 'true', { timeout: 3_000 });
  });

  test('expanded Documents folder lists at least one file when registry is non-empty', async ({ page, sidebarPage }) => {
    if ((await sidebarPage.folderCount('Documents')) === 0) {
      test.skip(true, 'Documents folder is empty in this environment');
    }
    await sidebarPage.openFolder('Documents');
    // The expanded panel sits immediately after the header in the DOM and uses ml-3 border-l styling.
    const panel = page.locator('div.ml-3.border-l').first();
    await expect(panel).toBeVisible();
  });
});
