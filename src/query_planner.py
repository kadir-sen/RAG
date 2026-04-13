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
    TIMELINE = "timeline"
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
        "- document: Search PDF/contract documents. Use ONLY for reading contract clauses, "
        "terms, specifications, or document prose that is NOT in any table.\n"
        "- timeline: Query document relationships. Use for correspondence flow, notice sequences.\n"
        "- combine: Synthesize results from previous steps into a final answer.\n\n"
        "AVAILABLE TABLES:\n{table_context}\n\n"
        "AVAILABLE DOCUMENTS:\n{doc_context}\n\n"
        "CONSTRUCTION QUERY PATTERNS:\n"
        "- 'Compare equipment and manpower for Block A' → sql(equipment) + sql(manpower) + combine\n"
        "- 'Does actual progress match the contract?' → sql(IPC progress) + document(contract terms) + combine\n"
        "- 'Which trade has best productivity?' → sql(manpower: output/workers) — single step\n"
        "- 'Total hours by equipment type' → sql(equipment) — single step\n"
        "- 'What does the contract say about delays?' → document — single step\n\n"
        "RULES:\n"
        "1. If one step suffices, return is_simple=true with one step.\n"
        "2. Multi-step plans must end with a 'combine' step.\n"
        "3. Steps can reference previous results via {{step_N}} placeholder.\n"
        "4. Maximum {max_steps} steps allowed.\n"
        "5. ALWAYS prefer 'sql' when tables contain relevant data.\n"
        "6. Each step instruction must be specific enough to execute independently.\n\n"
        "{user_query}\n\n"
        "Respond with ONLY valid JSON (no markdown):\n"
        '{{\"is_simple\": true/false, \"rationale\": \"brief\", '
        '\"steps\": [{{\"type\": \"sql|document|timeline|combine\", '
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
        expanded = self.jargon.expand_query(query)

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

            resp = llm_client.generate_text(prompt, system=system, max_tokens=1024)

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
        Only truly sequential multi-step patterns return False.
        Cross-source keyword detection is left to the LLM planner.
        """
        q = query.lower()

        multi_indicators = [
            ' then ', ' and then ', ' after that ', ' next ',
            'month-over-month', 'year-over-year',
        ]

        for indicator in multi_indicators:
            if indicator in q:
                return False

        return True

    def _detect_simple_type(self, query: str) -> str:
        """Detect the type for a simple query.
        Schema-aware: checks if query relates to loaded table columns before defaulting.
        """
        q = query.lower()

        timeline_kw = ['timeline', 'chronology', 'who sent', 'who received', 'correspondence']
        if any(kw in q for kw in timeline_kw):
            return StepType.TIMELINE.value

        data_kw = ['calculate', 'sum', 'average', 'count', 'total', 'max', 'min',
                    'filter', 'group', 'sort', 'list', 'how many', 'which',
                    'highest', 'lowest', 'top', 'bottom', 'compare']
        if any(kw in q for kw in data_kw):
            return StepType.SQL.value

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
        self._light_graph = None

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

    @property
    def light_graph(self):
        if self._light_graph is None:
            from .light_graph import get_light_graph
            self._light_graph = get_light_graph()
        return self._light_graph

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
                            str(prev.get('summary', prev.get('answer', '')))[:500]
                        )

            try:
                if step.step_type == StepType.SQL.value:
                    result = self._execute_sql_step(instruction, step_results, allowed_tables=allowed_tables)
                elif step.step_type == StepType.DOCUMENT.value:
                    result = self._execute_document_step(instruction, doc_ids=doc_ids)
                elif step.step_type == StepType.TIMELINE.value:
                    result = self._execute_timeline_step(instruction)
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
                logger.error(f"[Executor] Step {step.step_id} FAILED: {e}")
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
                            str(prev.get('summary', prev.get('answer', '')))[:500]
                        )

            try:
                if step.step_type == StepType.SQL.value:
                    result = self._execute_sql_step(instruction, step_results, provider=provider, allowed_tables=allowed_tables)
                elif step.step_type == StepType.DOCUMENT.value:
                    result = self._execute_document_step(instruction, provider=provider, doc_ids=doc_ids)
                elif step.step_type == StepType.TIMELINE.value:
                    result = self._execute_timeline_step(instruction)
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
            if provider != "gemini":
                result = self.data_analyzer.query_with_provider(instruction, provider, allowed_tables=allowed_tables)
            else:
                result = self.data_analyzer.query(instruction, allowed_tables=allowed_tables)

        return {
            "answer": result.get("answer", ""),
            "summary": result.get("answer", ""),
            "sources": result.get("sources", []),
            "sql": result.get("sql"),
            "result_data": result.get("result_data"),
            "result_columns": result.get("result_columns"),
        }

    def _execute_document_step(self, instruction: str, provider: str = "gemini",
                               doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a document search step."""
        if provider != "gemini":
            result = self.document_rag.query_with_provider(instruction, provider, doc_ids=doc_ids)
        else:
            result = self.document_rag.query(instruction, doc_ids=doc_ids)
        return {
            "answer": result.get("answer", ""),
            "summary": result.get("answer", "")[:300],
            "sources": result.get("sources", []),
        }

    def _execute_timeline_step(self, instruction: str) -> Dict[str, Any]:
        """Execute a timeline/graph query step."""
        graph = self.light_graph
        result = graph.smart_timeline_answer(instruction)

        return {
            "answer": result.get("answer", "No matching documents found."),
            "summary": result.get("answer", "")[:300],
            "sources": result.get("sources", []),
        }

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
            resp = llm_client.generate_text(prompt, system=system, max_tokens=1024, provider=provider)

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
