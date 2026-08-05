import type { Page, Route } from '@playwright/test';

type Role = 'owner' | 'editor' | 'viewer' | 'admin';

export interface ProjectFixture {
  project_id: string;
  name: string;
  slug: string;
  embedding_profile: 'local-bge-v1';
  role: Role;
  archived_at: null;
  stats: {
    files: { document: number; email: number; data: number; programme: number };
    total_files: number;
    queued: number;
    processing: number;
    ready: number;
    failed: number;
    eta_seconds: number | null;
    calibration_size: number;
    calibration_complete: boolean;
    report_ready: boolean;
    vector: {
      status: 'empty' | 'ready' | 'indexing';
      point_count: number;
      embedding_profile: 'local-bge-v1';
      last_error: null;
    };
  };
  usage: { calls: number; prompt_tokens: number; completion_tokens: number; credits_used: number };
}

export interface ApiRequestRecord {
  method: string;
  path: string;
  projectId: string;
  body: unknown;
}

export interface ProjectsApiState {
  projects: ProjectFixture[];
  files: Array<Record<string, unknown>>;
  jobs: Array<Record<string, unknown>>;
  runs: Array<Record<string, unknown>>;
  requests: ApiRequestRecord[];
  failCreate?: boolean;
}

export const fixtureUser = {
  username: 'e2e_user',
  display_name: 'E2E User',
  role: 'admin' as const,
  features: {},
  token_limit: 1_000_000,
  used_tokens: 40_000,
  percent_remaining: 96,
  plan_type: 'demo' as const,
  credits_total: 1000,
  credits_remaining: 960,
  credits_used: 40,
  credit_percent_remaining: 96,
  storage_used_bytes: 1_500_000_000,
  storage_limit_bytes: 30_000_000_000,
  storage_percent_used: 5,
};

export function makeProject(
  id: string,
  name: string,
  options: { ready?: boolean; role?: Role; processing?: boolean } = {},
): ProjectFixture {
  const ready = options.ready ?? true;
  const processing = options.processing ?? false;
  return {
    project_id: id,
    name,
    slug: name.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
    embedding_profile: 'local-bge-v1',
    role: options.role ?? 'owner',
    archived_at: null,
    stats: {
      files: { document: ready ? 12 : 0, email: 2, data: 3, programme: 1 },
      total_files: ready ? 18 : 1,
      queued: processing ? 1 : 0,
      processing: processing ? 1 : 0,
      ready: ready ? 18 : 0,
      failed: 0,
      eta_seconds: processing ? 95 : null,
      calibration_size: 10,
      calibration_complete: ready,
      report_ready: ready && !processing,
      vector: {
        status: processing ? 'indexing' : ready ? 'ready' : 'empty',
        point_count: ready ? 3200 : 0,
        embedding_profile: 'local-bge-v1',
        last_error: null,
      },
    },
    usage: { calls: 4, prompt_tokens: 1200, completion_tokens: 300, credits_used: 2.5 },
  };
}

export function makeFiles(count = 3): Array<Record<string, unknown>> {
  return Array.from({ length: count }, (_, index) => ({
    id: `file-${index + 1}`,
    name:
      index === 0
        ? 'Very long construction programme and correspondence record.pdf'
        : `record-${String(index + 1).padStart(3, '0')}.${index % 3 === 0 ? 'xlsx' : 'pdf'}`,
    file_type: index % 3 === 0 ? 'data' : 'document',
    status: 'ready',
    pages: 3,
    ocr_pages: 3,
    tables: 0,
    rows: 0,
    notice_extracted: false,
  }));
}

export async function seedProjectSession(
  page: Page,
  selectedProjectId: string | null,
): Promise<void> {
  await page.addInitScript(
    ({ selected, user }) => {
      localStorage.setItem(
        'coair-auth',
        JSON.stringify({ state: { token: 'e2e-token', user }, version: 0 }),
      );
      localStorage.setItem(
        'coair-project',
        JSON.stringify({ state: { selectedProjectId: selected }, version: 0 }),
      );
    },
    { selected: selectedProjectId, user: fixtureUser },
  );
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

export async function installProjectsApi(page: Page, state: ProjectsApiState): Promise<void> {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    // Vite serves source modules from paths such as /src/api/client.ts. The
    // broad Playwright glob also sees those; only mock the actual HTTP API.
    if (!url.pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }
    const path = url.pathname.replace(/^\/api/, '') || '/';
    const method = request.method();
    let body: unknown = null;
    if (request.postData()) {
      try {
        body = request.postDataJSON();
      } catch {
        body = request.postData();
      }
    }
    state.requests.push({
      method,
      path,
      projectId: request.headers()['x-project-id'] ?? '',
      body,
    });

    if (method === 'GET' && path === '/auth/me') return json(route, { user: fixtureUser });
    if (method === 'GET' && path === '/projects') {
      return json(route, { projects: state.projects, account_usage: fixtureUser });
    }
    if (method === 'POST' && path === '/projects') {
      if (state.failCreate) return json(route, { detail: 'fixture_create_failed' }, 500);
      const payload = body as { name?: string; embedding_profile?: string };
      const created = makeProject(
        `project-${state.projects.length + 1}`,
        String(payload.name ?? 'Untitled'),
        { ready: false },
      );
      state.projects.push(created);
      return json(route, created, 201);
    }
    const projectMatch = path.match(/^\/projects\/([^/]+)$/);
    if (method === 'PATCH' && projectMatch) {
      const project = state.projects.find((item) => item.project_id === projectMatch[1]);
      if (!project) return json(route, { detail: 'project_not_found' }, 404);
      project.name = String((body as { name?: string }).name ?? project.name);
      return json(route, project);
    }
    if (method === 'DELETE' && projectMatch) return json(route, { ok: true });
    if (method === 'GET' && path === '/files') return json(route, state.files);
    if (method === 'GET' && path === '/indexing/status') return json(route, state.jobs);
    if (method === 'GET' && path === '/runs') return json(route, { runs: state.runs });
    if (method === 'GET' && path === '/reports') return json(route, { reports: [] });
    if (method === 'GET' && path === '/conversations') return json(route, []);
    if (method === 'GET' && path === '/forensic/status') {
      return json(route, {
        available: true,
        enabled: true,
        coair_sha: 'fixture-coair',
        upstream_sha: 'fixture-engine',
        streamlit: false,
        max_workspace_bytes: 78_643_200,
        modules: [
          { slug: 'intake', title: 'Programme Intake', group: 'Programme', minimum_files: 0 },
        ],
      });
    }
    if (method === 'GET' && path === '/forensic/programmes') return json(route, { programmes: [] });
    if (method === 'GET' && path === '/forensic/workspaces') return json(route, { workspaces: [] });
    if (method === 'GET' && path === '/forensic/runs') return json(route, { runs: [] });

    return json(route, method === 'GET' ? {} : { ok: true });
  });
}

export function makeState(projects: ProjectFixture[] = []): ProjectsApiState {
  return { projects, files: makeFiles(), jobs: [], runs: [], requests: [] };
}
