# COAir LLM Reliability, Fallback and Cost Control — Implementation Report
*Date: 2026-07-08 · Scope delivered: gateway core + Gemini-internal fallback + error sanitization + per-call usage log + the 5 evaluation fixes. DeepSeek/Claude registered but disabled. Per-$ budgets / admin dashboard / live cross-provider / full model-comparison harness: designed-in seams, not built. No commit.*

## 1. Current LLM call-site inventory (pre-change)
~35 call sites, all funneling through `src/llm_client.py` (`generate_text` :363 / `generate_json` :591), all defaulting `provider="gemini"`. Highest-risk (leaked raw provider text into user answers via broad `except Exception`): `data_analyzer_sql.py` :2299/:2406/:2432 (+source cells :2300/:2407), `hybrid_executor.py` :399/:475, and two **gateway-bypassing raw `create_llm()+llm.complete()`** sites in `document_rag.py` :1559/:1876 (no cache/retry/usage/quota). Full table in the session exploration; not reproduced here.

## 2. Failure modes found (root causes)
- `llm_client.py:588` wraps errors as `RuntimeError("LLM call failed (gemini): <raw 429 + billing URL>")` — the leak source.
- Rate-limit branch (:576) only recognized `anthropic.RateLimitError` → **Gemini/OpenAI 429 unclassified**, no cross-provider fallback existed.
- `LLM_TIMEOUT_SECONDS` (config :165) defined but **never applied**.
- SQL/hybrid `except Exception` swallowed even `BudgetExceededError`/`UserQuotaExceededError` into answer text (second latent leak — bypassed the 402 handler).
- Router safety-net: schema-semantic DATA gate (:786) ran BEFORE the DOCUMENT default → causation/EOT with data vocab force-routed to SQL under classifier outage.
- Chronology scope regex `$`-anchored greedy → swallowed trailing instructions; no noun-first/possessive support.
- Trust-guard fail-open set `sufficiency_label="unverified"` but `_build_trust_guard` returned `None` on any skip → high-risk answers shipped badge-less.

## 3. Model registry (`src/llm/registry.py`)
`ModelSpec(model_id, provider, provider_model_name, supports_json, max_output_tokens, input_cost, output_cost, default_timeout_s, enabled)` — concrete model strings live ONLY here (unit-test enforces zero literals elsewhere in `src/llm/`, cost pulled from `config.LLM_PRICING`). Registered: gemini_flash/gemini_flash_lite (enabled), gemini_pro (env-gated), **deepseek_chat + claude_sonnet (enabled=False)** — the cross-provider plug-in. `MODEL_GROUPS`: cheap_json/cheap_classifier→[flash_lite], standard_synthesis→[flash, flash_lite], standard_reasoning→[flash], premium_review→[pro→flash].

## 4. Task-to-model policy (`src/llm/policy.py`)
15 `TaskPolicy` rows, each `{model_group, fallback_group, json_mode, fail_open, deterministic_fallback, max_output_tokens, timeout_s, retries, fallback_message}`. Owner rules encoded: `trust_guard_verification.fail_open=True` ("...marked unverified — analyst review recommended"), `final_claim_section_review.fail_open=False` (flagged for review), `sql_generation.fail_open=False + deterministic_fallback`, guards never downgraded to a cheaper reasoning tier. `select(task)` → ordered enabled-only ModelSpec chain.

## 5. Fallback chains (`src/llm/gateway.py`)
`gateway.complete(task_type, prompt, *, system, deterministic_fn, cache_key) -> GatewayResult{text, raw, usage, model_used, fallback_level, status, degraded_message, error_type}`. Walks the chain; per `errors.py`: BILLING_QUOTA/RATE_LIMIT → **switch tier immediately, no same-model retry**; TIMEOUT/MALFORMED_JSON → one same-model retry then advance; PROVIDER_DOWN → advance. Chain exhausted → deterministic_fn (fallback_level=-1) → fail_open (empty text + degraded_message) or fail_closed (sanitized text). **Enforces the previously-dead `LLM_TIMEOUT_SECONDS`** via a thread+future timeout. Wraps (does not replace) `llm_client` — caching/quota/attribution/soft-cap intact.

## 6. Error taxonomy + sanitization (`src/llm/errors.py`)
`classify_error(exc)`: (1) `Budget/UserQuotaExceededError` → **re-raise** (reaches 402); (2) provider SDK isinstance; (3) regex on wrapped message — **the critical addition that catches Gemini/OpenAI 429s** the old code missed (`429|RESOURCE_EXHAUSTED|quota`→RATE_LIMIT, `billing|403|PERMISSION_DENIED|generativelanguage.googleapis.com`→BILLING_QUOTA, timeout/provider-down/context/content/malformed-json). `sanitize()` returns the policy's user-safe message, **never `str(exc)`**. Guard test: 9 error types × 15 tasks contain none of {429, googleapis, quota, billing, RESOURCE_EXHAUSTED, http, stack}.

## 7. Error-sanitization changes (Fix 1 + 4)
`data_analyzer_sql.py`: added `SQL_UNAVAILABLE_MSG` + `_reraise_budget()`; all three except sites (:2299/:2406/:2432) now `_reraise_budget(e)` FIRST (budget→402), then emit the safe message with `str(e)` stripped from answer AND source cells. `hybrid_executor.py` :399/:475 same pattern. `document_rag.py` :1559/:1876 raw `.complete()` bypasses → `gateway.complete("rag_answer_synthesis")` (gains cache/retry/usage/quota/sanitization). **Live-proven:** "What equipment has the highest utilization?" under dead quota → `"SQL analysis is temporarily unavailable; please narrow the question or try again shortly."` (was `"Error executing query: ...429 You exceeded your quota... https://ai.google.dev"`).

## 8. Degraded-mode routing (Fix 2, `src/router.py`)
New `_classify_high_risk_document(query_lower)` reuses `trust_guard._HIGH_RISK_RE` + `programme_tools.SHARED_NEGATIVE_TRIGGERS` (no new lexicon), inserted in `_classify_safety_net` **before** the schema-semantic DATA gate. Runs ONLY on classifier outage. "Who caused the delay?"/"entitled to EOT?"/"who is responsible for the delay days?" → DOCUMENT; genuine "peak manpower day"/"total workers in June"/"sum of concrete m3" → still DATA. Unit-tested both directions.

## 9. Chronology scope robustness (Fix 3, `src/delay_reports/scope.py`)
Added `_NOUN_FIRST_RE` (noun-first/possessive/"X delay chronology"); `_strip_trailing_instructions()` drops trailing imperative sentences; `_clean_title` now caps length (>60 char/>8 token), rejects instruction-verb captures, splits on sentence boundary. 9/9 phrasings resolve correctly incl. "the Delayed Blockwork chronology", "Delayed Blockwork's chronology", "chronology for X. Use numbered paragraphs..." → "X"; generic → clarification.

## 10. Trust-guard fail-open UX (Fix 5, `response_builder.py`)
`_build_trust_guard`: a verdict skipped with `skipped_reason="error"` on medium/high risk now surfaces a `TrustGuardInfo(sufficiency_label="unverified", analyst_review_required=True, caveat="could not be automatically verified — analyst review recommended")` instead of `None`. Benign skips (low risk / disabled / route_excluded) still → None. Unit-tested.

## 11. Usage & token tracking (`src/llm/usage.py`)
New DuckDB `llm_usage_events` table (interaction_log idiom): per-call `{run_id, username, task_type, provider, model_id, model_group, fallback_level, input/output_tokens, est_cost_usd, latency_ms, status, error_type, customer_id, project_id}`. `customer_id/project_id` nullable = the per-$ budget / cost-dashboard plug-in seam. Gateway logs one row per invocation + still calls `trace.record_llm_call` (no regression). `usage_stats(days)` aggregates for the future admin panel.

## 12. Tests run
- **`tests/test_llm_gateway.py` (24)**: selection/chain-order, disabled-model filter, no-hardcoded-model grep, 8 error-classification cases, budget/quota re-raise, sanitize guard (9×15 no forbidden tokens), fallback (rate-limit no-retry, timeout one-retry, billing advance, deterministic fallback, fail-open vs fail-closed), usage logging.
- **`tests/test_llm_reliability_fixes.py` (23)**: SQL leak → safe message + no error in sources + budget re-raised; degraded routing matrix; chronology scope matrix (9 cases + no instruction contamination); trust-guard fail-open badge + benign-skip-no-badge.
- **Full suite: 909 passed** (+47 new), same 8 pre-existing failures (session-token/chunk-store/jargon-routing, unrelated). `tsc --noEmit` clean.
- **Live: raw-429 leak dead** (sanitized SQL message under quota outage); high-risk causation did not land in DATA.

## 13. Recommended default models
Keep gemini_flash (standard synthesis/reasoning) + gemini_flash_lite (classification/JSON/guards) — current, cheapest viable. Enable gemini_pro for `final_claim_section_review` only when a real reviewer tier is wanted (env `ENABLE_GEMINI_PRO`). DeepSeek/Claude: register live in the next sprint after the comparison harness runs.

## 14. Premium escalation policy
Only `final_claim_section_review` uses `premium_review` (fail_closed). No other task escalates by default. When per-$ budgets land, premium escalation should require explicit config or admin confirmation (schema seam present).

## 15. Risks / watch-items
- SQL `_generate_sql` itself is NOT yet routed through the gateway — the leak was killed at the except-block (Fix 1), which is sufficient and live-proven; full gateway migration of `_generate_sql` (for usage logging + tier fallback on SQL) is the top opportunistic item.
- Timeout enforcement is new behavior (30s never fired before) — watch `fallback_level` spikes.
- `document_rag` gateway migration newly subjects those two sites to `enforce_budget`/quota — intended; watch for unexpected mid-RAG 402.
- Non-Anthropic 429 recognition rests entirely on `errors.py` regex — keep the pattern list current with real Google/OpenAI error text.
- `app.py:3302` dead `get_llm_client` import and `generate_text_dual` (zero callers) left untouched as documented dead code.

## 16. Next sprint implementation order
1. Migrate `_generate_sql`/`_retry_sql_generation`/`_lazy_summary` through the gateway (usage + tier fallback on SQL).
2. Opportunistically migrate remaining fail-open sites (classify/scope/verify/rerank/guards/react/narrative) for usage capture.
3. Per-$ budgets on `llm_usage_events` (customer/project dims present) + downgrade/block policy + admin cost dashboard.
4. Enable DeepSeek (OpenAI-compatible) + Claude in registry; build the live model-comparison harness (Phase 7) and re-pick defaults.
5. Route the trust-guard verifier itself through the gateway (badge already surfaces; this adds sanitization + fallback tier to verification).

## 17. Verdict
The five evaluation blockers are fixed and the reliability spine (gateway, task-based selection, Gemini-internal fallback, error sanitization, per-call usage ledger) is in place and unit- + live-proven. **No raw provider error can now reach chat on the migrated paths; the LLM outage the evaluation hit now degrades cleanly instead of leaking.** The system is materially closer to pilot-ready; the remaining work is breadth (migrate the rest of the call sites) and the deferred budget/multi-provider layer, both designed-in.
