"""
Hybrid Executor - Multi-source query orchestrator.
Integrates QueryPlanner with all data sources (SQL, Document RAG, Light Graph)
to handle complex multi-step queries.

Architecture:
  Router -> Hybrid Executor -> Planner -> [Step1, Step2, ...] -> Combined Answer
"""
from typing import Dict, List, Optional, Any

from llama_index.llms.gemini import Gemini

from .config import GOOGLE_API_KEY, GEMINI_MODEL
from .logger import logger, log_separator
from .query_planner import (
    QueryPlanner, PlanExecutor, QueryPlan, PlanStep, StepType,
    get_planner, get_executor,
)


class HybridExecutor:
    """
    Orchestrates multi-source query execution.
    Wraps QueryPlanner + PlanExecutor with context-gathering and result formatting.
    """

    def __init__(self):
        """Initialize hybrid executor with lazy-loaded components."""
        self._planner = None
        self._executor = None
        self._data_analyzer = None
        self._document_rag = None
        self._light_graph = None
        self._jargon = None

    @property
    def planner(self) -> QueryPlanner:
        if self._planner is None:
            self._planner = get_planner()
        return self._planner

    @property
    def executor(self) -> PlanExecutor:
        if self._executor is None:
            self._executor = get_executor()
        return self._executor

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

    @property
    def jargon(self):
        if self._jargon is None:
            from .jargon_manager import get_jargon_manager
            self._jargon = get_jargon_manager()
        return self._jargon

    def _build_table_context(self) -> str:
        """Build context string describing available tables."""
        tables = self.data_analyzer.list_tables()
        if not tables:
            return "No tables loaded."

        lines = []
        for name in tables:
            info = self.data_analyzer.get_table_summary(name)
            if info:
                cols = info.get('columns', [])
                col_str = ', '.join(cols[:8])
                if len(cols) > 8:
                    col_str += f'... (+{len(cols) - 8} more)'
                rows = info.get('row_count', 0)
                lines.append(f"- {name}: {rows} rows | Columns: {col_str}")

                # Add jargon context for columns
                jargon_ctx = self.jargon.build_column_context(cols)
                if jargon_ctx:
                    lines.append(f"  {jargon_ctx}")

        return '\n'.join(lines)

    def _build_doc_context(self) -> str:
        """Build context string describing available documents."""
        if not self.document_rag.file_registry:
            return "No documents loaded."

        lines = []
        for fname, info in self.document_rag.file_registry.items():
            pages = info.get('page_count', 1)
            ftype = info.get('file_type', '')
            lines.append(f"- {fname} ({ftype}, {pages} pages)")

        # Also include graph info
        stats = self.light_graph.get_statistics()
        if stats['node_count'] > 0:
            lines.append(f"\nDocument Graph: {stats['node_count']} documents, {stats['edge_count']} relationships")
            parties = self.light_graph.get_all_parties()
            if parties:
                party_str = ', '.join(p['party'] for p in parties[:5])
                lines.append(f"Parties: {party_str}")

        return '\n'.join(lines)

    def execute(self, query: str) -> Dict[str, Any]:
        """
        Execute a query using the planner for complex queries, or directly for simple ones.

        Args:
            query: User query (may be in English or Turkish)

        Returns:
            Dict with answer, sources, plan details, and optional SQL/data
        """
        log_separator("Hybrid Executor")
        logger.info(f"[HybridExecutor] Query: {query[:100]}...")

        # Expand jargon
        expanded = self.jargon.expand_query(query)
        if expanded != query:
            logger.info(f"[HybridExecutor] Expanded: {expanded[:100]}...")

        # Gather context
        table_context = self._build_table_context()
        doc_context = self._build_doc_context()

        # Plan
        plan = self.planner.plan(expanded, table_context, doc_context)
        logger.info(f"[HybridExecutor] Plan: {len(plan.steps)} steps, simple={plan.is_simple}")

        # Execute
        result = self.executor.execute(plan)

        # Enrich result
        result['query'] = query
        result['expanded_query'] = expanded if expanded != query else None
        result['query_type'] = self._determine_query_type(plan)

        logger.info(f"[HybridExecutor] Done. Steps: {len(plan.steps)}, Sources: {len(result.get('sources', []))}")
        return result

    def execute_multi_step_sql(self, query: str) -> Dict[str, Any]:
        """
        Execute a multi-step SQL query that may require chaining.
        For queries like: "Group by X, then find max in each group, then filter where > threshold"

        Args:
            query: SQL-focused multi-step query

        Returns:
            Result dict with answer, SQL chain, and data
        """
        log_separator("Multi-Step SQL")
        logger.info(f"[HybridExecutor] Multi-step SQL: {query[:100]}...")

        expanded = self.jargon.expand_query(query)
        table_context = self._build_table_context()

        # Force planning even for seemingly simple queries
        plan = self.planner.plan(expanded, table_context, "")

        # If planner returns simple, try to decompose via SQL-specific heuristics
        if plan.is_simple and self._needs_sql_chain(query):
            plan = self._create_sql_chain_plan(expanded)

        result = self.executor.execute(plan)
        result['query'] = query
        result['query_type'] = 'data'
        return result

    def _needs_sql_chain(self, query: str) -> bool:
        """Check if a query needs SQL chaining."""
        q = query.lower()
        chain_indicators = [
            'then', 'sonra', 'ardından',
            'after that', 'bundan sonra',
            'group by', 'grupla',
            'outlier', 'aykırı',
            'compare', 'kıyasla',
            'top', 'bottom', 'en yüksek', 'en düşük',
            'above average', 'below average',
            'ortalamanın üstünde', 'ortalamanın altında',
        ]
        return any(ind in q for ind in chain_indicators)

    def _create_sql_chain_plan(self, query: str) -> QueryPlan:
        """Create a SQL chain plan from heuristic analysis."""
        q = query.lower()
        steps = []

        # Pattern: group by + aggregate
        if 'group' in q and any(agg in q for agg in ['max', 'min', 'avg', 'average', 'sum', 'count',
                                                       'en büyük', 'en küçük', 'ortalama', 'toplam']):
            steps.append(PlanStep(
                step_id=0,
                step_type=StepType.SQL.value,
                description="Group and aggregate",
                instruction=query,
            ))
            steps.append(PlanStep(
                step_id=1,
                step_type=StepType.COMBINE.value,
                description="Format results",
                instruction="Present the grouped aggregation results in a clear table format",
                depends_on=[0],
            ))

        # Pattern: outlier detection
        elif 'outlier' in q or 'aykırı' in q:
            steps.append(PlanStep(
                step_id=0,
                step_type=StepType.SQL.value,
                description="Calculate statistics",
                instruction=f"Calculate mean and standard deviation for the relevant numeric column in: {query}",
            ))
            steps.append(PlanStep(
                step_id=1,
                step_type=StepType.SQL.value,
                description="Find outliers",
                instruction=f"Find records where values exceed mean +/- 2 standard deviations for: {query}",
            ))
            steps.append(PlanStep(
                step_id=2,
                step_type=StepType.COMBINE.value,
                description="Present outliers",
                instruction="Combine statistics and outlier records into a clear analysis",
                depends_on=[0, 1],
            ))

        # Pattern: compare / top-N
        elif any(kw in q for kw in ['compare', 'kıyasla', 'top', 'bottom', 'en yüksek', 'en düşük']):
            steps.append(PlanStep(
                step_id=0,
                step_type=StepType.SQL.value,
                description="Execute comparison query",
                instruction=query,
            ))
            steps.append(PlanStep(
                step_id=1,
                step_type=StepType.COMBINE.value,
                description="Format comparison",
                instruction="Present the comparison results clearly",
                depends_on=[0],
            ))

        # Pattern: above/below average
        elif any(kw in q for kw in ['above average', 'below average', 'ortalamanın üstünde', 'ortalamanın altında']):
            steps.append(PlanStep(
                step_id=0,
                step_type=StepType.SQL.value,
                description="Calculate average",
                instruction=f"Calculate the average for the relevant column in: {query}",
            ))
            steps.append(PlanStep(
                step_id=1,
                step_type=StepType.SQL.value,
                description="Filter by average",
                instruction=f"Find records above/below the average for: {query}",
            ))
            steps.append(PlanStep(
                step_id=2,
                step_type=StepType.COMBINE.value,
                description="Present filtered results",
                instruction="Show the average value and the filtered records",
                depends_on=[0, 1],
            ))

        # Default: single SQL step
        else:
            steps.append(PlanStep(
                step_id=0,
                step_type=StepType.SQL.value,
                description="Execute query",
                instruction=query,
            ))

        return QueryPlan(
            original_query=query,
            is_simple=len(steps) <= 1,
            steps=steps,
            plan_rationale="Heuristic SQL chain",
        )

    def execute_dual(self, query: str) -> Dict[str, Any]:
        """
        Execute a complex query with both OpenAI and Claude in parallel.
        Plans once, then executes the plan with each provider independently.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .config import LLM_PROVIDERS

        log_separator("Hybrid Executor (Dual-LLM)")
        logger.info(f"[HybridExecutor] Dual query: {query[:100]}...")

        expanded = self.jargon.expand_query(query)
        table_context = self._build_table_context()
        doc_context = self._build_doc_context()

        # Plan once (plan structure is provider-independent)
        plan = self.planner.plan(expanded, table_context, doc_context)
        logger.info(f"[HybridExecutor] Plan: {len(plan.steps)} steps, executing with both providers...")

        results = {}

        def _execute_for_provider(provider: str):
            result = self.executor.execute_with_provider(plan, provider)
            result['query'] = query
            result['query_type'] = self._determine_query_type(plan)
            return provider, result

        with ThreadPoolExecutor(max_workers=len(LLM_PROVIDERS)) as executor:
            futures = {executor.submit(_execute_for_provider, p): p for p in LLM_PROVIDERS}
            for future in as_completed(futures):
                prov = futures[future]
                try:
                    _, result = future.result()
                    results[prov] = result
                except Exception as e:
                    logger.error(f"[HybridExecutor] [{prov}] Failed: {e}")
                    results[prov] = {
                        "answer": f"Error from {prov}: {e}",
                        "sources": [], "sql": None, "result_data": None,
                    }

        return results

    def _determine_query_type(self, plan: QueryPlan) -> str:
        """Determine the overall query type from a plan."""
        types = set()
        for step in plan.steps:
            if step.step_type == StepType.COMBINE.value:
                continue
            types.add(step.step_type)

        if len(types) > 1:
            return 'hybrid'
        if types:
            return types.pop()
        return 'unknown'


# Singleton
_hybrid_executor: Optional[HybridExecutor] = None


def get_hybrid_executor() -> HybridExecutor:
    """Get or create HybridExecutor singleton."""
    global _hybrid_executor
    if _hybrid_executor is None:
        _hybrid_executor = HybridExecutor()
    return _hybrid_executor
