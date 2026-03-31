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
    "machinery", "worker", "workers", "production", "floor", "block",
    "ipc", "boq", "activity", "activities", "types", "list all",
    # Construction-domain additions
    "show me all", "list all", "list the", "breakdown", "distribution", "utilization",
    "hours", "headcount", "productivity",
    "daily", "monthly", "weekly", "distinct", "unique",
    "how much", "what types", "what kind", "what are the",
    "trades", "craft", "crane", "excavator",
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
    # Clustering keywords
    "cluster", "group", "categorize", "document group",
}


# ── Embedding-similarity anchor texts ────────────────────────

_ANCHOR_TEXTS = {
    QueryType.DATA: [
        "Calculate the total amount from the spreadsheet",
        "How many rows match this filter condition",
        "What is the average value grouped by category",
        "Show me the maximum and minimum numbers in the table",
        "How many workers were deployed on Block A in January",
        "Total machinery hours by floor for the excavator",
        "List all activity types with their production quantities",
        "What is the breakdown of trades by block",
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

    CLASSIFICATION_PROMPT = (
        "You are a query router for a construction project management system.\n\n"
        "AVAILABLE FILES IN SYSTEM:\n{file_inventory}\n\n"
        "DATA TABLES (SQL queryable):\n{table_inventory}\n\n"
        "CATEGORIES — pick exactly ONE:\n"
        "- FILE_LIST: Questions about what files/documents exist, file counts, listing, deletion.\n"
        "  Examples: \"how many documents\", \"list all files\", \"show uploaded files\"\n\n"
        "- DATA: ANY question answerable from the DATA TABLES above. This is the PRIMARY category.\n"
        "  Route here if the query relates to ANY column name, table concept, or measurable metric.\n"
        "  Includes: calculations, aggregations, filtering, counting, listing entities, "
        "comparisons, trends, breakdowns, distributions, rankings, productivity, utilization.\n"
        "  CONSTRUCTION DATA examples:\n"
        "  - Equipment: \"crane hours\", \"equipment utilization\", \"machinery by block\"\n"
        "  - Manpower: \"how many workers\", \"trades deployed\", \"manpower by floor\", \"headcount\"\n"
        "  - Production: \"output per worker\", \"productivity\", \"quantification by activity\"\n"
        "  - Progress: \"overall progress\", \"IPC status\", \"BOQ completion\", \"remaining quantity\"\n"
        "  - Time-based: \"in January\", \"last month\", \"daily trend\", \"monthly comparison\"\n"
        "  - Location-based: \"on Block A\", \"which floor\", \"per block\"\n"
        "  - General: \"what types of\", \"list all\", \"show me\", \"how many\", \"breakdown of\"\n\n"
        "- DOCUMENT: Questions requiring reading document PROSE — contracts, clauses, terms, "
        "policies, specifications, scope definitions. The answer is TEXT from a document, not numbers.\n"
        "  Examples: \"what does clause 5 say\", \"explain liability terms\", \"summarize the contract\", "
        "\"what are the payment conditions\", \"scope of work definition\"\n\n"
        "- TIMELINE: Chronology, correspondence flow, notice sequences, who sent what when.\n"
        "  Examples: \"timeline of notices\", \"letters from contractor\", \"communication history\"\n\n"
        "- HYBRID: BOTH document prose AND table data needed in the SAME answer. Rare.\n"
        "  Examples: \"compare contract BOQ quantities with actual progress\", "
        "\"does production match the contractual requirements\"\n\n"
        "CRITICAL ROUTING RULES:\n"
        "1. ALWAYS prefer DATA if the query mentions any concept that exists in a DATA TABLE column "
        "(workers, hours, blocks, activities, equipment, production, progress, cost, quantity).\n"
        "2. 'How is Block A progressing?' = DATA (check IPC/production tables), NOT DOCUMENT.\n"
        "3. 'What equipment is being used?' = DATA (check equipment table), NOT DOCUMENT.\n"
        "4. 'What trades are on site?' = DATA (check manpower table), NOT DOCUMENT.\n"
        "5. Only use DOCUMENT when the answer is literally TEXT from a contract/report.\n"
        "6. Only use HYBRID when the user explicitly needs both document text AND table numbers.\n"
        "7. When in doubt: DATA > DOCUMENT > HYBRID.\n\n"
        "User query: {user_query}\n\n"
        "Respond with exactly ONE word: FILE_LIST, DATA, DOCUMENT, TIMELINE, or HYBRID."
    )

    HYBRID_SYNTHESIS_PROMPT = (
        "You are a construction project analyst combining contract/document information "
        "with actual project data to provide actionable insights.\n\n"
        "Do NOT invent facts - only use information from the sources below.\n\n"
        "QUESTION: {user_query}\n\n"
        "DOCUMENT/CONTRACT INFORMATION:\n{doc_results}\n\n"
        "ACTUAL PROJECT DATA:\n{data_results}\n\n"
        "Provide a comprehensive answer that:\n"
        "1. States what the contract/document specifies (the plan/requirement)\n"
        "2. States what the actual data shows (the reality)\n"
        "3. Highlights any gaps, discrepancies, or alignment between the two\n"
        "4. For quantities: compare contractual (BOQ) vs actual (cumulative) values\n"
        "5. For progress: compare planned milestones vs actual completion percentages\n"
        "6. Provides a clear conclusion: is the project on track, behind, or ahead?\n"
        "7. Is specific with numbers — always include actual values, not just 'higher' or 'lower'"
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
        self._schema_alias_cache: Dict[str, List[str]] = {}
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

    def _get_schema_aliases(self, target_schema: str) -> List[str]:
        """Load and cache schema column aliases (lowercase) for a given schema."""
        if target_schema in self._schema_alias_cache:
            return self._schema_alias_cache[target_schema]
        aliases = []
        try:
            import json
            schema_path = Path(__file__).parent.parent / "storage" / "schemas" / f"{target_schema}.json"
            if schema_path.exists():
                with open(schema_path) as f:
                    schema_def = json.load(f)
                for col_def in schema_def.get("columns", []):
                    for alias in col_def.get("aliases", []):
                        aliases.append(alias.lower())
        except Exception:
            pass
        self._schema_alias_cache[target_schema] = aliases
        return aliases

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

    def _get_classification_context(self) -> Tuple[str, str]:
        """Build rich context for LLM classifier: file inventory + table schemas."""
        from .document_registry import get_document_registry

        registry = get_document_registry()
        completed = registry.get_completed()

        # ── File inventory (grouped by type) ──
        emails = [r for r in completed if r.file_type == "email"]
        documents = [r for r in completed if r.file_type == "document"]
        data_files = [r for r in completed if r.file_type == "data"]

        file_lines = []
        if emails:
            names = ", ".join(r.file_name for r in emails[:10])
            extra = f" (+{len(emails) - 10} more)" if len(emails) > 10 else ""
            file_lines.append(f"Emails ({len(emails)}): {names}{extra}")
        if documents:
            names = ", ".join(r.file_name for r in documents[:10])
            extra = f" (+{len(documents) - 10} more)" if len(documents) > 10 else ""
            file_lines.append(f"Documents ({len(documents)}): {names}{extra}")
        if data_files:
            names = ", ".join(r.file_name for r in data_files[:10])
            extra = f" (+{len(data_files) - 10} more)" if len(data_files) > 10 else ""
            file_lines.append(f"Data files ({len(data_files)}): {names}{extra}")
        if not file_lines:
            # Fallback to RAG file registry
            if self.document_rag.file_registry:
                file_lines.append(
                    f"Files ({len(self.document_rag.file_registry)}): "
                    + ", ".join(list(self.document_rag.file_registry.keys())[:10])
                )
            else:
                file_lines.append("No files loaded.")
        file_inventory = "\n".join(file_lines)

        # ── Table inventory (name + columns + smart sampling for LLM awareness) ──
        tables = self.data_analyzer.list_tables()
        table_lines = []
        for tname in tables[:15]:
            info = self.data_analyzer.get_table_summary(tname)
            if info:
                cols = info.get("columns", [])
                dtypes = info.get("dtypes", {})
                row_count = info.get("row_count", 0)
                desc = info.get("description", "")
                tags = info.get("semantic_tags", [])

                line = f"- {tname} ({row_count} rows): columns = [{', '.join(cols)}]"
                if desc:
                    line += f"\n  Description: {desc}"
                if tags:
                    line += f"\n  Tags: {', '.join(tags[:6])}"

                # Smart sampling: show content based on column type
                try:
                    sample_parts = []
                    for col in cols:
                        dtype = str(dtypes.get(col, "VARCHAR")).upper()
                        is_numeric = any(t in dtype for t in [
                            "INT", "FLOAT", "DOUBLE", "DECIMAL", "BIGINT", "NUMBER",
                        ])
                        is_date = any(t in dtype for t in ["DATE", "TIMESTAMP", "TIME"])

                        if is_numeric:
                            # Numeric: show range (min-max)
                            try:
                                row = self.data_analyzer.conn.execute(
                                    f'SELECT MIN("{col}"), MAX("{col}") FROM {tname} '
                                    f'WHERE "{col}" IS NOT NULL'
                                ).fetchone()
                                if row and row[0] is not None:
                                    sample_parts.append(f'{col}=[{row[0]}..{row[1]}]')
                            except Exception:
                                pass
                        elif is_date:
                            # Date: show range
                            try:
                                row = self.data_analyzer.conn.execute(
                                    f'SELECT MIN("{col}"), MAX("{col}") FROM {tname} '
                                    f'WHERE "{col}" IS NOT NULL'
                                ).fetchone()
                                if row and row[0] is not None:
                                    sample_parts.append(f'{col}=[{row[0]}..{row[1]}]')
                            except Exception:
                                pass
                        else:
                            # Categorical/text: show ALL unique values up to 20
                            try:
                                count_row = self.data_analyzer.conn.execute(
                                    f'SELECT COUNT(DISTINCT "{col}") FROM {tname} '
                                    f'WHERE "{col}" IS NOT NULL'
                                ).fetchone()
                                n_unique = count_row[0] if count_row else 0

                                if n_unique <= 20:
                                    # Show all unique values
                                    uniques = self.data_analyzer.conn.execute(
                                        f'SELECT DISTINCT "{col}" FROM {tname} '
                                        f'WHERE "{col}" IS NOT NULL ORDER BY "{col}"'
                                    ).fetchall()
                                    vals = [str(r[0])[:40] for r in uniques]
                                    sample_parts.append(
                                        f'{col}=[{", ".join(vals)}] ({n_unique} values)'
                                    )
                                else:
                                    # High cardinality: show sample + count
                                    uniques = self.data_analyzer.conn.execute(
                                        f'SELECT DISTINCT "{col}" FROM {tname} '
                                        f'WHERE "{col}" IS NOT NULL LIMIT 10'
                                    ).fetchall()
                                    vals = [str(r[0])[:40] for r in uniques]
                                    sample_parts.append(
                                        f'{col}=[{", ".join(vals)}, ...] '
                                        f'({n_unique} unique values)'
                                    )
                            except Exception:
                                pass

                    if sample_parts:
                        line += "\n  Column details:\n    " + "\n    ".join(sample_parts)
                except Exception:
                    pass

                table_lines.append(line)
        table_inventory = "\n".join(table_lines) if table_lines else "No tables loaded."

        return file_inventory, table_inventory

    # ── Classification: 3-tier strategy (LLM-free by default) ──

    def classify_query(self, query: str) -> RouterDecision:
        """
        Classify query using 3-tier strategy:
          0. Regex pattern detection for THREAD / DRAFT (cheap, deterministic)
          1. Heuristic keyword scoring with schema-aware boost (no LLM)
          2. Embedding-similarity with anchor texts (no LLM)
          3. LLM classification with rich context (last resort)
        Returns RouterDecision with type, confidence, reasons.
        """
        logger.info("Classifying query...")

        # Expand abbreviations before any classification
        expanded_query = self.jargon.expand_query(query)
        if expanded_query != query:
            logger.info(f"   Jargon expanded: {expanded_query[:100]}...")

        query_lower = expanded_query.lower()

        # ── Tier 0: Thread/Draft pattern detection (deterministic) ──
        thread_decision = self._classify_thread_draft(query_lower)
        if thread_decision is not None:
            logger.info(f"   -> Pattern: {thread_decision.query_type.value.upper()} "
                        f"(conf={thread_decision.confidence:.2f})")
            return thread_decision

        # ── Tier 1: Heuristic keyword scoring (no LLM) ──
        heuristic_decision = self._classify_heuristic(query_lower)
        if heuristic_decision is not None:
            logger.info(f"   -> Heuristic: {heuristic_decision.query_type.value.upper()} "
                        f"(conf={heuristic_decision.confidence:.2f})")
            return heuristic_decision

        # ── Tier 2: Embedding similarity (no LLM) ──
        embedding_decision = self._classify_embedding(expanded_query)
        if embedding_decision is not None:
            logger.info(f"   -> Embedding: {embedding_decision.query_type.value.upper()} "
                        f"(conf={embedding_decision.confidence:.2f})")
            return embedding_decision

        # ── Tier 3: LLM classification with full context (last resort) ──
        decision = self._classify_llm_rich(query)
        logger.info(f"   -> LLM: {decision.query_type.value.upper()} "
                    f"(conf={decision.confidence:.2f})")
        return decision

    # Patterns for thread/draft/file-list detection
    _THREAD_PATTERNS = [
        r'(?:thread|conversation|correspondence|messages?|emails?)\s+(?:with|between|from)',
        r'(?:show|list|get)\s+(?:thread|conversation|correspondence|emails?|mail)',
    ]
    _DRAFT_PATTERNS = [
        r'(?:draft|write|prepare|compose)\s+(?:a\s+)?(?:reply|response|answer|letter)',
        r'(?:reply|respond)\s+to\s+',
    ]
    _FILE_LIST_PATTERNS = [
        r'(?:list|show|get|display)\s+(?:all\s+)?(?:files|documents|uploads)',
        r'(?:uploaded|indexed)\s+files?',
        r'(?:what|which)\s+files?\s+(?:are|have)',
        r'(?:how\s+many)\s+(?:documents?|files?)',
        r'(?:document|file)\s+(?:summary|overview|statistics|stats)',
        r'(?:which|what)\s+(?:documents?|files?)\s+(?:about|mention|related\s+to|regarding)\s+',
        r'(?:documents?|files?)\s+(?:about|on|regarding)\s+',
        r'(?:letters?|emails?)\s+(?:from|to|by)\s+',
    ]

    def _classify_thread_draft(self, query_lower: str) -> Optional[RouterDecision]:
        """Detect thread view or draft response requests via regex patterns.
        FILE_LIST detection removed — now handled by LLM classifier.
        """
        for pattern in self._THREAD_PATTERNS:
            if re.search(pattern, query_lower):
                return RouterDecision(
                    query_type=QueryType.THREAD,
                    confidence=0.95,
                    reasons=[f"Thread pattern matched: {pattern}"],
                )
        for pattern in self._DRAFT_PATTERNS:
            if re.search(pattern, query_lower):
                return RouterDecision(
                    query_type=QueryType.DRAFT,
                    confidence=0.95,
                    reasons=[f"Draft pattern matched: {pattern}"],
                )
        return None

    def _classify_heuristic(self, query_lower: str) -> Optional[RouterDecision]:
        """Tier 1: keyword-based scoring with schema-aware data boost."""
        data_score = sum(1 for kw in DATA_KEYWORDS if kw in query_lower)
        doc_score = sum(1 for kw in DOCUMENT_KEYWORDS if kw in query_lower)
        timeline_score = sum(1 for kw in TIMELINE_KEYWORDS if kw in query_lower)

        # Schema-aware boost: if query matches table column names or values, boost DATA
        schema_boost = self._schema_data_boost(query_lower)
        data_score += schema_boost

        scores = {
            QueryType.DATA: data_score,
            QueryType.DOCUMENT: doc_score,
            QueryType.TIMELINE: timeline_score,
        }

        logger.info(f"   Heuristic scores - Doc:{doc_score} Data:{data_score} "
                     f"(schema_boost:{schema_boost}) Timeline:{timeline_score}")

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

    def _schema_data_boost(self, query_lower: str) -> int:
        """Check if query terms match loaded table column names, schema aliases,
        or categorical values. Returns a boost score (0-3) to add to DATA score.
        """
        boost = 0
        try:
            tables = self.data_analyzer.list_tables()
            if not tables:
                return 0

            q_words = query_lower.split()

            for tname in tables:
                info = self.data_analyzer.get_table_summary(tname)
                if not info:
                    continue

                # Check column names
                for col in info.get('columns', []):
                    col_words = set(col.lower().replace('_', ' ').split())
                    if col_words & set(q_words):
                        boost += 1
                        break  # one boost per table for col name match

                # Check schema aliases from storage/schemas/*.json
                target_schema = info.get("header_metadata", {}).get("target_schema", "")
                if target_schema:
                    aliases = self._get_schema_aliases(target_schema)
                    for alias in aliases:
                        if alias in query_lower:
                            boost += 1
                            break  # one boost per schema for alias match

                # Check categorical column values (e.g. "steel fixer")
                dtypes = info.get('dtypes', {})
                for col in info.get('columns', []):
                    dtype = str(dtypes.get(col, "VARCHAR")).upper()
                    is_text = not any(t in dtype for t in [
                        "INT", "FLOAT", "DOUBLE", "DECIMAL", "BIGINT",
                        "NUMBER", "DATE", "TIMESTAMP", "TIME", "BOOL",
                    ])
                    if not is_text:
                        continue
                    try:
                        uniques = self.data_analyzer.conn.execute(
                            f'SELECT DISTINCT LOWER("{col}") FROM {tname} '
                            f'WHERE "{col}" IS NOT NULL LIMIT 50'
                        ).fetchall()
                        col_values = {str(r[0]) for r in uniques}
                        # n-gram matching: "steel fixer" in values
                        for n in range(1, min(4, len(q_words) + 1)):
                            for i in range(len(q_words) - n + 1):
                                ngram = ' '.join(q_words[i:i + n])
                                if len(ngram) < 3:
                                    continue
                                if any(ngram in v for v in col_values):
                                    boost += 2  # strong boost for value match
                                    return min(boost, 3)
                    except Exception:
                        pass

                if boost >= 3:
                    return 3
        except Exception:
            pass
        return min(boost, 3)

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

            # Default to DATA if tables loaded, DOCUMENT otherwise
            qtype = QueryType.DATA if self.data_analyzer.list_tables() else QueryType.DOCUMENT
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
            # Fallback: prefer DATA if tables are loaded
            qtype = QueryType.DATA if self.data_analyzer.list_tables() else QueryType.DOCUMENT
            return RouterDecision(
                query_type=qtype,
                confidence=0.5,
                reasons=[f"Fallback after LLM error: {e}"],
            )

    def _classify_llm_rich(self, query: str) -> RouterDecision:
        """Primary LLM classification with rich context (file inventory + table schemas)."""
        from . import llm_client
        from .prompt_security import safe_render_prompt, build_system_prompt

        try:
            file_inventory, table_inventory = self._get_classification_context()

            prompt = safe_render_prompt(
                self.CLASSIFICATION_PROMPT,
                user_query=query,
                file_inventory=file_inventory,
                table_inventory=table_inventory,
            )
            system = build_system_prompt("You are a precise query classifier.")

            resp = llm_client.generate_text(
                prompt, system=system, max_tokens=16,
                cache_key=None,  # Don't cache — context changes with uploads
            )
            result = resp.text.strip().upper()

            # Record telemetry
            from .telemetry import get_current_trace
            trace = get_current_trace()
            if trace:
                trace.record_llm_call(resp.usage)

            # Parse result — check FILE_LIST first (contains "DATA" substring)
            # Default to DATA if tables are loaded, DOCUMENT otherwise
            qtype = QueryType.DATA if self.data_analyzer.list_tables() else QueryType.DOCUMENT
            if "FILE_LIST" in result:
                qtype = QueryType.FILE_LIST
            elif "TIMELINE" in result:
                qtype = QueryType.TIMELINE
            elif "HYBRID" in result:
                qtype = QueryType.HYBRID
            elif "DATA" in result:
                qtype = QueryType.DATA

            logger.info(f"   LLM rich classified as: {qtype.value} (raw: {result})")

            return RouterDecision(
                query_type=qtype,
                confidence=0.85,
                reasons=[f"LLM classified as {qtype.value}"],
                used_llm=True,
                llm_usage={
                    "prompt_tokens": resp.usage.prompt_tokens,
                    "completion_tokens": resp.usage.completion_tokens,
                    "cost": resp.usage.cost_estimate,
                },
            )

        except Exception as e:
            logger.error(f"   LLM rich classification error: {e}")
            # Fallback: try heuristic
            decision = self._classify_heuristic(query.lower())
            if decision is not None:
                decision.reasons.append(f"Heuristic fallback after LLM error: {e}")
                return decision
            # Last resort: prefer DATA if tables are loaded
            qtype = QueryType.DATA if self.data_analyzer.list_tables() else QueryType.DOCUMENT
            return RouterDecision(
                query_type=qtype,
                confidence=0.5,
                reasons=[f"Fallback after LLM error: {e}"],
            )

    # ── Complex query detection ───────────────────────────────

    # ── Greeting detection ────────────────────────────────────

    GREETING_PATTERNS = {
        'hello', 'hi', 'hey', 'selam', 'merhaba', 'hola', 'bonjour',
        'good morning', 'good afternoon', 'good evening',
        'nasılsın', 'how are you', "what's up", 'whats up',
        'naber', 'sup', 'yo', 'hallo', 'greetings',
        'thanks', 'thank you', 'ok', 'okay', 'yes', 'no',
        'test', 'testing', 'ping',
    }

    def _is_greeting(self, query: str) -> bool:
        """Detect simple greetings that don't need routing."""
        q = query.strip().lower().rstrip('!?., ')
        # Remove chat context prefix if present
        if 'current question:' in q:
            q = q.split('current question:')[-1].strip().rstrip('!?., ')
        return q in self.GREETING_PATTERNS or (len(q) <= 3 and q.isalpha())

    def _build_greeting_response(self) -> Dict[str, Any]:
        """Build a construction-focused greeting with system capabilities."""
        tables = self.data_analyzer.list_tables()
        doc_count = len(self.document_rag.file_registry) if self.document_rag.file_registry else 0

        # Count table types
        schema_counts = {}
        for tname, info in self.data_analyzer.tables.items():
            if info.get("is_combined") or info.get("is_normalized"):
                continue
            schema = info.get("header_metadata", {}).get("target_schema", "other")
            schema_counts[schema] = schema_counts.get(schema, 0) + 1

        greeting = (
            "Welcome to **ConstructionIQ** — your intelligent construction project analytics platform.\n\n"
            "I analyze your project's **Excel data** (equipment logs, manpower reports, IPC certificates) "
            "and **documents** (contracts, letters, notices) to provide instant, data-driven insights.\n\n"
        )

        if tables or doc_count:
            greeting += "**Project Data Loaded:**\n"
            if doc_count:
                greeting += f"- {doc_count} documents indexed and searchable\n"
            if schema_counts.get("equipment_log"):
                greeting += f"- Equipment logs ({schema_counts['equipment_log']} files) — machinery hours, utilization tracking\n"
            if schema_counts.get("manpower_production"):
                greeting += f"- Manpower production logs ({schema_counts['manpower_production']} files) — workforce deployment, productivity\n"
            if schema_counts.get("ipc_sample"):
                greeting += f"- IPC/Progress certificates ({schema_counts['ipc_sample']} files) — BOQ, progress tracking\n"
            if tables:
                grouped = [t for t in tables if self.data_analyzer.tables.get(t, {}).get("is_grouped")]
                if grouped:
                    greeting += f"- {len(grouped)} consolidated dataset views for cross-file analysis\n"
            greeting += "\n"

        greeting += (
            "**Ask me anything about your project, for example:**\n"
            "- *\"What is the total number of workers by trade?\"*\n"
            "- *\"Show equipment utilization breakdown by block\"*\n"
            "- *\"What is the overall project progress percentage?\"*\n"
            "- *\"Which activities have zero progress?\"*\n"
            "- *\"Compare manpower deployment between Block A and Block B\"*\n"
            "- *\"What does the contract say about delay penalties?\"*\n\n"
            "Each query is answered by **three AI models** (Gemini, GPT, Claude) simultaneously "
            "so you can compare their analysis."
        )

        return {
            "answer": greeting,
            "query_type": QueryType.DOCUMENT.value,
            "sources": [],
        }

    def _is_complex_query(self, query: str) -> bool:
        """Detect if a query requires multi-step planning.
        Only triggers for genuinely sequential/multi-step queries.
        Cross-source detection is left to the LLM classifier.
        """
        q = query.lower()

        # Only truly sequential multi-step indicators
        sequential_indicators = [
            ' then ', ' and then ', ' after that ', ' next ',
            'month-over-month', 'year-over-year',
        ]

        for indicator in sequential_indicators:
            if indicator in q:
                return True

        return False

    # ── Query handlers ────────────────────────────────────────

    def _handle_document_query(self, query: str, doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Handle document-based query with metadata pre-filter."""
        # Jargon expansion for better RAG matching
        try:
            expanded = self.jargon.expand_query(query)
            if expanded != query:
                logger.info(f"[DocQuery] Jargon expanded: {query} → {expanded}")
                query = expanded
        except Exception as e:
            logger.warning(f"[DocQuery] Jargon expansion failed: {e}")
        logger.info("Routing to Document RAG...")

        # 1. DuckDB metadata search — find matching doc_ids from notices
        metadata_sources = []
        metadata_doc_ids = []
        try:
            from src.light_graph import get_light_graph
            graph = get_light_graph()
            meta_results = graph.search_by_topic(query, limit=20)
            if meta_results:
                metadata_doc_ids = [r["doc_id"] for r in meta_results if r.get("doc_id")]
                for r in meta_results:
                    file_name = r.get("file_name", "")
                    file_path = ""
                    total_pages = 1
                    try:
                        reg = self.document_rag.file_registry.get(file_name, {})
                        file_path = reg.get("file_path", "")
                        total_pages = reg.get("page_count", 1)
                    except Exception:
                        pass
                    metadata_sources.append({
                        "file_name": file_name,
                        "file_path": file_path,
                        "page_number": 1,
                        "total_pages": total_pages,
                        "doc_id": r.get("doc_id", ""),
                        "date": r.get("date", ""),
                        "sender": r.get("sender", ""),
                        "recipient": r.get("recipient", ""),
                        "subject": r.get("subject", ""),
                        "doc_type": r.get("doc_type", "document"),
                        "type": "notice",
                    })
                logger.info(f"Metadata pre-filter found {len(metadata_doc_ids)} docs")
        except Exception as e:
            logger.warning(f"Metadata search failed: {e}")

        # 2. RAG vector search — use metadata doc_ids as filter if available
        combined_ids = doc_ids or []
        if metadata_doc_ids and not combined_ids:
            combined_ids = metadata_doc_ids

        result = self.document_rag.query(query, doc_ids=combined_ids if combined_ids else None)

        # 3. Merge sources — metadata first, then RAG (deduplicated)
        rag_sources = result.get("sources", [])
        seen_files = {s.get("file_name") for s in metadata_sources}
        for rs in rag_sources:
            if rs.get("file_name") not in seen_files:
                metadata_sources.append(rs)
                seen_files.add(rs.get("file_name"))

        final_sources = metadata_sources if metadata_sources else rag_sources

        # 3b. Find related Excel/data tables for this topic
        try:
            related_tables = self.data_analyzer.select_tables(query, max_tables=3)
            for tname in related_tables:
                tinfo = self.data_analyzer.tables.get(tname, {})
                fname = tinfo.get("file_name", tname)
                if fname not in seen_files:
                    from .document_rag import generate_doc_id
                    fpath = self.data_analyzer.file_paths.get(tname, "")
                    final_sources.append({
                        "file_name": fname,
                        "file_path": fpath,
                        "doc_id": generate_doc_id(fpath) if fpath else "",
                        "type": "structured_data",
                        "doc_type": "data",
                        "table_name": tname,
                        "row_count": tinfo.get("row_count", 0),
                        "columns": tinfo.get("columns", [])[:5],
                    })
                    seen_files.add(fname)
        except Exception as e:
            logger.warning(f"Excel enrichment for doc query failed: {e}")

        # 4. If RAG answer is empty but we have metadata matches, generate summary
        answer = result.get("answer", "")
        if (not answer or "not found" in answer.lower() or "empty" in answer.lower()) and final_sources:
            doc_count = sum(1 for s in final_sources if s.get("type") != "structured_data")
            data_count = sum(1 for s in final_sources if s.get("type") == "structured_data")
            parts = []
            if doc_count:
                parts.append(f"**{doc_count}** related document(s)")
            if data_count:
                parts.append(f"**{data_count}** related Excel data source(s)")
            answer = f"Found {' and '.join(parts)}."

        return {
            "query": query,
            "query_type": QueryType.DOCUMENT.value,
            "answer": answer,
            "sources": final_sources,
        }

    def _handle_data_query(self, query: str, doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Handle data analysis query with related document enrichment.
        If the query references concepts from multiple tables, uses multi-table execution.
        """
        logger.info("Routing to SQL Data Analyzer...")
        allowed_tables = self.data_analyzer.get_tables_for_doc_ids(doc_ids) if doc_ids else None

        # Check if query needs multiple tables
        relevant = self.data_analyzer.select_tables(query, max_tables=3, allowed_tables=allowed_tables)
        if len(relevant) > 1:
            logger.info(f"   Multi-table query detected ({len(relevant)} tables)")
            result = self.hybrid_executor.execute_multi_table(query)
        else:
            result = self.data_analyzer.query(query, allowed_tables=allowed_tables)

        # Enrich with related documents (best-effort, non-blocking)
        all_sources = list(result.get("sources", []))
        all_sources.extend(self._fetch_related_doc_sources(query, doc_ids))

        return {
            "query": query,
            "query_type": QueryType.DATA.value,
            "answer": result["answer"],
            "sources": all_sources,
            "sql": result.get("sql"),
            "result_data": result.get("result_data"),
            "result_columns": result.get("result_columns"),
        }

    def _fetch_related_doc_sources(
        self, query: str, doc_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch related document sources for enriching DATA query responses.
        Returns notice metadata (RelatedDoc) + RAG citations (Citation).
        Best-effort: failures are logged but don't break the data query.
        """
        related_sources: List[Dict[str, Any]] = []
        seen_files: set = set()

        # 1. Light graph metadata search (fast, local DuckDB)
        try:
            from src.light_graph import get_light_graph
            graph = get_light_graph()
            meta_results = graph.search_by_topic(query, limit=5)
            for r in meta_results:
                file_name = r.get("file_name", "")
                if not file_name or file_name in seen_files:
                    continue
                seen_files.add(file_name)

                file_path = ""
                total_pages = 1
                try:
                    reg = self.document_rag.file_registry.get(file_name, {})
                    file_path = reg.get("file_path", "")
                    total_pages = reg.get("page_count", 1)
                except Exception:
                    pass

                related_sources.append({
                    "file_name": file_name,
                    "file_path": file_path,
                    "page_number": 1,
                    "total_pages": total_pages,
                    "doc_id": r.get("doc_id", ""),
                    "date": r.get("date", ""),
                    "sender": r.get("sender", ""),
                    "recipient": r.get("recipient", ""),
                    "subject": r.get("subject", ""),
                    "doc_type": r.get("doc_type", "document"),
                    "type": "notice",
                })
            if meta_results:
                logger.info(f"[DataQuery] Found {len(meta_results)} related notices")
        except Exception as e:
            logger.warning(f"[DataQuery] Related doc metadata search failed: {e}")

        # 2. RAG vector search (Pinecone, low top_k for speed)
        try:
            rag_result = self.document_rag.query(query, top_k=3, doc_ids=doc_ids)
            for rs in rag_result.get("sources", []):
                file_name = rs.get("file_name", "")
                if file_name in seen_files:
                    continue
                seen_files.add(file_name)
                related_sources.append(rs)
            rag_count = len(rag_result.get("sources", []))
            if rag_count:
                logger.info(f"[DataQuery] Found {rag_count} RAG citation(s)")
        except Exception as e:
            logger.warning(f"[DataQuery] Related doc RAG search failed: {e}")

        return related_sources

    def _handle_hybrid_query(self, query: str, doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Handle hybrid query needing both sources, using llm_client."""
        logger.info("Routing to BOTH handlers...")

        doc_result = self.document_rag.query(query, doc_ids=doc_ids)
        allowed_tables = self.data_analyzer.get_tables_for_doc_ids(doc_ids) if doc_ids else None
        data_result = self.data_analyzer.query(query, allowed_tables=allowed_tables)

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

    def _handle_file_list_query(self, query: str, doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Handle file list, topic search, document stats, and delete queries."""
        logger.info("Routing to File List handler...")
        q = query.lower()

        # 0. Delete intent detection
        delete_match = re.search(
            r'(?:sil|delete|kaldır|remove|çıkar)\s+["\']?(.+?)["\']?\s*$',
            q, re.IGNORECASE,
        )
        if delete_match:
            return self._handle_delete_query(delete_match.group(1).strip(), query)

        # 1. Topic-based document search (EN + TR patterns)
        topic_match = re.search(
            r'(?:about|mention|related\s+to|regarding|on'
            r'|hakkında|ilgili|konulu|konusunda|ile\s+ilgili)\s+(.+?)(?:\?|$)',
            q, re.IGNORECASE,
        )
        sender_match = re.search(
            r'(?:letters?|emails?|documents?|dosya|doküman|belge)\s+(?:from|by)\s+(.+?)(?:\?|$)',
            q, re.IGNORECASE,
        )
        # Possessive pattern: "Kevin Keith's emails", "John's documents about X"
        possessive_match = not topic_match and not sender_match and re.search(
            r"([\w][\w\s]*?)'s\s+(?:emails?|letters?|documents?|files?|mails?|correspondence)",
            q, re.IGNORECASE,
        )
        # Turkish: "X dokümanları", "X dosyaları", "X excelleri"
        tr_topic_match = not topic_match and not sender_match and not possessive_match and re.search(
            r'(.+?)\s+(?:doküman|dosya|belge|excel|döküman)(?:lar|ler)?(?:ı|i|ını|ini)?\s*(?:\?|$)',
            q, re.IGNORECASE,
        )

        if topic_match or sender_match or possessive_match or tr_topic_match:
            if topic_match:
                topic = topic_match.group(1).strip()
                label = f"about '{topic}'"
            elif sender_match:
                topic = sender_match.group(1).strip()
                label = f"from '{topic}'"
            elif possessive_match:
                topic = possessive_match.group(1).strip()
                label = f"from/to '{topic}'"
            else:
                topic = tr_topic_match.group(1).strip()
                label = f"about '{topic}'"

            results = self._unified_document_search(topic)

            if results:
                ext_icons = {
                    ".pdf": "PDF", ".xlsx": "Excel", ".xls": "Excel",
                    ".csv": "CSV", ".docx": "Word", ".doc": "Word",
                    ".txt": "Text", ".eml": "Email", ".msg": "Email",
                }
                type_icons = {"document": "PDF", "data": "Excel", "email": "Email"}

                lines = [f"**Found {len(results)} file(s) {label}:**\n"]
                for i, r in enumerate(results, 1):
                    ext = r.get("extension", "")
                    icon = ext_icons.get(ext, type_icons.get(r.get("file_type", ""), "File"))
                    date_str = f" ({r['date']})" if r.get("date") else ""
                    sender_str = f" — From: {r['sender']}" if r.get("sender") else ""
                    lines.append(f"{i}. **[{icon}]** {r['file_name']}{date_str}{sender_str}")
                    if r.get("subject"):
                        lines.append(f"   {r['subject']}")
                    elif r.get("description"):
                        lines.append(f"   {r['description']}")
                    if r.get("semantic_tags"):
                        lines.append(f"   Tags: {', '.join(r['semantic_tags'][:5])}")

                sources = [
                    {
                        "doc_id": r.get("doc_id", ""),
                        "file_name": r.get("file_name", ""),
                        "file_path": r.get("file_path", ""),
                        "file_type": r.get("file_type", ""),
                        "extension": r.get("extension", ""),
                        "date": r.get("date", ""),
                        "sender": r.get("sender", ""),
                        "subject": r.get("subject", ""),
                        "description": r.get("description", ""),
                        "type": "search_result",
                    }
                    for r in results
                ]
            else:
                lines = [f"No files found {label}."]
                sources = []

            return {
                "query": query,
                "query_type": QueryType.FILE_LIST.value,
                "answer": "\n".join(lines),
                "sources": sources,
            }

        # 2. Document stats query
        stats_match = re.search(
            r'(?:how\s+many|count|total|statistics|stats|summary|overview)',
            q, re.IGNORECASE,
        )
        if stats_match:
            from .document_registry import get_document_registry
            from .light_graph import get_light_graph
            registry = get_document_registry()
            graph = get_light_graph()

            # Hydrate registry from existing sources if empty
            all_docs = registry.get_all()
            if not all_docs:
                self._hydrate_registry(registry)
                all_docs = registry.get_all()

            completed = [r for r in all_docs if r.status == "completed"]
            graph_stats = graph.get_document_stats()

            lines = [f"**Document Library Overview:**\n"]
            lines.append(f"- **Total files:** {len(completed)}")

            # Breakdown by file type
            by_type: Dict[str, int] = {}
            total_tables = 0
            for rec in completed:
                by_type[rec.file_type] = by_type.get(rec.file_type, 0) + 1
                total_tables += len(rec.table_names)

            if by_type:
                lines.append(f"\n**By type:**")
                type_labels = {"document": "Documents", "data": "Data files", "email": "Emails"}
                for ftype, count in by_type.items():
                    label = type_labels.get(ftype, ftype.title())
                    lines.append(f"  - {label}: {count}")

            if total_tables:
                lines.append(f"- **Total data tables:** {total_tables}")

            # Graph stats (notices)
            if graph_stats.get("total_documents"):
                lines.append(f"- **Documents with notices:** {graph_stats['total_documents']}")
                lines.append(f"- **Relationships:** {graph_stats['total_edges']}")

            if graph_stats.get("date_range"):
                dr = graph_stats["date_range"]
                lines.append(f"- **Date range:** {dr.get('earliest', '')} to {dr.get('latest', '')}")

            if graph_stats.get("by_sender"):
                lines.append(f"\n**Top senders:**")
                for sender, count in list(graph_stats["by_sender"].items())[:5]:
                    lines.append(f"  - {sender}: {count}")

            return {
                "query": query,
                "query_type": QueryType.FILE_LIST.value,
                "answer": "\n".join(lines),
                "sources": [],
            }

        # 3. Default: list all files from DocumentRegistry
        from .document_registry import get_document_registry
        registry = get_document_registry()

        # Hydrate registry from existing sources if empty
        all_docs = registry.get_all()
        if not all_docs:
            self._hydrate_registry(registry)
            all_docs = registry.get_all()

        completed = [r for r in all_docs if r.status == "completed"]

        if not completed:
            return {
                "query": query,
                "query_type": QueryType.FILE_LIST.value,
                "answer": "No files uploaded yet. Please upload files first.",
                "sources": [],
            }

        # Build formatted answer
        ext_icons = {
            ".pdf": "PDF", ".xlsx": "Excel", ".xls": "Excel",
            ".csv": "CSV", ".docx": "Word", ".doc": "Word",
            ".txt": "Text", ".eml": "Email", ".msg": "Email",
        }
        type_icons = {"document": "PDF", "email": "Email", "data": "Excel"}

        lines = [f"**Found {len(completed)} file(s):**\n"]
        for i, rec in enumerate(completed, 1):
            meta_parts = []
            if rec.table_names:
                meta_parts.append(f"{len(rec.table_names)} tables")
            if rec.notice_extracted:
                meta_parts.append("notice extracted")
            if rec.file_size_kb:
                meta_parts.append(f"{rec.file_size_kb} KB")
            meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
            icon = ext_icons.get(rec.extension, type_icons.get(rec.file_type, "File"))
            lines.append(f"{i}. **[{icon}]** {rec.file_name}{meta}")

        return {
            "query": query,
            "query_type": QueryType.FILE_LIST.value,
            "answer": "\n".join(lines),
            "sources": [],
        }

    def _handle_delete_query(self, file_hint: str, original_query: str) -> Dict[str, Any]:
        """Handle file deletion requests from chat."""
        from .document_registry import get_document_registry
        registry = get_document_registry()

        # Hydrate if needed
        all_docs = registry.get_all()
        if not all_docs:
            self._hydrate_registry(registry)
            all_docs = registry.get_all()

        completed = [r for r in all_docs if r.status == "completed"]
        if not completed:
            return {
                "query": original_query,
                "query_type": QueryType.FILE_LIST.value,
                "answer": "No files to delete. The library is empty.",
                "sources": [],
            }

        # Find matching file(s) by name (fuzzy substring match)
        hint_lower = file_hint.lower()
        matches = [r for r in completed if hint_lower in r.file_name.lower()]

        if not matches:
            file_list = "\n".join(f"- {r.file_name}" for r in completed[:20])
            return {
                "query": original_query,
                "query_type": QueryType.FILE_LIST.value,
                "answer": f"No file matching **\"{file_hint}\"** found.\n\n**Available files:**\n{file_list}",
                "sources": [],
            }

        if len(matches) > 1:
            match_list = "\n".join(f"- {r.file_name}" for r in matches)
            return {
                "query": original_query,
                "query_type": QueryType.FILE_LIST.value,
                "answer": f"Multiple files match **\"{file_hint}\"**. Please be more specific:\n\n{match_list}",
                "sources": [],
            }

        # Single match — delete it
        target = matches[0]
        from .file_router import delete_document
        result = delete_document(target.doc_id)

        parts = [f"**{target.file_name}** has been deleted."]
        if result.get("tables_dropped"):
            parts.append(f"- {result['tables_dropped']} database tables removed")
        if result.get("catalog_cleaned"):
            parts.append("- Catalog entry cleaned")
        if result.get("rag_cleaned"):
            parts.append("- Search index cleaned")
        if result.get("notice_cleaned"):
            parts.append("- Notice data removed")
        if result.get("file_deleted"):
            parts.append("- Source file removed from disk")

        return {
            "query": original_query,
            "query_type": QueryType.FILE_LIST.value,
            "answer": "\n".join(parts),
            "sources": [],
        }

    def _unified_document_search(self, topic: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search across all sources: light_graph notices + catalog data files + registry fallback.

        Returns unified results sorted by date DESC with file_path for clickability.
        """
        from .document_registry import get_document_registry
        results: List[Dict[str, Any]] = []
        seen_doc_ids: set = set()
        registry = get_document_registry()

        # 1. Light graph: notices (richest metadata)
        try:
            from .light_graph import get_light_graph
            graph = get_light_graph()
            notice_results = graph.search_by_topic(topic, limit=limit)
            for r in notice_results:
                doc_id = r.get("doc_id", "")
                if not doc_id or doc_id in seen_doc_ids:
                    continue
                seen_doc_ids.add(doc_id)
                # Resolve file_path from registry
                file_path = ""
                rec = registry.get(doc_id)
                if rec:
                    file_path = rec.file_path
                elif self.document_rag and hasattr(self.document_rag, 'file_registry'):
                    for _fn, info in self.document_rag.file_registry.items():
                        if info.get("doc_id") == doc_id:
                            file_path = info.get("file_path", "")
                            break

                fname = r.get("file_name", "")
                results.append({
                    "doc_id": doc_id,
                    "file_name": fname,
                    "file_path": file_path,
                    "file_type": "document",
                    "extension": Path(fname).suffix.lower() if fname else "",
                    "date": r.get("date", ""),
                    "sender": r.get("sender", ""),
                    "subject": r.get("subject", ""),
                    "description": r.get("subject", ""),
                    "semantic_tags": [],
                    "source": "notice",
                })
        except Exception as e:
            logger.warning(f"[Search] Light graph search failed: {e}")

        # 2. Catalog: Excel/data files (semantic_tags, descriptions)
        try:
            from .catalog import get_catalog
            catalog = get_catalog()
            catalog_results = catalog.search_by_keyword(topic, limit=limit)
            for cr in catalog_results:
                doc_id = cr.get("doc_id", "")
                if not doc_id or doc_id in seen_doc_ids:
                    continue
                seen_doc_ids.add(doc_id)
                results.append({
                    "doc_id": doc_id,
                    "file_name": cr.get("file_name", ""),
                    "file_path": cr.get("file_path", ""),
                    "file_type": cr.get("file_type", "data"),
                    "extension": cr.get("extension", ""),
                    "date": cr.get("date", ""),
                    "sender": "",
                    "subject": "",
                    "description": cr.get("description", ""),
                    "semantic_tags": cr.get("semantic_tags", []),
                    "source": "catalog",
                })
        except Exception as e:
            logger.warning(f"[Search] Catalog search failed: {e}")

        # 3. Registry fallback: filename match
        try:
            name_matches = registry.search_by_name(topic)
            for rec in name_matches:
                if rec.doc_id in seen_doc_ids:
                    continue
                seen_doc_ids.add(rec.doc_id)
                results.append({
                    "doc_id": rec.doc_id,
                    "file_name": rec.file_name,
                    "file_path": rec.file_path,
                    "file_type": rec.file_type,
                    "extension": rec.extension,
                    "date": rec.completed_at[:10] if rec.completed_at else "",
                    "sender": "",
                    "subject": "",
                    "description": "",
                    "semantic_tags": [],
                    "source": "registry",
                })
        except Exception as e:
            logger.warning(f"[Search] Registry search failed: {e}")

        # Sort by date DESC (notice date first, then catalog date, then created_at)
        results.sort(key=lambda x: x.get("date", ""), reverse=True)
        return results[:limit]

    def _hydrate_registry(self, registry) -> None:
        """Hydrate DocumentRegistry from existing RAG file_registry + catalog entries."""
        rag_reg = {}
        if self.document_rag and hasattr(self.document_rag, 'file_registry'):
            rag_reg = self.document_rag.file_registry

        catalog_entries = {}
        try:
            from .catalog import get_catalog
            catalog_entries = get_catalog().entries
        except Exception as e:
            logger.warning(f"[Router] Catalog load failed: {e}")

        if rag_reg or catalog_entries:
            registry.hydrate_from_existing(rag_reg, catalog_entries)

    def _handle_thread_query(self, query: str) -> Dict[str, Any]:
        """Handle correspondence thread queries."""
        logger.info("Routing to Thread handler...")
        try:
            from .thread_builder import get_thread_builder
            builder = get_thread_builder()
            query_lower = query.lower()

            # Try to extract two parties (e.g., "thread between X and Y")
            parties = self._extract_two_parties(query_lower)
            if parties:
                thread = builder.get_thread_between(parties[0], parties[1])
                if thread.messages:
                    answer_lines = [
                        f"**Correspondence: {thread.party_a} ↔ {thread.party_b}** "
                        f"({len(thread.messages)} messages)\n"
                    ]
                    sources = []
                    for msg in thread.messages:
                        actions_str = f" **[{', '.join(msg.actions)}]**" if msg.actions else ""
                        answer_lines.append(
                            f"---\n"
                            f"**{msg.date}** | {msg.sender} → {msg.recipient}\n"
                            f"Subject: {msg.subject}{actions_str}\n"
                        )
                        if msg.body_preview:
                            answer_lines.append(f"> {msg.body_preview[:200]}\n")

                        # Build clickable source for each message
                        src = {
                            "type": "thread_message",
                            "file_name": msg.file_name,
                            "date": msg.date,
                            "sender": msg.sender,
                            "recipient": msg.recipient,
                            "subject": msg.subject,
                            "highlight_text": (msg.body_preview or "")[:200],
                        }
                        # Lookup file_path from RAG file_registry
                        reg = self.document_rag.file_registry.get(msg.file_name, {})
                        src["file_path"] = reg.get("file_path", "")
                        src["page_number"] = 1
                        src["total_pages"] = reg.get("page_count", 1)
                        sources.append(src)

                    return {
                        "query": query,
                        "query_type": QueryType.THREAD.value,
                        "answer": "\n".join(answer_lines),
                        "sources": sources,
                        "thread": thread,
                    }
                return {
                    "query": query,
                    "query_type": QueryType.THREAD.value,
                    "answer": f"No correspondence found between {parties[0]} and {parties[1]}.",
                    "sources": [],
                }

            # Try to extract single party (e.g., "thread with X")
            party = self._extract_party_from_query(query_lower)
            if party:
                threads = builder.find_threads(party)
                if threads:
                    answer_lines = [f"**Threads involving {party}:** ({len(threads)} threads)\n"]
                    sources = []
                    for t in threads:
                        msg_count = len(t.messages)
                        latest = t.messages[-1] if t.messages else None
                        latest_str = f" | Latest: {latest.date}" if latest else ""
                        answer_lines.append(
                            f"- **{t.party_b}** ({msg_count} messages{latest_str})"
                        )
                        # Add latest message as clickable source
                        if latest:
                            src = {
                                "type": "thread_message",
                                "file_name": latest.file_name,
                                "date": latest.date,
                                "sender": latest.sender,
                                "recipient": latest.recipient,
                                "subject": latest.subject,
                                "highlight_text": (latest.body_preview or "")[:200],
                            }
                            reg = self.document_rag.file_registry.get(latest.file_name, {})
                            src["file_path"] = reg.get("file_path", "")
                            src["page_number"] = 1
                            src["total_pages"] = reg.get("page_count", 1)
                            sources.append(src)

                    return {
                        "query": query,
                        "query_type": QueryType.THREAD.value,
                        "answer": "\n".join(answer_lines),
                        "sources": sources,
                    }
                return {
                    "query": query,
                    "query_type": QueryType.THREAD.value,
                    "answer": f"No threads found for '{party}'.",
                    "sources": [],
                }

            return {
                "query": query,
                "query_type": QueryType.THREAD.value,
                "answer": "Please specify a party name. Example: 'thread with ABC Company'",
                "sources": [],
            }
        except Exception as e:
            logger.error(f"Thread query error: {e}")
            return {
                "query": query,
                "query_type": QueryType.THREAD.value,
                "answer": f"Error processing thread query: {e}",
                "sources": [],
            }

    def _handle_draft_query(self, query: str) -> Dict[str, Any]:
        """Handle draft response generation queries."""
        logger.info("Routing to Draft handler...")
        try:
            from .thread_builder import get_thread_builder
            from .content_generator import draft_reply
            builder = get_thread_builder()
            query_lower = query.lower()

            # Extract parties from query
            parties = self._extract_two_parties(query_lower)
            if parties:
                thread = builder.get_thread_between(parties[0], parties[1])
            else:
                party = self._extract_party_from_query(query_lower)
                if party:
                    threads = builder.find_threads(party)
                    thread = threads[0] if threads else None
                else:
                    # Use latest unanswered
                    unanswered = builder.get_latest_unanswered()
                    if unanswered:
                        msg = unanswered[0]
                        from .thread_builder import CorrespondenceThread
                        thread = CorrespondenceThread(
                            party_a=msg.recipient,
                            party_b=msg.sender,
                            messages=[msg],
                        )
                    else:
                        thread = None

            if not thread or not thread.messages:
                return {
                    "query": query,
                    "query_type": QueryType.DRAFT.value,
                    "answer": "No thread found to draft a reply for. "
                              "Please specify parties, e.g., 'draft reply to ABC Company'.",
                    "sources": [],
                }

            # Extract optional instruction from query
            instruction = ""
            instruction_keywords = ["saying", "stating", "accepting", "rejecting",
                                    "regarding", "about", "for"]
            for kw in instruction_keywords:
                idx = query_lower.find(kw)
                if idx > 0:
                    instruction = query[idx + len(kw):].strip()
                    break

            draft = draft_reply(thread, instruction=instruction)

            answer = (
                f"**Draft Reply** ({thread.party_a} → {thread.party_b})\n\n"
                f"---\n\n{draft}\n\n---\n\n"
                f"*This is an auto-generated draft. Please review and edit before sending.*"
            )

            return {
                "query": query,
                "query_type": QueryType.DRAFT.value,
                "answer": answer,
                "sources": [],
            }
        except Exception as e:
            logger.error(f"Draft query error: {e}")
            return {
                "query": query,
                "query_type": QueryType.DRAFT.value,
                "answer": f"Error generating draft: {e}",
                "sources": [],
            }

    # ── Compound intent parsing ─────────────────────────────────

    _SEMANTIC_KEYWORDS = {
        "delay": "delay", "delays": "delay", "delayed": "delay",
        "notice of delay": "delay", "extension of time": "delay", "eot": "delay",
        "claim": "claim", "claims": "claim", "claiming": "claim",
        "notice of claim": "claim",
        "approval": "approval", "approvals": "approval", "approve": "approval",
        "variation": "variation", "change order": "variation",
        "payment": "payment", "invoice": "payment",
        "termination": "termination", "terminate": "termination",
        "suspension": "termination", "suspend": "termination",
        "progress": "progress",
        "quality": "quality", "defect": "quality", "inspection": "quality",
    }

    _SCOPE_KEYWORDS = {
        "correspondence": "correspondence", "letter": "correspondence",
        "letters": "correspondence", "communication": "correspondence",
        "communications": "correspondence",
        "notice": "notice", "notices": "notice",
        "email": "email", "emails": "email",
        "report": "report", "reports": "report",
        "contract": "contract", "agreement": "contract",
        "minutes": "minutes", "meeting": "minutes",
    }

    def _parse_compound_intent(self, query_lower: str) -> Dict[str, Optional[str]]:
        """
        Extract semantic filter (what to find) and scope filter (where to look)
        from a query.

        Example:
            "what are the delay events in the correspondence"
            -> {"semantic": "delay", "scope": "correspondence"}

        Returns:
            Dict with 'semantic' and 'scope' keys (values may be None)
        """
        semantic = None
        scope = None

        # Check multi-word keywords first (longer matches take priority)
        for kw in sorted(self._SEMANTIC_KEYWORDS, key=len, reverse=True):
            if kw in query_lower:
                semantic = self._SEMANTIC_KEYWORDS[kw]
                break

        for kw in sorted(self._SCOPE_KEYWORDS, key=len, reverse=True):
            if kw in query_lower:
                scope = self._SCOPE_KEYWORDS[kw]
                break

        return {"semantic": semantic, "scope": scope}

    def _build_compound_answer(
        self,
        query: str,
        intent: Dict[str, Optional[str]],
        matched_docs: List[Dict[str, Any]],
        rag_result: Optional[Dict[str, Any]],
    ) -> str:
        """Build answer combining metadata listing with RAG content."""
        semantic = intent.get("semantic", "")
        scope = intent.get("scope", "")

        lines = [f"Found **{len(matched_docs)}** {scope or 'document'}(s) related to **{semantic}**:\n"]

        for i, doc in enumerate(matched_docs[:20], 1):
            date = doc.get("date", "No date")
            sender = (doc.get("sender") or "Unknown")[:40]
            recipient = (doc.get("recipient") or "Unknown")[:40]
            subject = (doc.get("subject") or "")[:80]
            doc_type = doc.get("doc_type", "")
            actions = doc.get("actions", "")
            if isinstance(actions, list):
                actions = ", ".join(actions)

            type_badge = f" [{doc_type}]" if doc_type else ""
            action_str = f" | Actions: {actions}" if actions else ""

            lines.append(
                f"{i}. **{date}** - {doc.get('file_name', 'Unknown')}{type_badge}\n"
                f"   {sender} \u2192 {recipient}\n"
                f"   {subject}{action_str}\n"
            )

        # Append RAG content if available
        rag_answer = (rag_result or {}).get("answer", "")
        if rag_answer and "not found" not in rag_answer.lower() and "no documents" not in rag_answer.lower():
            lines.append(f"\n---\n**Detail from document content:**\n\n{rag_answer}")

        return "\n".join(lines)

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

            # === Cluster queries ===
            cluster_keywords = ["cluster", "group", "document group", "categorize"]
            if any(kw in query_lower for kw in cluster_keywords):
                # Try to extract a specific cluster name
                cluster_name = None
                for kw in ["about", "related to", "regarding"]:
                    if kw in query_lower:
                        cluster_name = query_lower.split(kw)[-1].strip().rstrip("?.")
                        break

                summary = graph.get_cluster_summary(cluster_name)
                return {
                    "query": query,
                    "query_type": QueryType.TIMELINE.value,
                    "answer": summary,
                    "sources": [],
                }

            # === 0. Compound queries: semantic intent + document scope ===
            intent = self._parse_compound_intent(query_lower)
            if intent["semantic"] and intent["scope"]:
                logger.info(f"   Compound intent: semantic={intent['semantic']}, scope={intent['scope']}")
                search_terms = self.jargon.get_concept_search_terms(query)
                logger.info(f"   Expanded search terms: {search_terms[:10]}...")
                matched_docs = graph.search_broad(terms=search_terms, scope=intent["scope"])

                if matched_docs:
                    logger.info(f"   Compound search found {len(matched_docs)} docs")
                    doc_ids = [d["doc_id"] for d in matched_docs if d.get("doc_id")]

                    # RAG augmentation: get content-level details
                    rag_result = None
                    if doc_ids:
                        try:
                            rag_result = self.document_rag.query(expanded_query, doc_ids=doc_ids)
                        except Exception as e:
                            logger.warning(f"   RAG augmentation failed: {e}")
                            # Fallback: try without doc_id filter
                            try:
                                rag_result = self.document_rag.query(expanded_query)
                            except Exception:
                                pass

                    answer = self._build_compound_answer(query, intent, matched_docs, rag_result)
                    compound_sources = [
                        self._build_source(d.get("doc_id"), d, NOTICES_DIR)
                        for d in matched_docs
                    ]

                    return {
                        "query": query,
                        "query_type": QueryType.TIMELINE.value,
                        "answer": answer,
                        "sources": compound_sources,
                    }
                else:
                    logger.info("   Compound search returned no results, falling through")

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

    def _build_source(self, doc_id: str, node: Dict, notices_dir: Path) -> Dict[str, Any]:
        """Build source entry with evidence from notice file, including file_path for clickability."""
        import json

        file_name = node.get('file_name', doc_id or 'Unknown')
        date = node.get('date', 'Unknown')
        sender = (node.get('sender') or 'Unknown')[:40]
        recipient = (node.get('recipient') or 'Unknown')[:40]
        subject = (node.get('subject') or '')[:100]

        evidence = []
        highlight_text = ""
        if doc_id:
            notice_path = notices_dir / f"{doc_id}.json"
            if notice_path.exists():
                try:
                    with open(notice_path, 'r', encoding='utf-8') as f:
                        notice_data = json.load(f)
                    evidence = notice_data.get('evidence_spans', [])[:3]
                    # Use first evidence span as highlight text
                    if evidence:
                        highlight_text = evidence[0].get('text', '') if isinstance(evidence[0], dict) else str(evidence[0])
                except Exception:
                    pass

        # Lookup file_path from RAG file_registry
        file_path = ""
        page_number = 1
        total_pages = 1
        reg = self.document_rag.file_registry.get(file_name, {})
        if reg:
            file_path = reg.get("file_path", "")
            total_pages = reg.get("page_count", 1)

        return {
            "type": "notice",
            "file_name": file_name,
            "file_path": file_path,
            "page_number": page_number,
            "total_pages": total_pages,
            "doc_id": doc_id,
            "date": date,
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "highlight_text": highlight_text,
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

    def route_and_execute(self, query: str, doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Classify and route query to appropriate handler.
        Complex queries are routed through the hybrid executor for multi-step planning.
        If doc_ids is provided, RAG and SQL queries are scoped to those documents.
        """
        from .telemetry import start_trace, finish_trace

        trace = start_trace(query)
        log_separator("Processing Query")
        logger.info(f"Query: {query[:100]}...")

        try:
            # Check for greetings first
            if self._is_greeting(query):
                logger.info("   Detected greeting -> returning welcome message")
                trace.route = "GREETING"
                return self._build_greeting_response()

            # Expand jargon
            expanded = self.jargon.expand_query(query)
            if expanded != query:
                logger.info(f"   Jargon expanded: {expanded[:100]}...")

            # Check if this is a complex multi-step query
            if self._is_complex_query(query):
                logger.info("   Detected complex query -> Hybrid Executor")
                trace.route = "HYBRID_COMPLEX"
                result = self.hybrid_executor.execute(expanded)
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
            if decision.query_type == QueryType.FILE_LIST:
                result = self._handle_file_list_query(query, doc_ids)
            elif decision.query_type == QueryType.THREAD:
                result = self._handle_thread_query(query)
            elif decision.query_type == QueryType.DRAFT:
                result = self._handle_draft_query(query)
            elif decision.query_type == QueryType.DATA:
                result = self._handle_data_query(expanded, doc_ids=doc_ids)
            elif decision.query_type == QueryType.DOCUMENT:
                result = self._handle_document_query(expanded, doc_ids=doc_ids)
            elif decision.query_type == QueryType.TIMELINE:
                result = self._handle_timeline_query(query)
            else:  # HYBRID
                result = self._handle_hybrid_query(expanded, doc_ids=doc_ids)

            # Fallback: if DOCUMENT returned empty and tables exist, retry as DATA
            if (decision.query_type == QueryType.DOCUMENT
                    and not result.get("sources")
                    and self.data_analyzer.list_tables()):
                logger.info("   Document query returned empty, retrying as DATA (tables available)")
                result = self._handle_data_query(expanded, doc_ids=doc_ids)
                result["query_type"] = QueryType.DATA.value
                decision = RouterDecision(
                    query_type=QueryType.DATA,
                    confidence=decision.confidence,
                    reasons=decision.reasons + ["fallback: doc empty, tables available"],
                )
                trace.route = "DATA_FALLBACK"

            # Fallback: if HYBRID returned error/empty and tables exist, retry as DATA
            if (decision.query_type == QueryType.HYBRID
                    and self.data_analyzer.list_tables()):
                answer = result.get("answer", "")
                has_error = answer.startswith("Error") or "failed" in answer.lower()
                has_no_sources = not result.get("sources")
                if has_error or has_no_sources:
                    logger.info("   Hybrid query returned error/empty, retrying as DATA")
                    result = self._handle_data_query(expanded, doc_ids=doc_ids)
                    result["query_type"] = QueryType.DATA.value
                    decision = RouterDecision(
                        query_type=QueryType.DATA,
                        confidence=decision.confidence,
                        reasons=decision.reasons + ["fallback: hybrid failed, retrying as DATA"],
                    )
                    trace.route = "DATA_FALLBACK_FROM_HYBRID"

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

    def route_and_execute_dual(self, query: str, doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Classify query and execute with both OpenAI and Claude in parallel.
        Returns dual answers keyed by provider.
        If doc_ids is provided, RAG and SQL queries are scoped to those documents.
        """
        from .telemetry import start_trace, finish_trace
        from .config import LLM_PROVIDERS

        trace = start_trace(query)
        log_separator("Processing Query (Dual-LLM)")
        logger.info(f"Query: {query[:100]}...")

        try:
            # Check for greetings first
            if self._is_greeting(query):
                logger.info("   Detected greeting -> returning welcome message")
                trace.route = "GREETING"
                return self._build_greeting_response()

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
            allowed_tables = self.data_analyzer.get_tables_for_doc_ids(doc_ids) if doc_ids else None
            if decision.query_type == QueryType.FILE_LIST:
                single = self._handle_file_list_query(query)
                answers = {p: single for p in LLM_PROVIDERS}
            elif decision.query_type == QueryType.THREAD:
                single = self._handle_thread_query(query)
                answers = {p: single for p in LLM_PROVIDERS}
            elif decision.query_type == QueryType.DRAFT:
                single = self._handle_draft_query(query)
                answers = {p: single for p in LLM_PROVIDERS}
            elif decision.query_type == QueryType.DATA:
                answers = self.data_analyzer.query_dual(expanded, allowed_tables=allowed_tables)
            elif decision.query_type == QueryType.DOCUMENT:
                answers = self.document_rag.query_dual(expanded, doc_ids=doc_ids)
                # Fallback: if document returned empty and tables exist, retry as DATA
                has_empty = all(
                    not (a.get("sources") if isinstance(a, dict) else False)
                    for a in answers.values()
                )
                if has_empty and self.data_analyzer.list_tables():
                    logger.info("   Document query (dual) returned empty, retrying as DATA")
                    answers = self.data_analyzer.query_dual(expanded, allowed_tables=allowed_tables)
                    decision = RouterDecision(
                        query_type=QueryType.DATA,
                        confidence=decision.confidence,
                        reasons=decision.reasons + ["fallback: doc empty, tables available"],
                    )
            elif decision.query_type == QueryType.TIMELINE:
                single = self._handle_timeline_query(query)
                answers = {p: single for p in LLM_PROVIDERS}
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
