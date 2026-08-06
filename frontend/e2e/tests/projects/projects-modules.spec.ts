import { expect, test } from '@playwright/test';
import {
  installProjectsApi,
  makeFiles,
  makeProject,
  makeState,
  seedProjectSession,
} from '../../fixtures/projects-api';

test.describe('Projects and module controls', () => {
  test('creates the first project and selects it without a real backend write', async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop');
    const state = makeState([]);
    await seedProjectSession(page, null);
    await installProjectsApi(page, state);
    await page.goto('/projects');

    await page.locator('#new-project-name').fill('Demo Construction Project');
    await page.getByRole('button', { name: 'Create project' }).click();

    await expect(
      page.getByRole('heading', { name: 'Demo Construction Project', exact: true }),
    ).toBeVisible();
    expect(state.projects).toHaveLength(1);
    const createRequest = state.requests.find(
      (item) => item.method === 'POST' && item.path === '/projects',
    );
    expect(createRequest?.body).toEqual({
      name: 'Demo Construction Project',
      embedding_profile: 'local-bge-v1',
    });
  });

  test('switches the active project and sends the new project boundary header', async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop');
    const first = makeProject('project-a', 'Alpha Project');
    const second = makeProject('project-b', 'Beta Project');
    const state = makeState([first, second]);
    await seedProjectSession(page, first.project_id);
    await installProjectsApi(page, state);
    await page.goto('/projects');

    const beta = page.locator('button[aria-pressed]').filter({ hasText: 'Beta Project' });
    await beta.focus();
    await page.keyboard.press('Space');
    await expect(beta).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name: 'Beta Project', exact: true })).toBeVisible();
    await expect
      .poll(() =>
        state.requests.some(
          (item) =>
            item.method === 'GET' && item.path === '/files' && item.projectId === second.project_id,
        ),
      )
      .toBe(true);
  });

  test('shows ready modules and opens the COAir routes plus the upstream toolkit', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop');
    const project = makeProject('project-ready', 'Ready Project');
    const state = makeState([project]);
    await seedProjectSession(page, project.project_id);
    await installProjectsApi(page, state);
    await page.goto('/projects');

    const chatbot = page.getByRole('link', { name: /Chatbot/ });
    const chronology = page.getByRole('link', { name: /Chronology/ });
    const forensic = page.getByRole('link', { name: /Forensic Reports/ });
    await expect(chatbot).toHaveAttribute('href', '/chat');
    await expect(chronology).toHaveAttribute('href', '/chronology');
    await expect(forensic).toHaveAttribute('href', '/toolkit/');

    await chatbot.click();
    await expect(page).toHaveURL(/\/chat$/);
    await page.goto('/projects');
    await chronology.click();
    await expect(page).toHaveURL(/\/chronology$/);
    await page.goto('/projects');
    // The exact upstream Streamlit application is mounted at /toolkit/.
    // It is deliberately not another native React route.
    await expect(forensic).toHaveAttribute('data-module', 'Forensic Reports');
  });

  test('disables document modules during ingestion but keeps the independent toolkit available', async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop');
    const project = makeProject('project-processing', 'Processing Project', {
      ready: false,
      processing: true,
    });
    const state = makeState([project]);
    state.jobs = [
      {
        file_id: 'job-1',
        filename: 'new-record.pdf',
        status: 'embedding',
        progress: 0.6,
        error: null,
        details: {},
      },
    ];
    await seedProjectSession(page, project.project_id);
    await installProjectsApi(page, state);
    await page.goto('/projects');

    await expect(
      page.locator('[data-testid="project-modules"] [aria-disabled="true"]'),
    ).toHaveCount(2);
    await expect(page.getByRole('link', { name: /Forensic Reports/ })).toHaveAttribute(
      'href',
      '/toolkit/',
    );
    await expect(page.locator('[data-testid="project-modules"]')).toContainText('1 remaining');
    await expect(page.locator('[data-testid="project-modules"]')).toContainText('ETA 2m');
  });

  test('keeps owner controls out of a viewer project', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop');
    const project = makeProject('project-viewer', 'Viewer Project', { role: 'viewer' });
    const state = makeState([project]);
    await seedProjectSession(page, project.project_id);
    await installProjectsApi(page, state);
    await page.goto('/projects');

    await expect(
      page.getByText('Viewer access · uploads and deletion are disabled.'),
    ).toBeVisible();
    await expect(page.locator('#project-name')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Delete / })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Archive project' })).toHaveCount(0);
  });

  test('filters and paginates project files', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop');
    const project = makeProject('project-files', 'Document Project');
    const state = makeState([project]);
    state.files = makeFiles(55);
    await seedProjectSession(page, project.project_id);
    await installProjectsApi(page, state);
    await page.goto('/projects');

    await expect(page.getByText('Page 1 / 2')).toBeVisible();
    await page.getByRole('button', { name: 'Next →' }).click();
    await expect(page.getByText('Page 2 / 2')).toBeVisible();
    await page.locator('#project-file-search').fill('record-055');
    await expect(page.getByText('record-055.xlsx')).toBeVisible();
    await expect(page.getByText('1 of 55 files')).toBeVisible();
  });

  test('surfaces a safe project creation error', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop');
    const state = makeState([]);
    state.failCreate = true;
    await seedProjectSession(page, null);
    await installProjectsApi(page, state);
    await page.goto('/projects');
    await page.locator('#new-project-name').fill('Rejected Project');
    await page.getByRole('button', { name: 'Create project' }).click();
    await expect(page.getByRole('alert')).toHaveText('The project could not be created.');
  });

  test('shows the shared 30 GB allowance beside the upload control', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop');
    const project = makeProject('project-storage', 'Storage Project');
    const state = makeState([project]);
    await seedProjectSession(page, project.project_id);
    await installProjectsApi(page, state);
    await page.goto('/projects');

    await expect(page.getByText('30 GB is shared across all projects.')).toBeVisible();
    await expect(page.getByText(/1\.50 GB used · 28\.50 GB remaining · 30\.00 GB limit/)).toBeVisible();
    await expect(page.getByText('OCR, metadata and indexing run automatically after upload.')).toBeVisible();
  });
});

test.describe('Projects responsive acceptance', () => {
  test('keeps navigation, module controls and touch targets usable', async ({ page }, testInfo) => {
    const project = makeProject('project-mobile', 'Mobile Construction Project');
    const state = makeState([project]);
    state.files = makeFiles(3);
    state.runs = [
      {
        run_id: 'run-1',
        username: 'e2e_user',
        module: 'chronology',
        query: 'Utility diversion chronology',
        route: 'REPORT',
        status: 'ready',
        created_at: '2026-08-05T00:00:00Z',
        latency_ms: 1200,
        total_steps: 4,
        successful_steps: 4,
        failed_steps: 0,
        fallback_steps: 0,
        llm_call_count: 2,
        input_tokens: 1000,
        output_tokens: 200,
        reasoning_tokens: 50,
        cached_tokens: 0,
        cost_usd: 0.02,
        source_count: 3,
        footnote_count: 3,
        metrics_complete: true,
      },
    ];
    await seedProjectSession(page, project.project_id);
    await installProjectsApi(page, state);
    await page.goto('/projects');
    await expect(page.locator('[data-testid="project-modules"]')).toBeVisible();

    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();
    const geometry = await page.evaluate(() => ({
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
    }));
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth);

    const projectContext = await page.getByTestId('project-context').boundingBox();
    const topnavActions = await page.getByTestId('topnav-actions').boundingBox();
    expect(projectContext).not.toBeNull();
    expect(topnavActions).not.toBeNull();
    if ((viewport?.width ?? 0) < 768) {
      expect((projectContext?.y ?? 0) + (projectContext?.height ?? 0)).toBeLessThanOrEqual(
        (topnavActions?.y ?? 0) + 1,
      );
    } else {
      expect((projectContext?.x ?? 0) + (projectContext?.width ?? 0)).toBeLessThanOrEqual(
        (topnavActions?.x ?? 0) + 1,
      );
    }

    const moduleLinks = page.locator('[data-testid="project-modules"] a[data-module]');
    await expect(moduleLinks).toHaveCount(3);
    const boxes = await moduleLinks.evaluateAll((nodes) =>
      nodes.map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          top: rect.top + window.scrollY,
          bottom: rect.bottom + window.scrollY,
          height: rect.height,
        };
      }),
    );

    if ((viewport?.width ?? 0) < 768) {
      for (const box of boxes) expect(box.height).toBeLessThanOrEqual(160);
      expect(boxes[0].top).toBeLessThan(900);
      expect(boxes[2].bottom - boxes[0].top).toBeLessThanOrEqual(520);
      await expect(page.locator('#mobile-project-select')).toBeVisible();
      await page.getByText('Create new project').click();
      await expect(page.locator('#new-project-name-mobile')).toBeVisible();
      const inputFontSize = await page
        .locator('#project-file-search')
        .evaluate((element) => getComputedStyle(element).fontSize);
      expect(Number.parseFloat(inputFontSize)).toBeGreaterThanOrEqual(16);
      const createInputFontSize = await page
        .locator('#new-project-name-mobile')
        .evaluate((element) => getComputedStyle(element).fontSize);
      expect(Number.parseFloat(createInputFontSize)).toBeGreaterThanOrEqual(16);
      await expect(page.getByTestId('query-history-cards')).toBeVisible();
      await expect(page.getByTestId('query-history-table')).toBeHidden();
    } else if ((viewport?.width ?? 0) === 768) {
      expect(Math.abs(boxes[0].top - boxes[1].top)).toBeLessThan(2);
      expect(Math.abs(boxes[1].top - boxes[2].top)).toBeLessThan(2);
      for (const box of boxes) expect(box.height).toBeLessThanOrEqual(330);
      await expect(page.getByTestId('query-history-table')).toBeVisible();
    }

    const metricColumns = await page
      .getByTestId('project-metrics')
      .evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length);
    expect(metricColumns).toBe(
      (viewport?.width ?? 0) < 768 ? 2 : (viewport?.width ?? 0) < 1024 ? 4 : 8,
    );

    for (const locator of [
      page.getByRole('button', { name: 'Back to main menu' }),
      page.getByRole('button', { name: /Account menu/ }),
      page.getByRole('button', { name: 'Switch between drawing sheet and blueprint' }),
      page.locator('#project-file-search'),
      page.getByRole('button', { name: /Delete Very long construction/ }),
    ]) {
      const box = await locator.boundingBox();
      expect(box).not.toBeNull();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    }

    if (testInfo.project.name.startsWith('phone')) {
      await page.getByRole('button', { name: /Account menu/ }).click();
      await expect(page.getByRole('menuitem', { name: 'Settings' })).toBeVisible();
    }
  });
});
