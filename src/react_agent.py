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
from typing import Any, Dict, List, Optional, Tuple

from .logger import logger
from . import llm_client
from .config import GEMINI_MODEL, REACT_MAX_ITERATIONS, MAX_LLM_CALLS_PER_QUERY
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
    "You are a methodical construction-domain research agent. You answer a user's "
    "question by choosing ONE tool at a time, observing the result, then deciding "
    "the next step. Use the fewest steps needed. When you have enough to answer "
    "fully, use the `finish` action. Output STRICT JSON only."
)

_TOOLS_DOC = """Available tools:
- document_search: semantic search over document text (contracts, letters, reports, notices). action_input = a focused search query string.
- sql_query: query structured project data tables (quantities, hours, workers, progress, cost). action_input = a natural-language data question.
- timeline_query: chronological sequence of notices / correspondence. action_input = a timeline question.
- file_list: list or count documents by topic. action_input = a topic or filter.
- finish: give the final answer. action_input = the complete answer text for the user.

Respond with JSON: {"thought": "<brief reasoning>", "action": "<tool name>", "action_input": "<string>"}"""


class ReActAgent:
    """Reuses the router's handlers as tools. Construct with the live router."""

    def __init__(self, router):
        self.router = router

    # ── public entry ────────────────────────────────────────────
    def run(self, query: str, doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        _emit("thinking", "planning the approach…")
        scratchpad: List[Dict[str, str]] = []
        sources: List[Dict[str, Any]] = []
        sql = result_data = result_columns = None
        final_answer: Optional[str] = None
        steps_taken = 0

        for i in range(max(1, REACT_MAX_ITERATIONS)):
            action = self._decide(query, scratchpad)
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

            obs, srcs, extra = self._run_tool(act, ainput, doc_ids)
            steps_taken += 1
            if srcs:
                sources.extend(srcs)
            if extra.get("sql"):
                sql = extra.get("sql")
                result_data = extra.get("result_data")
                result_columns = extra.get("result_columns")
            scratchpad.append({"action": act, "input": ainput, "observation": obs[:1500]})

            if self._budget_exhausted():
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
                "confidence": 1.0,
                "reasons": [f"ReAct agent ({steps_taken} tool step(s))"],
                "used_llm": True,
            },
        }

    # ── decide (one ReAct step) ─────────────────────────────────
    def _decide(self, query: str, scratchpad: List[Dict[str, str]]) -> Dict[str, Any]:
        history = ""
        for s in scratchpad:
            history += (f"\nAction: {s['action']}({s['input']})\n"
                        f"Observation: {s['observation']}\n")
        prompt = (
            f"{_TOOLS_DOC}\n\n"
            f"User question:\n{query}\n\n"
            f"History so far:{history or ' (none yet)'}\n\n"
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
    def _run_tool(self, action: str, tool_input: str, doc_ids: Optional[List[str]]
                  ) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
        q = tool_input.strip() or ""
        try:
            if action == "document_search":
                _emit("searching", "searching documents…", q[:80])
                r = self.router.document_rag.query(q, doc_ids=doc_ids, synthesize=False)
                srcs = [{**s, "source_type": "document"} for s in r.get("sources", [])]
                return self._excerpts(r.get("sources", [])) or "(no matching passages)", srcs, {}

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

            if action == "timeline_query":
                _emit("searching", "searching the timeline…", q[:80])
                r = self.router._handle_timeline_query(q)
                return (r.get("answer") or "(no timeline result)"), r.get("sources", []), {}

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
            )
            _record(resp)
            return resp.text.strip()
        except Exception as e:
            logger.error(f"[ReActAgent] final synthesis failed: {e}")
            # Last-resort: stitch the raw observations so the answer never drops.
            return "\n\n".join(s["observation"] for s in scratchpad if s.get("observation"))

    # ── helpers ─────────────────────────────────────────────────
    @staticmethod
    def _budget_exhausted() -> bool:
        try:
            from .telemetry import get_current_trace
            tr = get_current_trace()
            if tr is not None:
                return max(0, tr.llm_calls - tr.cache_hits) >= MAX_LLM_CALLS_PER_QUERY
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
