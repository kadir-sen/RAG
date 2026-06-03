"""Maps raw router Dict[str, Any] → ChatResponse contract."""

import hashlib
import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Any, List


def _json_safe(value: Any) -> Any:
    """Recursively coerce a value into JSON-native types.

    DuckDB/pandas SQL results carry numpy scalars, NaN/Inf, Decimals and
    Timestamps that FastAPI's response serialization cannot encode — these
    raised an unhandled 500 on every DATA/sql_result answer. Normalizing here,
    at the artifact boundary, keeps the SQL path serialization-safe.
    """
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    # NaN-like sentinels (numpy NaN already handled above; this catches NaT / pd.NA)
    try:
        if value != value:  # noqa: PLR0124 — NaN is the only value unequal to itself
            return None
    except Exception:
        pass
    if isinstance(value, Decimal):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    # numpy scalars expose .item(); arrays/Series expose .tolist()
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            pass
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _json_safe(tolist())
        except Exception:
            pass
    return str(value)
from backend.models.responses import (
    CallToAction,
    ChatResponse,
    Citation,
    ProviderAnswer,
    RelatedDoc,
    SQLArtifact,
)


# Regex: only safe URL chars (hex hash, alphanumeric, dash, underscore, dot)
_SAFE_DOC_ID_RE = re.compile(r'^[a-zA-Z0-9_.\-]+$')


def _safe_doc_id(src: Dict[str, Any]) -> str:
    """Return a URL-safe doc_id. Falls back to hashing file_name if raw ID
    contains special/unicode characters that would break frontend URL encoding."""
    doc_id = src.get("doc_id") or ""
    if doc_id and _SAFE_DOC_ID_RE.match(doc_id):
        return doc_id
    # Fallback: generate stable hash from file_name
    file_name = src.get("file_name") or ""
    if file_name:
        return hashlib.md5(file_name.encode()).hexdigest()[:16]
    return doc_id  # return whatever we have, even if empty

# Old QueryType → new ui_intent
INTENT_MAP = {
    "document": "answer",
    "data": "sql_result",
    "hybrid": "answer",
    "timeline": "doc_list",
    "thread": "email_trace",
    "draft": "answer",
    "file_list": "doc_list",
}


def build_chat_response(raw: Dict[str, Any], is_dual: bool = False) -> ChatResponse:
    """Convert raw router output to ChatResponse."""
    if is_dual:
        return _build_from_dual(raw)
    return _build_from_single(raw)


def _looks_like_no_document_answer(answer: str) -> bool:
    text = (answer or "").strip().lower()
    if not text:
        return False
    patterns = [
        r"\bno\s+(?:relevant\s+)?(?:documents?|files?|sources?)\b",
        r"\bno\s+documents?\s+(?:are\s+)?related\b",
        r"\bnot\s+found\b",
        r"\bwas\s+not\s+found\b",
        r"\bwere\s+not\s+found\b",
        r"\bcould\s+not\s+find\b",
        r"\bprovided\s+(?:context|information)\s+does\s+not\s+contain\b",
        r"\bdoes\s+not\s+contain\s+(?:information|details)\b",
        r"\bno\s+information\s+(?:related\s+to|about|regarding)\b",
        r"\bcannot\s+provide\s+information\b",
        r"\bcan't\s+provide\s+information\b",
    ]
    return any(re.search(p, text) for p in patterns)


def _build_from_single(raw: Dict[str, Any]) -> ChatResponse:
    query_type = raw.get("query_type", "document")
    answer_text = raw.get("answer", "")
    sources = raw.get("sources", [])
    sql = raw.get("sql")
    result_data = raw.get("result_data")

    ui_intent = INTENT_MAP.get(query_type, "answer")
    if query_type in ("document", "file_list") and _looks_like_no_document_answer(answer_text):
        sources = []
    citations, related_docs = _extract_citations_and_related(sources, query_type)
    sql_artifact = _build_sql_artifact(sql, result_data, sources)
    cta = _extract_cta(result_data)

    # Extract routing confidence for frontend display
    routing = raw.get("routing", {})
    routing_confidence = routing.get("confidence") if routing else None

    return ChatResponse(
        ui_intent=ui_intent,
        assistant_text=answer_text,
        citations=citations,
        related_docs=related_docs,
        routing_confidence=routing_confidence,
        sql_artifact=sql_artifact,
        cta=cta,
    )


def _build_from_dual(raw: Dict[str, Any]) -> ChatResponse:
    from src.config import GEMINI_MODEL, OPENAI_MODEL, ANTHROPIC_MODEL

    MODEL_NAMES = {
        "gemini": GEMINI_MODEL,
        "openai": OPENAI_MODEL,
        "claude": ANTHROPIC_MODEL,
    }

    # Be tolerant of single-result fallback payloads reaching dual mode.
    # This can happen when the orchestrator degrades gracefully after a router failure.
    if "answers" not in raw:
        return _build_from_single(raw)

    query_type = raw.get("query_type", "document")
    answers = raw.get("answers", {})
    ui_intent = INTENT_MAP.get(query_type, "answer")
    routing = raw.get("routing", {})
    routing_confidence = routing.get("confidence") if routing else None

    # Build per-provider answers
    provider_answers: list[ProviderAnswer] = []
    first_answer = {}
    for provider, prov_ans in answers.items():
        if not isinstance(prov_ans, dict):
            continue
        if not first_answer:
            first_answer = prov_ans

        prov_sql = prov_ans.get("sql")
        prov_result_data = prov_ans.get("result_data")
        prov_sources = prov_ans.get("sources", [])
        prov_sql_artifact = _build_sql_artifact(prov_sql, prov_result_data, prov_sources)

        provider_answers.append(ProviderAnswer(
            provider=provider,
            model=MODEL_NAMES.get(provider, provider),
            text=prov_ans.get("answer", ""),
            sql=prov_sql,
            sql_artifact=prov_sql_artifact,
        ))

    # Use first provider for primary fields (citations, related docs)
    answer_text = first_answer.get("answer", "")
    sources = first_answer.get("sources", [])
    sql = first_answer.get("sql")
    result_data = first_answer.get("result_data")

    if query_type in ("document", "file_list") and _looks_like_no_document_answer(answer_text):
        sources = []
    citations, related_docs = _extract_citations_and_related(sources, query_type)
    sql_artifact = _build_sql_artifact(sql, result_data, sources)
    cta = _extract_cta(result_data)

    return ChatResponse(
        ui_intent=ui_intent,
        assistant_text=answer_text,
        citations=citations,
        related_docs=related_docs,
        sql_artifact=sql_artifact,
        provider_answers=provider_answers,
        routing_confidence=routing_confidence,
        cta=cta,
    )


def _resolve_canonical_doc_id(file_name: str, fallback: str) -> str:
    """Return the DocumentRegistry's canonical doc_id for ``file_name``.

    Pinecone often holds two ingestions of the same source file (e.g. one
    with a Windows path and one with a Linux container path). Each carries
    its own LlamaIndex UUID, so naive forwarding would surface both as
    separate citations and one of them — the one whose path no longer
    exists on disk — would 404 in the viewer. Remapping every reference to
    the canonical registry id eliminates that mismatch.

    Falls back to ``fallback`` (typically the raw ``doc_id`` from the
    source) when no registry record matches the filename.
    """
    if not file_name:
        return fallback
    try:
        from src.document_registry import get_document_registry
        registry = get_document_registry()
        for rec in registry.get_all():
            if rec.file_name == file_name:
                return rec.doc_id
    except Exception:
        pass
    return fallback


def _extract_citations_and_related(
    sources: List[Dict[str, Any]], query_type: str
) -> tuple:
    """Deduplicate references by filename and remap every doc_id to the
    canonical registry id.

    Guarantees:
      * No two citations or related_docs share the same ``file_name``.
      * Every ``doc_id`` resolves through DocumentRegistry when a matching
        record exists, so the right-panel viewer can find the file.
    """
    citations: list[Citation] = []
    related_docs: list[RelatedDoc] = []
    seen_citation_names: set[str] = set()
    seen_related_names: set[str] = set()

    for src in sources:
        src_type = src.get("type", "")
        file_name = src.get("file_name") or ""

        if src_type == "structured_data":
            # Data sources handled by sql_artifact, skip
            continue
        elif src_type in ("notice", "thread_message", "search_result"):
            if file_name and file_name in seen_related_names:
                continue
            if file_name:
                seen_related_names.add(file_name)
            raw_id = _safe_doc_id(src)
            safe_id = _resolve_canonical_doc_id(file_name, raw_id)
            # doc_type cascade: notice doc_type → extension (".pdf"→"pdf") →
            # file_type. Keeps the timeline chip populated for non-notice PDFs.
            doc_type = src.get("doc_type") or ""
            if not doc_type:
                ext = (src.get("extension") or "").lstrip(".")
                doc_type = ext or src.get("file_type") or ""
            related_docs.append(RelatedDoc(
                doc_id=safe_id,
                doc_name=file_name,
                date=src.get("date") or "",
                doc_type=doc_type,
                reason=src.get("subject") or "",
                score=src.get("score"),
                sender=src.get("sender") or "",
                recipient=src.get("recipient") or "",
            ))
        else:
            # Document source → citation
            if file_name and file_name in seen_citation_names:
                continue
            if file_name:
                seen_citation_names.add(file_name)
            raw_id = _safe_doc_id(src)
            safe_id = _resolve_canonical_doc_id(file_name, raw_id)
            page = src.get("page_number", 1)
            citations.append(Citation(
                doc_id=safe_id,
                doc_name=file_name,
                anchor=f"page_{page}",
                snippet=(
                    src.get("highlight_text", "")
                    or src.get("text_snippet", "")
                )[:300],
                score=src.get("score"),
            ))

    return citations, related_docs


def _build_sql_artifact(
    sql: str | None,
    result_data: Any,
    sources: List[Dict[str, Any]],
) -> SQLArtifact | None:
    if not sql:
        return None

    # When a query fans out across multiple tables (e.g. the monthly manpower /
    # equipment / IPC logs), the data handler returns sql as a {table: sql} dict
    # and result_data as a {table: rows} dict — not a single string/list. The
    # SQLArtifact contract is a single SQL string + flat rows, so normalize here.
    # (Previously the dict reached SQLArtifact.generated_sql and 500'd every
    # multi-table DATA answer with a Pydantic string_type error.)
    fanned_tables: List[str] = []
    if isinstance(sql, dict):
        fanned_tables = [str(k) for k in sql.keys()]
        sql = "\n\n".join(
            f"-- {name}\n{stmt}" for name, stmt in sql.items() if stmt
        )
    elif not isinstance(sql, str):
        sql = str(sql)

    data_source = next(
        (s for s in sources if s.get("type") == "structured_data"), None
    )
    tables_used = list(fanned_tables)
    source_file_id = ""
    source_file_name = ""
    if data_source:
        if "table_name" in data_source and data_source["table_name"] not in tables_used:
            tables_used.append(data_source["table_name"])
        source_file_id = data_source.get("doc_id", "")
        source_file_name = data_source.get("file_name", "")

    rows: List[Dict[str, Any]] = []
    if isinstance(result_data, list):
        rows = result_data
    elif isinstance(result_data, dict):
        # {table: [rows]} → flatten in table order for a combined preview
        for part in result_data.values():
            if isinstance(part, list):
                rows.extend(part)

    return SQLArtifact(
        generated_sql=sql,
        tables_used=tables_used,
        row_count=len(rows),
        preview_rows=_json_safe(rows[:20]),
        source_file_id=source_file_id,
        source_file_name=source_file_name,
    )


def _extract_cta(result_data: Any) -> CallToAction | None:
    """Pull a CallToAction hint from result_data when it's a dict carrying 'action'.
    Used by SQL handler to surface 'Reindex Data Tables' when no tables exist."""
    if not isinstance(result_data, dict):
        return None
    action = result_data.get("action")
    if not action:
        return None
    label = ""
    if action == "reindex_data_tables":
        label = "Reindex Data Tables"
    metadata = {k: v for k, v in result_data.items() if k != "action"}
    return CallToAction(action=action, label=label, metadata=metadata)
