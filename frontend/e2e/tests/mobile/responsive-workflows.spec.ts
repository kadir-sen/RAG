import { expect, test, type Page } from '@playwright/test';
import { installProjectsApi, makeProject, makeState, seedProjectSession } from '../../fixtures/projects-api';

const project = makeProject('project-mobile-suite', 'Mobile Construction Workspace');
const modules = [
  ['intake', 'Data Intake', 'programme'], ['dcma', 'DCMA 14-Point Assessment', 'programme'],
  ['baseline-critical-path', 'Baseline Critical Path', 'programme'],
  ['revision-comparison', 'Revision Comparison', 'programme'],
  ['out-of-sequence', 'Out-of-Sequence Progress', 'programme'],
  ['float-erosion', 'Float Erosion', 'programme'], ['progress-s-curve', 'Progress S-Curve', 'programme'],
  ['resource-loading', 'Resource Loading', 'programme'], ['sequence-coding', 'Sequence Coding', 'programme'],
  ['hierarchy', 'Hierarchy Rebuild', 'programme'], ['milestone-shift', 'Milestone Shift', 'programme'],
  ['progress-transfer', 'Progress Transfer', 'programme'],
  ['as-built-critical-path', 'As-Built Critical Path', 'programme'],
  ['report-assembler', 'Report Assembler', 'programme'],
  ['as-planned-vs-as-built', 'As-Planned vs As-Built', 'retrospective'],
  ['windows-analysis', 'Windows Analysis', 'retrospective'],
  ['impacted-as-planned', 'Impacted As-Planned', 'retrospective'],
  ['collapsed-as-built', 'Collapsed As-Built', 'retrospective'],
  ['time-impact-analysis', 'Time Impact Analysis', 'prospective'],
] as const;

const workspace = {
  workspace_id: 'workspace-mobile', project_id: project.project_id, name: 'Mobile Analysis',
  programme_ids: ['programme-mobile'], settings: {}, source_revision: 'a'.repeat(64),
  upstream_sha: 'bb52fa0a5e41fc2040979b226911b192463701d5',
  created_at: '2026-08-06T00:00:00Z', updated_at: '2026-08-06T00:00:00Z',
  state_version: 1, pipeline_version: 'forensic-parity-v1', evidence_source_ids: [],
};

const chronologyJob = {
  job_id: 'job-mobile', project_id: project.project_id, module: 'chronology',
  title: 'Utility Diversion Chronology', status: 'ready', stage: 'ready', progress: 1,
  error: null, retryable: false, pipeline_version: 'chronology-v3', coverage_status: 'complete',
  created_at: '2026-08-06T00:00:00Z', sequence_number: 1,
  report_url: '/chronology/reports/job-mobile',
  result: {
    entries: [{ event_date: '2026-01-10', claims: [{ text: 'The Engineer issued Notice 88.', source_ids: ['SRC-PDF', 'SRC-XLS'] }] }],
    evidence: [
      { source_id: 'SRC-PDF', file_name: 'Engineer Notice 88.pdf', page: 2 },
      { source_id: 'SRC-XLS', file_name: 'Delay Register.xlsx', kind: 'excel', sheet: 'Register', row_from: 4, row_to: 7 },
    ],
  },
};

const forensicRun = {
  run_id: 'run-mobile', workspace_id: workspace.workspace_id, project_id: project.project_id,
  module_slug: 'dcma', status: 'ready', stage: 'complete', progress: 1,
  parameters: {}, error_code: null, attempt: 1, created_at: '2026-08-06T00:00:00Z',
  started_at: '2026-08-06T00:00:00Z', completed_at: '2026-08-06T00:01:00Z',
  updated_at: '2026-08-06T00:01:00Z', upstream_sha: workspace.upstream_sha,
  source_revision: workspace.source_revision, artifacts: [],
  result: {
    title: 'DCMA Assessment', module: 'dcma', metrics: [{ label: 'Activities', value: 120 }],
    warnings: ['One open-ended activity was identified.'], caveats: ['Review data date quality.'],
    artifacts: [], upstream_sha: workspace.upstream_sha, source_revision: workspace.source_revision,
    chart: {
      $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
      data: { values: [{ check: 'Logic', value: 4 }, { check: 'Constraints', value: 2 }] },
      mark: 'bar', encoding: { x: { field: 'check', type: 'nominal' }, y: { field: 'value', type: 'quantitative' } },
    },
    tables: [{
      name: 'result.dcma_checks', total_rows: 2, truncated: false,
      rows: [
        { activity_id: 'A-1000', activity_name: 'A very long construction activity name', status: 'warning', result: 'Open end' },
        { activity_id: 'A-1010', activity_name: 'Install utility diversion', status: 'pass', result: 'Complete' },
      ],
    }],
  },
};

async function installMobileApi(page: Page) {
  const state = makeState([project]);
  await seedProjectSession(page, project.project_id);
  await installProjectsApi(page, state);
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const fulfill = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/api/reports/job-mobile') return fulfill(chronologyJob);
    if (path === '/api/reports/job-mobile/sources/SRC-PDF') return fulfill({ source: chronologyJob.result.evidence[0], record: { doc_id: 'doc-pdf', file_name: 'Engineer Notice 88.pdf', status: 'ready' } });
    if (path === '/api/reports/job-mobile/sources/SRC-XLS') return fulfill({ source: chronologyJob.result.evidence[1], record: { doc_id: 'doc-xls', file_name: 'Delay Register.xlsx', status: 'ready' } });
    if (path === '/api/docs/doc-pdf/content') return fulfill({ type: 'pdf', file_name: 'Engineer Notice 88.pdf', page: 2, total_pages: 3, image_base64: '', text: 'The Engineer issued Notice 88.', columns: [], rows: [], total_rows: 0, error: null });
    if (path === '/api/docs/doc-xls/content') return fulfill({ type: 'table', file_name: 'Delay Register.xlsx', page: 1, total_pages: 1, image_base64: '', text: '', columns: ['Reference', 'Description', 'Owner', 'Status', 'Very wide evidence column'], rows: [{ Reference: 'EI-88', Description: 'Utility diversion instruction', Owner: 'Engineer', Status: 'Open', 'Very wide evidence column': 'Contemporary register evidence' }], total_rows: 1, error: null, sheet_name: 'Register', row_from: 4, row_to: 7 });
    if (path === '/api/forensic/status') return fulfill({ available: true, enabled: true, parity_available: true, parity_enabled: true, parity_validation: true, pipeline_version: 'forensic-parity-v1', parity_fingerprint: 'f'.repeat(64), coair_sha: 'coair123', upstream_sha: workspace.upstream_sha, streamlit: false, max_workspace_bytes: 75 * 1024 * 1024, modules: modules.map(([slug, title, group]) => ({ slug, title, group, minimum_files: 1, parity: { controls: [], actions: ['run'], views: ['table', 'chart'] } })) });
    if (path === '/api/forensic/programmes') return fulfill({ programmes: [{ file_id: 'programme-mobile', name: 'Baseline.xer', size_bytes: 1000, sha256: '1'.repeat(64), created_at: '2026-08-06T00:00:00Z' }] });
    if (path === '/api/forensic/workspaces') return fulfill({ workspaces: [workspace] });
    if (path === '/api/forensic/workspaces/workspace-mobile/state') return fulfill({ workspace_id: workspace.workspace_id, project_id: project.project_id, version: 1, state: { pipeline_version: 'forensic-parity-v1', baseline_programme_id: 'programme-mobile', current_programme_id: 'programme-mobile', contract_completion_milestone: '', missing_inputs: [], analysis_basis: {}, event_register: {}, apab: {}, umbrella: {}, sequence: {}, hierarchy: {}, explain: {}, iap: {}, cab: {}, narratives: {}, report: {} }, created_at: workspace.created_at, updated_at: workspace.updated_at });
    if (path === '/api/forensic/runs') return fulfill({ runs: [forensicRun] });
    if (path === '/api/forensic/runs/run-mobile') return fulfill(forensicRun);
    return route.fallback();
  });
  return state;
}

async function expectNoPageOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
}

test.beforeEach(async ({ page }) => {
  await installMobileApi(page);
});

test('shared shell and Projects controls remain usable at every breakpoint', async ({ page }, testInfo) => {
  await page.goto('/projects');
  await expect(page.getByTestId('project-modules')).toBeVisible();
  await expectNoPageOverflow(page);

  const viewport = page.viewportSize()!;
  const context = await page.getByTestId('project-context').boundingBox();
  const actions = await page.getByTestId('topnav-actions').boundingBox();
  expect(context).not.toBeNull();
  expect(actions).not.toBeNull();
  if (viewport.width < 768) expect(context!.y + context!.height).toBeLessThanOrEqual(actions!.y + 1);

  for (const control of [
    page.getByRole('button', { name: 'Back to main menu' }),
    page.getByRole('button', { name: /Account menu/ }),
    page.getByRole('button', { name: 'Switch between drawing sheet and blueprint' }),
  ]) {
    const box = await control.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }

  if (testInfo.project.name === 'chromium-phone-390' || testInfo.project.name === 'chromium-tablet-768') {
    await expect(page.getByTestId('project-modules')).toHaveScreenshot('projects-modules.png', {
      animations: 'disabled',
      maxDiffPixelRatio: 0.08,
    });
  }
});

test('Chronology sources open in the shared responsive PDF and spreadsheet viewer', async ({ page }) => {
  await page.goto('/chronology/reports/job-mobile');
  await page.getByRole('button', { name: 'SRC-PDF' }).first().click();
  const openSource = page.getByRole('button', { name: /Open project document/ });
  await openSource.click();
  const viewer = page.getByTestId('document-viewer');
  await expect(viewer).toBeVisible();
  await expect(viewer).toContainText('Engineer Notice 88.pdf');

  const viewport = page.viewportSize()!;
  const box = await viewer.boundingBox();
  if (viewport.width < 768) {
    expect(Math.abs((box?.width ?? 0) - viewport.width)).toBeLessThanOrEqual(1);
    expect(box?.x ?? -1).toBe(0);
    await expect(viewer).toHaveAttribute('aria-modal', 'true');
  } else if (viewport.width < 1024) {
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(viewport.width * 0.68);
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(viewport.width + 1);
  } else {
    expect(Math.abs((box?.width ?? 0) - 420)).toBeLessThanOrEqual(1);
  }

  await page.keyboard.press('Escape');
  await expect(viewer).toBeHidden();
  await expect(openSource).toBeFocused();
  await page.getByRole('button', { name: 'Close source preview' }).click();

  await page.getByRole('button', { name: 'SRC-XLS' }).first().click();
  await page.getByRole('button', { name: /Open project document/ }).click();
  await expect(page.getByTestId('document-table-scroll')).toBeVisible();
  await expectNoPageOverflow(page);
});

test('Forensic exposes every module and confines dense results to internal scrolling', async ({ page }) => {
  await page.goto('/forensic/dcma?workspace=workspace-mobile');
  const viewport = page.viewportSize()!;
  if (viewport.width < 1024) {
    const moduleSelect = page.getByRole('combobox', { name: 'Analysis module' });
    await expect(moduleSelect.locator('option')).toHaveCount(20);
  } else {
    await expect(page.getByRole('navigation', { name: 'Forensic analysis modules' }).getByRole('link')).toHaveCount(20);
  }
  await expect(page.getByText('Analysis complete')).toBeVisible();
  const tableScroll = page.getByTestId('forensic-table-scroll');
  await expect(tableScroll).toBeVisible();
  await expectNoPageOverflow(page);

  const visual = page.getByTestId('forensic-visual');
  await expect(visual).toBeVisible();
  const expand = page.getByRole('button', { name: 'Expand Analysis chart' });
  await expand.click();
  await expect(visual).toHaveAttribute('aria-modal', 'true');
  await expect(page.getByRole('button', { name: 'Close expanded Analysis chart' })).toBeFocused();
  await page.keyboard.press('Tab');
  expect(await visual.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  const expanded = await visual.boundingBox();
  expect(expanded?.width ?? 0).toBeGreaterThanOrEqual(viewport.width - 2);
  await page.keyboard.press('Escape');
  await expect(visual).not.toHaveAttribute('aria-modal', 'true');
  await expect(expand).toBeFocused();
});

test('mobile settings is keyboard-contained and uses the available viewport', async ({ page }) => {
  await page.goto('/projects');
  if (page.viewportSize()!.width < 768) {
    await page.getByRole('button', { name: /Account menu/ }).click();
    await page.getByRole('menuitem', { name: 'Settings' }).click();
  } else {
    await page.getByRole('button', { name: 'Open settings' }).click();
  }
  const dialog = page.getByRole('dialog', { name: 'Settings' });
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box?.height ?? 0).toBeLessThanOrEqual(page.viewportSize()!.height);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});
