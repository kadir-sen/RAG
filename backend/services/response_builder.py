"""Maps raw router Dict[str, Any] → ChatResponse contract."""

import hashlib
import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Any, List


# Matches an ISO date/datetime with a stray trailing letter glued on, e.g.
# "2027-03-23T00:00:00A" or "2016-05-01B" — these come from upstream column-bleed
# during Excel extraction (a Block value like "A"/"B" bleeding into the Date
# column). We strip the trailing letters so the displayed value is valid ISO.
_TRAILING_ALPHA_DATE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?)[A-Za-z]+$"
)


def clean_corrupted_date_string(text: str) -> str:
    """Return an ISO date/datetime string with any stray trailing letters removed.

    Existing parquet/DuckDB tables already hold corrupted strings such as
    "2027-03-23T00:00:00A"; cleaning at the serialization boundary fixes the
    user-visible value for both the SQL artifact and the document viewer without
    needing a full re-index. (The root-cause extraction fix lives in
    excel_table_extractor; this guards already-indexed data.)
    """
    if not isinstance(text, str):
        return text
    m = _TRAILING_ALPHA_DATE_RE.match(text)
    return m.group(1) if m else text


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
    if isinstance(value, str):
        return clean_corrupted_date_string(value)
    if value is None or isinstance(value, (bool, int)):
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
    ChartSpec,
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
    "thread": "email_trace",
    "draft": "answer",
    "file_list": "doc_list",  # "what files exist" → flat doc table
}


def build_chat_response(raw: Dict[str, Any], is_dual: bool = False) -> ChatResponse:
    """Convert raw router output to ChatResponse."""
    if is_dual:
        return _build_from_dual(raw)
    return _build_from_single(raw)


def _clean_answer_text(text: str) -> str:
    """Tidy small LLM grammar slips before the answer reaches the UI — chiefly the
    accidental double negative ("does not not contain") reported in testing."""
    if not text:
        return text
    cleaned = re.sub(r"\b(does|do|did|is|are|was|were|has|have)\s+not\s+not\b",
                     r"\1 not", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bnot\s+not\b", "not", cleaned, flags=re.IGNORECASE)
    return cleaned


def _is_bare_refusal(answer: str) -> bool:
    """True for a short, content-free 'no documents' answer — safe to drop
    citations for. A longer answer that contains a refusal phrase but ALSO real
    content keeps its citations: the live-test report explicitly valued graceful
    refusals that still surface relevant documents, so a nuanced
    "no document directly states X, but the inspection report covers ..." must
    not lose its sources."""
    text = (answer or "").strip()
    if not text:
        return True
    return len(text) < 220 and _looks_like_no_document_answer(text)


def _looks_like_no_document_answer(answer: str) -> bool:
    """Shared with the router — see src/answer_signals. The two used to be
    separate lists with different patterns, which meant each recognised
    refusals the other let through."""
    from src.answer_signals import denies_corpus
    return denies_corpus(answer)


def _is_empty_response(answer: str) -> bool:
    """True for LlamaIndex's placeholder string for an unsynthesized answer.

    `str(Response)` yields the literal "Empty Response" when the query engine
    retrieves no usable nodes. This leaked verbatim into the chronological /
    related-docs display (the answer read "Empty Response" with a document list
    below it). Treat it as no answer so the guard below replaces it.
    """
    return (answer or "").strip().lower() in ("", "empty response", "none")


def _normalize_empty_answer(
    answer_text: str,
    related_docs: List["RelatedDoc"],
    citations: List["Citation"],
) -> str:
    """Replace an empty/placeholder answer with a clean lead-in.

    When the synthesizer produced nothing usable ("Empty Response") but the
    handler still surfaced related documents/citations (timeline, hybrid, doc
    list), show a short summary instead of the raw placeholder. With no
    references at all, just strip the "Empty Response" placeholder to an empty
    string — never surface it verbatim, and don't invent a message (keeps the
    existing empty-answer contract).
    """
    if not _is_empty_response(answer_text):
        return answer_text
    n = len(related_docs)
    if n:
        return f"Found {n} related document{'s' if n != 1 else ''}, listed chronologically below."
    if citations:
        c = len(citations)
        return f"Found {c} related document{'s' if c != 1 else ''}."
    return ""


def _build_from_single(raw: Dict[str, Any]) -> ChatResponse:
    query_type = raw.get("query_type", "document")
    answer_text = _clean_answer_text(raw.get("answer", ""))
    sources = raw.get("sources", [])
    sql = raw.get("sql")
    result_data = raw.get("result_data")

    ui_intent = INTENT_MAP.get(query_type, "answer")
    # Drop citations only for empty or bare-refusal document answers. Nuanced
    # answers keep their citations (routing fixes handle the old misroute case
    # where a data query produced irrelevant email citations).
    if query_type in ("document", "file_list") and _is_bare_refusal(answer_text):
        sources = []
    citations, related_docs = _extract_citations_and_related(sources, query_type)
    # Never surface LlamaIndex's "Empty Response" placeholder: when documents
    # were found (timeline/hybrid/doc_list) replace it with a chronological
    # lead-in; otherwise a graceful no-result message.
    answer_text = _normalize_empty_answer(answer_text, related_docs, citations)
    sql_artifact = _build_sql_artifact(sql, result_data, sources)
    cta = _extract_cta(result_data)

    # Extract routing confidence + route for frontend display / observability.
    routing = raw.get("routing", {})
    routing_confidence = routing.get("confidence") if routing else None
    route = (routing.get("route") or routing.get("decision")) if routing else None

    return ChatResponse(
        ui_intent=ui_intent,
        assistant_text=answer_text,
        citations=citations,
        related_docs=related_docs,
        routing_confidence=routing_confidence,
        route=route,
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
            text=_clean_answer_text(prov_ans.get("answer", "")),
            sql=prov_sql,
            sql_artifact=prov_sql_artifact,
        ))

    # Use first provider for primary fields (citations, related docs)
    answer_text = _clean_answer_text(first_answer.get("answer", ""))
    sources = first_answer.get("sources", [])
    sql = first_answer.get("sql")
    result_data = first_answer.get("result_data")

    if query_type in ("document", "file_list") and _is_bare_refusal(answer_text):
        sources = []
    citations, related_docs = _extract_citations_and_related(sources, query_type)
    answer_text = _normalize_empty_answer(answer_text, related_docs, citations)
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

    preview = _json_safe(rows[:20])
    return SQLArtifact(
        generated_sql=sql,
        tables_used=tables_used,
        row_count=len(rows),
        preview_rows=preview,
        source_file_id=source_file_id,
        source_file_name=source_file_name,
        chart=_infer_chart(preview),
    )


# A result has to earn a chart. Two rows is a sentence, forty categories is a
# wall of labels — both read better as the table that is already there.
_CHART_MIN_ROWS = 3
_CHART_MAX_ROWS = 24
_DATE_HINTS = ("date", "month", "week", "day", "period", "year")


def _infer_chart(rows: List[Dict[str, Any]]) -> "ChartSpec | None":
    """Decide whether a result plots, from the shape of its columns alone.

    Deliberately conservative and deliberately not an LLM call: the model does
    not compute these numbers and should not be choosing how to draw them
    either. One label column plus at least one numeric column, and a row count
    in a range where a chart actually helps — otherwise None and the table
    stands on its own.
    """
    if not (_CHART_MIN_ROWS <= len(rows) <= _CHART_MAX_ROWS):
        return None

    cols = list(rows[0].keys())
    if len(cols) < 2:
        return None

    def numeric(col: str) -> bool:
        vals = [r.get(col) for r in rows if r.get(col) is not None]
        return bool(vals) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals)

    numeric_cols = [c for c in cols if numeric(c)]
    label_cols = [c for c in cols if c not in numeric_cols]
    if not numeric_cols or not label_cols:
        return None

    # The x axis is the first label column; a date-ish name makes it a line,
    # because a sequence over time reads as a trend and categories do not.
    x = label_cols[0]
    kind = "line" if any(h in x.lower() for h in _DATE_HINTS) else "bar"

    # Every label distinct, or the bars are stacking two things under one tick.
    labels = [str(r.get(x, "")) for r in rows]
    if len(set(labels)) != len(labels):
        return None

    return ChartSpec(type=kind, x=x, y=numeric_cols[:3])


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
