"""Evidence-grounded AI generation for the existing Chronology/Forensic modules."""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Dict, Iterable, List, Sequence, Tuple

from .evidence_model import ChronologyEntry, EvidenceItem, VerifiedClaim
from .report_docx import FORENSIC_SECTIONS, build_ai_chronology_docx, build_forensic_report_docx


PROMPT_VERSION = "evidence-report-v1"
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
    prompt = (
        "Create a compact research plan for this chronology/report topic. "
        "Return JSON as {\"questions\":[...]} with 7-10 non-overlapping questions.\n"
        f"Topic: {topic}\nDate range: {date_from or 'open'} to {date_to or 'open'}\n"
        f"Parties: {', '.join(parties) or 'not specified'}"
    )
    try:
        from .config import GEMINI_MODEL_LITE
        from .llm_client import generate_json
        response = generate_json(
            prompt, system="You are a fast legal-document research planner. JSON only.",
            provider="gemini", model=GEMINI_MODEL_LITE,
            cache_key="chron-plan:" + hashlib.sha256(prompt.encode()).hexdigest()[:24],
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
            return (rag.query(
                question, top_k=top_k, synthesize=False, rerank=True,
                project_id=project_id,
            ) or {}).get("sources", [])
        except Exception:
            return []

    def bm25(question: str) -> List[Dict]:
        return lexical.search_chunks(question, top_k=top_k, project_id=project_id)

    collected: List[Dict] = []
    with ThreadPoolExecutor(max_workers=min(6, max(2, len(questions) * 2))) as pool:
        futures = []
        for question in questions:
            futures.extend((pool.submit(dense, question), pool.submit(bm25, question)))
        for future in futures:
            try:
                collected.extend(future.result())
            except Exception:
                pass

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
    return sorted(by_id.values(), key=lambda x: x.score, reverse=True)[:120]


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
        "properties": {"entries": {"type": "array", "items": entry}},
        "required": ["entries"],
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


def generate_chronology(
    *, project_id: str, project_name: str, topic: str, issue_number: int = 1,
    date_from: str = "", date_to: str = "", parties: Sequence[str] = (),
) -> Dict:
    from .config import OPENAI_MODEL
    from .llm_client import generate_response_json

    questions = build_research_plan(topic, date_from, date_to, parties)
    evidence = retrieve_evidence(project_id, questions)
    if not evidence:
        raise ValueError("No project evidence was found for this report topic")
    prompt = (
        f"Prepare a factual chronology about: {topic}\n"
        f"Date range: {date_from or 'open'} to {date_to or 'open'}\n"
        f"Named parties: {', '.join(parties) or 'not specified'}\n"
        "Order entries by event date and use ISO YYYY-MM-DD where the record permits. "
        "Write one factual sentence per claim and give that claim source_ids. Do not combine "
        "a party allegation with an established fact. Mark inferred dates explicitly.\n\n"
        f"EVIDENCE JSON:\n{_evidence_payload(evidence)}"
    )
    response = generate_response_json(
        prompt, system=_SYSTEM, schema=_chronology_schema(),
        schema_name="chronology_report", model=OPENAI_MODEL, reasoning_effort="high",
        cache_key="chronology-report:" + hashlib.sha256(prompt.encode()).hexdigest()[:28],
    )
    by_id = {e.source_id: e for e in evidence}
    entries: List[ChronologyEntry] = []
    removed = 0
    for index, raw in enumerate(response.raw.get("entries", []), 1):
        claims = []
        for item in raw.get("claims", []):
            claim = VerifiedClaim(
                text=str(item.get("text") or "").strip(),
                source_ids=[str(x) for x in item.get("source_ids", [])],
                is_inference=bool(item.get("is_inference")),
                inference_basis=str(item.get("inference_basis") or ""),
                confidence=str(item.get("confidence") or "low"),
            )
            claim.supported = _claim_supported(claim, by_id)
            if claim.supported:
                claims.append(claim)
            else:
                removed += 1
        if str(raw.get("date_precision") or "unknown") != "exact" and claims:
            claims[0].is_inference = True
            if not claims[0].inference_basis:
                claims[0].inference_basis = "The event date is inferred from the cited record"
        entries.append(ChronologyEntry(
            entry_ref=f"6.{issue_number}.{index}", event_date=str(raw.get("event_date") or ""),
            date_precision=str(raw.get("date_precision") or "unknown"), claims=claims,
            parties=[str(x) for x in raw.get("parties", [])],
            event_type=str(raw.get("event_type") or "event"),
            conflicting_positions=[str(x) for x in raw.get("conflicting_positions", [])],
        ))
    blob, audit = build_ai_chronology_docx(
        project_name=project_name, issue_number=issue_number, title=topic,
        entries=entries, evidence=evidence,
        audit_metadata={"prompt": PROMPT_VERSION, "model": response.usage.model,
                        "policy": MODEL_POLICY},
    )
    if audit.unresolved_source_ids:
        raise ValueError("Report contains unresolved source references")
    return {"entries": [asdict(e) for e in entries], "evidence": [asdict(e) for e in evidence],
            "research_questions": questions, "removed_claims": removed,
            "audit": asdict(audit), "docx": blob, "model": response.usage.model}


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
        f"EVIDENCE JSON:\n{_evidence_payload(evidence)}"
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
        status=status, audit_metadata={"prompt": PROMPT_VERSION, "model": response.usage.model,
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
