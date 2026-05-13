# Playwright Test Plan — `feature/design-refresh-asistant`

**Branch:** `feature/design-refresh-asistant`
**Commit:** `c87f0e2 — Rebrand to Asistant, restructure sidebar + chat, add usage budget`
**Authored:** 2026-05-13
**Owner:** kadir
**Gate:** all P0 + P1 must pass locally before deploy; all P0 must pass post-deploy on the server.

---

## 0. Why this plan

The design refresh changed user-facing strings, the left sidebar layout, the chat layout, and added a global usage budget. Some existing Playwright specs (welcome-screen, provider-tabs, branding selectors) will fail as-is. This document is the single source of truth for:

1. **Which existing tests need to change**, and *exactly what to change*.
2. **Which new tests need to be added**, and *exactly the steps each test performs*.
3. **The run procedure** locally (against `http://localhost:5173`) and against the deployed server.
4. **The pass/fail gates** that block deploy.

The aim is that any contributor can pick up this document and implement the test code in one sitting, without re-reading the diff.

---

## 1. Scope

### In scope
- Smoke: app loads, health endpoint, brand string.
- Sidebar: AI Assistant chat list + Documents / Correspondence / Spreadsheet collapsible folders.
- Chat: input anchored at bottom, action chips above input, send a message, retry.
- Welcome screen: no example queries, no inline input, mode tiles still work.
- Settings modal: opens/closes, "LLM Providers" section is gone.
- Usage budget: `/api/usage` returns a valid shape, `UsageBadge` renders in TopNav.
- Provider hiding: no "Gemini" / "OpenAI" / "Claude" / "GPT" string anywhere in the rendered DOM.
- Document viewer: open a doc, navigate pages, close.
- Correspondence mode: enter via action chip, the Correspondence folder auto-opens, multi-select + quick-prompt.
- Library API health: `/api/library` returns ≥1 doc on the seeded server.

### Out of scope (defer)
- Document Analysis correctness (Phase 4 — needs PM repro).
- Document anonymisation (PM-owned, Phase 9).
- Heavy LLM correctness checks — those belong in unit tests, not E2E.
- Visual regression / pixel diffs (would be a separate Percy / argos pass).
- Cross-browser — chromium only for this gate (matches existing config).
- Mobile viewports — desktop only.

---

## 2. Environment matrix

| Target | BASE_URL | When | Who runs it |
|---|---|---|---|
| **Local dev** | `http://localhost:5173` (Vite) with backend on `http://localhost:8080` | Before every push to PR | dev (kadir) |
| **Server (production)** | the deployed origin (Lightsail / Cloud Run; current default in `.env.e2e` is `https://rag-chatbot-357290910216.europe-west1.run.app`) | Right after deploy, before announcing the PR | dev / CI |

The same spec set runs against both — only `BASE_URL` differs. The Playwright config is already wired to honour `BASE_URL` (see [playwright.config.ts](../frontend/e2e/playwright.config.ts) line 13).

### Local prerequisites

```bash
# 1. Backend reachable on :8080
cd <repo-root>
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload &

# 2. Frontend dev server
cd frontend
npm install                # fixes the rollup-darwin-arm64 optional-dep issue
npm run dev                # serves on :5173, proxies /api to :8080

# 3. Verify
curl -s http://localhost:8080/api/health   # → {"status":"ok"}
curl -s http://localhost:5173/             # → HTML shell
```

`frontend/e2e/.env.e2e` currently points at the cloud URL. **For local runs, override it on the command line** rather than editing the file:

```bash
cd frontend
BASE_URL=http://localhost:5173 npm run e2e
```

### Server prerequisites
- Deploy is finished, `curl -fsS $BASE_URL/api/health` returns 200.
- At least one seeded document exists in the registry (the demo dataset of 108 docs is fine).
- `ASISTANT_USAGE_LIMIT_USD` env var is set on the server (default 100 — fine for testing).

---

## 3. What's already there vs. what changes

### 3.1 Existing files to **update**

| File | Why it breaks | Concrete fix |
|---|---|---|
| [helpers/selectors.ts](../frontend/e2e/helpers/selectors.ts) | `branding: '[aria-label="ConstructionIQ"]'` no longer matches; `welcomeSearch: '#welcome-search'` element was removed; `correspondenceCard: 'button:has-text("Correspondence Mode")'` label is now "Correspondence" only. | See **§4 Selectors registry** below — replace those three plus add new ones for folders, chips, usage badge. |
| [page-objects/welcome.page.ts](../frontend/e2e/page-objects/welcome.page.ts) | References `welcomeSearch` and `searchAndSend()`. | Remove `searchInput` field and `searchAndSend()` method. Welcome no longer has its own input — input is now part of `ChatPage`. |
| [page-objects/sidebar.page.ts](../frontend/e2e/page-objects/sidebar.page.ts) | Old single-section docs list with chip filters is gone. | Add helpers: `openFolder(name)`, `expectFolderCount(name, n)`, `expectChatSection()`. |
| [tests/chat/welcome-screen.spec.ts](../frontend/e2e/tests/chat/welcome-screen.spec.ts) | 3 tests reference the removed inline search input + example queries. | Delete those 3 cases, keep mode-card tests. |
| [tests/chat/provider-tabs.spec.ts](../frontend/e2e/tests/chat/provider-tabs.spec.ts) | Provider tabs are intentionally hidden. | **Repurpose** the file as a guard: assert "Gemini" / "OpenAI" / "Claude" / "GPT" are *not* visible in the message DOM. |
| [tests/modals/settings.spec.ts](../frontend/e2e/tests/modals/settings.spec.ts) | "LLM Providers" section was removed. | Replace any assertion that the section exists with `expect(text="LLM Providers").toHaveCount(0)`. |
| [tests/navigation/topnav.spec.ts](../frontend/e2e/tests/navigation/topnav.spec.ts) | Brand aria-label changed. | Update assertions to `aria-label="Asistant"` and brand text "Asistant". |

### 3.2 New spec files to **create**

| File | Coverage |
|---|---|
| `tests/sidebar/folders.spec.ts` | The three new collapsible folders (Documents / Correspondence / Spreadsheet) — counts, expand/collapse, click a file. |
| `tests/chat/action-chips.spec.ts` | Action chip strip above the composer — chip switches mode, active state visible. |
| `tests/chat/composer-layout.spec.ts` | Composer is anchored at the bottom regardless of whether Welcome / DocAnalysisIntro / CorrespondenceCenter / ChatStream is active. |
| `tests/chat/branding.spec.ts` | Brand string is "Asistant" in TopNav + `<title>`; "Construction" is absent from the visible DOM. |
| `tests/chat/provider-hidden.spec.ts` | After sending a message, no provider name renders. |
| `tests/usage/usage-badge.spec.ts` | `/api/usage` returns the right schema; the badge is visible and shows `$x / $y`. |
| `tests/usage/usage-enforce.spec.ts` (server-only, optional) | When the budget is forced over via `/api/usage/reset` + a stub, sending returns 402. Skipped by default — guarded by env `RUN_BUDGET_ENFORCE=1`. |

---

## 4. Selectors registry — exact updates to `helpers/selectors.ts`

Replace / add these entries. Anything not mentioned is unchanged.

```ts
// REPLACE
branding: '[aria-label="Asistant"]',

// REMOVE (no longer in DOM)
// welcomeSearch: '#welcome-search',

// REPLACE — Welcome no longer has "Mode" in card label
correspondenceCard: 'button:has-text("Correspondence")',
documentAnalysisCard: 'button:has-text("Document Analysis")',

// ── NEW: Sidebar folders ───────────────────────────
folderDocuments:     'button[aria-expanded]:has-text("Documents")',
folderCorrespondence:'button[aria-expanded]:has-text("Correspondence")',
folderSpreadsheet:   'button[aria-expanded]:has-text("Spreadsheet")',
folderHeader: (name: string) =>
  `button[aria-expanded]:has-text("${name}")`,
sidebarAiAssistantHeading: 'p:has-text("AI Assistant")',

// ── NEW: Chat action chips ─────────────────────────
actionChipsStrip:        'div:has(> span:has-text("Programs"))',
chipCorrespondence:      'button[aria-pressed]:has-text("Correspondence")',
chipDocumentAnalysis:    'button[aria-pressed]:has-text("Document Analysis")',
chipByLabel: (label: string) =>
  `button[aria-pressed]:has-text("${label}")`,

// ── NEW: Usage badge ───────────────────────────────
usageBadge: '[aria-label="Usage budget"]',
```

The Composer textarea is still `#chat-input` — no change. The send button is still `[aria-label="Send message"]` — no change.

---

## 5. Test scenarios — step by step

Each scenario lists **priority**, **selectors used**, **steps**, **expected**, and **gate**. Steps are deliberately granular so the implementer doesn't have to guess.

Priorities:
- **P0** — blocks deploy. Smoke + branding + composer + budget endpoint.
- **P1** — blocks PR merge. Full sidebar + chat flow.
- **P2** — nice-to-have within this PR.

### 5.1 Smoke

#### 5.1.1 App loads (P0)
- **File:** `tests/smoke/app-loads.spec.ts` (exists; verify it still passes).
- **Steps:**
  1. `page.goto('/')`.
  2. `await page.waitForLoadState('networkidle')`.
  3. Assert `<title>` text === `"Asistant"`.
  4. Assert `[aria-label="Asistant"]` exists in the DOM.
- **Expected:** Title and brand match; no console errors > severity `warning`.
- **Gate:** P0.

#### 5.1.2 Health endpoint (P0)
- **File:** `tests/smoke/health-check.spec.ts` (exists).
- **Steps:** `GET /api/health` → expect `{status:"ok"}`.
- **Gate:** P0.

#### 5.1.3 Usage endpoint shape (P0, **new**)
- **File:** `tests/usage/usage-badge.spec.ts` — first case.
- **Steps:**
  1. `request.get('/api/usage')`.
  2. Assert status 200.
  3. Assert body has numeric `used_usd`, `limit_usd`, `remaining_usd`, `remaining_pct`; boolean `over_budget`; integers `prompt_tokens`, `completion_tokens`, `total_tokens`, `total_calls`.
- **Expected:** All fields present, types match.
- **Gate:** P0.

### 5.2 Branding & provider hiding

#### 5.2.1 Brand string surfaces only "Asistant" (P0, **new**)
- **File:** `tests/chat/branding.spec.ts`.
- **Steps:**
  1. `page.goto('/')`.
  2. `expect(page.getByRole('banner').locator('[aria-label="Asistant"]')).toBeVisible()`.
  3. `expect(page.locator('body')).not.toContainText(/Construction(IQ)?/i)`.
  4. `expect(page).toHaveTitle(/^Asistant$/)`.
- **Gate:** P0.

#### 5.2.2 Provider names never render (P0, **new** — repurposes `provider-tabs.spec.ts`)
- **File:** `tests/chat/provider-hidden.spec.ts`.
- **Steps:**
  1. Create a new conversation.
  2. Send a benign message (e.g. `"List my documents."`).
  3. Wait for the assistant response (`role="log"` contains a new bubble).
  4. Assert the page body does NOT contain any of: `"Gemini"`, `"OpenAI"`, `"Claude"`, `"GPT"`, `"claude-sonnet"`, `"gemini-2.5"`, `"gpt-4"`. Use a regex with `i` flag.
- **Expected:** Zero matches.
- **Gate:** P0. *(High-leverage test — catches accidental regressions.)*

### 5.3 Sidebar folders

#### 5.3.1 AI Assistant section header is present (P1)
- **File:** `tests/sidebar/folders.spec.ts`.
- **Steps:** Open the page; assert `sidebarAiAssistantHeading` is visible.

#### 5.3.2 All three folders render with counts (P1)
- **Steps:**
  1. `await sidebarPage.waitForVisible()`.
  2. For each folder name `["Documents", "Correspondence", "Spreadsheet"]`:
     - Assert `folderHeader(name)` is visible.
     - Read the count badge (last span inside the header); assert it's a non-negative integer.
- **Expected:** All three folders visible; sum of counts equals total files (cross-check with `GET /api/library`).
- **Gate:** P1.

#### 5.3.3 Folder expand/collapse (P1)
- **Steps for each folder:**
  1. Get `aria-expanded` on the header — initially `false`.
  2. Click the header.
  3. Assert `aria-expanded` is now `true`, the chevron has class `rotate-90`, and the content panel `ml-3 mt-0.5 border-l` is visible.
  4. Click again; assert `aria-expanded` becomes `false`.
- **Gate:** P1.

#### 5.3.4 Click a file opens the viewer (P1)
- **Pre-req:** at least one Document, one Spreadsheet, and one Correspondence email exist in the library.
- **Steps:**
  1. Open the Documents folder; click the first file row.
  2. Assert the right viewer is open: `[aria-label="Close viewer"]` is visible.
  3. Close the viewer (`viewerClose` selector).
  4. Repeat for Spreadsheet folder.
- **Gate:** P1.

#### 5.3.5 Empty folder shows "Empty" placeholder (P2)
- **Pre-req:** create a temporary fixture where one folder is empty (or rely on Correspondence being empty in a clean env).
- **Steps:** Expand the empty folder; expect `text="Empty"` to be visible inside.

### 5.4 Chat action chips

#### 5.4.1 Chips render above the composer (P1)
- **File:** `tests/chat/action-chips.spec.ts`.
- **Steps:**
  1. Open the page; create a new chat.
  2. Assert `actionChipsStrip` is visible.
  3. Assert `chipCorrespondence` and `chipDocumentAnalysis` are both visible.
  4. Assert the strip is above the composer (`#chat-input`) in document order — use `evaluate` to compare `getBoundingClientRect().top`.

#### 5.4.2 Chip click activates the mode (P1)
- **Steps:**
  1. Click `chipCorrespondence`.
  2. Assert `chipCorrespondence` now has `aria-pressed="true"` and the active style class `border-[var(--accent)]`.
  3. Assert the page transitions into Correspondence center (heading `CORRESPONDENCE MODE` visible).
  4. Click "Back" (`backButton` selector); assert chip returns to `aria-pressed="false"`.

#### 5.4.3 Active chip persists across reload (P2)
- **Steps:**
  1. Pick a mode via chip.
  2. Reload the page.
  3. Assert the chip is still pressed (mode is persisted in chat store).

### 5.5 Composer layout (bottom anchor)

#### 5.5.1 Composer is always anchored bottom (P0)
- **File:** `tests/chat/composer-layout.spec.ts`.
- **For each of these states:** welcome, document_analysis mode, correspondence mode, mid-conversation:
  1. Enter the state (helpers).
  2. Assert `#chat-input` is visible.
  3. Compute `composer.boundingBox().y + composer.boundingBox().height`.
  4. Compute `mainContent.boundingBox().y + mainContent.boundingBox().height`.
  5. Assert the composer bottom is within 24px of the main content bottom (allows for padding).
- **Gate:** P0.

#### 5.5.2 Send a message from the bottom composer (P1)
- **Steps:**
  1. Type `"Hello"` into `#chat-input`.
  2. Click `sendButton`.
  3. Wait for `typingIndicator` to appear within 5s.
  4. Wait for an assistant bubble (`.prose` containing non-empty text) to render within 30s.
- **Gate:** P1.

#### 5.5.3 Welcome screen no longer renders an inline input (P0)
- **Steps:**
  1. Open a fresh conversation (welcome state).
  2. Assert `#welcome-search` is **not** present (`toHaveCount(0)`).
  3. Assert no `button:has-text("MANPOWER")`, `button:has-text("EQUIPMENT")` (the example query category prefixes) are present.
- **Gate:** P0.

### 5.6 Welcome screen

#### 5.6.1 Mode tiles still navigate (P1)
- **File:** updated `tests/chat/welcome-screen.spec.ts`.
- **Steps:**
  1. From a fresh conversation, click `correspondenceCard`.
  2. Assert the page transitions to Correspondence center.
  3. Go back; click `documentAnalysisCard`.
  4. Assert the page transitions to Document Analysis intro.

### 5.7 Settings modal

#### 5.7.1 Settings opens / closes (P1)
- **File:** updated `tests/modals/settings.spec.ts`.
- **Steps:**
  1. Click `settingsButton`.
  2. Assert `settingsDialog` is visible.
  3. Press `Escape`.
  4. Assert `settingsDialog` is gone.

#### 5.7.2 No LLM Providers section (P0)
- **Steps:**
  1. Open Settings.
  2. Assert `text="LLM Providers"` has **count 0**.
  3. Assert `text="Vector Database"` is visible (sanity — section we kept).
- **Gate:** P0.

### 5.8 Usage badge

#### 5.8.1 Badge renders with $used / $limit (P0)
- **File:** `tests/usage/usage-badge.spec.ts`.
- **Steps:**
  1. `page.goto('/')`.
  2. Stub `/api/usage` once with: `{ used_usd: 12.34, limit_usd: 100, remaining_usd: 87.66, remaining_pct: 0.8766, over_budget: false, prompt_tokens: 1234, completion_tokens: 567, total_tokens: 1801, total_calls: 7 }`.
  3. Assert `usageBadge` is visible.
  4. Assert it contains both `$12` (or `$12.3`) and `$100`.
  5. Assert the progress bar element exists inside the badge.
- **Gate:** P0.

#### 5.8.2 Amber / red colour ramp (P2)
- **Steps:** Stub with `used_usd: 75` → bar should have `bg-amber-400`. Stub with `used_usd: 95` → bar should have `bg-[var(--danger)]`. Stub with `over_budget: true` → text colour switches to `text-[var(--danger)]`.

#### 5.8.3 Budget exceeded returns 402 (P2, opt-in)
- **File:** `tests/usage/usage-enforce.spec.ts`.
- **Guard:** skip unless `process.env.RUN_BUDGET_ENFORCE === '1'`.
- **Steps:**
  1. Lower `ASISTANT_USAGE_LIMIT_USD` to `0.001` on the backend (server-only; locally restart with `ASISTANT_USAGE_LIMIT_USD=0.001`).
  2. Reset counter via `POST /api/usage/reset`.
  3. Send a chat message.
  4. Expect first response to come back; after a few calls, `POST /api/chat` returns HTTP 402 with body `{ "error": "budget_exceeded" }`.
  5. Cleanup: restore the env value, reset the counter.

### 5.9 Correspondence flow

#### 5.9.1 Entering Correspondence auto-opens the folder (P1)
- **File:** `tests/sidebar/folders.spec.ts` — extension.
- **Steps:**
  1. Initially assert `aria-expanded="false"` on the Correspondence folder.
  2. Click the Correspondence chip.
  3. Within 2s assert `aria-expanded="true"` on the Correspondence folder.

#### 5.9.2 Select an email and run a quick prompt (P2)
- **Steps:**
  1. Enter Correspondence mode.
  2. Expand the first thread.
  3. Check the first email checkbox.
  4. Click the "Summarize selected emails" quick prompt.
  5. Wait for an assistant bubble to render.

### 5.10 Document viewer

#### 5.10.1 Open / navigate / close (P1)
- **File:** existing `tests/viewer/navigation.spec.ts` — verify it still passes after Documents folder change. The selectors `viewerClose`, `prevPage`, `nextPage` are unchanged.

---

## 6. Network stubbing patterns

For tests that need deterministic backend responses (e.g. usage colour ramp, provider-hidden assertion), use `page.route`:

```ts
await page.route('**/api/usage', (route) =>
  route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      used_usd: 12.34, limit_usd: 100, remaining_usd: 87.66,
      remaining_pct: 0.8766, over_budget: false,
      prompt_tokens: 1234, completion_tokens: 567,
      total_tokens: 1801, total_calls: 7,
    }),
  })
);
```

For chat tests, **prefer hitting the real backend** — the orchestrator path is what we care about. Only stub for predictable colour / state tests.

---

## 7. Pass / fail gates

| Gate | What must pass | Where |
|---|---|---|
| **Pre-push (local)** | All P0 + P1 specs against `localhost` | dev machine |
| **PR merge** | All P0 + P1 + P2 specs against `localhost`, GitHub Actions green | CI |
| **Deploy gate (pre-deploy)** | All P0 + P1 against `localhost` re-run on top of the *deploy build* (so we build the frontend, serve it via the FastAPI static mount, and point Playwright at `:8080`) | dev / CI |
| **Post-deploy smoke** | All P0 against the real server URL | dev / CI |

A failing P0 blocks deploy. A failing P1 blocks merge. A failing P2 should be filed as an issue but does not block.

---

## 8. Run procedures

### 8.1 Local — Vite dev server

```bash
# Terminal 1 — backend
cd <repo-root>
. .venv/bin/activate                                    # if applicable
ASISTANT_USAGE_LIMIT_USD=100 python -m uvicorn backend.main:app \
  --host 0.0.0.0 --port 8080 --reload

# Terminal 2 — frontend (Vite serves on :5173, proxies /api → :8080)
cd frontend
rm -rf node_modules && npm install     # one-time, fixes rollup optional-dep on macOS
npm run dev

# Terminal 3 — Playwright
cd frontend
BASE_URL=http://localhost:5173 npm run e2e

# Filter to one suite while iterating:
BASE_URL=http://localhost:5173 npm run e2e -- tests/chat/branding.spec.ts

# Headed (visible browser) while debugging:
BASE_URL=http://localhost:5173 npm run e2e:headed

# Or full UI mode:
BASE_URL=http://localhost:5173 npm run e2e:ui
```

### 8.2 Local — production build (deploy-parity)

This catches build-only regressions (CSS purge, env var inlining) before deploy.

```bash
cd frontend
npm run build                                          # → frontend/dist/

# Serve from FastAPI (which mounts frontend/dist if present)
cd ..
ASISTANT_USAGE_LIMIT_USD=100 python -m uvicorn backend.main:app \
  --host 0.0.0.0 --port 8080

# Playwright against :8080 (single-origin, exactly like prod)
cd frontend
BASE_URL=http://localhost:8080 npm run e2e
```

### 8.3 Server — post-deploy smoke

```bash
cd frontend
BASE_URL=https://<your-server-url> npm run e2e -- tests/smoke/ tests/chat/branding.spec.ts \
  tests/chat/provider-hidden.spec.ts tests/chat/composer-layout.spec.ts \
  tests/modals/settings.spec.ts tests/usage/usage-badge.spec.ts
```

If everything green, you're done. If any spec fails:
1. Inspect `playwright-report/` (HTML report) — it has screenshot + trace for failures.
2. Cross-check the HTTP response in DevTools network panel.
3. Compare the actual DOM against the assertions in this document.

---

## 9. Implementation checklist (for the dev writing the test code)

In order, with rough effort:

- [ ] **(15 min)** Update [helpers/selectors.ts](../frontend/e2e/helpers/selectors.ts) per §4.
- [ ] **(10 min)** Update [page-objects/welcome.page.ts](../frontend/e2e/page-objects/welcome.page.ts) — remove `searchInput` and `searchAndSend()`.
- [ ] **(20 min)** Extend [page-objects/sidebar.page.ts](../frontend/e2e/page-objects/sidebar.page.ts) — add `openFolder()`, `expectFolderCount()`, `expectChatSection()`.
- [ ] **(10 min)** Rewrite [tests/chat/welcome-screen.spec.ts](../frontend/e2e/tests/chat/welcome-screen.spec.ts) — drop the 3 obsolete cases, keep the mode-card cases.
- [ ] **(20 min)** Repurpose [tests/chat/provider-tabs.spec.ts](../frontend/e2e/tests/chat/provider-tabs.spec.ts) → rename to `provider-hidden.spec.ts`, implement §5.2.2.
- [ ] **(10 min)** Update [tests/modals/settings.spec.ts](../frontend/e2e/tests/modals/settings.spec.ts) for §5.7.
- [ ] **(10 min)** Update [tests/navigation/topnav.spec.ts](../frontend/e2e/tests/navigation/topnav.spec.ts) for the new aria-label/title.
- [ ] **(30 min)** Implement `tests/sidebar/folders.spec.ts` per §5.3 + §5.9.1.
- [ ] **(20 min)** Implement `tests/chat/action-chips.spec.ts` per §5.4.
- [ ] **(20 min)** Implement `tests/chat/composer-layout.spec.ts` per §5.5.
- [ ] **(15 min)** Implement `tests/chat/branding.spec.ts` per §5.2.1.
- [ ] **(25 min)** Implement `tests/usage/usage-badge.spec.ts` per §5.1.3 + §5.8.
- [ ] **(15 min, opt-in)** Implement `tests/usage/usage-enforce.spec.ts` per §5.8.3.

**Total:** ~3.5 hours of focused work for full test coverage of this PR.

---

## 10. Triage / known footguns

1. **`rm -rf node_modules && npm install`** is required at least once on macOS — npm's optional-dep handling for `@rollup/rollup-darwin-arm64` is buggy. Once installed, `npm ci` is fine.
2. **`BASE_URL` defaults to a Cloud Run URL** in `.env.e2e`. **Always pass `BASE_URL=http://localhost:5173`** for local runs, or the tests will silently target prod. (Consider changing the default to `http://localhost:5173` once we're confident.)
3. The first Playwright run after a fresh deploy may hit a cold start (15-30s). `navigationTimeout: 60000` is already set — leave it.
4. The Welcome screen now renders **only** when `activeMode === null && messages.length === 0`. Make sure the test resets to a fresh conversation before any Welcome assertion (call `sidebarPage.createNewChat()`).
5. The mock conversation seed in CI must not have stale `Gemini` text in it — clear `storage/conversations/` before running the provider-hidden test if it flakes.
6. Usage counter persists between runs in `storage/usage_counter.json`. For deterministic budget tests, call `POST /api/usage/reset` in `beforeAll`.
7. Cloud Run / Lightsail static asset cache may serve a stale `index.html` for ~5 minutes after deploy — if the brand still says "Construction" right after deploy, refresh / cache-bust before declaring failure.

---

## 11. After this PR ships — follow-ups

These tests should be added once the corresponding features land, but are **not** in scope of this gate:

- **Faz 4 — Document Analysis fix** → add a `tests/chat/document-analysis.spec.ts` that verifies topic-trace timeline rendering with seeded data, once PM provides concrete repro inputs.
- **Anonymisation** → diff snapshot tests once that feature is in.
- **Multi-tenant token isolation** → if/when we move to LiteLLM proxy with per-key budgets.
