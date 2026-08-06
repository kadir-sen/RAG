"""Evidence-grounded AI generation for the existing Chronology/Forensic modules."""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .evidence_model import ChronologyEntry, EvidenceItem, VerifiedClaim
from .evidence_pack import CANDIDATE_PASSAGES, assess_pack, select_pack
from .report_docx import FORENSIC_SECTIONS, build_ai_chronology_docx, build_forensic_report_docx


PROMPT_VERSION = "chronology-v2"
FORENSIC_PROMPT_VERSION = "evidence-report-v1"
MODEL_POLICY = "quality-demo-v1"

DEFAULT_RESEARCH_QUESTIONS = [
    "What is the starting point of the issue?",
    "Which contract or obligation applies?",
    "Which events and correspondence occurred?",
    "What positions did the parties take?",
    "Which dates are exact and which are inferred?",
    "Are there conflicting or missing records?",
    "What later event or outcome followed?",
]

_SYSTEM = """You are preparing an evidence-led construction dispute report.
Use only the supplied evidence objects. Keep facts, party allegations, and
inferences distinct. Never invent a document identifier, date, person, number,
quotation, entitlement, causation conclusion, delay duration, or critical path
calculation. Every factual claim must cite one or more supplied source_id values.
If the record does not establish a point, state that the record is not
established. Produce professional English suitable for solicitor review."""


def build_research_plan(topic: str, date_from: str = "", date_to: str = "",
                        parties: Sequence[str] = ()) -> List[str]:
    from .jargon_manager import prepare_query, set_current_prepared_query
    prepared = prepare_query(topic)
    set_current_prepared_query(prepared)
    prompt = (
        "Create a compact research plan for this chronology/report topic. "
        "Return JSON as {\"questions\":[...]} with 7-10 non-overlapping questions. "
        "Write every research question in English, regardless of the input language.\n"
        f"Topic: {topic}\nDate range: {date_from or 'open'} to {date_to or 'open'}\n"
        f"Parties: {', '.join(parties) or 'not specified'}\n{prepared.context}"
    )
    try:
        from .config import GEMINI_MODEL_LITE
        from .llm_client import generate_json
        response = generate_json(
            prompt, system="You are a fast legal-document research planner. JSON only.",
            provider="gemini", model=GEMINI_MODEL_LITE,
            cache_key="chron-plan:" + hashlib.sha256(prompt.encode()).hexdigest()[:24],
            task_type="research_plan",
        )
        questions = response.raw.get("questions", []) if isinstance(response.raw, dict) else []
        questions = [str(q).strip() for q in questions if str(q).strip()]
        if len(questions) >= 4:
            return questions[:10]
    except Exception:
        pass
    return list(DEFAULT_RESEARCH_QUESTIONS)


def _source_id(project_id: str, doc_id: str, page: int, text: str) -> str:
    return "src_" + hashlib.sha256(
        f"{project_id}|{doc_id}|{page}|{text[:240]}".encode("utf-8")
    ).hexdigest()[:16]


def _to_evidence(project_id: str, source: Dict) -> EvidenceItem | None:
    file_name = str(source.get("file_name") or source.get("doc_name") or "").strip()
    doc_id = str(source.get("doc_id") or file_name).strip()
    text = str(source.get("text_snippet") or source.get("highlight_text")
               or source.get("text") or "").strip()
    if not file_name or not text:
        return None
    try:
        page = int(source.get("page_number") or 1)
    except Exception:
        page = 1
    kind = "email" if file_name.lower().endswith((".eml", ".msg")) else (
        "excel" if file_name.lower().endswith((".xlsx", ".xls", ".csv")) else "document"
    )
    sid = _source_id(project_id, doc_id, page, text)
    return EvidenceItem(
        source_id=sid, doc_id=doc_id, file_name=file_name,
        title=str(source.get("title") or file_name),
        document_date=str(source.get("date") or source.get("document_date") or ""),
        page=page if kind == "document" else None, kind=kind,
        sender=str(source.get("sender") or ""), recipient=str(source.get("recipient") or ""),
        subject=str(source.get("subject") or ""), sheet=str(source.get("sheet") or ""),
        row_from=source.get("row_from"), row_to=source.get("row_to"),
        excerpt=text[:1200], score=float(source.get("score") or source.get("lex_score") or 0.0),
    )


def _rank_normalised(rows: Sequence[Dict]) -> List[Dict]:
    """Put one lane's results on a 0..1 scale so lanes can be compared.

    The lanes return incompatible quantities: RRF fusion scores (~0.03), raw
    cosine (0..1) and raw BM25 (unbounded, commonly 1..15). Merging them by
    `max` let BM25 win every contest by magnitude alone, and summing them per
    document — which chronology selection did — ranked documents by how
    lexically verbose they were.

    Each lane already returns its own results best-first, so position is the one
    signal that means the same thing everywhere. Normalising by rank discards
    magnitude deliberately: the magnitudes were not comparable, and a made-up
    common scale would be worse than an honest ordinal one.
    """
    total = len(rows)
    if not total:
        return []
    out: List[Dict] = []
    for position, row in enumerate(rows):
        item = dict(row)
        item["lane_score"] = row.get("score", row.get("lex_score"))
        item["score"] = (total - position) / total
        out.append(item)
    return out


def retrieve_evidence(project_id: str, questions: Sequence[str], top_k: int = 12) -> List[EvidenceItem]:
    """Run dense/hybrid and lexical lanes concurrently per research question."""
    from .document_rag import get_document_rag
    from .lexical_index import get_lexical_index
    from .project_context import set_current_project

    set_current_project(project_id, "editor")
    rag = get_document_rag()
    lexical = get_lexical_index()

    def dense(question: str) -> List[Dict]:
        try:
            from .jargon_manager import set_current_prepared_query
            set_current_prepared_query(question)
            return (rag.query(
                question, top_k=top_k, synthesize=False, rerank=True,
                project_id=project_id,
            ) or {}).get("sources", [])
        except Exception:
            return []

    def bm25(question: str) -> List[Dict]:
        return lexical.search_chunks(question, top_k=top_k, project_id=project_id)

    from .jargon_manager import prepare_query
    collected: List[Dict] = []
    with ThreadPoolExecutor(max_workers=min(6, max(2, len(questions) * 2))) as pool:
        futures = []
        for question in questions:
            prepared = prepare_query(question)
            for variant in prepared.retrieval_queries[:2]:
                futures.extend((pool.submit(dense, variant), pool.submit(bm25, variant)))
        for future in futures:
            try:
                collected.extend(_rank_normalised(future.result()))
            except Exception:
                pass
    # Relevance order, not submission order: the neighbour lane below reads the
    # first 60, and those used to be whatever the first two or three research
    # questions happened to return.
    collected.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)

    # Add adjacent pages from the scoped chunk mirror. A top-ranked sentence
    # often depends on the paragraph immediately before or after it; this lane
    # provides that context without broadening to another project.
    try:
        from .chunk_store import get_chunk_store
        con = get_chunk_store().connection()
        neighbours: List[Dict] = []
        for source in collected[:60]:
            file_name = str(source.get("file_name") or source.get("doc_name") or "")
            doc_id = str(source.get("doc_id") or "")
            page = int(source.get("page_number") or 1)
            rows = con.execute(
                "SELECT doc_id,file_name,page_number,text FROM chunks WHERE project_id=? "
                "AND (doc_id=? OR file_name=?) AND page_number BETWEEN ? AND ?",
                [project_id, doc_id, file_name, max(1, page - 1), page + 1],
            ).fetchall()
            neighbours.extend({
                "doc_id": row[0], "file_name": row[1], "page_number": row[2],
                "text": row[3], "score": float(source.get("score") or 0) * 0.85,
            } for row in rows)
        collected.extend(neighbours)
    except Exception:
        pass

    by_id: Dict[str, EvidenceItem] = {}
    for raw in collected:
        item = _to_evidence(project_id, raw)
        if item is None:
            continue
        current = by_id.get(item.source_id)
        if current is None or item.score > current.score:
            by_id[item.source_id] = item
    return sorted(by_id.values(), key=lambda x: x.score, reverse=True)[:CANDIDATE_PASSAGES]


def _evidence_payload(evidence: Sequence[EvidenceItem]) -> str:
    return json.dumps([asdict(e) for e in evidence], ensure_ascii=False)


def _chronology_schema() -> Dict:
    claim = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "text": {"type": "string"},
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "is_inference": {"type": "boolean"},
            "inference_basis": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["text", "source_ids", "is_inference", "inference_basis", "confidence"],
    }
    entry = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "event_date": {"type": "string"},
            "date_precision": {"type": "string", "enum": ["exact", "month", "year", "inferred", "unknown"]},
            "claims": {"type": "array", "items": claim},
            "parties": {"type": "array", "items": {"type": "string"}},
            "event_type": {"type": "string"},
            "conflicting_positions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["event_date", "date_precision", "claims", "parties", "event_type", "conflicting_positions"],
    }
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "overview_claims": {"type": "array", "items": claim},
            "entries": {"type": "array", "items": entry},
        },
        "required": ["overview_claims", "entries"],
    }


def _claim_supported(claim: VerifiedClaim, evidence_by_id: Dict[str, EvidenceItem]) -> bool:
    if not claim.source_ids or any(s not in evidence_by_id for s in claim.source_ids):
        return False
    words = {w for w in re.findall(r"[a-z0-9]{4,}", claim.text.lower())}
    source_words = set()
    for sid in claim.source_ids:
        source_words.update(re.findall(r"[a-z0-9]{4,}", evidence_by_id[sid].excerpt.lower()))
    combined_sources = " ".join(evidence_by_id[sid].excerpt for sid in claim.source_ids).lower()
    # Numbers and quoted passages are the highest-risk hallucinations in this
    # domain; every one must occur verbatim in at least one cited excerpt.
    claim_numbers = re.findall(r"(?<![a-z])\d[\d,.%/-]*", claim.text.lower())
    if any(number not in combined_sources for number in claim_numbers):
        return False
    quoted = re.findall(r"[\"“]([^\"”]{3,})[\"”]", claim.text)
    if any(value.lower().strip() not in combined_sources for value in quoted):
        return False
    # Entity/number-heavy claims need real overlap; prose can pass at a modest
    # threshold because the verifier receives short evidence excerpts.
    return not words or len(words & source_words) / max(1, len(words)) >= 0.12


def _generate_chronology_v2(
    *, project_id: str, project_name: str, topic: str, issue_number: int = 1,
    job_id: str = "",
    date_from: str = "", date_to: str = "", parties: Sequence[str] = (),
    source_doc_ids: Sequence[str] = (), preparation: Optional[Dict] = None,
    stage_callback: Optional[Callable[[str, float], None]] = None,
    load_step: Optional[Callable[[str, str], Dict | None]] = None,
    save_step: Optional[Callable[[str, str, str, Dict | None, str], None]] = None,
) -> Dict:
    """Generate a checkpointable chronology from a Markdown evidence pack."""
    from .chronology_prompts import chronology_prompt_hash
    from .chronology_v2 import (
        PIPELINE_VERSION, PreparedChronologyQuery, coverage_matrix,
        aggregate_candidates, evidence_from_documents, extract_batches,
        prepare_chronology_query, source_preview, synthesize, verify_claims,
    )
    from .jargon_manager import jargon_dictionary_version

    def stage(name: str, progress: float) -> None:
        if stage_callback:
            stage_callback(name, progress)

    stage("research_plan", .08)
    if preparation and preparation.get("prepared"):
        raw = preparation["prepared"]
        prepared = PreparedChronologyQuery(
            original_query=str(raw.get("original_query") or topic),
            english_query=str(raw.get("english_query") or topic),
            jargon_matches=tuple(tuple(value) for value in raw.get("jargon_matches", [])),
            parties=tuple(raw.get("parties", parties)), contracts=tuple(raw.get("contracts", [])),
            work_packages=tuple(raw.get("work_packages", [])),
            exclusions=tuple(raw.get("exclusions", [])),
            research_queries=tuple(raw.get("research_queries", [])),
        )
    else:
        prepared = prepare_chronology_query(
            topic, date_from=date_from, date_to=date_to, parties=parties,
            project_id=project_id,
        )

    chosen = [str(value) for value in source_doc_ids if str(value).strip()]
    if not chosen:
        # source_preview used to run here purely to turn retrieval into a list
        # of doc_ids, which the pack builder then re-read from disk. The pack
        # builder now keeps the passages directly, so calling it would mean
        # paying for the same retrieval twice. It remains the API's preview
        # endpoint, where showing the analyst the candidate documents is the
        # whole point.
        stage("source_selection", .14)
    stage("evidence_pack", .2)
    selection_stats: Dict = {}
    if source_doc_ids:
        # An explicit selection is the analyst's, not ours: read those documents
        # whole and do not second-guess the choice.
        evidence = evidence_from_documents(project_id, chosen)
    else:
        # Otherwise keep the passages retrieval actually scored, and bound the
        # pack by text. The previous path threw the scored passages away, kept
        # only their doc_ids and re-read those fragments whole — which is how a
        # 240 MB corpus produced a 24,000-character pack.
        from .chronology_v2 import COVERAGE_FACETS
        selection = select_pack(
            retrieve_evidence(project_id, prepared.research_queries),
            facets=COVERAGE_FACETS,
        )
        evidence = selection.evidence
        selection_stats = selection.stats
        chosen = sorted({item.doc_id for item in evidence if item.doc_id})
    if not evidence:
        raise ValueError("no_evidence")

    # Provider calls are governed by credits, bounded research rounds and
    # request timeouts. Do not make completion depend on corpus/cache-specific
    # call counts.

    stage("evidence_extraction", .3)
    extraction_stats: Dict = {}
    candidates = extract_batches(
        evidence, prepared, load_step=load_step, save_step=save_step,
        job_scope=job_id or f"project:{project_id}", stats=extraction_stats,
    )
    if not candidates:
        raise ValueError("insufficient_evidence")
    stage("aggregation", .58)
    candidates = aggregate_candidates(
        prepared=prepared, candidates=candidates, evidence=evidence,
        load_step=load_step, save_step=save_step,
    )
    stage("synthesis", .68)
    response = synthesize(
        prepared=prepared, candidates=candidates, evidence=evidence,
        cache_context=(
            f"{job_id or project_id}:{chronology_prompt_hash()}:"
            f"{jargon_dictionary_version()}:"
            f"{hashlib.sha256(_evidence_payload(evidence).encode()).hexdigest()}"
        ),
    )
    verification_hash = hashlib.sha256(json.dumps(
        response, sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()
    verification_step = load_step("verification", verification_hash) if load_step else None
    if verification_step and verification_step.get("status") == "ready":
        verification = dict((verification_step.get("output") or {}).get("decisions", {}))
    else:
        if save_step:
            save_step("verification", verification_hash, "processing", None, "")
        try:
            verification = verify_claims(
                prepared=prepared, chronology=response, evidence=evidence,
                cache_context=f"{job_id or project_id}:{verification_hash}",
            )
        except Exception:
            if save_step:
                save_step(
                    "verification", verification_hash, "failed", None,
                    "source_verification_failed",
                )
            raise
        if save_step:
            save_step(
                "verification", verification_hash, "ready",
                {"decisions": verification}, "",
            )
    by_id = {e.source_id: e for e in evidence}
    entries: List[ChronologyEntry] = []
    removed = 0
    overview_claims = []
    stage("verification", .82)
    for claim_index, item in enumerate(response.get("overview_claims", [])):
        claim = VerifiedClaim(
            text=str(item.get("text") or "").strip(),
            source_ids=[str(x) for x in item.get("source_ids", [])],
            is_inference=bool(item.get("is_inference")),
            inference_basis=str(item.get("inference_basis") or ""),
            confidence=str(item.get("confidence") or "low"),
        )
        claim.supported = (
            verification.get(f"overview:{claim_index}", False)
            and _claim_supported(claim, by_id)
        )
        if claim.supported:
            overview_claims.append(claim)
        else:
            removed += 1
    entries.append(ChronologyEntry(
        entry_ref=f"6.{issue_number}.1", event_date="", date_precision="unknown",
        claims=overview_claims, parties=[], event_type="overview",
        conflicting_positions=[],
    ))
    if not overview_claims:
        raise ValueError("source_verification_failed")
    ordered_raw = sorted(response.get("entries", []), key=lambda raw: (
        str(raw.get("event_date") or "9999-99-99"),
        " ".join(str(c.get("text") or "") for c in raw.get("claims", [])),
    ))
    original_event_indexes = {id(raw): index for index, raw in enumerate(response.get("entries", []))}
    for index, raw in enumerate(ordered_raw, 2):
        claims = []
        event_index = original_event_indexes[id(raw)]
        for claim_index, item in enumerate(raw.get("claims", [])):
            claim = VerifiedClaim(
                text=str(item.get("text") or "").strip(),
                source_ids=[str(x) for x in item.get("source_ids", [])],
                is_inference=bool(item.get("is_inference")),
                inference_basis=str(item.get("inference_basis") or ""),
                confidence=str(item.get("confidence") or "low"),
            )
            claim.supported = (
                verification.get(f"event:{event_index}:{claim_index}", False)
                and _claim_supported(claim, by_id)
            )
            if claim.supported:
                claims.append(claim)
            else:
                removed += 1
        if str(raw.get("date_precision") or "unknown") != "exact" and claims:
            claims[0].is_inference = True
            if not claims[0].inference_basis:
                claims[0].inference_basis = "The event date is inferred from the cited record"
        if not claims:
            continue
        entries.append(ChronologyEntry(
            entry_ref=f"6.{issue_number}.{index}", event_date=str(raw.get("event_date") or ""),
            date_precision=str(raw.get("date_precision") or "unknown"), claims=claims,
            parties=[str(x) for x in raw.get("parties", [])],
            event_type=str(raw.get("event_type") or "event"),
            conflicting_positions=[str(x) for x in raw.get("conflicting_positions", [])],
        ))
    if len(entries) < 2:
        raise ValueError("insufficient_evidence")
    blob, audit = build_ai_chronology_docx(
        project_name=project_name, issue_number=issue_number, title=topic,
        entries=entries, evidence=evidence, audit_metadata=None,
    )
    if audit.unresolved_source_ids:
        raise ValueError("Report contains unresolved source references")

    # Coverage of the pack that was actually read, not of everything retrieval
    # happened to surface. `preview` measures the pre-selection superset, so a
    # facet covered only by a document that was never selected still counted as
    # covered — which is how a three-entry report came back "complete".
    pack_coverage = coverage_matrix(evidence)
    assessment = assess_pack(
        evidence=evidence,
        event_count=len(entries) - 1,       # entries[0] is the synthetic overview
        coverage=pack_coverage,
        extraction_stats=extraction_stats,
    )
    assessment.pack["selection"] = selection_stats

    return {
        "entries": [asdict(e) for e in entries],
        "evidence": [asdict(e) for e in evidence],
        "research_questions": list(prepared.research_queries),
        "removed_claims": removed, "audit": asdict(audit), "docx": blob,
        "model": "gemini-3.6-flash", "pipeline_version": PIPELINE_VERSION,
        "prompt_version": PROMPT_VERSION,
        "coverage": pack_coverage,
        "coverage_status": assessment.status,
        "partial_reasons": assessment.reasons,
        "selected_doc_ids": chosen,
        # What the model was actually given. None of this was recorded before,
        # which is why a thin report could not be told from a broken one.
        "pack": assessment.pack,
    }


def generate_chronology(**kwargs) -> Dict:
    """Run the job-pinned chronology pipeline inside an isolated call budget."""
    from .llm_client import begin_chronology_call_budget, end_chronology_call_budget
    begin_chronology_call_budget()
    try:
        pipeline_version = str(kwargs.pop("pipeline_version", "chronology-v2") or "chronology-v2")
        if pipeline_version == "chronology-v3":
            from .chronology_v3 import generate_chronology_v3
            return generate_chronology_v3(**kwargs)
        return _generate_chronology_v2(**kwargs)
    finally:
        end_chronology_call_budget()


def _forensic_schema() -> Dict:
    claim = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "text": {"type": "string"},
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "counter_source_ids": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "missing_records": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["text", "source_ids", "counter_source_ids", "confidence", "missing_records"],
    }
    section = {
        "type": "object", "additionalProperties": False,
        "properties": {"name": {"type": "string", "enum": list(FORENSIC_SECTIONS)},
                       "claims": {"type": "array", "items": claim}},
        "required": ["name", "claims"],
    }
    return {"type": "object", "additionalProperties": False,
            "properties": {"sections": {"type": "array", "items": section}},
            "required": ["sections"]}


def generate_forensic(
    *, project_id: str, project_name: str, topic: str,
    date_from: str = "", date_to: str = "", parties: Sequence[str] = (),
    toolkit_evidence: Sequence[EvidenceItem] = (), status: str = "Draft",
    toolkit_artifact_ids: Sequence[str] = (),
) -> Dict:
    from .config import OPENAI_MODEL
    from .llm_client import generate_response_json
    from .jargon_manager import prepare_query, set_current_prepared_query
    prepared = prepare_query(topic)
    set_current_prepared_query(prepared)
    questions = build_research_plan(topic, date_from, date_to, parties)
    artifact_evidence: List[EvidenceItem] = []
    if toolkit_artifact_ids:
        from .toolkit_evidence_store import get_toolkit_evidence_store
        artifact_evidence = get_toolkit_evidence_store().as_evidence(
            list(toolkit_artifact_ids), project_id,
        )
    evidence = retrieve_evidence(project_id, questions) + list(toolkit_evidence) + artifact_evidence
    canonical_claims: List[VerifiedClaim] = []
    # Reuse an already verified chronology for the same project/topic. This is
    # what prevents the two existing modules from issuing different dates or
    # citations for the same event, while avoiding another model call.
    try:
        from backend.tasks.report_jobs import get_report_job_store
        previous = next((job for job in get_report_job_store().list_project(
            project_id, module="chronology"
        ) if job.get("status") == "ready" and
            str(job.get("title") or "").casefold() == topic.casefold() and
            job.get("result")), None)
        if previous:
            old_evidence = [EvidenceItem(**item) for item in previous["result"].get("evidence", [])]
            merged = {item.source_id: item for item in [*evidence, *old_evidence]}
            evidence = list(merged.values())
            for entry in previous["result"].get("entries", []):
                for raw_claim in entry.get("claims", []):
                    claim = VerifiedClaim(**raw_claim)
                    if claim.supported:
                        canonical_claims.append(claim)
    except Exception:
        canonical_claims = []
    if not evidence:
        raise ValueError("No project evidence was found for this report topic")
    prompt = (
        f"Prepare a {status} forensic report about: {topic}\n"
        "Use all nine required section names exactly. Do not calculate delay duration, "
        "critical path, concurrency or entitlement unless a toolkit evidence object supplies it.\n\n"
        f"{prepared.context}\n\nEVIDENCE JSON:\n{_evidence_payload(evidence)}"
    )
    response = generate_response_json(
        prompt, system=_SYSTEM, schema=_forensic_schema(), schema_name="forensic_report",
        model=OPENAI_MODEL, reasoning_effort="high", pro_mode=(status.lower() == "issue"),
        cache_key="forensic-report:" + hashlib.sha256(prompt.encode()).hexdigest()[:28],
    )
    by_id = {e.source_id: e for e in evidence}
    sections: Dict[str, List[VerifiedClaim]] = {name: [] for name in FORENSIC_SECTIONS}
    removed = 0
    for section in response.raw.get("sections", []):
        name = str(section.get("name") or "")
        if name not in sections:
            continue
        for raw in section.get("claims", []):
            claim = VerifiedClaim(
                text=str(raw.get("text") or ""),
                source_ids=[str(x) for x in raw.get("source_ids", [])],
                counter_source_ids=[str(x) for x in raw.get("counter_source_ids", [])],
                confidence=str(raw.get("confidence") or "low"),
                missing_records=[str(x) for x in raw.get("missing_records", [])],
            )
            claim.supported = _claim_supported(claim, by_id)
            if claim.supported:
                sections[name].append(claim)
            else:
                removed += 1
    if canonical_claims:
        sections["Factual chronology"] = canonical_claims
    blob, audit = build_forensic_report_docx(
        project_name=project_name, title=topic, sections=sections, evidence=evidence,
        status=status, audit_metadata={"prompt": FORENSIC_PROMPT_VERSION,
                                       "model": response.usage.model,
                                       "policy": MODEL_POLICY},
    )
    missing_sections = [name for name in FORENSIC_SECTIONS if not sections.get(name)]
    if status.lower() == "issue" and (
        audit.unresolved_source_ids or removed or missing_sections or audit.footnote_records == 0
    ):
        raise ValueError("Issue report failed mandatory evidence verification")
    return {"sections": {k: [asdict(c) for c in v] for k, v in sections.items()},
            "evidence": [asdict(e) for e in evidence], "research_questions": questions,
            "removed_claims": removed, "audit": asdict(audit), "docx": blob,
            "model": response.usage.model}


__all__ = [
    "MODEL_POLICY", "PROMPT_VERSION", "build_research_plan", "generate_chronology",
    "generate_forensic", "retrieve_evidence",
]
