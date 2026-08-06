"""Chronology V3: document-first research for newly uploaded demo projects."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .chronology_prompts import chronology_v3_prompt_hash, load_chronology_v3_prompts
from .chronology_v2 import COVERAGE_FACETS, PreparedChronologyQuery, coverage_matrix
from .document_index import CandidateDocument, get_document_index
from .evidence_model import ChronologyEntry, EvidenceItem, VerifiedClaim
from .jargon_manager import jargon_dictionary_version, prepare_query, set_current_prepared_query


PIPELINE_VERSION = "chronology-v3"
EVIDENCE_BATCH_CHARS = 80_000
TARGET_DOCUMENTS = 12
MAX_DOCUMENTS = 20
ALLOWED_DATE_SOURCES = {"content_header", "content_body", "table_period", "unresolved"}


class ResearchPlanModel(BaseModel):
    english_topic: str
    parties: List[str] = Field(default_factory=list, max_length=30)
    entities: List[str] = Field(default_factory=list, max_length=50)
    acronyms: List[str] = Field(default_factory=list, max_length=30)
    contracts: List[str] = Field(default_factory=list, max_length=30)
    work_packages: List[str] = Field(default_factory=list, max_length=30)
    expected_document_families: List[str] = Field(default_factory=list, max_length=30)
    queries: List[str] = Field(min_length=4, max_length=16)


class ResearchLeadModel(BaseModel):
    kind: str
    value: str
    suggested_query: str
    source_id: str = ""


class MapExtractionModel(BaseModel):
    skeleton: List[str] = Field(default_factory=list, max_length=30)
    leads: List[ResearchLeadModel] = Field(default_factory=list, max_length=40)


DateSource = Literal["content_header", "content_body", "table_period", "unresolved"]


class EventCandidateModel(BaseModel):
    event_date: str = ""
    date_precision: str = "unresolved"
    date_source: DateSource = "unresolved"
    date_evidence: str = ""
    actor: str = ""
    action: str = ""
    established_fact: str = ""
    party_position: str = ""
    analytical_inference: str = ""
    immediate_consequence: str = ""
    supporting_source_ids: List[str] = Field(min_length=1, max_length=3)
    counter_source_ids: List[str] = Field(default_factory=list, max_length=3)
    missing_records: List[str] = Field(default_factory=list, max_length=10)


class ExtractionModel(BaseModel):
    entries: List[EventCandidateModel] = Field(default_factory=list, max_length=30)


class FinalClaimModel(BaseModel):
    text: str
    source_ids: List[str] = Field(min_length=1, max_length=3)
    is_inference: bool = False
    inference_basis: str = ""
    confidence: str = "medium"


class FinalEventModel(BaseModel):
    event_date: str
    date_precision: str = "exact"
    date_source: DateSource
    date_evidence: str
    claims: List[FinalClaimModel] = Field(min_length=1, max_length=2)
    parties: List[str] = Field(default_factory=list, max_length=20)
    event_type: str = "event"
    conflicting_positions: List[str] = Field(default_factory=list, max_length=10)


class ChronologyModel(BaseModel):
    overview_claims: List[FinalClaimModel] = Field(min_length=1, max_length=3)
    entries: List[FinalEventModel] = Field(default_factory=list, max_length=18)


Decision = Literal["PASS", "QUALIFY", "SPLIT", "REMOVE", "NEEDS_HUMAN_REVIEW"]


class VerificationDecisionModel(BaseModel):
    claim_ref: str
    decision: Decision
    reason_code: str


class VerificationModel(BaseModel):
    decisions: List[VerificationDecisionModel] = Field(min_length=1, max_length=50)


class RepairItemModel(BaseModel):
    claim_ref: str
    texts: List[str] = Field(min_length=1, max_length=2)


class RepairModel(BaseModel):
    repairs: List[RepairItemModel] = Field(default_factory=list, max_length=30)


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, default=str,
    ).encode("utf-8")).hexdigest()


def _is_structured_output_error(exc: Exception) -> bool:
    """Only malformed/truncated/oversized model output is safe to batch-split."""
    return exc.__class__.__name__ in {
        "LLMIncompleteResponseError", "LLMInvalidStructuredOutputError",
        "LLMInputBudgetExceededError",
    } or any(marker in str(exc).casefold() for marker in (
        "model_output_incomplete", "model_output_invalid", "input_budget_exceeded",
    ))


def _fallback_queries(topic: str) -> List[str]:
    return [
        f"{topic} overview historical review audit",
        f"{topic} contract agreement clause scope obligation",
        f"{topic} baseline programme schedule milestone",
        f"{topic} instruction notice change variation correspondence",
        f"{topic} progress delay disruption contemporaneous record",
        f"{topic} employer contractor engineer position dispute",
        f"{topic} adjudication mediation decision settlement outcome",
        f"{topic} contradiction missing attachment counterparty response",
    ]


def prepare_chronology_query(
    topic: str, *, date_from: str = "", date_to: str = "",
    parties: Sequence[str] = (), project_id: str = "",
) -> PreparedChronologyQuery:
    clean = str(topic or "").strip()
    if len(clean) < 3:
        raise ValueError("chronology_topic_required")
    jargon = prepare_query(clean); set_current_prepared_query(jargon)
    prompts = load_chronology_v3_prompts()
    prompt = (
        f"{prompts['research_planner']}\n\nORIGINAL TOPIC: {clean}\n"
        f"DATE WINDOW: {date_from or 'open'} to {date_to or 'open'}\n"
        f"NAMED PARTIES: {', '.join(parties) or 'not specified'}\n{jargon.context}"
    )
    try:
        from .llm_client import generate_response_json
        response = generate_response_json(
            prompt, system=prompts["system"], schema=ResearchPlanModel.model_json_schema(),
            schema_name="chronology_v3_research_plan", validation_model=ResearchPlanModel,
            task_type="chronology_research_plan", thinking_level="low", max_tokens=4_096,
            prompt_version=prompts["version"], cache_key="chron-v3-plan",
            cache_context=f"{project_id}:{jargon_dictionary_version()}", ttl_s=86_400,
        )
        plan = ResearchPlanModel.model_validate(response.raw)
    except Exception as exc:
        # A malformed planning response can safely use deterministic discovery
        # lanes. Credit, auth, provider and operational failures must retain
        # their real error identity for the job state and admin diagnostics.
        if not _is_structured_output_error(exc):
            raise
        plan = ResearchPlanModel(
            english_topic=clean, parties=list(parties), queries=_fallback_queries(clean),
        )
    queries: List[str] = []
    for query in plan.queries:
        for variant in prepare_query(query).retrieval_queries[:2]:
            value = variant.strip()
            if value and value not in queries:
                queries.append(value)
    return PreparedChronologyQuery(
        original_query=clean, english_query=plan.english_topic.strip() or clean,
        jargon_matches=jargon.matches, parties=tuple(plan.parties or parties),
        contracts=tuple(plan.contracts), work_packages=tuple(plan.work_packages),
        exclusions=tuple(plan.expected_document_families),
        research_queries=tuple(queries[:24]),
    )


def _source_id(project_id: str, doc_id: str, page: int, offset: int, text: str) -> str:
    return "src_" + hashlib.sha256(
        f"{project_id}|{doc_id}|{page}|{offset}|{text}".encode("utf-8")
    ).hexdigest()[:16]


def _markdown_table(frame) -> str:
    """Render evidence without depending on pandas' optional tabulate package."""
    columns = [str(value) for value in frame.columns]

    def cell(value: object) -> str:
        if value is None:
            return ""
        try:
            if value != value:  # NaN / NaT
                return ""
        except Exception:
            pass
        return str(value).replace("|", "\\|").replace("\n", " ").strip()

    lines = [
        "| " + " | ".join(cell(value) for value in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for values in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    return "\n".join(lines)


def _table_evidence(
    project_id: str, selected: Sequence[str], metadata: Dict[str, object],
) -> Tuple[List[EvidenceItem], set[str]]:
    """Load project-scoped Excel/CSV/PDF tables from their canonical parquet store."""
    try:
        import pandas as pd
        from .catalog import get_catalog
    except Exception:
        return [], set()

    selected_set = set(selected); evidence: List[EvidenceItem] = []; found: set[str] = set()
    by_name = {
        Path(getattr(record, "file_name", "")).name.casefold(): doc_id
        for doc_id, record in metadata.items() if doc_id in selected_set
    }
    for entry in get_catalog().entries.values():
        if entry.project_id != project_id:
            continue
        source_name = Path(entry.source_file).name
        doc_id = by_name.get(source_name.casefold())
        if not doc_id:
            continue
        for table in entry.tables:
            parquet = Path(table.parquet_path)
            if not parquet.is_file():
                continue
            try:
                frame = pd.read_parquet(parquet)
            except Exception:
                continue
            # A source excerpt stays small enough for exact number validation while
            # preserving an addressable row range in the original workbook.
            for offset in range(0, len(frame), 40):
                part = frame.iloc[offset:offset + 40]
                if part.empty:
                    continue
                row_from = offset + 2  # workbook row 1 is the header
                row_to = offset + len(part) + 1
                excerpt = _markdown_table(part)
                page = int(table.page_number or 1)
                identity = f"{table.sheet_name or ''}:{row_from}:{row_to}:{table.table_id}"
                source_id = _source_id(project_id, doc_id, page, offset, identity + excerpt)
                evidence.append(EvidenceItem(
                    source_id=source_id, doc_id=doc_id, file_name=source_name,
                    title=getattr(metadata[doc_id], "title", "") or source_name,
                    document_date=getattr(metadata[doc_id], "metadata_date", ""),
                    page=page if entry.source_type == "pdf" else None,
                    kind="excel" if entry.source_type in ("excel", "csv") else "document",
                    sheet=str(table.sheet_name or table.table_name),
                    row_from=row_from, row_to=row_to, excerpt=excerpt,
                ))
                found.add(doc_id)
    return evidence, found


def evidence_from_documents(project_id: str, doc_ids: Sequence[str]) -> List[EvidenceItem]:
    chosen = list(dict.fromkeys(str(value).strip() for value in doc_ids if str(value).strip()))
    if not chosen or len(chosen) > MAX_DOCUMENTS:
        raise ValueError("source_document_selection_invalid")
    from .chunk_store import get_chunk_store
    marks = ",".join("?" for _ in chosen)
    rows = get_chunk_store().connection().execute(
        f"SELECT doc_id,file_name,page_number,text FROM chunks WHERE project_id=? "
        f"AND doc_id IN ({marks}) ORDER BY file_name,page_number,chunk_id",
        [project_id, *chosen],
    ).fetchall()
    metadata = {record.doc_id: record for record in get_document_index().list_project(project_id)}
    # Table files intentionally never enter the RAG/chunk queue.  Their canonical
    # evidence is read from project-scoped parquet and receives sheet/row anchors.
    table_evidence, table_found = _table_evidence(project_id, chosen, metadata)
    found = {str(row[0]) for row in rows} | table_found
    if found != set(chosen):
        raise ValueError("source_document_not_in_project")
    evidence: List[EvidenceItem] = []
    for doc_id, file_name, page, text in rows:
        record = metadata.get(str(doc_id)); raw = str(text or "")
        for offset in range(0, len(raw), 3_500):
            excerpt = raw[offset:offset + 3_500].strip()
            if not excerpt:
                continue
            kind = "email" if str(file_name).lower().endswith((".eml", ".msg")) else "document"
            evidence.append(EvidenceItem(
                source_id=_source_id(project_id, str(doc_id), int(page or 1), offset, excerpt),
                doc_id=str(doc_id), file_name=str(file_name),
                title=(record.title if record else str(file_name)),
                document_date=(record.metadata_date if record else ""),
                page=int(page or 1), kind=kind, excerpt=excerpt,
            ))
    evidence.extend(table_evidence)
    return evidence


def evidence_markdown(evidence: Sequence[EvidenceItem]) -> str:
    lines: List[str] = []
    last_doc = ""; last_page: int | None = None
    for item in evidence:
        if item.doc_id != last_doc:
            lines.extend((
                f"<!-- DOC:BEGIN id={item.doc_id} file={item.file_name} -->",
                f"# {item.title or item.file_name}",
                f"- document_id: {item.doc_id}",
                f"- discovery_metadata_date: {item.document_date or 'unknown'} "
                "(FOR SEARCH ONLY; NOT EVENT-DATE EVIDENCE)",
            ))
            last_doc, last_page = item.doc_id, None
        if item.kind == "excel":
            lines.append(
                f"\n<!-- TABLE sheet={item.sheet or 'unknown'} "
                f"rows={item.row_from or 'unknown'}-{item.row_to or 'unknown'} -->"
            )
        elif item.page != last_page:
            lines.append(f"\n<!-- PAGE:{item.page or 'unknown'} -->")
            last_page = item.page
        lines.extend((f"<!-- EXCERPT id={item.source_id} -->", item.excerpt))
    if last_doc:
        lines.append("<!-- DOC:END -->")
    return "\n".join(lines)


def _batches(evidence: Sequence[EvidenceItem]) -> List[List[EvidenceItem]]:
    batches: List[List[EvidenceItem]] = []; current: List[EvidenceItem] = []; size = 0
    for item in evidence:
        item_size = len(item.excerpt) + 220
        if current and size + item_size > EVIDENCE_BATCH_CHARS:
            batches.append(current); current = []; size = 0
        current.append(item); size += item_size
    if current:
        batches.append(current)
    return batches


def _select(candidates: Sequence[CandidateDocument], *, maximum: int = TARGET_DOCUMENTS) -> List[CandidateDocument]:
    readable = [item for item in candidates if item.ocr_quality != "unreadable"]
    maps = [item for item in readable if item.role == "map"][:2]
    primary = [item for item in readable if item.role == "primary"][:7]
    corroborators = [item for item in readable if item.role == "corroborator"][:3]
    selected: List[CandidateDocument] = []
    for item in [*maps, *primary, *corroborators, *readable]:
        if item.doc_id not in {value.doc_id for value in selected}:
            selected.append(item)
        if len(selected) >= maximum:
            break
    return selected


def _map_extract(
    evidence: Sequence[EvidenceItem], *, prepared: PreparedChronologyQuery,
    cache_context: str,
) -> Dict:
    if not evidence:
        return {"skeleton": [], "leads": []}
    prompts = load_chronology_v3_prompts()
    from .llm_client import generate_response_json
    response = generate_response_json(
        f"TOPIC: {prepared.english_query}\n{prompts['map_extractor']}\n\n"
        f"EVIDENCE BEGIN\n{evidence_markdown(evidence)}\nEVIDENCE END",
        system=prompts["system"], schema=MapExtractionModel.model_json_schema(),
        schema_name="chronology_v3_map_extraction", validation_model=MapExtractionModel,
        task_type="chronology_extract", thinking_level="low", max_tokens=8_192,
        prompt_version=prompts["version"], cache_key="chron-v3-map",
        cache_context=cache_context, ttl_s=0,
    )
    value = MapExtractionModel.model_validate(response.raw).model_dump()
    valid_ids = {item.source_id for item in evidence}
    value["leads"] = [lead for lead in value["leads"]
                      if not lead.get("source_id") or lead["source_id"] in valid_ids]
    return value


def research_documents(
    project_id: str, prepared: PreparedChronologyQuery,
    *, load_step: Callable[[str, str], Dict | None] | None = None,
    save_step: Callable[[str, str, str, Dict | None, str], None] | None = None,
) -> Tuple[List[CandidateDocument], List[EvidenceItem], Dict]:
    index = get_document_index()
    discovery_input = {
        "topic": prepared.english_query, "queries": prepared.research_queries,
        "parties": prepared.parties, "index_revision": _hash([
            asdict(record) for record in index.list_project(project_id)
        ]),
    }
    discovery_hash = _hash(discovery_input)
    initial = index.search(
        project_id=project_id, topic=prepared.english_query,
        queries=prepared.research_queries, parties=prepared.parties, limit=100,
    )
    selected = _select(initial)
    if not selected:
        raise ValueError("no_evidence")
    if save_step:
        save_step("document_discovery", discovery_hash, "ready", {
            "candidates": [asdict(item) for item in initial],
            "selected": [item.doc_id for item in selected],
        }, "")

    map_docs = [item for item in selected if item.role == "map"]
    map_evidence = evidence_from_documents(project_id, [item.doc_id for item in map_docs]) if map_docs else []
    map_hash = _hash({
        "evidence": [asdict(item) for item in map_evidence],
        "prompt": chronology_v3_prompt_hash(),
        "schema": MapExtractionModel.model_json_schema(),
    })
    previous = load_step("map_extraction", map_hash) if load_step else None
    if previous and previous.get("status") == "ready":
        map_result = previous.get("output") or {"skeleton": [], "leads": []}
    else:
        try:
            map_result = _map_extract(
                map_evidence, prepared=prepared,
                cache_context=f"{chronology_v3_prompt_hash()}:{map_hash}",
            )
            if save_step:
                save_step("map_extraction", map_hash, "ready", map_result, "")
        except Exception as exc:
            if save_step:
                save_step(
                    "map_extraction", map_hash, "failed", None,
                    "model_output_incomplete" if _is_structured_output_error(exc) else "",
                )
            if not _is_structured_output_error(exc):
                raise
            raise RuntimeError("model_output_incomplete") from exc

    lead_queries = [str(item.get("suggested_query") or "").strip()
                    for item in map_result.get("leads", []) if item.get("suggested_query")]
    if not lead_queries:
        lead_queries = [value for item in selected[:5]
                        for value in (item.reference, item.title) if value]
    second = index.search(
        project_id=project_id, topic=prepared.english_query,
        queries=[*prepared.research_queries, *lead_queries],
        parties=prepared.parties, limit=120,
    )
    combined = {item.doc_id: item for item in initial}
    for item in second:
        current = combined.get(item.doc_id)
        if current is None or item.score > current.score:
            combined[item.doc_id] = item
    selected = _select(sorted(combined.values(), key=lambda item: -item.score))

    # Two deterministic coverage gap rounds.  New documents extend the source
    # set up to the hard maximum; they never displace a stronger map/primary.
    evidence = evidence_from_documents(project_id, [item.doc_id for item in selected])
    coverage = coverage_matrix(evidence)
    for _ in range(2):
        missing = [facet for facet, value in coverage.items() if value == 0]
        if not missing or len(selected) >= MAX_DOCUMENTS:
            break
        gap_queries = [f"{prepared.english_query} {facet.replace('_', ' ')}" for facet in missing]
        gap = index.search(
            project_id=project_id, topic=prepared.english_query,
            queries=gap_queries, parties=prepared.parties, limit=100,
        )
        before = len(selected)
        for item in gap:
            if item.ocr_quality != "unreadable" and item.doc_id not in {d.doc_id for d in selected}:
                selected.append(item)
            if len(selected) >= MAX_DOCUMENTS:
                break
        if len(selected) == before:
            break
        evidence = evidence_from_documents(project_id, [item.doc_id for item in selected])
        coverage = coverage_matrix(evidence)

    warnings: List[str] = []
    if not map_docs:
        warnings.append("map_document_missing")
    unreadable = [item.doc_id for item in initial if item.ocr_quality == "unreadable"]
    if unreadable:
        warnings.append("unreadable_leads_excluded")
    indexed_by_id = {item.doc_id: item for item in index.list_project(project_id)}
    selected_blob = " ".join(indexed_by_id[item.doc_id].search_text.casefold()
                             for item in selected if item.doc_id in indexed_by_id)
    missing_parties = [party for party in prepared.parties if party.casefold() not in selected_blob]
    if len(prepared.parties) >= 2 and missing_parties:
        warnings.append("counter_source_missing")
    audit = {
        "candidates": [asdict(item) for item in sorted(combined.values(), key=lambda item: -item.score)],
        "selected": [asdict(item) for item in selected],
        "research_leads": map_result.get("leads", []),
        "map_skeleton": map_result.get("skeleton", []),
        "coverage": coverage, "warnings": warnings,
        "unreadable_lead_doc_ids": unreadable,
    }
    lead_hash = _hash({"leads": lead_queries, "selected": audit["selected"]})
    if save_step:
        save_step("lead_search", lead_hash, "ready", audit, "")
        save_step("coverage_review", _hash(coverage), "ready", {
            "coverage": coverage, "warnings": warnings,
        }, "")
    return selected, evidence, audit


def _events_valid(value: Dict, evidence: Sequence[EvidenceItem]) -> bool:
    by_id = {item.source_id: item.excerpt.casefold() for item in evidence}
    for event in value.get("entries", []):
        ids = [str(value) for value in event.get("supporting_source_ids", [])]
        if not ids or any(source_id not in by_id for source_id in ids):
            return False
        date_source = str(event.get("date_source") or "unresolved")
        event_date = str(event.get("event_date") or "").strip()
        date_evidence = str(event.get("date_evidence") or "").strip()
        if date_source not in ALLOWED_DATE_SOURCES:
            return False
        if date_source == "unresolved" and (event_date or date_evidence):
            return False
        if date_source != "unresolved":
            precision = str(event.get("date_precision") or "exact").casefold()
            date_patterns = {
                "exact": r"\d{4}-\d{2}-\d{2}",
                "day": r"\d{4}-\d{2}-\d{2}",
                "month": r"\d{4}-\d{2}",
                "year": r"\d{4}",
                "approximate": r"\d{4}(?:-\d{2}(?:-\d{2})?)?",
            }
            pattern = date_patterns.get(precision)
            if not pattern or not re.fullmatch(pattern, event_date):
                return False
            source_text = " ".join(by_id[source_id] for source_id in ids)
            if not date_evidence or date_evidence.casefold() not in source_text:
                return False
        source_text = " ".join(by_id[source_id] for source_id in ids)
        prose = " ".join(str(event.get(key) or "") for key in (
            "actor", "action", "established_fact", "party_position",
            "analytical_inference", "immediate_consequence",
        ))
        numbers = re.findall(r"(?<![a-z])\d[\d,.%/-]*", prose.casefold())
        if any(number not in source_text for number in numbers):
            return False
        quotes = re.findall(r'["“]([^"”]{3,})["”]', prose)
        if any(quote.casefold().strip() not in source_text for quote in quotes):
            return False
    return True


def extract_events(
    evidence: Sequence[EvidenceItem], prepared: PreparedChronologyQuery,
    *, map_skeleton: Sequence[str] = (),
    load_step: Callable[[str, str], Dict | None] | None = None,
    save_step: Callable[[str, str, str, Dict | None, str], None] | None = None,
    job_scope: str = "",
) -> List[Dict]:
    prompts = load_chronology_v3_prompts(); results: List[Dict] = []
    from .llm_client import generate_response_json

    def run(batch: List[EvidenceItem], key: str, depth: int = 0) -> None:
        input_hash = _hash({
            "evidence": [asdict(item) for item in batch],
            "prompt": chronology_v3_prompt_hash(),
            "schema": ExtractionModel.model_json_schema(),
        })
        previous = load_step(key, input_hash) if load_step else None
        if previous and previous.get("status") == "ready":
            results.extend((previous.get("output") or {}).get("entries", [])); return
        if save_step:
            save_step(key, input_hash, "processing", None, "")
        prompt = (
            f"TOPIC: {prepared.english_query}\nMAP SKELETON (DISCOVERY GUIDE ONLY):\n"
            f"{json.dumps(list(map_skeleton), ensure_ascii=False)}\n{prompts['extractor']}\n\n"
            f"EVIDENCE BEGIN\n{evidence_markdown(batch)}\nEVIDENCE END"
        )
        try:
            response = generate_response_json(
                prompt, system=prompts["system"], schema=ExtractionModel.model_json_schema(),
                schema_name="chronology_v3_extraction", validation_model=ExtractionModel,
                task_type="chronology_extract", thinking_level="low", max_tokens=16_384,
                prompt_version=prompts["version"], cache_key="chron-v3-extract",
                cache_context=f"{job_scope}:{chronology_v3_prompt_hash()}:{input_hash}",
                ttl_s=0, semantic_validator=lambda value: _events_valid(value, batch),
            )
            entries = response.raw.get("entries", [])
            if save_step:
                save_step(key, input_hash, "ready", {"entries": entries}, "")
            results.extend(entries)
        except Exception as exc:
            if _is_structured_output_error(exc) and len(batch) > 1 and depth < 8:
                middle = len(batch) // 2
                run(batch[:middle], key + "a", depth + 1)
                run(batch[middle:], key + "b", depth + 1)
                return
            if save_step:
                save_step(
                    key, input_hash, "failed", None,
                    "model_output_incomplete" if _is_structured_output_error(exc) else "",
                )
            if not _is_structured_output_error(exc):
                raise
            raise RuntimeError("model_output_incomplete") from exc

    for index, batch in enumerate(_batches(evidence), 1):
        run(list(batch), f"extract:{index}")
    return results


def aggregate_events(
    events: Sequence[Dict], evidence: Sequence[EvidenceItem],
    prepared: PreparedChronologyQuery,
) -> List[Dict]:
    # Exact duplicate removal is deterministic.  The LLM aggregation call is
    # only paid when the evidence batches produced more than the final schema can hold.
    unique: Dict[Tuple[str, str, str], Dict] = {}
    for event in events:
        key = (
            str(event.get("event_date") or ""), str(event.get("actor") or "").casefold(),
            re.sub(r"\W+", " ", str(event.get("action") or "").casefold())[:120],
        )
        unique.setdefault(key, event)
    current = sorted(unique.values(), key=lambda item: (
        str(item.get("event_date") or "9999-99-99"), str(item.get("actor") or ""),
    ))
    if len(current) <= 18:
        return current
    used = {str(source_id) for event in current for source_id in (
        list(event.get("supporting_source_ids", [])) + list(event.get("counter_source_ids", []))
    )}
    cited = [item for item in evidence if item.source_id in used]
    prompts = load_chronology_v3_prompts()
    from .llm_client import generate_response_json
    response = generate_response_json(
        f"TOPIC: {prepared.english_query}\nConsolidate duplicates into at most 18 material "
        "events. Preserve date_source/date_evidence, counter-sources and missing records. "
        "Do not introduce facts or sources.\n\nEVENTS:\n"
        f"{json.dumps(current, ensure_ascii=False)}\n\nEVIDENCE BEGIN\n"
        f"{evidence_markdown(cited)}\nEVIDENCE END",
        system=prompts["system"], schema=ExtractionModel.model_json_schema(),
        schema_name="chronology_v3_aggregation", validation_model=ExtractionModel,
        task_type="chronology_aggregation", thinking_level="low", max_tokens=16_384,
        prompt_version=prompts["version"], cache_key="chron-v3-aggregate",
        cache_context=_hash(current), ttl_s=0,
        semantic_validator=lambda value: _events_valid(value, cited),
    )
    return response.raw.get("entries", [])[:18]


def _style_valid(value: Dict) -> bool:
    overview_words = sum(
        len(re.findall(r"\b\w+[’'-]?\w*\b", str(claim.get("text") or "")))
        for claim in value.get("overview_claims", [])
    )
    if not 90 <= overview_words <= 160:
        return False
    entries = list(value.get("entries", []))
    if not entries or len(entries) > 18:
        return False
    dates = [str(event.get("event_date") or "") for event in entries]
    if dates != sorted(dates):
        return False
    for event in entries:
        words = sum(
            len(re.findall(r"\b\w+[’'-]?\w*\b", str(claim.get("text") or "")))
            for claim in event.get("claims", [])
        )
        if not 30 <= words <= 120:
            return False
    return True


def _final_valid(
    value: Dict, evidence: Sequence[EvidenceItem], *, enforce_style: bool = True,
) -> bool:
    by_id = {item.source_id: item.excerpt.casefold() for item in evidence}
    events = list(value.get("entries", []))
    for event in events:
        if event.get("date_source") not in ALLOWED_DATE_SOURCES - {"unresolved"}:
            return False
        date_evidence = str(event.get("date_evidence") or "")
        ids = [str(source_id) for claim in event.get("claims", [])
               for source_id in claim.get("source_ids", [])]
        source_text = " ".join(by_id.get(source_id, "") for source_id in ids)
        if not date_evidence or date_evidence.casefold() not in source_text:
            return False
    claim_groups = [{"claims": value.get("overview_claims", [])}, *events]
    for group in claim_groups:
        for claim in group.get("claims", []):
            ids = [str(source_id) for source_id in claim.get("source_ids", [])]
            if not ids or any(source_id not in by_id for source_id in ids):
                return False
            source_text = " ".join(by_id[source_id] for source_id in ids)
            text = str(claim.get("text") or "").casefold()
            if any(number not in source_text for number in re.findall(r"(?<![a-z])\d[\d,.%/-]*", text)):
                return False
            if any(quote.casefold().strip() not in source_text for quote in
                   re.findall(r'["“]([^"”]{3,})["”]', str(claim.get("text") or ""))):
                return False
    return not enforce_style or _style_valid(value)


def synthesize(
    events: Sequence[Dict], evidence: Sequence[EvidenceItem],
    prepared: PreparedChronologyQuery, *, cache_context: str,
) -> Dict:
    prompts = load_chronology_v3_prompts()
    used = {str(source_id) for event in events for source_id in (
        list(event.get("supporting_source_ids", [])) + list(event.get("counter_source_ids", []))
    )}
    cited = [item for item in evidence if item.source_id in used]
    from .llm_client import generate_response_json
    response = generate_response_json(
        f"TOPIC: {prepared.english_query}\nPARTIES: {', '.join(prepared.parties)}\n"
        f"{prompts['synthesizer']}\n{prompts['style_profile']}\n\nVERIFIED LEDGER:\n"
        f"{json.dumps(list(events), ensure_ascii=False)}\n\nEVIDENCE BEGIN\n"
        f"{evidence_markdown(cited)}\nEVIDENCE END",
        system=prompts["system"], schema=ChronologyModel.model_json_schema(),
        schema_name="chronology_v3_report", validation_model=ChronologyModel,
        task_type="chronology_synthesis", thinking_level="medium", max_tokens=32_768,
        prompt_version=prompts["version"], cache_key="chron-v3-synthesis",
        cache_context=cache_context, ttl_s=0,
        semantic_validator=lambda value: _final_valid(value, cited),
    )
    return ChronologyModel.model_validate(response.raw).model_dump()


def verify_and_repair(
    chronology: Dict, evidence: Sequence[EvidenceItem],
    prepared: PreparedChronologyQuery, *, cache_context: str,
) -> Tuple[Dict, Dict]:
    prompts = load_chronology_v3_prompts(); claims: List[Dict] = []
    for index, claim in enumerate(chronology.get("overview_claims", [])):
        claims.append({"claim_ref": f"overview:{index}", **claim})
    for event_index, event in enumerate(chronology.get("entries", [])):
        for claim_index, claim in enumerate(event.get("claims", [])):
            claims.append({
                "claim_ref": f"event:{event_index}:{claim_index}",
                "event_date": event.get("event_date"),
                "date_source": event.get("date_source"),
                "date_evidence": event.get("date_evidence"), **claim,
            })
    refs = {str(claim["claim_ref"]) for claim in claims}
    used = {str(source_id) for claim in claims for source_id in claim.get("source_ids", [])}
    cited = [item for item in evidence if item.source_id in used]
    from .llm_client import generate_response_json

    def valid_decisions(value: Dict) -> bool:
        decisions = value.get("decisions", [])
        return len(decisions) == len(refs) and {
            str(item.get("claim_ref") or "") for item in decisions
        } == refs

    verification = generate_response_json(
        f"TOPIC: {prepared.english_query}\n{prompts['verifier']}\n\nCLAIMS:\n"
        f"{json.dumps(claims, ensure_ascii=False)}\n\nEVIDENCE BEGIN\n"
        f"{evidence_markdown(cited)}\nEVIDENCE END",
        system=prompts["system"], schema=VerificationModel.model_json_schema(),
        schema_name="chronology_v3_verification", validation_model=VerificationModel,
        task_type="chronology_verify", thinking_level="low", max_tokens=8_192,
        prompt_version=prompts["version"], cache_key="chron-v3-verification",
        cache_context=cache_context, ttl_s=0, semantic_validator=valid_decisions,
    ).raw
    flagged = [item for item in verification.get("decisions", [])
               if item.get("decision") in ("QUALIFY", "SPLIT")]
    repairs_by_ref: Dict[str, List[str]] = {}
    if flagged:
        flagged_refs = {str(item["claim_ref"]) for item in flagged}
        flagged_claims = [item for item in claims if item["claim_ref"] in flagged_refs]

        def repairs_valid(value: Dict) -> bool:
            repairs = value.get("repairs", [])
            if {str(item.get("claim_ref") or "") for item in repairs} != flagged_refs:
                return False
            probe = {"overview_claims": []}
            by_ref = {item["claim_ref"]: item for item in flagged_claims}
            for item in repairs:
                original = by_ref[item["claim_ref"]]
                for text in item.get("texts", []):
                    probe["overview_claims"].append({
                        "text": text, "source_ids": original.get("source_ids", []),
                    })
            return _final_valid(
                {"overview_claims": probe["overview_claims"], "entries": []},
                cited, enforce_style=False,
            )

        repaired = generate_response_json(
            f"{prompts['repair']}\n\nFLAGGED CLAIMS:\n"
            f"{json.dumps(flagged_claims, ensure_ascii=False)}\n\nDECISIONS:\n"
            f"{json.dumps(flagged, ensure_ascii=False)}\n\nEVIDENCE BEGIN\n"
            f"{evidence_markdown(cited)}\nEVIDENCE END",
            system=prompts["system"], schema=RepairModel.model_json_schema(),
            schema_name="chronology_v3_repair", validation_model=RepairModel,
            task_type="chronology_verify", thinking_level="low", max_tokens=8_192,
            prompt_version=prompts["version"], cache_key="chron-v3-repair",
            cache_context=f"{cache_context}:repair", ttl_s=0,
            semantic_validator=repairs_valid,
        ).raw
        repairs_by_ref = {str(item["claim_ref"]): list(item.get("texts", []))
                          for item in repaired.get("repairs", [])}

    decisions = {str(item["claim_ref"]): item for item in verification.get("decisions", [])}

    def apply_claims(raw_claims: Sequence[Dict], prefix: str) -> List[Dict]:
        output: List[Dict] = []
        for index, claim in enumerate(raw_claims):
            ref = f"{prefix}:{index}"; decision = decisions[ref]["decision"]
            if decision in ("REMOVE", "NEEDS_HUMAN_REVIEW"):
                continue
            texts = repairs_by_ref.get(ref, [claim["text"]])
            for text in texts:
                output.append({**claim, "text": text})
        return output[:3 if prefix == "overview" else 2]

    result = dict(chronology)
    result["overview_claims"] = apply_claims(chronology.get("overview_claims", []), "overview")
    repaired_entries: List[Dict] = []
    for event_index, event in enumerate(chronology.get("entries", [])):
        value = dict(event)
        value["claims"] = apply_claims(event.get("claims", []), f"event:{event_index}")
        if value["claims"]:
            repaired_entries.append(value)
    result["entries"] = repaired_entries
    if not result["overview_claims"] or not result["entries"] or not _final_valid(result, evidence):
        raise ValueError("source_verification_failed")
    return result, {"decisions": verification.get("decisions", []), "repairs": repairs_by_ref}


def generate_chronology_v3(
    *, project_id: str, project_name: str, topic: str, issue_number: int = 1,
    job_id: str = "", date_from: str = "", date_to: str = "",
    parties: Sequence[str] = (),
    stage_callback: Optional[Callable[[str, float], None]] = None,
    load_step: Optional[Callable[[str, str], Dict | None]] = None,
    save_step: Optional[Callable[[str, str, str, Dict | None, str], None]] = None,
    **_ignored,
) -> Dict:
    from .report_docx import build_ai_chronology_docx, validate_ai_chronology_docx

    def stage(name: str, progress: float) -> None:
        if stage_callback:
            stage_callback(name, progress)

    stage("topic_preparation", .06)
    preparation_hash = _hash({
        "topic": topic, "date_from": date_from, "date_to": date_to,
        "parties": list(parties), "project_id": project_id,
        "prompt": chronology_v3_prompt_hash(), "jargon": jargon_dictionary_version(),
    })
    prepared_step = load_step("topic_preparation", preparation_hash) if load_step else None
    if prepared_step and prepared_step.get("status") == "ready":
        raw_prepared = prepared_step.get("output") or {}
        prepared = PreparedChronologyQuery(
            original_query=str(raw_prepared.get("original_query") or topic),
            english_query=str(raw_prepared.get("english_query") or topic),
            jargon_matches=tuple(tuple(item) for item in raw_prepared.get("jargon_matches", [])),
            parties=tuple(raw_prepared.get("parties", parties)),
            contracts=tuple(raw_prepared.get("contracts", [])),
            work_packages=tuple(raw_prepared.get("work_packages", [])),
            exclusions=tuple(raw_prepared.get("exclusions", [])),
            research_queries=tuple(raw_prepared.get("research_queries", _fallback_queries(topic))),
        )
    else:
        prepared = prepare_chronology_query(
            topic, date_from=date_from, date_to=date_to, parties=parties,
            project_id=project_id,
        )
        if save_step:
            save_step("topic_preparation", preparation_hash, "ready", asdict(prepared), "")
    stage("document_discovery", .13)
    selected, evidence, research_audit = research_documents(
        project_id, prepared, load_step=load_step, save_step=save_step,
    )
    if not evidence:
        raise ValueError("no_evidence")
    evidence_hash = _hash([asdict(item) for item in evidence])
    if save_step:
        save_step("evidence_pack", evidence_hash, "ready", {
            "source_count": len(evidence), "batch_count": len(_batches(evidence)),
            "selected_doc_ids": [item.doc_id for item in selected],
        }, "")
    stage("evidence_pack", .25)
    stage("extraction", .36)
    events = extract_events(
        evidence, prepared, map_skeleton=research_audit.get("map_skeleton", []),
        load_step=load_step, save_step=save_step, job_scope=job_id or project_id,
    )
    if not events:
        raise ValueError("insufficient_evidence")
    stage("coverage_review", .54)
    stage("aggregation", .58)
    aggregation_hash = _hash({"events": events, "evidence": evidence_hash})
    aggregation_step = load_step("aggregation", aggregation_hash) if load_step else None
    if aggregation_step and aggregation_step.get("status") == "ready":
        events = list((aggregation_step.get("output") or {}).get("entries", []))
    else:
        events = aggregate_events(events, evidence, prepared)
        if save_step:
            save_step("aggregation", aggregation_hash, "ready", {"entries": events}, "")
    stage("synthesis", .70)
    synthesis_hash = _hash({"events": events, "evidence": evidence_hash,
                            "prompt": chronology_v3_prompt_hash()})
    synthesis_step = load_step("synthesis", synthesis_hash) if load_step else None
    if (synthesis_step and synthesis_step.get("status") == "ready"
            and (synthesis_step.get("output") or {}).get("chronology")):
        chronology = dict((synthesis_step.get("output") or {})["chronology"])
    else:
        chronology = synthesize(
            events, evidence, prepared,
            cache_context=f"{job_id}:{chronology_v3_prompt_hash()}:{evidence_hash}",
        )
        if save_step:
            save_step("synthesis", synthesis_hash, "ready", {"chronology": chronology}, "")
    stage("verification", .82)
    verification_hash = _hash({
        "chronology": chronology, "evidence": evidence_hash,
        "prompt": chronology_v3_prompt_hash(),
        "schemas": [VerificationModel.model_json_schema(), RepairModel.model_json_schema()],
    })
    verification_step = load_step("verification", verification_hash) if load_step else None
    if (verification_step and verification_step.get("status") == "ready"
            and (verification_step.get("output") or {}).get("chronology")):
        verification_output = verification_step.get("output") or {}
        chronology = dict(verification_output.get("chronology", {}))
        verification_audit = dict(verification_output.get("audit", {}))
    else:
        chronology, verification_audit = verify_and_repair(
            chronology, evidence, prepared,
            cache_context=f"{job_id}:{_hash(chronology)}",
        )
        if save_step:
            save_step("verification", verification_hash, "ready", {
                "chronology": chronology, "audit": verification_audit,
            }, "")
    entries: List[ChronologyEntry] = []
    entries.append(ChronologyEntry(
        entry_ref=f"6.{issue_number}.1", event_date="", date_precision="unknown",
        claims=[VerifiedClaim(**claim, supported=True) for claim in chronology["overview_claims"]],
        event_type="overview",
    ))
    for index, event in enumerate(chronology["entries"], 2):
        entries.append(ChronologyEntry(
            entry_ref=f"6.{issue_number}.{index}", event_date=event["event_date"],
            date_precision=event["date_precision"],
            claims=[VerifiedClaim(**claim, supported=True) for claim in event["claims"]],
            parties=list(event.get("parties", [])), event_type=event.get("event_type", "event"),
            conflicting_positions=list(event.get("conflicting_positions", [])),
        ))
    issued_source_ids = {
        source_id for entry in entries for claim in entry.claims
        for source_id in claim.source_ids
    }
    issued_evidence = [
        item for item in evidence if item.source_id in issued_source_ids
    ]
    stage("word_render", .91)
    blob, word_audit = build_ai_chronology_docx(
        project_name=project_name, issue_number=issue_number, title=topic,
        entries=entries, evidence=issued_evidence, audit_metadata=None,
    )
    if word_audit.unresolved_source_ids or word_audit.footnote_records == 0:
        raise ValueError("source_verification_failed")
    render_audit = validate_ai_chronology_docx(blob, expected_entries=len(entries))
    if save_step:
        save_step("word_render", _hash({
            "chronology": chronology, "evidence": evidence_hash,
            "project_name": project_name, "issue_number": issue_number,
        }), "ready", render_audit, "")
    return {
        "entries": [asdict(item) for item in entries],
        "evidence": [asdict(item) for item in issued_evidence],
        "audit": asdict(word_audit), "docx": blob,
        "model": "gemini-3.6-flash", "pipeline_version": PIPELINE_VERSION,
        "prompt_version": load_chronology_v3_prompts()["version"],
        "coverage_status": "partial" if research_audit["warnings"] else "complete",
        "research_audit": research_audit,
        "verification_audit": verification_audit,
        "render_audit": render_audit,
        "selected_doc_ids": [item.doc_id for item in selected],
        "research_questions": list(prepared.research_queries),
        "removed_claims": sum(1 for item in verification_audit["decisions"]
                              if item["decision"] in ("REMOVE", "NEEDS_HUMAN_REVIEW")),
    }


__all__ = [
    "PIPELINE_VERSION", "prepare_chronology_query", "research_documents",
    "extract_events", "generate_chronology_v3",
]
