"""Maps raw router Dict[str, Any] → ChatResponse contract."""

from typing import Dict, Any, List
from backend.models.responses import ChatResponse, Citation, RelatedDoc, SQLArtifact, ProviderAnswer

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

    return ChatResponse(
        ui_intent=ui_intent,
        assistant_text=answer_text,
        citations=citations,
        related_docs=related_docs,
        sql_artifact=sql_artifact,
    )


def _build_from_dual(raw: Dict[str, Any]) -> ChatResponse:
    from src.config import GEMINI_MODEL, OPENAI_MODEL, ANTHROPIC_MODEL

    MODEL_NAMES = {
        "gemini": GEMINI_MODEL,
        "openai": OPENAI_MODEL,
        "claude": ANTHROPIC_MODEL,
    }

    query_type = raw.get("query_type", "document")
    answers = raw.get("answers", {})
    ui_intent = INTENT_MAP.get(query_type, "answer")

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

    return ChatResponse(
        ui_intent=ui_intent,
        assistant_text=answer_text,
        citations=citations,
        related_docs=related_docs,
        sql_artifact=sql_artifact,
        provider_answers=provider_answers,
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
        elif src_type in ("notice", "thread_message"):
            related_docs.append(RelatedDoc(
                doc_id=src.get("doc_id", src.get("file_name", "")),
                doc_name=src.get("file_name", ""),
                date=src.get("date", ""),
                doc_type=src.get("doc_type", ""),
                reason=src.get("subject", ""),
                score=src.get("score"),
                sender=src.get("sender", ""),
                recipient=src.get("recipient", ""),
            ))
        else:
            # Document source → citation
            page = src.get("page_number", 1)
            citations.append(Citation(
                doc_id=src.get("doc_id", src.get("file_name", "")),
                doc_name=src.get("file_name", ""),
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
    result_data: list | None,
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

    preview = []
    if result_data and isinstance(result_data, list):
        preview = result_data[:20]

    return SQLArtifact(
        generated_sql=sql,
        tables_used=tables_used,
        row_count=len(result_data) if result_data else 0,
        preview_rows=preview,
        source_file_id=source_file_id,
        source_file_name=source_file_name,
    )
