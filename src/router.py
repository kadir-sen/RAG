"""
Query Router - Routes queries to Document RAG, SQL Data Analyzer, or Timeline/Graph handler.

Routing strategy (LLM-free by default):
  1. Heuristic keyword scoring
  2. Embedding-similarity with anchor texts (if ambiguous)
  3. LLM classification via llm_client (last resort)
"""
import re
from pathlib import Path
from typing import Tuple, Dict, Any, List, Optional

from .config import GOOGLE_API_KEY, GEMINI_MODEL, ENABLE_TIMELINE
from .types import QueryType, RouterDecision, LLMUsage
from .logger import logger, log_separator


# ── Keyword sets (English only) ───────────────────────────────

DATA_KEYWORDS = {
    "calculate", "sum", "average", "mean", "total", "count", "how many",
    "filter", "sort", "group by", "aggregate", "maximum", "minimum", "max", "min",
    "variance", "std", "deviation", "percentage", "ratio", "percent",
    "compare", "trend", "statistics", "column", "row", "table", "excel", "csv",
    "spreadsheet", "data", "number", "numeric", "value",
    "manpower", "equipment", "cost", "quantity", "rate", "amount",
}

DOCUMENT_KEYWORDS = {
    "what does", "explain", "describe", "define", "definition", "meaning",
    "terms", "clause", "contract", "policy", "agreement", "section", "article",
    "according to", "mentioned in", "stated in", "says", "written",
    "liability", "obligation", "requirement", "condition", "provision",
    "report", "document", "text", "paragraph", "page", "summary", "summarize",
    "letter", "notice", "correspondence", "scope of work",
}

TIMELINE_KEYWORDS = {
    "timeline", "chronology", "sequence", "history", "chain", "trace",
    "what happened", "when did", "order of events", "between dates",
    "who replied", "who responded", "who sent", "who received",
    "notices", "all notices", "list notices", "show notices",
    "correspondence", "letters sent", "letters received",
    "delay notices", "extension notices", "claim notices",
    "before", "after", "during", "period",
    "communication flow", "parties involved", "document trail",
}


# ── Embedding-similarity anchor texts ────────────────────────

_ANCHOR_TEXTS = {
    QueryType.DATA: [
        "Calculate the total amount from the spreadsheet",
        "How many rows match this filter condition",
        "What is the average value grouped by category",
        "Show me the maximum and minimum numbers in the table",
    ],
    QueryType.DOCUMENT: [
        "What does the contract clause say about liability",
        "Explain the terms and conditions in section 5",
        "According to the agreement what are the obligations",
        "Summarize the policy document regarding requirements",
    ],
    QueryType.TIMELINE: [
        "Show the timeline of notices sent between parties",
        "Who sent the delay notice and when was it received",
        "What is the chronological sequence of correspondence",
        "List all notices related to contract claims",
    ],
    QueryType.HYBRID: [
        "Compare the contract terms with the actual data values",
        "What does the agreement say and how does it match the numbers",
        "Correlate document clauses with spreadsheet calculations",
    ],
}

# Cached anchor embeddings (populated once on first use)
_anchor_embeddings: Optional[Dict[str, list]] = None


def _get_anchor_embeddings() -> Dict[str, list]:
    """Embed anchor texts once and cache in memory."""
    global _anchor_embeddings
    if _anchor_embeddings is not None:
        return _anchor_embeddings

    try:
        from llama_index.embeddings.google_genai import GoogleGenAIEmbedding
        from .config import EMBEDDING_MODEL, EMBEDDING_DIMENSION

        embed_model = GoogleGenAIEmbedding(
            api_key=GOOGLE_API_KEY,
            model_name=EMBEDDING_MODEL,
            embedding_config={"output_dimensionality": EMBEDDING_DIMENSION},
        )

        _anchor_embeddings = {}
        for qtype, texts in _ANCHOR_TEXTS.items():
            vecs = embed_model.get_text_embedding_batch(texts)
            _anchor_embeddings[qtype.value] = vecs
            logger.info(f"[Router] Embedded {len(texts)} anchors for {qtype.value}")

        return _anchor_embeddings

    except Exception as e:
        logger.warning(f"[Router] Anchor embedding failed: {e}")
        _anchor_embeddings = {}
        return _anchor_embeddings


def _cosine_similarity(a: list, b: list) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class QueryRouter:
    """Routes queries to appropriate handlers with multilingual support and jargon awareness."""

    # Heuristic confidence thresholds
    STRONG_HEURISTIC_THRESHOLD = 3   # keyword hits for high-confidence match
    MARGIN_THRESHOLD = 2             # gap between top-2 scores for clear winner
    EMBEDDING_MARGIN = 0.05          # cosine similarity margin for embedding routing

    # Prompts (used only as last-resort LLM fallback)
    CLASSIFICATION_PROMPT = (
        "Classify this query into exactly ONE category: DOCUMENT, DATA, TIMELINE, or HYBRID.\n"
        "DOCUMENT = about text content, contracts, clauses, definitions.\n"
        "DATA = calculations, aggregations, statistics on tabular data.\n"
        "TIMELINE = chronology, correspondence, notices, who sent what when.\n"
        "HYBRID = needs BOTH document context AND data calculations.\n\n"
        "Available tables: {data_files}\n\n"
        "{user_query}\n\n"
        "Respond with exactly ONE word."
    )

    HYBRID_SYNTHESIS_PROMPT = (
        "Combine these two information sources to answer the user's question.\n"
        "Do NOT invent facts - only use information from the sources below.\n\n"
        "QUESTION: {user_query}\n\n"
        "DOCUMENT SEARCH RESULTS:\n{doc_results}\n\n"
        "DATA ANALYSIS RESULTS:\n{data_results}\n\n"
        "Provide a comprehensive answer that:\n"
        "1. Clearly states which information comes from documents vs data analysis\n"
        "2. Does not make claims unsupported by either source\n"
        "3. Is concise and well-structured"
    )

    def __init__(self):
        """Initialize the router."""
        log_separator("Initializing Query Router")
        from .document_rag import get_document_rag
        from .data_analyzer_sql import get_data_analyzer

        self.document_rag = get_document_rag()
        self.data_analyzer = get_data_analyzer()
        self._jargon = None
        self._hybrid_executor = None
        logger.info("Query Router initialized")

    @property
    def hybrid_executor(self):
        """Lazy-load hybrid executor."""
        if self._hybrid_executor is None:
            from .hybrid_executor import get_hybrid_executor
            self._hybrid_executor = get_hybrid_executor()
        return self._hybrid_executor

    @property
    def jargon(self):
        """Lazy-load jargon manager."""
        if self._jargon is None:
            from .jargon_manager import get_jargon_manager
            self._jargon = get_jargon_manager()
        return self._jargon

    def _get_available_sources(self) -> Tuple[str, str]:
        """Get descriptions of available sources."""
        doc_files = "None loaded"
        if self.document_rag.file_registry:
            doc_list = []
            for fname, info in self.document_rag.file_registry.items():
                pages = info.get('page_count', 1)
                doc_list.append(f"{fname} ({pages} pages)")
            doc_files = ", ".join(doc_list[:10])
            if len(doc_list) > 10:
                doc_files += f" (+{len(doc_list) - 10} more)"

        data_files = "None loaded"
        tables = self.data_analyzer.list_tables()
        if tables:
            table_list = []
            for tname in tables[:10]:
                info = self.data_analyzer.get_table_summary(tname)
                if info:
                    cols = info.get('columns', [])
                    col_preview = ', '.join(cols[:3])
                    if len(cols) > 3:
                        col_preview += '...'
                    table_list.append(f"{tname} (cols: {col_preview})")
            data_files = ", ".join(table_list)
            if len(tables) > 10:
                data_files += f" (+{len(tables) - 10} more)"

        return doc_files, data_files

    # ── Classification: 3-tier strategy ───────────────────────

    def classify_query(self, query: str) -> RouterDecision:
        """
        Classify query using 3-tier strategy:
          1. Heuristic keyword scoring (free)
          2. Embedding-similarity with anchors (cheap)
          3. LLM classification (last resort)
        Returns RouterDecision with type, confidence, reasons.
        """
        logger.info("Classifying query...")

        # Expand abbreviations
        expanded_query = self.jargon.expand_query(query)
        if expanded_query != query:
            logger.info(f"   Jargon expanded: {expanded_query[:100]}...")

        query_lower = expanded_query.lower()

        # ── Tier 1: Heuristic scoring ──
        decision = self._classify_heuristic(query_lower)
        if decision is not None:
            logger.info(f"   -> Heuristic: {decision.query_type.value.upper()} "
                        f"(conf={decision.confidence:.2f})")
            return decision

        # ── Tier 2: Embedding similarity ──
        decision = self._classify_embedding(query)
        if decision is not None:
            logger.info(f"   -> Embedding: {decision.query_type.value.upper()} "
                        f"(conf={decision.confidence:.2f})")
            return decision

        # ── Tier 3: LLM fallback ──
        decision = self._classify_llm(query)
        logger.info(f"   -> LLM: {decision.query_type.value.upper()} "
                    f"(conf={decision.confidence:.2f})")
        return decision

    def _classify_heuristic(self, query_lower: str) -> Optional[RouterDecision]:
        """Tier 1: keyword-based scoring. Returns None if ambiguous."""
        data_score = sum(1 for kw in DATA_KEYWORDS if kw in query_lower)
        doc_score = sum(1 for kw in DOCUMENT_KEYWORDS if kw in query_lower)
        timeline_score = sum(1 for kw in TIMELINE_KEYWORDS if kw in query_lower)

        scores = {
            QueryType.DATA: data_score,
            QueryType.DOCUMENT: doc_score,
            QueryType.TIMELINE: timeline_score,
        }

        logger.info(f"   Heuristic scores - Doc:{doc_score} Data:{data_score} Timeline:{timeline_score}")

        # Timeline priority (important for domain)
        if timeline_score >= 2 and ENABLE_TIMELINE:
            return RouterDecision(
                query_type=QueryType.TIMELINE,
                confidence=min(0.95, 0.5 + timeline_score * 0.1),
                reasons=[f"Timeline keywords matched: {timeline_score}"],
            )

        # Sort scores descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_type, top_score = ranked[0]
        second_score = ranked[1][1]

        # Strong match: top score high AND clear margin
        if top_score >= self.STRONG_HEURISTIC_THRESHOLD and (top_score - second_score) >= self.MARGIN_THRESHOLD:
            return RouterDecision(
                query_type=top_type,
                confidence=min(0.95, 0.5 + top_score * 0.08),
                reasons=[f"Keyword match: {top_type.value}={top_score}, margin={top_score - second_score}"],
            )

        # Moderate match: only one category has any hits
        if top_score >= 2 and second_score == 0:
            return RouterDecision(
                query_type=top_type,
                confidence=min(0.85, 0.5 + top_score * 0.08),
                reasons=[f"Sole keyword match: {top_type.value}={top_score}"],
            )

        # Ambiguous — fall through to next tier
        return None

    def _classify_embedding(self, query: str) -> Optional[RouterDecision]:
        """Tier 2: cosine similarity to anchor texts."""
        anchors = _get_anchor_embeddings()
        if not anchors:
            return None

        try:
            from llama_index.embeddings.google_genai import GoogleGenAIEmbedding
            from .config import EMBEDDING_MODEL, EMBEDDING_DIMENSION

            embed_model = GoogleGenAIEmbedding(
                api_key=GOOGLE_API_KEY,
                model_name=EMBEDDING_MODEL,
                embedding_config={"output_dimensionality": EMBEDDING_DIMENSION},
            )
            query_vec = embed_model.get_text_embedding(query)

            best_type = None
            best_sim = -1.0
            second_sim = -1.0
            reasons = []

            for qtype_val, anchor_vecs in anchors.items():
                avg_sim = sum(
                    _cosine_similarity(query_vec, av) for av in anchor_vecs
                ) / len(anchor_vecs) if anchor_vecs else 0.0

                reasons.append(f"{qtype_val}={avg_sim:.3f}")

                if avg_sim > best_sim:
                    second_sim = best_sim
                    best_sim = avg_sim
                    best_type = qtype_val
                elif avg_sim > second_sim:
                    second_sim = avg_sim

            margin = best_sim - second_sim
            logger.info(f"   Embedding sims: {', '.join(reasons)} | margin={margin:.3f}")

            if margin >= self.EMBEDDING_MARGIN and best_type is not None:
                return RouterDecision(
                    query_type=QueryType(best_type),
                    confidence=round(min(0.90, 0.6 + margin), 3),
                    reasons=[f"Embedding routing: {', '.join(reasons)}", f"margin={margin:.3f}"],
                )

        except Exception as e:
            logger.warning(f"   Embedding routing failed: {e}")

        return None

    def _classify_llm(self, query: str) -> RouterDecision:
        """Tier 3: LLM classification (last resort)."""
        from . import llm_client
        from .prompt_security import safe_render_prompt, build_system_prompt

        try:
            _, data_files = self._get_available_sources()

            prompt = safe_render_prompt(
                self.CLASSIFICATION_PROMPT,
                user_query=query,
                data_files=data_files,
            )
            system = build_system_prompt("You are a query classifier.")

            resp = llm_client.generate_text(prompt, system=system, max_tokens=16)
            result = resp.text.strip().upper()

            # Record telemetry
            from .telemetry import get_current_trace
            trace = get_current_trace()
            if trace:
                trace.record_llm_call(resp.usage)

            qtype = QueryType.DOCUMENT  # default
            if "DATA" in result:
                qtype = QueryType.DATA
            elif "TIMELINE" in result:
                qtype = QueryType.TIMELINE
            elif "HYBRID" in result:
                qtype = QueryType.HYBRID

            return RouterDecision(
                query_type=qtype,
                confidence=0.75,
                reasons=[f"LLM classified as {qtype.value}"],
                used_llm=True,
                llm_usage={
                    "prompt_tokens": resp.usage.prompt_tokens,
                    "completion_tokens": resp.usage.completion_tokens,
                    "cost": resp.usage.cost_estimate,
                },
            )

        except Exception as e:
            logger.error(f"   LLM classification error: {e}")
            # Fallback: pick based on what's available
            if self.data_analyzer.list_tables() and not self.document_rag.documents:
                qtype = QueryType.DATA
            else:
                qtype = QueryType.DOCUMENT
            return RouterDecision(
                query_type=qtype,
                confidence=0.5,
                reasons=[f"Fallback after LLM error: {e}"],
            )

    # ── Complex query detection ───────────────────────────────

    def _is_complex_query(self, query: str) -> bool:
        """Detect if a query requires multi-step planning."""
        q = query.lower()

        complex_indicators = [
            ' then ', ' and then ', ' after that ', ' next ',
            'group by', 'compare', 'outlier',
            'above average', 'below average',
            'month-over-month', 'year-over-year',
            'correlate', 'cross-reference', 'combined with',
        ]

        for indicator in complex_indicators:
            if indicator in q:
                return True

        # Cross-source: needs both doc + data
        has_doc = any(kw in q for kw in ['clause', 'contract', 'agreement', 'letter', 'notice'])
        has_data = any(kw in q for kw in ['calculate', 'total', 'average', 'count', 'amount', 'quantity'])
        if has_doc and has_data:
            return True

        return False

    # ── Query handlers ────────────────────────────────────────

    def _handle_document_query(self, query: str) -> Dict[str, Any]:
        """Handle document-based query."""
        logger.info("Routing to Document RAG...")
        result = self.document_rag.query(query)
        return {
            "query": query,
            "query_type": QueryType.DOCUMENT.value,
            "answer": result["answer"],
            "sources": result["sources"],
        }

    def _handle_data_query(self, query: str) -> Dict[str, Any]:
        """Handle data analysis query."""
        logger.info("Routing to SQL Data Analyzer...")
        result = self.data_analyzer.query(query)
        return {
            "query": query,
            "query_type": QueryType.DATA.value,
            "answer": result["answer"],
            "sources": result["sources"],
            "sql": result.get("sql"),
            "result_data": result.get("result_data"),
            "result_columns": result.get("result_columns"),
        }

    def _handle_hybrid_query(self, query: str) -> Dict[str, Any]:
        """Handle hybrid query needing both sources, using llm_client."""
        logger.info("Routing to BOTH handlers...")

        doc_result = self.document_rag.query(query)
        data_result = self.data_analyzer.query(query)

        # Synthesize with llm_client
        logger.info("   Synthesizing results...")
        try:
            from . import llm_client
            from .prompt_security import safe_render_prompt, build_system_prompt

            prompt = safe_render_prompt(
                self.HYBRID_SYNTHESIS_PROMPT,
                user_query=query,
                doc_results=doc_result["answer"],
                data_results=data_result["answer"],
            )
            system = build_system_prompt("You synthesize information from multiple sources.")

            resp = llm_client.generate_text(prompt, system=system)
            combined_answer = resp.text

            # Record telemetry
            from .telemetry import get_current_trace
            trace = get_current_trace()
            if trace:
                trace.record_llm_call(resp.usage)

        except Exception as e:
            logger.error(f"   Synthesis error: {e}")
            combined_answer = (
                f"**From Documents:**\n{doc_result['answer']}\n\n"
                f"**From Data Analysis:**\n{data_result['answer']}"
            )

        # Combine sources
        all_sources = []
        for s in doc_result.get("sources", []):
            s["source_type"] = "document"
            all_sources.append(s)
        for s in data_result.get("sources", []):
            s["source_type"] = "data"
            all_sources.append(s)

        return {
            "query": query,
            "query_type": QueryType.HYBRID.value,
            "answer": combined_answer,
            "sources": all_sources,
            "sql": data_result.get("sql"),
            "result_data": data_result.get("result_data"),
            "result_columns": data_result.get("result_columns"),
        }

    def _handle_timeline_query(self, query: str) -> Dict[str, Any]:
        """Handle timeline/notice-based query using light graph with enhanced capabilities."""
        logger.info("Routing to Timeline/Graph handler...")

        try:
            from .light_graph import get_light_graph
            from .notice_extractor import NOTICES_DIR
            import json

            graph = get_light_graph()

            # Expand jargon in query
            expanded_query = self.jargon.expand_query(query)
            query_lower = expanded_query.lower()

            # Parse query for filters
            results = []
            sources = []
            answer_prefix = ""

            # === Pattern matching for different query types ===

            # 1. Communication flow queries
            if any(kw in query_lower for kw in ['who sent', 'who received',
                                                   'correspondence', 'communication',
                                                   'from whom', 'sent to']):
                party = self._extract_party_from_query(query_lower)
                flow = graph.communication_flow(party=party)

                if flow:
                    answer_prefix = f"Communication flow{' for ' + party if party else ''}:\n\n"
                    answer_lines = [answer_prefix]
                    for i, record in enumerate(flow[:25], 1):
                        direction_arrow = "\u2192" if record['direction'] != 'incoming' else "\u2190"
                        cc_str = f" (CC: {', '.join(record['cc_list'][:2])})" if record.get('cc_list') else ""
                        actions_str = f" [{', '.join(record['actions'][:3])}]" if record.get('actions') else ""

                        answer_lines.append(
                            f"{i}. **{record['date']}** | {record['sender']} {direction_arrow} {record['recipient']}{cc_str}\n"
                            f"   {record.get('subject', '')[:80]}{actions_str}\n"
                        )
                        sources.append(self._build_source(record['doc_id'], record, NOTICES_DIR))

                    answer = "\n".join(answer_lines)
                    parties = graph.get_all_parties()
                    if parties:
                        answer += "\n**Active parties:**\n"
                        for p in parties[:10]:
                            answer += f"- {p['party']}: {p['sent_count']} sent, {p['received_count']} received\n"
                else:
                    answer = "No communication records found."

                return {"query": query, "query_type": QueryType.TIMELINE.value, "answer": answer, "sources": sources}

            # 2. Correspondence between two parties
            if any(kw in query_lower for kw in ['between']):
                parties = self._extract_two_parties(query_lower)
                if parties:
                    corr = graph.correspondence_between(parties[0], parties[1])
                    if corr:
                        answer_lines = [f"Correspondence between **{parties[0]}** and **{parties[1]}**:\n\n"]
                        for i, record in enumerate(corr[:25], 1):
                            answer_lines.append(
                                f"{i}. **{record['date']}** | {record['from']} \u2192 {record['to']}\n"
                                f"   {record.get('subject', '')[:80]}\n"
                            )
                            sources.append(self._build_source(record['node']['doc_id'], record['node'], NOTICES_DIR))
                        answer = "\n".join(answer_lines)
                    else:
                        answer = f"No correspondence found between {parties[0]} and {parties[1]}."
                    return {"query": query, "query_type": QueryType.TIMELINE.value, "answer": answer, "sources": sources}

            # 3. Project-based queries
            if any(kw in query_lower for kw in ['project', 'contract']):
                project_filter = self._extract_filter_term(query_lower, ['project'])
                contract_ref = self._extract_filter_term(query_lower, ['contract'])
                proj_docs = graph.project_documents(project_filter=project_filter, contract_ref=contract_ref)

                if proj_docs:
                    filter_label = project_filter or contract_ref or "all"
                    answer_prefix = f"Documents for project/contract **{filter_label}**:\n\n"
                    results = proj_docs
                else:
                    answer = "No documents found for the specified project/contract."
                    return {"query": query, "query_type": QueryType.TIMELINE.value, "answer": answer, "sources": sources}

            # 4. Action-based queries
            elif any(kw in query_lower for kw in ['delay']):
                delay_docs = graph.search_by_action('delay')
                results = [d['node'] for d in delay_docs]
                answer_prefix = "Documents mentioning delays:\n\n"

            elif any(kw in query_lower for kw in ['claim']):
                claim_docs = graph.search_by_action('claim')
                results = [d['node'] for d in claim_docs]
                answer_prefix = "Documents mentioning claims:\n\n"

            elif any(kw in query_lower for kw in ['approval', 'approve']):
                approve_docs = graph.search_by_action('approve')
                results = [d['node'] for d in approve_docs]
                answer_prefix = "Documents related to approvals:\n\n"

            elif any(kw in query_lower for kw in ['termination', 'terminate']):
                term_docs = graph.search_by_action('terminate')
                results = [d['node'] for d in term_docs]
                answer_prefix = "Documents related to termination:\n\n"

            # 5. Project analysis queries (via DocumentAgent)
            elif any(kw in query_lower for kw in ['analysis', 'insight', 'overview', 'issues',
                                                    'parties involved', 'participants', 'summary of project']):
                try:
                    from .document_agent import get_document_agent
                    agent = get_document_agent()
                    agent_result = agent.answer_project_question(query)
                    return {
                        "query": query,
                        "query_type": QueryType.TIMELINE.value,
                        "answer": agent_result.get("answer", "No analysis available."),
                        "sources": agent_result.get("sources", []),
                    }
                except Exception as e:
                    logger.warning(f"   DocumentAgent error: {e}")
                    results = graph.timeline()
                    answer_prefix = "Document overview:\n\n"

            # 6. All notices / list view
            elif any(kw in query_lower for kw in ['all notices', 'list notices', 'show notices']):
                results = graph.timeline()
                answer_prefix = "All documents in chronological order:\n\n"

            # 7. Chain/trace queries
            elif 'chain' in query_lower or 'trace' in query_lower:
                nodes = list(graph.graph.nodes.keys())
                if nodes:
                    chain = graph.trace_chain(nodes[0], depth=5)
                    results = [chain['start']] if chain['start'] else []
                    results.extend([item['node'] for item in chain['downstream']])
                    answer_prefix = f"Document chain starting from {nodes[0]}:\n\n"
                else:
                    answer_prefix = "No documents in graph.\n\n"

            # 8. Default: show timeline
            else:
                results = graph.timeline()
                answer_prefix = "Document timeline:\n\n"

            # Build answer from results
            if results:
                answer_lines = [answer_prefix]
                for i, node in enumerate(results[:25], 1):
                    date = node.get('date', 'No date')
                    sender = (node.get('sender') or 'Unknown')[:40]
                    recipient = (node.get('recipient') or 'Unknown')[:40]
                    subject = (node.get('subject') or '')[:80]
                    file_name = node.get('file_name', node.get('doc_id', 'Unknown'))
                    doc_type = node.get('doc_type', '')
                    actions = node.get('actions', [])
                    direction = node.get('direction', '')

                    type_badge = f" [{doc_type}]" if doc_type else ""
                    action_str = f" | Actions: {', '.join(actions[:3])}" if actions else ""
                    dir_str = f" ({direction})" if direction else ""

                    answer_lines.append(
                        f"{i}. **{date}** - {file_name}{type_badge}{dir_str}\n"
                        f"   From: {sender} \u2192 To: {recipient}\n"
                        f"   {subject}{action_str}\n"
                    )

                    sources.append(self._build_source(
                        node.get('doc_id'), node, NOTICES_DIR
                    ))

                answer = "\n".join(answer_lines)

                # Add graph stats
                stats = graph.get_statistics()
                answer += f"\n\n*Graph: {stats['node_count']} documents, {stats['edge_count']} relationships*"
            else:
                answer = "No notices found matching your query. Make sure documents have been processed with notice extraction enabled."

            return {
                "query": query,
                "query_type": QueryType.TIMELINE.value,
                "answer": answer,
                "sources": sources,
            }

        except ImportError as e:
            logger.error(f"   Timeline handler import error: {e}")
            return {
                "query": query,
                "query_type": QueryType.TIMELINE.value,
                "answer": "Timeline feature requires notice extraction. Please ensure documents are processed first.",
                "sources": [],
            }
        except Exception as e:
            logger.error(f"   Timeline query error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "query": query,
                "query_type": QueryType.TIMELINE.value,
                "answer": f"Error processing timeline query: {str(e)}",
                "sources": [],
            }

    # ── Helper methods ────────────────────────────────────────

    @staticmethod
    def _build_source(doc_id: str, node: Dict, notices_dir: Path) -> Dict[str, Any]:
        """Build source entry with evidence from notice file."""
        import json

        file_name = node.get('file_name', doc_id or 'Unknown')
        date = node.get('date', 'Unknown')
        sender = (node.get('sender') or 'Unknown')[:40]
        recipient = (node.get('recipient') or 'Unknown')[:40]

        evidence = []
        if doc_id:
            notice_path = notices_dir / f"{doc_id}.json"
            if notice_path.exists():
                try:
                    with open(notice_path, 'r', encoding='utf-8') as f:
                        notice_data = json.load(f)
                    evidence = notice_data.get('evidence_spans', [])[:3]
                except Exception:
                    pass

        return {
            "type": "notice",
            "file_name": file_name,
            "doc_id": doc_id,
            "date": date,
            "sender": sender,
            "recipient": recipient,
            "evidence": evidence,
        }

    @staticmethod
    def _extract_party_from_query(query_lower: str) -> Optional[str]:
        """Extract a party name from query text."""
        patterns = [
            r'(?:from|by|for)\s+"?([^"]+?)"?\s',
            r'(?:to)\s+"?([^"]+?)"?\s',
        ]
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_two_parties(query_lower: str) -> Optional[List[str]]:
        """Extract two party names from a between query."""
        patterns = [
            r'between\s+"?(.+?)"?\s+and\s+"?(.+?)"?(?:\s|$|\?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                return [match.group(1).strip(), match.group(2).strip()]
        return None

    @staticmethod
    def _extract_filter_term(query_lower: str, keywords: List[str]) -> Optional[str]:
        """Extract a filter term following a keyword."""
        for kw in keywords:
            match = re.search(rf'{kw}\s+"([^"]+)"', query_lower)
            if match:
                return match.group(1).strip()
            match = re.search(rf'{kw}\s+(\S+(?:\s+\S+)?)', query_lower)
            if match:
                term = match.group(1).strip()
                term = re.sub(r'[?.!,]+$', '', term)
                if len(term) > 2:
                    return term
        return None

    # ── Main entry point ──────────────────────────────────────

    def route_and_execute(self, query: str) -> Dict[str, Any]:
        """Classify and route query to appropriate handler.
        Complex queries are routed through the hybrid executor for multi-step planning.
        """
        from .telemetry import start_trace, finish_trace

        trace = start_trace(query)
        log_separator("Processing Query")
        logger.info(f"Query: {query[:100]}...")

        try:
            # Expand jargon
            expanded = self.jargon.expand_query(query)
            if expanded != query:
                logger.info(f"   Jargon expanded: {expanded[:100]}...")

            # Check if this is a complex multi-step query
            if self._is_complex_query(query):
                logger.info("   Detected complex query -> Hybrid Executor")
                trace.route = "HYBRID_COMPLEX"
                result = self.hybrid_executor.execute(query)
                logger.info(f"Query complete (hybrid) - {len(result.get('sources', []))} sources")
                return result

            # Classify with 3-tier strategy
            decision = self.classify_query(query)
            trace.route = decision.query_type.value.upper()
            if decision.llm_usage:
                trace.record_llm_call(LLMUsage(
                    prompt_tokens=decision.llm_usage.get("prompt_tokens", 0),
                    completion_tokens=decision.llm_usage.get("completion_tokens", 0),
                    cost_estimate=decision.llm_usage.get("cost", 0),
                ))

            logger.info(f"   Classified as: {decision.query_type.value.upper()} "
                        f"(conf={decision.confidence:.2f}, llm={decision.used_llm})")

            # Route to handler
            if decision.query_type == QueryType.DATA:
                result = self._handle_data_query(expanded)
            elif decision.query_type == QueryType.DOCUMENT:
                result = self._handle_document_query(expanded)
            elif decision.query_type == QueryType.TIMELINE:
                result = self._handle_timeline_query(query)
            else:  # HYBRID
                result = self._handle_hybrid_query(expanded)

            # Attach routing metadata
            result["routing"] = {
                "decision": decision.query_type.value,
                "confidence": decision.confidence,
                "reasons": decision.reasons,
                "used_llm": decision.used_llm,
            }

            logger.info(f"Query complete - {len(result.get('sources', []))} sources")
            return result

        finally:
            finish_trace()

    # ── Dual-LLM execution ───────────────────────────────────

    def route_and_execute_dual(self, query: str) -> Dict[str, Any]:
        """
        Classify query and execute with both OpenAI and Claude in parallel.
        Returns dual answers keyed by provider.
        """
        from .telemetry import start_trace, finish_trace

        trace = start_trace(query)
        log_separator("Processing Query (Dual-LLM)")
        logger.info(f"Query: {query[:100]}...")

        try:
            expanded = self.jargon.expand_query(query)
            if expanded != query:
                logger.info(f"   Jargon expanded: {expanded[:100]}...")

            # Complex query -> dual hybrid executor
            if self._is_complex_query(query):
                logger.info("   Detected complex query -> Hybrid Executor (Dual)")
                trace.route = "HYBRID_COMPLEX_DUAL"
                answers = self.hybrid_executor.execute_dual(query)
                return {
                    "query": query,
                    "query_type": "hybrid",
                    "answers": answers,
                    "routing": {"decision": "hybrid_complex", "confidence": 1.0,
                                "reasons": ["Complex multi-step query"], "used_llm": False},
                }

            # Classify once (uses existing 3-tier, no need to dual-head routing)
            decision = self.classify_query(query)
            trace.route = decision.query_type.value.upper() + "_DUAL"
            if decision.llm_usage:
                trace.record_llm_call(LLMUsage(
                    prompt_tokens=decision.llm_usage.get("prompt_tokens", 0),
                    completion_tokens=decision.llm_usage.get("completion_tokens", 0),
                    cost_estimate=decision.llm_usage.get("cost", 0),
                ))

            logger.info(f"   Classified as: {decision.query_type.value.upper()} "
                        f"(conf={decision.confidence:.2f})")

            # Route to dual handlers
            if decision.query_type == QueryType.DATA:
                answers = self.data_analyzer.query_dual(expanded)
            elif decision.query_type == QueryType.DOCUMENT:
                answers = self.document_rag.query_dual(expanded)
            elif decision.query_type == QueryType.TIMELINE:
                single = self._handle_timeline_query(query)
                answers = {"openai": single, "claude": single}
            else:  # HYBRID
                answers = self._handle_hybrid_query_dual(expanded)

            result = {
                "query": query,
                "query_type": decision.query_type.value,
                "answers": answers,
                "routing": {
                    "decision": decision.query_type.value,
                    "confidence": decision.confidence,
                    "reasons": decision.reasons,
                    "used_llm": decision.used_llm,
                },
            }

            logger.info("Query complete (dual-LLM)")
            return result

        finally:
            finish_trace()

    def _handle_hybrid_query_dual(self, query: str) -> Dict[str, Dict[str, Any]]:
        """Handle hybrid query with both providers in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .config import LLM_PROVIDERS

        def _run_hybrid(provider: str):
            doc_result = self.document_rag.query_with_provider(query, provider)
            data_result = self.data_analyzer.query_with_provider(query, provider)

            from . import llm_client
            from .prompt_security import safe_render_prompt, build_system_prompt

            try:
                prompt = safe_render_prompt(
                    self.HYBRID_SYNTHESIS_PROMPT,
                    user_query=query,
                    doc_results=doc_result["answer"],
                    data_results=data_result["answer"],
                )
                system = build_system_prompt("You synthesize information from multiple sources.")
                resp = llm_client.generate_text(prompt, system=system, provider=provider)
                combined_answer = resp.text
            except Exception as e:
                logger.error(f"   [{provider}] Hybrid synthesis error: {e}")
                combined_answer = (
                    f"**From Documents:**\n{doc_result['answer']}\n\n"
                    f"**From Data Analysis:**\n{data_result['answer']}"
                )

            all_sources = doc_result.get("sources", []) + data_result.get("sources", [])
            return {
                "answer": combined_answer,
                "sources": all_sources,
                "sql": data_result.get("sql"),
                "result_data": data_result.get("result_data"),
                "result_columns": data_result.get("result_columns"),
            }

        results = {}
        with ThreadPoolExecutor(max_workers=len(LLM_PROVIDERS)) as executor:
            futures = {executor.submit(_run_hybrid, p): p for p in LLM_PROVIDERS}
            for future in as_completed(futures):
                prov = futures[future]
                try:
                    results[prov] = future.result()
                except Exception as e:
                    logger.error(f"   [{prov}] Hybrid dual failed: {e}")
                    results[prov] = {"answer": f"Error from {prov}: {e}", "sources": []}

        return results


# Singleton
_router = None


def get_router() -> QueryRouter:
    """Get or create QueryRouter singleton."""
    global _router
    if _router is None:
        _router = QueryRouter()
    return _router
