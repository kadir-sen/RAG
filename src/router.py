"""
Query Router with multilingual support (English + Turkish).
Routes queries to Document RAG, SQL Data Analyzer, or both.
"""
from enum import Enum
from typing import Tuple, Dict, Any

from llama_index.llms.gemini import Gemini

from .config import GOOGLE_API_KEY, GEMINI_MODEL
from .document_rag import get_document_rag
from .data_analyzer_sql import get_data_analyzer
from .logger import logger, log_separator


class QueryType(Enum):
    DOCUMENT = "document"
    DATA = "data"
    HYBRID = "hybrid"


# Multilingual keywords for classification
DATA_KEYWORDS = {
    # English
    "calculate", "sum", "average", "mean", "total", "count", "how many",
    "filter", "sort", "group by", "aggregate", "maximum", "minimum", "max", "min",
    "variance", "std", "deviation", "percentage", "ratio", "percent",
    "compare", "trend", "statistics", "column", "row", "table", "excel", "csv",
    "spreadsheet", "data", "number", "numeric", "value",
    # Turkish
    "hesapla", "toplam", "ortalama", "kaç tane", "kaç", "say", "sayı",
    "filtrele", "sırala", "grupla", "gruplandır", "en büyük", "en küçük",
    "yüzde", "oran", "kıyasla", "karşılaştır", "trend", "istatistik",
    "sütun", "satır", "tablo", "veri", "değer",
}

DOCUMENT_KEYWORDS = {
    # English
    "what does", "explain", "describe", "define", "definition", "meaning",
    "terms", "clause", "contract", "policy", "agreement", "section", "article",
    "according to", "mentioned in", "stated in", "says", "written",
    "liability", "obligation", "requirement", "condition", "provision",
    "report", "document", "text", "paragraph", "page", "summary", "summarize",
    # Turkish
    "ne demek", "açıkla", "tanımla", "tanım", "anlam", "anlat",
    "şart", "madde", "sözleşme", "politika", "anlaşma", "bölüm", "kısım",
    "göre", "belirtilen", "yazılan", "diyor", "yazan",
    "yükümlülük", "sorumluluk", "gereklilik", "koşul", "hüküm",
    "rapor", "raporda", "belge", "metin", "paragraf", "sayfa", "özet", "özetle",
}


class QueryRouter:
    """Routes queries to appropriate handlers with multilingual support."""

    CLASSIFICATION_PROMPT = """You are a query classifier for a hybrid RAG system.
Classify the user's query into exactly ONE category.

Categories:
- DOCUMENT: Questions about text content, contracts, reports, policies, terms, clauses, definitions, descriptions, explanations
- DATA: Questions requiring calculations, aggregations, filtering, sorting, statistics, or numerical analysis on tabular data
- HYBRID: Questions that need BOTH document context AND data calculations together

Available Sources:
DOCUMENTS: {doc_files}
DATA TABLES: {data_files}

User Query: {query}

Important:
- If the query asks about numbers FROM documents (like "what percentage is mentioned"), that's DOCUMENT
- If the query needs to CALCULATE numbers from tables, that's DATA
- If the query needs to correlate document content with table calculations, that's HYBRID

Respond with exactly ONE word: DOCUMENT, DATA, or HYBRID"""

    HYBRID_SYNTHESIS_PROMPT = """Combine these two information sources to answer the user's question.
Do NOT invent facts - only use information from the sources below.

QUESTION: {question}

DOCUMENT SEARCH RESULTS:
{doc_results}

DATA ANALYSIS RESULTS:
{data_results}

Provide a comprehensive answer that:
1. Clearly states which information comes from documents vs data analysis
2. Does not make claims unsupported by either source
3. Is concise and well-structured"""

    def __init__(self):
        """Initialize the router."""
        log_separator("Initializing Query Router")
        self.llm = Gemini(api_key=GOOGLE_API_KEY, model=GEMINI_MODEL)
        self.document_rag = get_document_rag()
        self.data_analyzer = get_data_analyzer()
        logger.info("✅ Query Router initialized")

    def _get_available_sources(self) -> Tuple[str, str]:
        """Get descriptions of available sources."""
        # Documents
        doc_files = "None loaded"
        if self.document_rag.file_registry:
            doc_list = []
            for fname, info in self.document_rag.file_registry.items():
                pages = info.get('page_count', 1)
                doc_list.append(f"{fname} ({pages} pages)")
            doc_files = ", ".join(doc_list[:10])
            if len(doc_list) > 10:
                doc_files += f" (+{len(doc_list) - 10} more)"

        # Data tables
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

    def classify_query(self, query: str) -> QueryType:
        """Classify query using heuristics + LLM."""
        logger.info("🧠 Classifying query...")
        query_lower = query.lower()

        # Heuristic scoring
        data_score = sum(1 for kw in DATA_KEYWORDS if kw in query_lower)
        doc_score = sum(1 for kw in DOCUMENT_KEYWORDS if kw in query_lower)

        logger.info(f"   Heuristic scores - Document: {doc_score}, Data: {data_score}")

        # Strong heuristic match
        if data_score >= 3 and doc_score == 0:
            logger.info("   → Heuristic: DATA")
            return QueryType.DATA
        if doc_score >= 3 and data_score == 0:
            logger.info("   → Heuristic: DOCUMENT")
            return QueryType.DOCUMENT

        # Use LLM for ambiguous cases
        try:
            logger.info("   Using LLM for classification...")
            doc_files, data_files = self._get_available_sources()

            prompt = self.CLASSIFICATION_PROMPT.format(
                doc_files=doc_files,
                data_files=data_files,
                query=query,
            )

            response = self.llm.complete(prompt)
            result = response.text.strip().upper()
            logger.info(f"   LLM classification: {result}")

            if "DATA" in result:
                return QueryType.DATA
            elif "HYBRID" in result:
                return QueryType.HYBRID
            else:
                return QueryType.DOCUMENT

        except Exception as e:
            logger.error(f"   Classification error: {e}")
            # Default based on what's available
            if self.data_analyzer.list_tables() and not self.document_rag.documents:
                return QueryType.DATA
            return QueryType.DOCUMENT

    def _handle_document_query(self, query: str) -> Dict[str, Any]:
        """Handle document-based query."""
        logger.info("📚 Routing to Document RAG...")
        result = self.document_rag.query(query)
        return {
            "query": query,
            "query_type": QueryType.DOCUMENT.value,
            "answer": result["answer"],
            "sources": result["sources"],
        }

    def _handle_data_query(self, query: str) -> Dict[str, Any]:
        """Handle data analysis query."""
        logger.info("📊 Routing to SQL Data Analyzer...")
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
        """Handle hybrid query needing both sources."""
        logger.info("🔀 Routing to BOTH handlers...")

        # Get results from both
        doc_result = self.document_rag.query(query)
        data_result = self.data_analyzer.query(query)

        # Synthesize with LLM
        logger.info("   Synthesizing results...")
        try:
            synthesis_prompt = self.HYBRID_SYNTHESIS_PROMPT.format(
                question=query,
                doc_results=doc_result["answer"],
                data_results=data_result["answer"],
            )

            response = self.llm.complete(synthesis_prompt)
            combined_answer = response.text.strip()

        except Exception as e:
            logger.error(f"   Synthesis error: {e}")
            combined_answer = f"""**From Documents:**
{doc_result['answer']}

**From Data Analysis:**
{data_result['answer']}"""

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

    def route_and_execute(self, query: str) -> Dict[str, Any]:
        """Classify and route query to appropriate handler."""
        log_separator("Processing Query")
        logger.info(f"🔍 Query: {query[:100]}...")

        query_type = self.classify_query(query)
        logger.info(f"   Classified as: {query_type.value.upper()}")

        if query_type == QueryType.DATA:
            result = self._handle_data_query(query)
        elif query_type == QueryType.DOCUMENT:
            result = self._handle_document_query(query)
        else:  # HYBRID
            result = self._handle_hybrid_query(query)

        logger.info(f"✅ Query complete - {len(result.get('sources', []))} sources")
        return result


# Singleton
_router = None


def get_router() -> QueryRouter:
    """Get or create QueryRouter singleton."""
    global _router
    if _router is None:
        _router = QueryRouter()
    return _router
