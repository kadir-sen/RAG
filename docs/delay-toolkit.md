# The Delay Analysis Toolkit, served at /toolkit/

Programme forensics — DCMA, critical path, windows, retrospective and
prospective delay analysis — are delivered by the toolkit's **own Streamlit
application**, not by COAir screens.

## Why

COAir used to re-render the toolkit's 19 modules natively in React over the same
vendored engines. It computed the same numbers, but it was not the same product:
different charts, different export buttons, different session model. The ask was
for the toolkit exactly as its author built it — "hiçbir şey değişmesin, ne
grafikler ne draft kısımlar ne raporların nereden nasıl çıkartılacağı" — and for
programme files to stay out of COAir. A re-implementation cannot satisfy that by
construction, so it was closed rather than corrected.

## What runs

`Dockerfile.toolkit` installs the vendored tree's own `requirements.txt` and runs
upstream `app.py` unmodified. Nothing under `vendor/delay-analysis-toolkit` is
wrapped or imported by COAir-side code on this path, and the only edit to that
tree is the managed-provider patch described below.

The tree is copied to the image's working directory so Streamlit reads the
upstream `.streamlit/config.toml` itself — the light Drawing Sheet theme, the
400 MB upload ceiling and XSRF protection are upstream's values, not ours.
`--server.baseUrlPath=toolkit` is a runtime flag; `app.py` has no idea it is
proxied.

Verified against this image with upstream's own harnesses: `audit_app_walk.py`
77/77, `test_qa.py` 497/497, `test_engine.py`, `test_programme.py` and
`test_rlpa.py` 22/22 — every page renders exception-free on the bundled Harbour
Point pair and on degenerate input, cross-module figures agree, the workbook
export builds and the Gantt PNG renders.

## Boundary

The `toolkit` service in `docker-compose.prod.yml` shares the host and nothing
else. No `env_file: .env.production`, no `./data` mount, no `depends_on: api`.
That is deliberate: the toolkit is reachable without a COAir session, so
anything mounted into it would be public too. Analysts upload programmes to the
toolkit directly; those files never enter COAir's registry, OCR, RAG or
embedding queues.

A toolkit failure is a broken link, never a broken COAir. The deploy brings it
up **after** the API health gate and treats the result as non-fatal.

## Access and credentials

There is no password today — anyone with the URL can use it. Upstream ships a
gate for this (`APP_PASSWORD` in `app.py`); turning it on is one line in
`.env.toolkit` and a container restart, with no code change.

The managed AI provider is **Gemini, running `gemini-flash-latest`** on COAir's
own Google billing. The alias is deliberate: a pinned `gemini-2.5-flash` was
rejected in production on 2026-08-06 — *"no longer available to new users"* —
and the alias always resolves to the newest Flash the account can actually
reach. Set the key on the host, not in Git or CI:

```bash
# on the server, in $APP_DIR (default /opt/mvp-api)
printf 'GEMINI_API_KEY=...\n' | sudo tee .env.toolkit >/dev/null
sudo chmod 600 .env.toolkit
sudo docker compose -f docker-compose.prod.yml up -d toolkit
```

With that set, every AI panel shows *"AI enabled — managed Google (Gemini)
endpoint. No key needed."*, preselects `gemini-flash-latest`, and renders **no
key field at all**; the value is never shown or exported. Analysts can still
switch to their own key for Gemini, Anthropic or OpenAI.

The deploy creates `.env.toolkit` empty when missing and never overwrites it.
Left empty, the toolkit still works — the provider picker just defaults to
Gemini and asks for a key. Note that these calls are **not** metered by COAir's
credit ledger.

`GOOGLE_API_KEY` is deliberately **not** forwarded to this container even though
upstream accepts it as a fallback for the same provider: that is COAir's own
variable name, and an operator with it exported would otherwise hand COAir's
billed key to an app that has no login.

## The local patch

This is the only place COAir departs from upstream, and it is recorded in three
places so it cannot be lost quietly:

- `vendor/patches/0001-coair-managed-gemini.patch` — the diff, re-appliable.
- `local_patches` in `vendor/delay-analysis-toolkit.upstream.json`, alongside
  `tree_matches_upstream_commit: false`.
- A guard step in `forensic-toolkit-sync.yml` that fails the weekly sync loudly
  if a subtree pull takes any of it back — including the dead model name.

It does three things:

- **Gemini is the managed provider instead of NVIDIA**, via a single
  `MANAGED_PROVIDER` constant in `dcma/narrative.py` that `views/_shared.py`,
  `views/_umbrella.py` and `test_ui.py` read rather than naming a provider.
- **The NVIDIA provider is removed.** COAir holds no NVIDIA key, so leaving it
  in the dropdown only offered a dead end. It was upstream's only provider with
  a `base_url`, so `refresh_models`' live-catalogue behaviour is now covered by
  a synthetic pinfo in `test_qa.py` — same assertions, no dependence on which
  providers ship.
- **A "← Back to COAir" link** in the sidebar, gated on `COAIR_URL`. Unset — as
  on a standalone or Streamlit Cloud deployment — it is not drawn at all.

Everything else — engines, charts, draft panels, exports — is untouched upstream
code.

The trade this accepts: the vendored tree no longer matches upstream byte for
byte, and the patch now spans eight files (`app.py`, `state.py`,
`dcma/narrative.py`, `views/_shared.py`, `views/_umbrella.py`,
`views/sequence.py`, `test_qa.py`, `test_ui.py`), so upstream edits to any of
them will conflict on the next sync. The cheaper long-term fix is for the
change to land upstream, since Ozan owns that repo.

## One-time server setup

The host nginx must route `/toolkit/` before its catch-all, because FastAPI
answers every unmatched path with the React `index.html`. Without this the URL
renders a COAir 404:

```bash
# on the server, once, after the first deploy that includes the toolkit
sudo bash ~/coair-deploy/deploy/install_toolkit_nginx.sh ~/coair-deploy/deploy/nginx
```

Both files are shipped to `~/coair-deploy/` by every deploy, so no repository
checkout is needed on the server. Re-running is safe; a config that fails
`nginx -t` is rolled back.

## Upstream updates

Unchanged: `.github/workflows/forensic-toolkit-sync.yml` still pins, verifies and
syncs `vendor/delay-analysis-toolkit`. A vendor change now also rebuilds the
toolkit image, which is the point — the app users see moves with upstream.

## The native module

The code remains in the tree, closed to project users by
`FORENSIC_NATIVE_UI_V1=false`; admins can still validate the parity APIs.
Setting it back to `true` is the whole rollback. See
[forensic-native-analysis.md](forensic-native-analysis.md) and
[forensic-native-parity.md](forensic-native-parity.md) for how that layer works.

`/forensic/evidence-report` is **not** part of it. The Evidence-led Forensic
Draft is COAir's own AI report over the project's documents — no programme file,
no engine, no workspace — and stays available with the native module closed.
`frontend/e2e/tests/forensic/parity-workspace.spec.ts` guards that.
