> **Kullanım (TR):** Bu promptu diagram/görselleştirme üreten bir araca (Claude Artifact, Mermaid/diagram üretici, teknik illüstratör agent) olduğu gibi ver. Çıktıda en az 5 diagram + kısa açıklama metinleri beklenir. Tüm bileşen adları koddan doğrulanmıştır — araç yeni bileşen UYDURMAMALIDIR.

# PROMPT: Visualize the COAir AI Architecture

You are a senior technical illustrator and systems-documentation specialist. Produce a set of clear, presentation-grade **diagrams plus short explanatory captions** describing the AI architecture of **COAir** — a construction-industry delay/EOT analysis platform ("Delay Claim Workbench") that combines hybrid RAG, deterministic programme engines, SQL analytics and layered answer-validation.

**Hard rules for you:**
- Use ONLY the components, names and relationships defined below. Do not invent agents, databases or flows.
- Every diagram must have a legend and a 2–4 sentence caption explaining what the viewer is seeing.
- Color-code consistently across ALL diagrams: **blue = LLM-powered components**, **green = deterministic Python engines (no LLM)**, **amber = validation/guard layers**, **grey = data stores**, **purple = user-facing surfaces/reports**.
- Deliver these 5 views: (1) System overview, (2) Request lifecycle / routing decision tree, (3) Agent–Tool–Database access matrix, (4) Workflows & report outputs, (5) Validation & trust layers.

---

## 1. SYSTEM OVERVIEW (what COAir is)

One FastAPI backend + React chat frontend. A user asks a question in chat; a deterministic-first **Router** decides which skill answers it; skills range from pure-LLM RAG synthesis to zero-LLM deterministic engines; every answer passes through validation layers before the user sees it. Core design principle: **the LLM never computes facts it can fabricate — engines compute, the LLM routes, retrieves, narrates and is audited.**

LLM models in use (label components with these):
- **Main model** `gemini-2.5-flash`: answer synthesis, SQL generation, ReAct agent reasoning, plan generation.
- **Lite model** `gemini-2.5-flash-lite`: query classification, retrieval reranking, SQL lazy summaries, Trust Guard claim verification, programme narrative drafting + groundedness check.
- Embeddings: 768-dim (`gemini-embedding-001` cloud or bge-base local/fastembed/api — wire-compatible).
- Optional multi-provider fan-out (OpenAI gpt-4o-mini, Claude Sonnet) — off by default.

---

## 2. REQUEST LIFECYCLE (routing decision tree — draw as flowchart)

```
User question (chat)
 └─ Chat Orchestrator (auth, conversation memory, corpus scoping)
     └─ QueryRouter.route_and_execute
         ├─ [deterministic] Greeting? → canned welcome (no LLM)
         ├─ [deterministic] User pinned documents/emails? → answer from injected full text
         ├─ [deterministic] PROGRAMME trigger match? → Programme Tools (see §4) — NEVER goes to an agent
         ├─ [deterministic] Complex multi-step query? → ReAct Agent (or Hybrid Executor fallback)
         └─ classify_query (3 tiers):
             ├─ Tier 1 [deterministic regex]: THREAD / DRAFT / FILE_LIST / PROGRAMME shortcuts
             ├─ Tier 2 [LLM, lite model]: rich classifier (schema + document-topic context, learned few-shots)
             └─ Tier 3 [safety net]: heuristics → embedding similarity → mode default
                 ↓ QueryType
   DOCUMENT → Hybrid RAG   DATA → SQL Skills   TIMELINE → Chronology   THREAD → Correspondence
   DRAFT → Letter drafting  FILE_LIST → Document catalog  HYBRID → ReAct Agent  PROGRAMME → Programme Tools
                 ↓
         Answer + sources
                 ↓
     Trust Guard (see §6) → response contract → frontend render
```
Caption must note: low classifier confidence (<0.7) triggers fallback re-routing; every route's answer flows through the Trust Guard choke point in the orchestrator, and the guard itself decides to verify or skip (recording why).

---

## 3. AGENTS & SKILLS (capability cards — draw one card per skill with icon, inputs, what it CAN do)

### 3a. Hybrid RAG (DOCUMENT) — LLM + deterministic retrieval
Pipeline: jargon expansion → dense vector search (Pinecone prod / Qdrant alt, corpus-filtered) + BM25 lexical lane (chunk store) → Reciprocal Rank Fusion → lite-model rerank (30→15→6 chunks) → synthesis with citations (doc + page). Special path for named documents ("what does letter X say") with direct metadata fetch. Capabilities: cited Q&A over 7,600+ construction documents (letters, notices, reports, contracts), per-user corpus isolation (demo vs edinburgh).

### 3b. SQL / Data Skills (DATA) — LLM writes SQL, engine executes
DuckDB in-memory over parquet tables extracted from uploaded Excel (schemas: **equipment_log, manpower_production, ipc_sample**). Guard: SELECT-only, dangerous-pattern blocklist, self-correcting retry. Capabilities: equipment utilization by machine/block/month, manpower by trade/activity/peak-day, IPC quantities & cumulative progress %, cross-file unified-schema UNION queries, grouped/consolidated views, multi-step SQL chains (group→aggregate, outliers ±2σ, top-N compare), tiny results summarized by lite model.

### 3c. ReAct Agent (HYBRID / complex queries) — LLM tool loop, bounded
Iterative reason+act loop (max 5 iterations, 90s wall-clock, 8-LLM-call soft budget). Its 7 tools: `survey_documents` (metadata scan), `read_documents` (deep read named docs), `document_search` (semantic excerpts), `sql_query` (→ SQL skills), `timeline_query` (→ chronology), `file_list` (→ catalog), `finish`. Anti-loop guards: stuck-action detection, empty-observation cutoff, per-run read memory. Used for multi-part questions mixing documents + data.

### 3d. Query Planner / Hybrid Executor (legacy multi-step alternative)
LLM generates a ≤5-step plan (step types: sql, document, timeline, combine, filter); deterministic executor runs steps with dependency placeholders, fails fast, ends with a single COMBINE synthesis.

### 3e. Correspondence Skills (THREAD / DRAFT)
Thread reconstruction between parties from the notice graph; latest-unanswered detection; formal reply drafting (LLM) with instruction parsing (accept/reject/regarding...). Sources: notice metadata JSON + light correspondence graph + RAG bodies.

### 3f. Timeline / Chronology (TIMELINE)
Structured event chronology from the events store (delay/excuse/decision events with actor, dates, evidence), falling back to notice metadata. Deterministic ordering; LLM only phrases the narrative.

### 3g. Programme Tools (PROGRAMME) — 100% deterministic engines, LLM only narrates
Vendored Primavera P6 (XER) analysis engines behind a **Tool Registry** (positive/negative regex triggers + preconditions; LLM cannot invent tool names — whitelist executor):
- `programme.inventory` — catalogue XER revisions, auto baseline/current designation, missing-input caveats.
- `programme.dcma_14_point` — DCMA 14-point schedule health scorecard (logic, leads/lags, constraints, float, durations, CPLI, BEI) with affected activities.
- `programme.milestone_shift` — milestone forecast/actual drift across ≥2 revisions; fuzzy name-matches are NEVER auto-merged (analyst confirmation table).
Missing inputs → clarification message ("please upload an XER"), never a wrong tool. Causation/EOT/liability wording blocks the route (negative triggers) — those go to the Trust-Guarded document path.

---

## 4. WORKFLOWS & REPORTS (draw as pipeline diagram + report gallery)

**Workflow `report.preliminary_programme_analysis_pack`** (triggered by "generate preliminary programme analysis report"):
inventory → DCMA per revision (cap 6) → milestone shift (if ≥2 revisions, else caveat) → per-section LLM narrative → narrative guard per section → sections_json pack (DOCX/PDF assembly = next sprint).

**Producible outputs today (purple):**
- Chat answers with page-level citations; related-documents chronological tables; email thread views; drafted reply letters.
- SQL result tables with generated-SQL transparency.
- Programme artifacts (downloadable .xlsx): DCMA scorecard, programme inventory, milestone shift workbook; milestone shift SVG chart in chat.
- Preliminary Programme Analysis Pack (multi-section, per-section validation audit trail).
- Files inventory export (.xlsx). Admin: Trust Guard telemetry dashboard.

---

## 5. AGENT ↔ DATABASE ACCESS MATRIX (draw as matrix/heatmap — THE key governance view)

Data stores (grey), with tech:
| Store | Tech | Contents |
|---|---|---|
| Vector store | Pinecone (prod) / Qdrant (alt) | 768-dim chunk embeddings + metadata (corpus, file, page) |
| Chunk store | DuckDB `chunks.db` | full chunk text for BM25 lexical lane (135k chunks) |
| Parquet catalog | Parquet + DuckDB (in-memory) | extracted Excel tables (equipment/manpower/IPC), corpus-tagged |
| Document registry | JSON | per-file type/status/summary/topics/cluster |
| Notices + light graph | JSON | correspondence metadata (sender/recipient/subject/date/ref) |
| Events store | `events.db` | structured delay/excuse/decision chronology |
| Entity registry | DuckDB `entities.db` | corpus-scoped canonical named entities + aliases (44k edinburgh) |
| Interactions | `interactions.db` | query log, co-retrieval graph, **trust_guard_runs telemetry** |
| Programme files | `data/programmes/*.xer` | uploaded P6 exports (parsed on demand, never embedded) |
| Artifacts | `storage/artifacts/` | generated .xlsx reports |
| Learning stores | JSONL/JSON | feedback, golden set, learned routing/scope few-shots, teacher outputs |
| Conversations / Users | JSON / `users.db` | chat history; auth & quotas |

Access rows (✓R read, ✓W write):
- **Hybrid RAG**: vector ✓R, chunk ✓R, registry ✓R, entity — , parquet —
- **SQL Skills**: parquet ✓R (SELECT-only), catalog ✓R
- **ReAct Agent**: everything the 6 sub-tools reach (vector/chunk/registry/parquet/notices/events ✓R) — never writes
- **Correspondence/Timeline**: notices ✓R, light graph ✓R, events ✓R, vector ✓R
- **Programme Tools**: programme files ✓R, artifacts ✓W — deliberately NO access to vector/chunk/SQL stores
- **Trust Guard**: entity registry ✓R, chunk store ✓R (FTS fallback), interactions ✓W (telemetry), can re-drive Hybrid RAG once
- **Ingest pipeline** (upload): writes vector/chunk/registry/notices/parquet/programme files/entity registry
- **Learning loop** (flywheel/teacher): reads interactions+feedback, writes learned stores; feeds few-shots back into Router
Caption: corpus isolation (demo vs edinburgh) is enforced at the vector filter, catalog tag and entity registry; programme engines are sandboxed to XER files + artifact output only.

---

## 6. VALIDATION & TRUST LAYERS (draw as layered shield diagram)

Layer 0 — **Input guards**: SELECT-only SQL validator; prompt-injection hardening; upload-time XER parse validation (corrupt files never register).
Layer 1 — **Computation Guard** (green/amber, no LLM): pre-execution (file exists, is .xer, parses, has TASK table, enough revisions) and post-execution (JSON contract, caveat propagation, analyst-flag enforcement; violations downgrade status to partial — never silently upgraded).
Layer 2 — **Narrative Guard** (amber): deterministic rules — invented dates/metrics vs computed output, blame/entitlement/liability lexicon, "as-recorded"→"as-built" substitution, dropped caveats, partial-presented-as-complete, unconfirmed-match-claimed-confirmed — plus one lite-LLM groundedness check; max 1 rewrite, then deterministic fallback (data always ships).
Layer 3 — **Trust Guard** (amber, chat-wide choke point): risk classifier (keyword tiers; liability/EOT/causation = high) → corpus entity pre-check (registry-first, "did you mean Mott MacDonald?") → lite-LLM claim-by-claim verification against citations → substitution override (fake entities never silently answered as their nearest match) → approve / caveat / rewrite / refuse, with draft-then-verified UX streaming and per-query telemetry (coverage %, actions, latency) on the admin panel.
Layer 4 — **Audit trails**: every programme report carries `validation:{computation_guard, narrative_guard}`; every chat query logs a trust_guard_runs row (including skips with reasons); analyst-review flags surface as UI badges.

---

## 7. OUTPUT FORMAT

Produce: the 5 diagrams (SVG/Mermaid/HTML as your medium allows), each with legend + caption; a one-page "How a question becomes a validated answer" walkthrough tracing TWO example queries end-to-end: (a) "Show milestone movements" → programme path, (b) "Who caused the delay to Princes Street?" → Trust-Guarded RAG path. Keep all labels in English; keep component names EXACTLY as given.
