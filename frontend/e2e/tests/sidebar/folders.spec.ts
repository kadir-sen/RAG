import { test, expect } from '../../fixtures/base.fixture';
import { S } from '../../helpers/selectors';

const FOLDERS = ['Documents', 'Correspondence', 'Spreadsheet'] as const;

test.describe('Sidebar library folders', () => {
  test.beforeEach(async ({ page, sidebarPage }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sidebarPage.createNewChat();
  });

  test('"Chat history" section header is rendered above the recent chat list', async ({ page }) => {
    await expect(page.locator(S.sidebarChatsHeading)).toBeVisible();
  });

  test('top primary action buttons render in the expected order', async ({ page }) => {
    // The five rail entries (in order):
    //   New Chat → Search → Documents → Correspondence → Spreadsheet
    const labels = ['New Chat', 'Search', 'Documents', 'Correspondence', 'Spreadsheet'];
    const tops: number[] = [];
    for (const label of labels) {
      const btn = page.locator(`aside button:has-text("${label}")`).first();
      await expect(btn).toBeVisible();
      const box = await btn.boundingBox();
      expect(box).not.toBeNull();
      if (box) tops.push(box.y);
    }
    // Strictly increasing vertical order — no ties allowed.
    for (let i = 1; i < tops.length; i++) {
      expect(tops[i], `${labels[i]} should sit below ${labels[i - 1]}`).toBeGreaterThan(tops[i - 1]);
    }
  });

  test('Search toggles an inline search input', async ({ page }) => {
    await expect(page.locator('input[aria-label="Search chats"]')).toHaveCount(0);
    await page.locator(S.sidebarSearchChats).click();
    await expect(page.locator('input[aria-label="Search chats"]')).toBeVisible();
    await page.locator(S.sidebarSearchChats).click();
    await expect(page.locator('input[aria-label="Search chats"]')).toHaveCount(0);
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
    // After expansion an indented file panel sits in the sidebar with the
    // border-l guide rail. We assert a file row (a button rendered via
    // FileTypeBadge) is visible somewhere inside the sidebar.
    const fileRow = page.locator('aside .border-l button').first();
    await expect(fileRow).toBeVisible();
  });
});
