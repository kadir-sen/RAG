import { expect, test } from '@playwright/test';
import { installProjectsApi, makeProject, makeState, seedProjectSession } from '../../fixtures/projects-api';

const workspace = {
  workspace_id: 'fws-e2e', project_id: 'project-forensic', name: 'Programme Analysis',
  programme_ids: ['xer-baseline', 'xer-update'], settings: {}, source_revision: 'a'.repeat(64),
  upstream_sha: 'bb52fa0a5e41fc2040979b226911b192463701d5',
  created_at: '2026-08-05T00:00:00Z', updated_at: '2026-08-05T00:00:00Z',
  state_version: 1, pipeline_version: 'forensic-parity-v1', evidence_source_ids: [],
};

test('pins existing project evidence and exposes the complete native navigation', async ({ page }) => {
  const project = makeProject('project-forensic', 'Forensic Project');
  await seedProjectSession(page, project.project_id);
  await installProjectsApi(page, makeState([project]));
  const writes: Array<{ method: string; path: string; body: unknown }> = [];

  await page.route('**/api/forensic/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/forensic', '');
    if (request.method() !== 'GET') {
      writes.push({ method: request.method(), path, body: request.postDataJSON() });
    }
    if (path === '/status') return route.fulfill({ json: {
      available: true, enabled: true, parity_available: true, parity_enabled: false,
      parity_validation: true,
      pipeline_version: 'forensic-parity-v1', parity_fingerprint: 'f'.repeat(64),
      coair_sha: 'coair123', upstream_sha: workspace.upstream_sha, streamlit: false,
      max_workspace_bytes: 75 * 1024 * 1024,
      modules: [
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
      ].map(([slug, title, group]) => ({ slug, title, group, minimum_files: 1,
        parity: { controls: [], actions: ['run'], views: [] } })),
    }});
    if (path === '/programmes') return route.fulfill({ json: { programmes: [
      { file_id: 'xer-baseline', name: 'Baseline.xer', size_bytes: 1000, sha256: '1'.repeat(64), created_at: '2026-08-05T00:00:00Z' },
      { file_id: 'xer-update', name: 'Update.xer', size_bytes: 1200, sha256: '2'.repeat(64), created_at: '2026-08-05T00:00:00Z' },
    ] } });
    if (path === '/workspaces' && request.method() === 'GET') return route.fulfill({ json: { workspaces: [workspace] } });
    if (path === '/sources') return route.fulfill({ json: { sources: [
      { source_id: 'xer-baseline', source_kind: 'programme', file_name: 'Baseline.xer', extension: '.xer', size_bytes: 1000, content_hash: '1'.repeat(64), status: 'ready', capabilities: ['programme_analysis'], metadata: {} },
      { source_id: 'doc-notice', source_kind: 'document', file_name: 'Engineer Notice 88.pdf', extension: '.pdf', size_bytes: 2400, content_hash: '3'.repeat(64), status: 'ready', capabilities: ['text_extraction', 'tia_event_extraction'], metadata: { reference: 'EI-88' } },
      { source_id: 'doc-legacy', source_kind: 'document', file_name: 'Legacy correspondence.pdf', extension: '.pdf', size_bytes: 0, content_hash: '4'.repeat(64), status: 'text_only', capabilities: ['text_extraction', 'text_only'], metadata: { text_only: true } },
    ] } });
    if (path === '/workspaces/fws-e2e/state' && request.method() === 'GET') return route.fulfill({ json: {
      workspace_id: 'fws-e2e', project_id: project.project_id, version: 1,
      state: { pipeline_version: 'forensic-parity-v1', baseline_programme_id: 'xer-baseline', current_programme_id: 'xer-update', contract_completion_milestone: '', missing_inputs: [], analysis_basis: {}, event_register: {}, apab: {}, umbrella: {}, sequence: {}, hierarchy: {}, explain: {}, iap: {}, cab: {}, narratives: {}, report: {} },
      created_at: '2026-08-05T00:00:00Z', updated_at: '2026-08-05T00:00:00Z',
    } });
    if (path === '/workspaces/fws-e2e' && request.method() === 'PATCH') return route.fulfill({ json: workspace });
    if (path === '/workspaces/fws-e2e/sources' && request.method() === 'PUT') return route.fulfill({ json: {
      workspace: { ...workspace, state_version: 2, evidence_source_ids: ['doc-notice'] },
      state: { workspace_id: 'fws-e2e', project_id: project.project_id, version: 2, state: {}, created_at: '', updated_at: '' },
      sources: [], source_revision: 'b'.repeat(64),
    } });
    if (path === '/workspaces/fws-e2e/state' && request.method() === 'PATCH') return route.fulfill({ json: { workspace_id: 'fws-e2e', project_id: project.project_id, version: 3, state: {}, created_at: '', updated_at: '' } });
    if (path === '/runs') return route.fulfill({ json: { runs: [] } });
    return route.fulfill({ status: 404, json: { detail: 'unmocked_forensic_route' } });
  });

  await page.goto('/forensic/intake?workspace=fws-e2e');
  await expect(page.getByRole('navigation', { name: 'Forensic analysis modules' }).getByRole('link')).toHaveCount(20);
  await expect(page.getByText('Use existing evidence without uploading it again')).toBeVisible();
  await page.getByText('Engineer Notice 88.pdf').click();
  await expect(page.getByText('Text only', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Update workspace' }).click();

  await expect.poll(() => writes.some((item) => item.method === 'PUT' && item.path.endsWith('/sources'))).toBe(true);
  const selection = writes.find((item) => item.method === 'PUT' && item.path.endsWith('/sources'))?.body as { sources: Array<{ source_id: string }> };
  expect(selection.sources.map((item) => item.source_id)).toEqual(['xer-baseline', 'xer-update', 'doc-notice']);
});

// Programme forensics moved out to the standalone Delay Analysis Toolkit, so
// FORENSIC_NATIVE_UI_V1 is off for project users and /forensic/status reports
// available: false. Two things must survive that, and both are one careless
// edit away from silently disappearing.
test('keeps the evidence draft and the toolkit link when the native module is closed', async ({ page }) => {
  const project = makeProject('project-forensic', 'Forensic Project');
  await seedProjectSession(page, project.project_id);
  await installProjectsApi(page, makeState([project]));

  await page.route('**/api/forensic/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/forensic', '');
    if (path === '/status') return route.fulfill({ json: {
      available: false, enabled: false, parity_available: false, parity_enabled: false,
      parity_validation: false, pipeline_version: 'forensic-parity-v1',
      parity_fingerprint: 'f'.repeat(64), coair_sha: 'coair123',
      upstream_sha: workspace.upstream_sha, streamlit: false,
      max_workspace_bytes: 75 * 1024 * 1024, modules: [],
    } });
    return route.fulfill({ status: 404, json: { detail: 'forensic_native_ui_disabled' } });
  });

  // COAir's own AI draft over the project record needs no programme file, so
  // closing the native module must not take it down with it.
  await page.goto('/forensic/evidence-report');
  await expect(page.getByRole('heading', { name: 'Evidence-led Forensic Draft' })).toBeVisible();
  await expect(page.getByText('Native forensic analysis is in validation')).toHaveCount(0);

  // The Forensic Reports tile hands over to the toolkit rather than a COAir route.
  await page.goto('/');
  await expect(page.getByRole('link', { name: /Forensic Reports/ })).toHaveAttribute('href', '/toolkit/');
});
