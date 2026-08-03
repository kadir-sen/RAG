"""
Query Planner - Decomposes complex queries into executable sub-steps.
Handles multi-step analytics (group by + aggregate + filter), cross-source
queries, and chronological reasoning.

Hardening features:
  - Fail-fast: abort plan on step error, return structured PlanExecutionError
  - MAX_PLAN_STEPS guardrail
  - All LLM calls via llm_client (cached, tracked)
  - Prompt injection hardening via prompt_security
  - Per-step telemetry
"""
import json
import re
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

from .config import MAX_PLAN_STEPS
from .types import (
    StepError, PlanExecutionError,
)
from .logger import logger


# Re-export for backwards compatibility with tests and other modules
class StepType(Enum):
    """Types of executable steps."""
    SQL = "sql"
    DOCUMENT = "document"
    COMBINE = "combine"
    FILTER = "filter"


@dataclass
class PlanStep:
    """A single step in the execution plan."""
    step_id: int
    step_type: str
    description: str
    instruction: str
    depends_on: List[int] = field(default_factory=list)
    result: Optional[Any] = None
    status: str = "pending"
    error: Optional[str] = None


@dataclass
class QueryPlan:
    """A plan containing ordered steps to answer a query."""
    original_query: str
    steps: List[PlanStep] = field(default_factory=list)
    is_simple: bool = True
    plan_rationale: str = ""


# Multi-step detection — shared by the planner and the router so they agree on
# which queries deserve decomposition. Conservative: a false negative just gives
# a single-step plan; a false positive only costs one extra LLM planning call.
_SEQUENTIAL_INDICATORS = (
    ' then ', ' and then ', ' after that ', ' next ',
    'month-over-month', 'year-over-year',
)
_COMPOUND_INDICATORS = (
    ' and also ', ', also ', ' as well as ', 'additionally',
    ' ayrıca ', ' ve ayrıca ', 'bir de ', ' bunun yanında ',
)


def is_multi_step_query(query: str) -> bool:
    """True when a query stacks multiple questions / sequential steps and should
    be decomposed (sequential chains, explicit compound conjunctions, 'hem ... hem',
    or two or more question marks)."""
    q = (query or "").lower()
    # The orchestrator augments queries with conversation history. Evaluate ONLY
    # the current turn so historical "?"/conjunctions don't falsely trigger.
    if "current question:" in q:
        q = q.split("current question:")[-1]
    padded = f" {q} "  # so leading/trailing tokens match the space-delimited markers
    if any(ind in padded for ind in _SEQUENTIAL_INDICATORS):
        return True
    if any(ind in padded for ind in _COMPOUND_INDICATORS):
        return True
    if padded.count(" hem ") >= 2:  # Turkish "hem X hem Y"
        return True
    if q.count("?") >= 2:
        return True
    return False


class QueryPlanner:
    """
    Decomposes complex queries into executable sub-steps.
    Uses llm_client for all LLM calls with caching and cost tracking.
    Enforces MAX_PLAN_STEPS guardrail.
    """

    PLAN_PROMPT = (
        "You are a query planner for a construction project intelligence system.\n"
        "The system has tabular data (Excel-based daily logs, progress certificates) "
        "and document data (contracts, letters, reports in PDF).\n\n"
        "Given a user query, determine if it needs one or multiple steps.\n\n"
        "AVAILABLE STEP TYPES:\n"
        "- sql: Query tabular data (equipment hours, manpower counts, production output, "
        "IPC progress, BOQ quantities). Use for ANY numerical, analytical, or listing question.\n"
        "- document: Search PDF/contract documents. Use for reading contract clauses, terms, "
        "specifications, prose, AND for a SINGLE specific letter/notice — 'who sent X', "
        "'what date is X', 'what does X say'. This is the reliable default for document content.\n"
        "- combine: Synthesize results from previous steps into a final answer.\n\n"
        "AVAILABLE DATA TABLES (reliable, schema-matched — the ONLY valid sql sources):\n{table_context}\n\n"
        "AVAILABLE DOCUMENTS (topics + summaries):\n{doc_context}\n\n"
        "CONTENT-AWARE ROUTING (decide each sub-question's type by what the ANSWER is):\n"
        "- A person/sender/recipient, a date of a SPECIFIC letter/notice, a clause/term, "
        "'who sent X', 'what does X say', a single delay/EOT/RFI notice → document "
        "(the answer is document PROSE), NOT sql.\n"
        "- A count, sum, average, hours, headcount, %, BOQ/IPC amount over a DATA TABLE above "
        "→ sql.\n"
        "- Only emit a 'sql' step when a table in AVAILABLE DATA TABLES genuinely holds the "
        "numbers. Never run sql against a document just because its title resembles a table name "
        "— prose PDFs are NOT data tables and have been excluded from the list above.\n\n"
        "CONSTRUCTION QUERY PATTERNS:\n"
        "- 'Compare equipment and manpower for Block A' → sql(equipment) + sql(manpower) + combine\n"
        "- 'Does actual progress match the contract?' → sql(IPC progress) + document(contract terms) + combine\n"
        "- 'Which trade has best productivity?' → sql(manpower: output/workers) — single step\n"
        "- 'Total hours by equipment type' → sql(equipment) — single step\n"
        "- 'What does the contract say about delays?' → document — single step\n"
        "COMPOUND / STACKED QUESTIONS (split each part into its own step, then combine):\n"
        "- 'What were the crane hours, and also which trades were on site?' → "
        "sql(equipment hours) + sql(manpower trades) + combine\n"
        "- 'Summarize the delay notice and additionally show the actual progress %' → "
        "document(delay notice) + sql(IPC progress) + combine\n"
        "- 'Does the contract allow EOT, and what do the production logs show for that period?' → "
        "document(EOT clause) + sql(production for period) + combine\n"
        "- 'What were the total crane hours, and who sent the CCTV delay notification and when?' → "
        "sql(crane hours from equipment table) + document(who sent the CCTV delay notification and when) + combine "
        "(a single notice's sender/date is document prose — use document, NOT sql)\n"
        "- A follow-up like 'and manpower?' after an equipment question → "
        "sql(manpower) + combine (compare with the previous turn's result)\n\n"
        "RULES:\n"
        "1. If one step suffices, return is_simple=true with one step.\n"
        "2. Multi-step plans must end with a 'combine' step.\n"
        "3. Steps can reference previous results via {{step_N}} placeholder.\n"
        "4. Maximum {max_steps} steps allowed.\n"
        "5. Choose each step's type by CONTENT-AWARE ROUTING above: sql ONLY for numbers/"
        "aggregations over a reliable DATA TABLE; document for prose, senders, dates, "
        "clauses, correspondence. Do NOT default to sql.\n"
        "6. Each step instruction must be specific enough to execute independently.\n\n"
        "{user_query}\n\n"
        "Respond with ONLY valid JSON (no markdown):\n"
        '{{\"is_simple\": true/false, \"rationale\": \"brief\", '
        '\"steps\": [{{\"type\": \"sql|document|combine\", '
        '\"description\": \"short\", \"instruction\": \"detailed\", \"depends_on\": []}}]}}'
    )

    def __init__(self):
        """Initialize query planner."""
        self._jargon = None

    @property
    def jargon(self):
        if self._jargon is None:
            from .jargon_manager import get_jargon_manager
            self._jargon = get_jargon_manager()
        return self._jargon

    def plan(
        self,
        query: str,
        table_context: str = "",
        doc_context: str = "",
    ) -> QueryPlan:
        """
        Create an execution plan for a query.
        Enforces MAX_PLAN_STEPS guardrail.
        """
        logger.info(f"[Planner] Planning query: {query[:80]}...")

        # First check if simple via heuristics
        if self._is_obviously_simple(query):
            step_type = self._detect_simple_type(query)
            return QueryPlan(
                original_query=query,
                is_simple=True,
                steps=[PlanStep(
                    step_id=0,
                    step_type=step_type,
                    description="Direct query",
                    instruction=query,
                )],
                plan_rationale="Simple single-source query",
            )

        # Expand jargon for better planning
        prepared = self.jargon.prepare_query(query)
        from .jargon_manager import set_current_prepared_query
        set_current_prepared_query(prepared)
        expanded = prepared.llm_query

        # Use LLM to plan complex queries
        try:
            from . import llm_client
            from .prompt_security import safe_render_prompt, build_system_prompt

            prompt = safe_render_prompt(
                self.PLAN_PROMPT,
                user_query=expanded,
                table_context=table_context or "No tables loaded",
                doc_context=doc_context or "No documents loaded",
                max_steps=str(MAX_PLAN_STEPS),
            )
            system = build_system_prompt("You are a query planner. Return only valid JSON.")

            # Cache the plan by normalized query + an inventory signature so repeat
            # compound queries skip the ~3-4k-token planning call, while a change to
            # the documents/tables (which alters table_context/doc_context) busts it.
            import hashlib as _hl
            _norm = " ".join(expanded.lower().split())
            _inv = _hl.sha256((table_context + "||" + doc_context).encode()).hexdigest()[:16]
            _plan_key = "plan:" + _hl.sha256(f"{_norm}|{_inv}".encode()).hexdigest()[:32]

            resp = llm_client.generate_text(prompt, system=system, max_tokens=1024,
                                            cache_key=_plan_key,
                                            task_type="query_plan")

            # Record telemetry
            from .telemetry import get_current_trace
            trace = get_current_trace()
            if trace:
                trace.record_llm_call(resp.usage)

            plan_data = self._parse_plan_json(resp.text)

            if not plan_data:
                return self._simple_fallback(query)

            # Build plan with guardrail
            steps = []
            raw_steps = plan_data.get('steps', [])[:MAX_PLAN_STEPS]  # enforce max
            for i, step_data in enumerate(raw_steps):
                steps.append(PlanStep(
                    step_id=i,
                    step_type=step_data.get('type', 'sql'),
                    description=step_data.get('description', f'Step {i+1}'),
                    instruction=step_data.get('instruction', query),
                    depends_on=step_data.get('depends_on', []),
                ))

            plan = QueryPlan(
                original_query=query,
                is_simple=plan_data.get('is_simple', True),
                steps=steps,
                plan_rationale=plan_data.get('rationale', ''),
            )

            logger.info(f"[Planner] Plan: {len(plan.steps)} steps, simple={plan.is_simple}")
            for s in plan.steps:
                logger.info(f"   Step {s.step_id}: [{s.step_type}] {s.description}")

            return plan

        except Exception as e:
            logger.error(f"[Planner] Planning error: {e}")
            return self._simple_fallback(query)

    def _is_obviously_simple(self, query: str) -> bool:
        """Check if query is obviously single-step.
        Sequential AND compound (stacked) multi-part queries return False so the
        LLM planner decomposes them. Cross-source detection is left to the LLM.
        """
        return not is_multi_step_query(query)

    def _detect_simple_type(self, query: str) -> str:
        """Detect the type for a simple query.
        Schema-aware: checks if query relates to loaded table columns before defaulting.
        """
        q = query.lower()

        data_kw = ['calculate', 'sum', 'average', 'count', 'total', 'max', 'min',
                    'filter', 'group', 'sort', 'list', 'how many', 'which',
                    'highest', 'lowest', 'top', 'bottom', 'compare']
        if any(kw in q for kw in data_kw):
            return StepType.SQL.value

        # Single-doc correspondence lookup → document (not a data table).
        # Checked AFTER data_kw so numeric intent ('how many letters') stays sql.
        doc_corr_kw = ['who sent', 'who received', 'who issued', 'what date', 'when was',
                       'sender of', 'recipient of', 'notice', 'notification', 'letter']
        if any(kw in q for kw in doc_corr_kw):
            return StepType.DOCUMENT.value

        # Schema-aware: check if query terms match column names OR column values
        try:
            from .data_analyzer_sql import get_data_analyzer
            analyzer = get_data_analyzer()
            tables = analyzer.list_tables()
            if tables:
                query_words = set(q.split())
                for tname in tables:
                    info = analyzer.get_table_summary(tname)
                    if not info:
                        continue

                    # Check column names
                    cols = info.get('columns', [])
                    for col in cols:
                        col_words = set(col.lower().replace('_', ' ').split())
                        if col_words & query_words:
                            return StepType.SQL.value

                    # Check categorical column values (e.g. "steel fixer" in trade column)
                    dtypes = info.get('dtypes', {})
                    for col in cols:
                        dtype = str(dtypes.get(col, "VARCHAR")).upper()
                        is_text = not any(t in dtype for t in [
                            "INT", "FLOAT", "DOUBLE", "DECIMAL", "BIGINT",
                            "NUMBER", "DATE", "TIMESTAMP", "TIME", "BOOL",
                        ])
                        if not is_text:
                            continue
                        try:
                            uniques = analyzer.conn.execute(
                                f'SELECT DISTINCT LOWER("{col}") FROM {tname} '
                                f'WHERE "{col}" IS NOT NULL LIMIT 50'
                            ).fetchall()
                            col_values = {str(r[0]) for r in uniques}
                            # Check if any query n-gram matches a column value
                            q_words = q.split()
                            for n in range(1, min(4, len(q_words) + 1)):
                                for i in range(len(q_words) - n + 1):
                                    ngram = ' '.join(q_words[i:i+n])
                                    if any(ngram in v for v in col_values):
                                        return StepType.SQL.value
                        except Exception:
                            pass
        except Exception:
            pass

        # Default to SQL if tables are loaded, DOCUMENT otherwise
        try:
            from .data_analyzer_sql import get_data_analyzer
            if get_data_analyzer().list_tables():
                return StepType.SQL.value
        except Exception:
            pass

        return StepType.DOCUMENT.value

    def _parse_plan_json(self, raw: str) -> Optional[Dict]:
        """Parse JSON from LLM response, handling common artifacts."""
        raw = raw.strip()
        if raw.startswith('```'):
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]+\}', raw)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return None

    def _simple_fallback(self, query: str) -> QueryPlan:
        """Fallback to simple single-step plan."""
        step_type = self._detect_simple_type(query)
        return QueryPlan(
            original_query=query,
            is_simple=True,
            steps=[PlanStep(
                step_id=0,
                step_type=step_type,
                description="Direct query",
                instruction=query,
            )],
            plan_rationale="Fallback to simple query",
        )


class PlanExecutor:
    """
    Executes a QueryPlan step by step.
    Fail-fast: aborts on step error and returns structured PlanExecutionError.
    """

    def __init__(self):
        """Initialize executor with lazy-loaded handlers."""
        self._data_analyzer = None
        self._document_rag = None

    @property
    def data_analyzer(self):
        if self._data_analyzer is None:
            from .data_analyzer_sql import get_data_analyzer
            self._data_analyzer = get_data_analyzer()
        return self._data_analyzer

    @property
    def document_rag(self):
        if self._document_rag is None:
            from .document_rag import get_document_rag
            self._document_rag = get_document_rag()
        return self._document_rag

    def execute(self, plan: QueryPlan, doc_ids: Optional[List[str]] = None,
                allowed_tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Execute all steps in a plan. Fail-fast on step error.

        Returns:
            Dict with answer, sources, steps, and metadata.
            On failure, answer contains structured error message.
        """
        logger.info(f"[Executor] Executing plan: {len(plan.steps)} steps")

        all_sources = []
        step_results = {}
        completed_ids = []

        # When a COMBINE step does the single final synthesis, intermediate
        # DOCUMENT steps run retrieve-only (no per-step synthesis LLM call) and
        # hand their raw excerpts to COMBINE.
        has_combine = any(s.step_type == StepType.COMBINE.value for s in plan.steps)

        for step in plan.steps:
            step.status = "running"
            logger.info(f"[Executor] Step {step.step_id}: [{step.step_type}] {step.description}")

            step_start = time.time()

            # Resolve dependencies
            instruction = step.instruction
            for dep_id in step.depends_on:
                if dep_id in step_results:
                    prev = step_results[dep_id]
                    placeholder = f"{{step_{dep_id}}}"
                    if placeholder in instruction:
                        instruction = instruction.replace(
                            placeholder,
                            str(prev.get('summary', prev.get('answer', '')))[:2000]
                        )

            try:
                if step.step_type == StepType.SQL.value:
                    result = self._execute_sql_step(instruction, step_results, allowed_tables=allowed_tables)
                elif step.step_type == StepType.DOCUMENT.value:
                    is_last = step.step_id == len(plan.steps) - 1
                    result = self._execute_document_step(
                        instruction, doc_ids=doc_ids,
                        synthesize=not (has_combine and not is_last),
                    )
                elif step.step_type == StepType.COMBINE.value:
                    result = self._execute_combine_step(
                        plan.original_query, instruction, step.depends_on, step_results
                    )
                else:
                    result = {"answer": f"Unknown step type: {step.step_type}", "sources": []}

                # Check for error in result answer (propagated from downstream)
                answer = result.get('answer', '')
                if answer.startswith("Error"):
                    raise RuntimeError(answer)

                step.result = answer
                step.status = "done"
                step_results[step.step_id] = result
                all_sources.extend(result.get('sources', []))
                completed_ids.append(step.step_id)

                # Record step telemetry
                from .telemetry import get_current_trace
                trace = get_current_trace()
                if trace:
                    elapsed = (time.time() - step_start) * 1000
                    trace.record_step(step.step_id, step.step_type, "done", elapsed)

            except Exception as e:
                logger.error(f"[Executor] Step {step.step_id} FAILED: {e}", exc_info=True)
                step.status = "error"
                step.error = str(e)

                # Record error telemetry
                from .telemetry import get_current_trace
                trace = get_current_trace()
                if trace:
                    elapsed = (time.time() - step_start) * 1000
                    trace.record_step(step.step_id, step.step_type, "error", elapsed)
                    trace.record_error(f"Step {step.step_id} ({step.step_type}): {e}")

                # Fail-fast: abort remaining steps
                error = PlanExecutionError(
                    failed_step=StepError(
                        step_id=step.step_id,
                        step_type=step.step_type,
                        error_message=str(e),
                        recoverable=False,
                    ),
                    completed_steps=completed_ids,
                    partial_results={sid: step_results[sid].get('answer', '') for sid in completed_ids},
                )

                return {
                    "answer": error.user_message,
                    "sources": all_sources,
                    "plan": self._build_plan_meta(plan),
                    "sql": None,
                    "result_data": None,
                    "result_columns": None,
                    "error": {
                        "failed_step": step.step_id,
                        "step_type": step.step_type,
                        "message": str(e),
                        "completed_steps": completed_ids,
                    },
                }

        # Get final answer from last step
        final = step_results.get(len(plan.steps) - 1, {})

        return {
            "answer": final.get('answer', 'No result produced'),
            "sources": all_sources,
            "plan": self._build_plan_meta(plan),
            "sql": final.get('sql'),
            "result_data": final.get('result_data'),
            "result_columns": final.get('result_columns'),
        }

    def _build_plan_meta(self, plan: QueryPlan) -> Dict:
        """Build plan metadata for the response."""
        return {
            "is_simple": plan.is_simple,
            "rationale": plan.plan_rationale,
            "steps": [
                {
                    "step_id": s.step_id,
                    "type": s.step_type,
                    "description": s.description,
                    "status": s.status,
                    "error": s.error,
                }
                for s in plan.steps
            ],
        }

    def execute_with_provider(self, plan: QueryPlan, provider: str,
                              doc_ids: Optional[List[str]] = None,
                              allowed_tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute plan with a specific LLM provider."""
        logger.info(f"[Executor] Executing plan with provider={provider}: {len(plan.steps)} steps")

        all_sources = []
        step_results = {}
        completed_ids = []

        for step in plan.steps:
            step_start = time.time()
            instruction = step.instruction
            for dep_id in step.depends_on:
                if dep_id in step_results:
                    prev = step_results[dep_id]
                    placeholder = f"{{step_{dep_id}}}"
                    if placeholder in instruction:
                        instruction = instruction.replace(
                            placeholder,
                            str(prev.get('summary', prev.get('answer', '')))[:2000]
                        )

            try:
                if step.step_type == StepType.SQL.value:
                    result = self._execute_sql_step(instruction, step_results, provider=provider, allowed_tables=allowed_tables)
                elif step.step_type == StepType.DOCUMENT.value:
                    result = self._execute_document_step(instruction, provider=provider, doc_ids=doc_ids)
                elif step.step_type == StepType.COMBINE.value:
                    result = self._execute_combine_step(
                        plan.original_query, instruction, step.depends_on, step_results,
                        provider=provider,
                    )
                else:
                    result = {"answer": f"Unknown step type: {step.step_type}", "sources": []}

                answer = result.get('answer', '')
                if answer.startswith("Error"):
                    raise RuntimeError(answer)

                step_results[step.step_id] = result
                all_sources.extend(result.get('sources', []))
                completed_ids.append(step.step_id)

            except Exception as e:
                logger.error(f"[Executor] [{provider}] Step {step.step_id} FAILED: {e}")
                return {
                    "answer": f"[{provider}] Step {step.step_id} failed: {e}",
                    "sources": all_sources,
                    "plan": self._build_plan_meta(plan),
                    "sql": None, "result_data": None, "result_columns": None,
                }

        final = step_results.get(len(plan.steps) - 1, {})
        return {
            "answer": final.get('answer', 'No result produced'),
            "sources": all_sources,
            "plan": self._build_plan_meta(plan),
            "sql": final.get('sql'),
            "result_data": final.get('result_data'),
            "result_columns": final.get('result_columns'),
        }

    def _execute_sql_step(self, instruction: str, prev_results: Dict,
                          provider: str = "gemini",
                          allowed_tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a SQL analysis step, passing context from prior steps."""
        context = ""
        for step_id, res in prev_results.items():
            if res.get('answer'):
                context += f"Step {step_id} result: {res['answer'][:300]}\n"

        if context:
            result = self.data_analyzer.query_with_context(instruction, context, provider=provider, allowed_tables=allowed_tables)
        else:
            # Use the schema layer: unified aggregation over same-schema base tables
            # with deterministic schema shortcuts, avoiding fragile LLM SQL over
            # grouped/combined views (the source of the compound-query SQL errors).
            result = self.data_analyzer.query_schema_aware(
                instruction, allowed_tables=allowed_tables, provider=provider,
            )

        return {
            "answer": result.get("answer", ""),
            "summary": result.get("answer", ""),
            "sources": result.get("sources", []),
            "sql": result.get("sql"),
            "result_data": result.get("result_data"),
            "result_columns": result.get("result_columns"),
        }

    def _execute_document_step(self, instruction: str, provider: str = "gemini",
                               doc_ids: Optional[List[str]] = None,
                               synthesize: bool = True) -> Dict[str, Any]:
        """Execute a document search step.

        synthesize=False (retrieve-only) skips the per-step synthesis LLM call for
        intermediate steps that feed a COMBINE step; the raw chunk excerpts are
        joined deterministically so COMBINE (and dependency templating) still have
        document text without paying for a synthesis that COMBINE would re-do.
        """
        if provider != "gemini":
            # Provider/dual path keeps its own synthesis (dual is off by default).
            result = self.document_rag.query_with_provider(instruction, provider, doc_ids=doc_ids)
        else:
            result = self.document_rag.query(instruction, doc_ids=doc_ids, synthesize=synthesize)
        answer = result.get("answer", "")
        sources = result.get("sources", [])
        if not answer and sources:
            answer = self._excerpts_from_sources(sources)
        return {
            "answer": answer,
            "summary": answer[:300],
            "sources": sources,
        }

    @staticmethod
    def _excerpts_from_sources(sources: List[Dict[str, Any]], max_chunks: int = 6) -> str:
        """Deterministic raw-excerpt join (no LLM) for retrieve-only document
        steps, so COMBINE has the chunk text to synthesize from."""
        parts = []
        for i, s in enumerate((sources or [])[:max_chunks], 1):
            text = (s.get("text_snippet") or s.get("highlight_text") or "").strip()
            if not text:
                continue
            parts.append(f"[{i}] {s.get('file_name', 'Unknown')} "
                         f"p.{s.get('page_number', '?')}: {text}")
        return "\n\n".join(parts)

    def _execute_combine_step(
        self,
        original_query: str,
        instruction: str,
        depends_on: List[int],
        prev_results: Dict,
        provider: str = "gemini",
    ) -> Dict[str, Any]:
        """Combine results from previous steps using llm_client."""
        from . import llm_client
        from .prompt_security import safe_render_prompt, build_system_prompt

        parts = []
        all_sources = []
        for dep_id in depends_on:
            if dep_id in prev_results:
                res = prev_results[dep_id]
                parts.append(f"--- Step {dep_id + 1} Result ---\n{res.get('answer', 'No result')}")
                all_sources.extend(res.get('sources', []))

        if not parts:
            for step_id, res in sorted(prev_results.items()):
                parts.append(f"--- Step {step_id + 1} Result ---\n{res.get('answer', 'No result')}")
                all_sources.extend(res.get('sources', []))

        combined_input = "\n\n".join(parts)

        prompt = safe_render_prompt(
            "You are a construction project analyst synthesizing data from multiple sources.\n\n"
            "ORIGINAL QUESTION: {original_query}\n\n"
            "ANALYSIS RESULTS:\n{results}\n\n"
            "INSTRUCTIONS: {instruction}\n\n"
            "Synthesize into a clear, professional answer:\n"
            "1. Directly answer the question with specific numbers and facts\n"
            "2. Cross-reference data between steps — highlight correlations or discrepancies\n"
            "3. For equipment + manpower data: note if high equipment hours align with high headcount\n"
            "4. For data + document: compare actual values against contractual requirements\n"
            "5. Do NOT invent information not present in the results\n"
            "6. Conclude with an actionable insight when the data supports it",
            user_query=original_query,
            original_query=original_query,
            results=combined_input[:3000],
            instruction=instruction,
        )
        system = build_system_prompt(
            "You are a senior construction project analyst. "
            "Synthesize findings with domain expertise."
        )

        try:
            resp = llm_client.generate_text(
                prompt, system=system, max_tokens=1024, provider=provider,
                task_type="answer_synthesis",
            )

            from .telemetry import get_current_trace
            trace = get_current_trace()
            if trace:
                trace.record_llm_call(resp.usage)

            answer = resp.text
        except Exception as e:
            logger.error(f"[Executor] [{provider}] Combine error: {e}")
            answer = f"**Combined Results:**\n\n{combined_input}"

        return {
            "answer": answer,
            "sources": all_sources,
        }


# Singletons
_planner: Optional[QueryPlanner] = None
_executor: Optional[PlanExecutor] = None


def get_planner() -> QueryPlanner:
    """Get or create QueryPlanner singleton."""
    global _planner
    if _planner is None:
        _planner = QueryPlanner()
    return _planner


def get_executor() -> PlanExecutor:
    """Get or create PlanExecutor singleton."""
    global _executor
    if _executor is None:
        _executor = PlanExecutor()
    return _executor


def plan_and_execute(
    query: str,
    table_context: str = "",
    doc_context: str = "",
) -> Dict[str, Any]:
    """Convenience function: plan and execute a query in one call."""
    planner = get_planner()
    executor = get_executor()

    plan = planner.plan(query, table_context, doc_context)
    return executor.execute(plan)
