"""Maps raw router Dict[str, Any] → ChatResponse contract."""

import hashlib
import re
from typing import Dict, Any, List
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


def _build_from_single(raw: Dict[str, Any]) -> ChatResponse:
    query_type = raw.get("query_type", "document")
    answer_text = raw.get("answer", "")
    sources = raw.get("sources", [])
    sql = raw.get("sql")
    result_data = raw.get("result_data")

    ui_intent = INTENT_MAP.get(query_type, "answer")
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


def _extract_citations_and_related(
    sources: List[Dict[str, Any]], query_type: str
) -> tuple:
    citations = []
    related_docs = []

    for src in sources:
        src_type = src.get("type", "")

        if src_type == "structured_data":
            # Data sources handled by sql_artifact, skip
            continue
        elif src_type in ("notice", "thread_message", "search_result"):
            safe_id = _safe_doc_id(src)
            related_docs.append(RelatedDoc(
                doc_id=safe_id,
                doc_name=src.get("file_name") or "",
                date=src.get("date") or "",
                doc_type=src.get("doc_type") or "",
                reason=src.get("subject") or "",
                score=src.get("score"),
                sender=src.get("sender") or "",
                recipient=src.get("recipient") or "",
            ))
        else:
            # Document source → citation
            safe_id = _safe_doc_id(src)
            page = src.get("page_number", 1)
            citations.append(Citation(
                doc_id=safe_id,
                doc_name=src.get("file_name") or "",
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

    data_source = next(
        (s for s in sources if s.get("type") == "structured_data"), None
    )
    tables_used = []
    source_file_id = ""
    source_file_name = ""
    if data_source:
        if "table_name" in data_source:
            tables_used = [data_source["table_name"]]
        source_file_id = data_source.get("doc_id", "")
        source_file_name = data_source.get("file_name", "")

    rows: List[Dict[str, Any]] = []
    if isinstance(result_data, list):
        rows = result_data

    return SQLArtifact(
        generated_sql=sql,
        tables_used=tables_used,
        row_count=len(rows),
        preview_rows=rows[:20],
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
