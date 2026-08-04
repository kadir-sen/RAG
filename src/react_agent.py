"""Bounded ReAct tool-using agent for complex multi-step queries.

The router dispatches genuinely complex / multi-question queries here (gated by
ENABLE_REACT_AGENT). Unlike the fixed plan-then-execute planner, the agent
decides its next tool one step at a time from what it has seen so far, then
synthesizes a final answer. It is deliberately *bounded*:

  * a hard iteration cap (REACT_MAX_ITERATIONS),
  * the llm_client soft per-query budget (MAX_LLM_CALLS_PER_QUERY) as backstop,
  * fail-soft: on budget/parse exhaustion it synthesizes from what it has rather
    than dropping the answer.

There is no native function-calling in llm_client, so the loop is a prompt-based
JSON-action protocol (generate_json). Tools reuse the router's existing handlers;
the document tool is retrieve-only so per-step synthesis isn't paid for twice
(the agent does the single final synthesis).

Every step publishes a live activity event (report_step) so the UI feed shows
the agent thinking / reading / analysing in real time.
"""

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from .logger import logger
from . import llm_client
from .config import (GEMINI_MODEL, REACT_MAX_ITERATIONS, MAX_LLM_CALLS_PER_QUERY,
                     REACT_TIME_BUDGET_SEC)
from .prompt_security import build_system_prompt


def _emit(kind: str, label: str, detail: str = "") -> None:
    try:
        from backend.tasks.query_progress import report_step
        report_step(kind, label, detail)
    except Exception:
        pass


def _record(resp) -> None:
    """Record an agent LLM call into the per-request trace (budget + cost)."""
    try:
        from .telemetry import get_current_trace
        tr = get_current_trace()
        if tr is not None:
            tr.record_llm_call(resp.usage)
    except Exception:
        pass


_DECIDE_SYSTEM = (
    "You are a methodical construction/legal-inquiry research agent. You answer a "
    "user's question by choosing ONE tool at a time, observing the result, then "
    "deciding the next step. Work METADATA-FIRST: use `survey_documents` to see "
    "WHICH documents exist on a topic (cheap, no full text), judge relevance from "
    "each document's one-line gist, then `read_documents` ONLY the few whose gist "
    "matches. NEVER read a document already listed under 'Already read'. Prefer a "
    "survey + a couple of targeted reads over many broad searches. Use the fewest "
    "steps needed; when you can answer fully, use `finish`. Output STRICT JSON only."
)

_TOOLS_DOC = """Available tools (prefer survey → read):
- survey_documents: METADATA-ONLY scan — returns a numbered list of documents about a topic with a one-line gist each (no full text). Use this FIRST to find which documents are relevant. action_input = a topic/keywords string.
- read_documents: deep-read the full text of specific documents you picked from a survey. action_input = comma-separated file names from the survey list.
- document_search: broad semantic search that returns text excerpts directly (use only when a survey is not enough). action_input = a focused search query.
- sql_query: query structured project data tables (quantities, hours, costs). action_input = a natural-language data question.
- file_list: list or count documents by topic. action_input = a topic or filter.
- finish: give the final answer. action_input = the complete answer text for the user.

Respond with JSON: {"thought": "<brief reasoning>", "action": "<tool name>", "action_input": "<string>"}"""


class ReActAgent:
    """Reuses the router's handlers as tools. Construct with the live router."""

    def __init__(self, router):
        self.router = router

    # ── public entry ────────────────────────────────────────────
    def run(self, query: str, doc_ids: Optional[List[str]] = None,
            max_iterations: Optional[int] = None,
            time_budget_sec: Optional[float] = None,
            llm_call_budget: Optional[int] = None) -> Dict[str, Any]:
        """Run the bounded loop. The three optional budgets let a caller run a
        cheaper or deeper variant — the router's negative-answer escalation pass
        needs more LLM headroom than the module defaults, because by the time it
        starts, the shallow pass has already spent most of the per-query budget.
        Passing them as arguments rather than reading config keeps the defaults
        (and every existing caller) untouched."""
        max_steps = max(1, int(REACT_MAX_ITERATIONS if max_iterations is None
                               else max_iterations))
        time_budget = float(REACT_TIME_BUDGET_SEC if time_budget_sec is None
                            else time_budget_sec)
        _emit("thinking", "planning the approach…")
        scratchpad: List[Dict[str, str]] = []
        sources: List[Dict[str, Any]] = []
        sql = result_data = result_columns = None
        final_answer: Optional[str] = None
        steps_taken = 0
        # Per-run read-memory (request-local, NOT instance state — the agent is a
        # singleton). (file_name, page) keys we've already surfaced, so the same
        # document is never read twice across iterations.
        seen: set = set()
        seen_files: List[str] = []
        survey_cache: Dict[str, List[Dict[str, Any]]] = {}  # file_name → already-retrieved chunks
        corpus_map = self._corpus_map()
        tools_used: List[str] = []
        last_step: Optional[Tuple[str, str]] = None  # (action, input) for stuck-loop detection
        empty_obs_streak = 0
        t_start = time.monotonic()

        for i in range(max_steps):
            # Wall-clock guard: don't start another step once over budget — bounds
            # rare provider-contention spikes. We still synthesize what we have.
            if i > 0 and (time.monotonic() - t_start) > time_budget:
                logger.info("[ReActAgent] time budget exceeded — synthesizing from current observations")
                break
            action = self._decide(query, scratchpad, corpus_map, seen_files)
            thought = (action.get("thought") or "").strip()
            act = (action.get("action") or "").strip().lower()
            ainput = action.get("action_input") or ""
            if not isinstance(ainput, str):
                ainput = json.dumps(ainput, ensure_ascii=False)

            if thought:
                _emit("thinking", thought[:200])

            if act in ("finish", "final", "answer", "done"):
                final_answer = ainput.strip()
                break

            # Stuck-loop guard: the LLM repeating the exact same (action,input) makes
            # no new progress — stop and synthesize from what we have.
            if last_step == (act, ainput):
                logger.info("[ReActAgent] repeated identical action — synthesizing early")
                break
            last_step = (act, ainput)

            obs, srcs, extra = self._run_tool(act, ainput, doc_ids, seen, survey_cache)
            tools_used.append(act)
            steps_taken += 1
            # Two consecutive empty/no-result observations → no traction, stop.
            if obs.startswith("(no ") or obs.startswith("(tool "):
                empty_obs_streak += 1
                if empty_obs_streak >= 2:
                    logger.info("[ReActAgent] two empty observations — synthesizing early")
                    break
            else:
                empty_obs_streak = 0
            if srcs:
                sources.extend(srcs)
                for s in srcs:
                    fn = s.get("file_name")
                    if fn and fn not in seen_files:
                        seen_files.append(fn)
            if extra.get("sql"):
                sql = extra.get("sql")
                result_data = extra.get("result_data")
                result_columns = extra.get("result_columns")
            scratchpad.append({"action": act, "input": ainput, "observation": obs[:1500]})

            if self._budget_exhausted(llm_call_budget):
                logger.info("[ReActAgent] hard budget reached — synthesizing from current observations")
                break

        if final_answer is None or not final_answer:
            final_answer = self._final_synthesis(query, scratchpad)

        return {
            "query": query,
            "query_type": "hybrid",
            "answer": final_answer,
            "sources": self._dedupe_sources(sources),
            "sql": sql,
            "result_data": result_data,
            "result_columns": result_columns,
            "routing": {
                "decision": "agent",
                "route": "AGENT",
                "tools_used": tools_used,
                "confidence": 1.0,
                "reasons": [f"ReAct agent ({steps_taken} tool step(s): {', '.join(tools_used) or 'none'})"],
                "used_llm": True,
            },
        }

    # ── decide (one ReAct step) ─────────────────────────────────
    def _decide(self, query: str, scratchpad: List[Dict[str, str]],
                corpus_map: str = "", seen_files: Optional[List[str]] = None) -> Dict[str, Any]:
        history = ""
        for s in scratchpad:
            history += (f"\nAction: {s['action']}({s['input']})\n"
                        f"Observation: {s['observation']}\n")
        already = ""
        if seen_files:
            already = "\nAlready read (do NOT read these again): " + ", ".join(seen_files[:30]) + "\n"
        prompt = (
            f"{_TOOLS_DOC}\n\n"
            f"{corpus_map}"
            f"User question:\n{query}\n\n"
            f"History so far:{history or ' (none yet)'}\n"
            f"{already}\n"
            "Decide the next single action as strict JSON."
        )
        try:
            resp = llm_client.generate_json(
                prompt, system=build_system_prompt(_DECIDE_SYSTEM), model=GEMINI_MODEL,
            )
            _record(resp)
            parsed = resp.raw if isinstance(resp.raw, dict) else json.loads(resp.text)
            return parsed if isinstance(parsed, dict) else {"action": "finish", "action_input": ""}
        except Exception as e:
            logger.warning(f"[ReActAgent] decide failed → finishing: {e}")
            return {"action": "finish", "action_input": ""}

    # ── tool dispatch (reuse router handlers) ───────────────────
    def _run_tool(self, action: str, tool_input: str, doc_ids: Optional[List[str]],
                  seen: set, survey_cache: Dict[str, List[Dict[str, Any]]]
                  ) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
        q = tool_input.strip() or ""
        try:
            if action in ("survey_documents", "survey"):
                _emit("searching", "surveying documents…", q[:80])
                rows, chunks_by_file = self._metadata_survey(q, doc_ids)
                survey_cache.update(chunks_by_file)  # stash chunks for read_documents
                if not rows:
                    return "(no documents found on this topic)", [], {}
                lines = ["Documents found (metadata only — read_documents the relevant file names):"]
                for i, m in enumerate(rows, 1):
                    tag = f" [{m['doc_type']}]" if m.get("doc_type") else ""
                    dt = f" ({m['date']})" if m.get("date") else ""
                    lines.append(f"{i}. {m['file_name']}{tag}{dt} — {m['gist']}")
                return "\n".join(lines), [], {}  # survey adds NO sources (no full read yet)

            if action in ("read_documents", "read_document", "read"):
                names = [n.strip() for n in q.replace("\n", ",").split(",") if n.strip()]
                _emit("reading", f"reading {len(names)} document(s)…", ", ".join(names[:3])[:80])
                # Serve from the survey cache (already-retrieved chunks) — avoids a
                # scoped re-query that returns nothing on the edinburgh/Qdrant path.
                picked: List[Dict[str, Any]] = []
                for n in names:
                    for fn, chunks in survey_cache.items():
                        if n == fn or n in fn or fn in n:
                            picked.extend(chunks)
                if not picked and names:  # not surveyed → best-effort scoped fetch
                    try:
                        r = self.router.document_rag.query(
                            names[0], file_names=names, doc_ids=doc_ids, synthesize=False)
                        picked = r.get("sources", [])
                    except Exception:
                        picked = []
                fresh = self._filter_new(picked, seen)
                srcs = [{**s, "source_type": "document"} for s in fresh]
                return self._excerpts(fresh) or "(no new text in those documents)", srcs, {}

            if action == "document_search":
                _emit("searching", "searching documents…", q[:80])
                r = self.router.document_rag.query(q, doc_ids=doc_ids, synthesize=False)
                fresh = self._filter_new(r.get("sources", []), seen)
                srcs = [{**s, "source_type": "document"} for s in fresh]
                return self._excerpts(fresh) or "(no new matching passages)", srcs, {}

            if action == "sql_query":
                _emit("tool", "querying project data…", q[:80])
                r = self.router._handle_data_query(q, doc_ids=doc_ids)
                obs = r.get("answer") or self._table_preview(r)
                srcs = [{**s, "source_type": "data"} for s in r.get("sources", [])]
                return obs or "(no rows)", srcs, {
                    "sql": r.get("sql"),
                    "result_data": r.get("result_data"),
                    "result_columns": r.get("result_columns"),
                }

            if action == "file_list":
                _emit("tool", "listing documents…", q[:80])
                r = self.router._handle_file_list_query(q, doc_ids=doc_ids)
                return (r.get("answer") or "(no documents)"), r.get("sources", []), {}

            return f"(unknown tool: {action})", [], {}
        except Exception as e:
            logger.warning(f"[ReActAgent] tool '{action}' failed: {e}")
            return f"(tool {action} error: {e})", [], {}

    # ── final synthesis (single LLM call over observations) ─────
    def _final_synthesis(self, query: str, scratchpad: List[Dict[str, str]]) -> str:
        _emit("analysing", "composing the answer…")
        context = ""
        for s in scratchpad:
            context += f"\n[{s['action']}] {s['observation']}\n"
        if not context.strip():
            return ("I couldn't gather enough information to answer that. "
                    "Please try rephrasing the question.")
        prompt = (
            f"Answer the user's question using ONLY the findings below. Be specific, "
            f"cite document names where relevant, and say plainly if something is "
            f"missing.\n\nQuestion: {query}\n\nFindings:{context}"
        )
        try:
            resp = llm_client.generate_text(
                prompt,
                system=build_system_prompt("You synthesize a final answer from multi-step findings."),
                max_tokens=2048,
                task_type="answer_synthesis",
            )
            _record(resp)
            return resp.text.strip()
        except Exception as e:
            logger.error(f"[ReActAgent] final synthesis failed: {e}")
            # Last-resort: stitch the raw observations so the answer never drops.
            return "\n\n".join(s["observation"] for s in scratchpad if s.get("observation"))

    # ── metadata-first helpers ──────────────────────────────────
    @staticmethod
    def _corpus_map() -> str:
        """Compact corpus topic map (cluster labels + counts) so the agent knows
        what topic-clusters exist before searching. Reuses the document clusterer
        (wires the otherwise-dormant cluster layer). Empty when unavailable."""
        try:
            from .document_clusterer import get_clusterer
            clusters = get_clusterer().list_clusters() or []
            parts = []
            for c in clusters[:12]:
                label = getattr(c, "label", None) if not isinstance(c, dict) else c.get("label")
                cnt = getattr(c, "doc_count", None) if not isinstance(c, dict) else c.get("doc_count")
                if label:
                    parts.append(f"{label} ({cnt})" if cnt else str(label))
            if parts:
                return "Corpus topic clusters: " + "; ".join(parts) + "\n\n"
        except Exception:
            pass
        return ""

    def _metadata_survey(self, topic: str, doc_ids: Optional[List[str]],
                         limit: int = 12) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Doc-level metadata list for a topic WITHOUT returning full chunk text.
        Cheap retrieve-only (no LLM) finds candidate docs; registry enrichment
        (llm_summary/topics/cluster) gives the gist. Falls back to the retrieval
        highlight when a doc has no enrichment (e.g. the bulk edinburgh corpus).

        Returns (metadata_rows, chunks_by_file): the chunks already retrieved are
        stashed by file_name so read_documents can serve them directly instead of
        re-retrieving (a scoped re-query returns nothing on the edinburgh/Qdrant
        path where dense=0 and a file_name filter matches no payload)."""
        try:
            r = self.router.document_rag.query(
                topic, top_k=max(limit * 2, 20), doc_ids=doc_ids, synthesize=False)
        except Exception as e:
            logger.warning(f"[ReActAgent] survey retrieval failed: {e}")
            return [], {}
        reg = None
        try:
            from .document_registry import get_document_registry
            reg = get_document_registry()
        except Exception:
            reg = None
        out: List[Dict[str, Any]] = []
        chunks_by_file: Dict[str, List[Dict[str, Any]]] = {}
        for s in r.get("sources", []):
            fn = s.get("file_name")
            if not fn:
                continue
            chunks_by_file.setdefault(fn, []).append(s)
            if fn in chunks_by_file and len(chunks_by_file[fn]) > 1:
                continue  # already added this file to the metadata list
            rec = None
            if reg and s.get("doc_id"):
                try:
                    rec = reg.get(s.get("doc_id"))
                except Exception:
                    rec = None
            summary = getattr(rec, "llm_summary", "") if rec else ""
            topics = getattr(rec, "llm_topics", None) if rec else None
            cluster = getattr(rec, "cluster_label", "") if rec else ""
            doc_type = (getattr(rec, "file_type", "") if rec else "") or s.get("doc_type", "")
            gist = (summary or s.get("highlight_text") or (s.get("text_snippet") or "")[:160]).strip()
            if topics:
                gist = f"{gist} · topics: {', '.join(topics[:4])}"
            out.append({"file_name": fn, "doc_type": doc_type, "date": s.get("date", ""),
                        "cluster": cluster, "gist": gist[:220] or "(no preview)"})
        return out[:limit], chunks_by_file

    @staticmethod
    def _filter_new(sources: List[Dict[str, Any]], seen: set) -> List[Dict[str, Any]]:
        """Read-memory: drop (file_name, page) pairs already surfaced this run so
        the agent never re-reads the same document across iterations."""
        fresh = []
        for s in sources or []:
            key = (s.get("file_name"), s.get("page_number"))
            if key in seen:
                continue
            seen.add(key)
            fresh.append(s)
        return fresh

    # ── helpers ─────────────────────────────────────────────────
    @staticmethod
    def _budget_exhausted(limit: Optional[int] = None) -> bool:
        """Counts the TRACE's calls, not this run's — so an escalated second pass
        inherits everything the first pass already spent. That is why the caller
        can raise the ceiling: with the default 8, an escalation starting at ~5
        would get two or three steps and stop."""
        cap = MAX_LLM_CALLS_PER_QUERY if limit is None else int(limit)
        try:
            from .telemetry import get_current_trace
            tr = get_current_trace()
            if tr is not None:
                return max(0, tr.llm_calls - tr.cache_hits) >= cap
        except Exception:
            pass
        return False

    @staticmethod
    def _excerpts(sources: List[Dict[str, Any]], max_chunks: int = 6) -> str:
        parts = []
        for i, s in enumerate((sources or [])[:max_chunks], 1):
            text = (s.get("text_snippet") or s.get("highlight_text") or "").strip()
            if not text:
                continue
            parts.append(f"[{i}] {s.get('file_name', 'Unknown')} "
                         f"p.{s.get('page_number', '?')}: {text}")
        return "\n\n".join(parts)

    @staticmethod
    def _table_preview(r: Dict[str, Any], max_rows: int = 20) -> str:
        cols = r.get("result_columns") or []
        rows = r.get("result_data") or []
        if not (cols and rows):
            return ""
        lines = [" | ".join(str(c) for c in cols)]
        for row in rows[:max_rows]:
            if isinstance(row, dict):
                lines.append(" | ".join(str(row.get(c, "")) for c in cols))
            elif isinstance(row, (list, tuple)):
                lines.append(" | ".join(str(v) for v in row))
            else:
                lines.append(str(row))
        if len(rows) > max_rows:
            lines.append(f"... (+{len(rows) - max_rows} more rows)")
        return "\n".join(lines)

    @staticmethod
    def _dedupe_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out, seen = [], set()
        for s in sources:
            key = (s.get("file_name"), s.get("page_number"))
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out
