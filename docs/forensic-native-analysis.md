# Native forensic programme analysis

> **Closed to project users.** Programme forensics are now served by the
> toolkit's own Streamlit app at `/toolkit/` — see
> [delay-toolkit.md](delay-toolkit.md). `FORENSIC_NATIVE_UI_V1=false` in
> production; admins may still validate the parity APIs, and setting the flag
> back to `true` restores everything below. The document describes the native
> layer as built.

COAir runs the Delay Analysis Toolkit's deterministic engines directly inside
the FastAPI process. No Streamlit page, iframe, launch ticket, port 8501 or
`/toolkit/` reverse proxy participates in this flow.

## Source boundary

The unmodified upstream tree is pinned under
`vendor/delay-analysis-toolkit` at commit `bb52fa0`. Its URL, revision and a
content digest are recorded in `vendor/delay-analysis-toolkit.upstream.json`.
`scripts/verify_forensic_vendor.py` fails CI if a local vendor file drifts.

All COAir-specific code remains outside that tree:

- `backend/services/forensic_toolkit` imports only the pure `dcma`,
  `programme`, `rlpa_apvab_v2` and `path_studio` packages.
- `src/forensic_store.py` owns project-scoped programmes, workspaces, runs and
  artifacts.
- `backend/tasks/forensic_jobs.py` runs one heavy deterministic analysis at a
  time and resumes jobs left processing after a restart.
- `backend/api/forensic.py` exposes typed project-authorized endpoints.
- `frontend/src/pages/ForensicPage.tsx` renders the 19 native modules.

The upstream `app.py` and `views/` directory are never imported. Production
dependency installation filters Streamlit out of `requirements.txt`.

## Data and authorization

XER uploads are validated for the P6 `PROJECT` and `TASK` tables, hashed, and
stored below `data/projects/<project_id>/programmes`. They count toward the
uploader's source-storage quota but bypass the document registry, OCR, RAG and
embedding queues. Exact duplicate content within a project is reused without
consuming storage twice.

A workspace is an immutable source-revision hash over the selected programme
SHA values, settings and upstream engine SHA. Selected XER content is limited
to 75 MiB per workspace. Owner/editor roles upload, change a workspace and run
analysis; viewers may inspect completed runs and download their artifacts.
Every lookup includes the current project ID, so identifiers from another
project resolve as not found.

## Run and artifact lifecycle

`POST /api/forensic/workspaces/{workspace_id}/modules/{module_slug}/runs`
accepts one of 19 discriminated Pydantic parameter models. A worker parses the
pinned source set, invokes the module's pure engine, writes a bounded result
preview and persists full JSON and Excel exports. Report Assembler additionally
creates a Word artifact from completed workspace runs. Successful metrics and
warnings are registered in `toolkit_evidence_store`, making them selectable by
the existing Evidence-led Forensic Draft.

User responses omit engine tracebacks. Admin responses include the traceback
identifier, upstream SHA, source revision and source hashes needed to correlate
server diagnostics.

## Rollout and upstream updates

`FORENSIC_NATIVE_UI_V1` gates project-user access; admins may validate while it
is disabled. Production compose explicitly enables the completed native UI.
`/forensic` redirects to `/forensic/intake`, while the existing AI draft remains
at `/forensic/evidence-report`.

The weekly/manual `forensic-toolkit-sync.yml` workflow compares upstream main
with the lock, applies a squashed subtree pull, refreshes the tree digest, runs
upstream engine and COAir parity tests, and opens a review PR. It never merges
automatically and never copies Streamlit UI behaviour without an explicit
adapter/UI change.
