"""Project-scoped document metadata index used by Chronology V3.

The chunk index answers "which passage resembles this query?".  This index
answers the earlier and more important question: "which records should be read
at all?".  It is generic to newly uploaded projects and contains no Edinburgh
Tram identifiers or topic-specific exceptions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from .chunk_store import get_chunk_store


MAP_TERMS = (
    "overview", "historical", "history", "audit", "lessons learned", "review",
    "investigation", "update report", "close-out", "closeout",
)
PRIMARY_TERMS = (
    "agreement", "contract", "notice", "instruction", "decision", "minutes",
    "adjudication", "programme", "schedule", "progress report", "letter",
    "correspondence", "email", "certificate", "change", "variation",
)
RETROSPECTIVE_FAMILIES = {"overview", "audit", "review", "witness statement"}
CORROBORATION_TERMS = (
    "corroborat", "confirmation", "confirmed", "contemporaneous record",
    "site diary", "daily record", "photograph", "independent record",
)
COUNTER_SOURCE_TERMS = (
    "response", "reply", "rebuttal", "rejected", "denied", "counterclaim",
    "employer position", "contractor position", "engineer position",
)
DATE_RE = re.compile(
    r"\b(?:0?[1-9]|[12]\d|3[01])[\s./-]+(?:0?[1-9]|1[0-2]|"
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)[\s,./-]+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
REFERENCE_RE = re.compile(
    r"\b(?:[A-Z]{2,10}[\s_-]?(?:CORR[\s_-]?)?\d{3,}|"
    r"(?:NOTICE|INSTRUCTION|CLAUSE|SCHEDULE)[\s:#-]*[A-Z0-9./-]{2,})\b",
    re.IGNORECASE,
)


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _values(value: Iterable[Any]) -> List[str]:
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


@dataclass(frozen=True)
class DocumentIndexRecord:
    project_id: str
    doc_id: str
    file_name: str
    reference: str = ""
    title: str = ""
    description: str = ""
    document_family: str = "other"
    parties: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    sheet_names: List[str] = field(default_factory=list)
    metadata_date: str = ""
    metadata_date_source: str = "unknown"
    ocr_quality: str = "good"
    content_hash: str = ""

    @property
    def search_id(self) -> str:
        return hashlib.sha256(
            f"{self.project_id}|{self.doc_id}".encode("utf-8")
        ).hexdigest()[:32]

    @property
    def search_text(self) -> str:
        return "\n".join(filter(None, (
            self.file_name, self.reference, self.title, self.description,
            self.document_family, " ".join(self.parties), " ".join(self.topics),
            " ".join(self.sheet_names), self.metadata_date,
        )))


@dataclass(frozen=True)
class CandidateDocument:
    doc_id: str
    file_name: str
    reference: str
    title: str
    description: str
    document_family: str
    metadata_date: str
    metadata_date_source: str
    ocr_quality: str
    score: float
    role: str
    reasons: List[str]
    content_hash: str = ""


def _plausible_title(lines: Sequence[str], fallback: str) -> str:
    stem = Path(fallback).stem
    for raw in lines[:20]:
        line = re.sub(r"\s+", " ", raw).strip(" -|\t")
        if not 5 <= len(line) <= 240:
            continue
        low = line.casefold()
        if low.startswith(("page ", "from:", "to:", "sent:", "date:")):
            continue
        if re.fullmatch(r"[\d\s./-]+", line):
            continue
        return line
    return stem


def infer_document_record(
    *, project_id: str, doc_id: str, file_name: str,
    page_texts: Dict[int, str] | None = None,
    summary: str = "", topics: Sequence[str] = (), family: str = "",
    parties: Sequence[str] = (), reference: str = "", title: str = "",
    metadata_date: str = "", metadata_date_source: str = "unknown",
    ocr_pages: int = 0, total_pages: int = 0, sheet_names: Sequence[str] = (),
) -> DocumentIndexRecord:
    pages = page_texts or {}
    ordered = [str(pages[key] or "") for key in sorted(pages)]
    full_text = "\n".join(ordered).strip()
    head = "\n".join(ordered[:2])[:12_000]
    lines = [line for line in head.splitlines() if line.strip()]
    found_reference = reference.strip()
    if not found_reference:
        match = REFERENCE_RE.search(head)
        found_reference = match.group(0).strip() if match else ""
    found_title = title.strip() or _plausible_title(lines, file_name)
    found_date = metadata_date.strip()
    found_date_source = metadata_date_source.strip() or "unknown"
    if not found_date:
        match = DATE_RE.search(head[:4_000])
        if match:
            found_date = match.group(0)
            found_date_source = "content_header"
    blob = _normal(" ".join((found_title, summary, head[:4_000], family)))
    found_family = family.strip().casefold()
    if not found_family:
        if any(term in blob for term in MAP_TERMS):
            found_family = "overview"
        else:
            found_family = next((term for term in PRIMARY_TERMS if term in blob), "other")
    if not full_text:
        quality = "unreadable"
    elif total_pages and ocr_pages >= total_pages:
        quality = "ocr"
    elif ocr_pages:
        quality = "mixed"
    else:
        quality = "good"
    return DocumentIndexRecord(
        project_id=project_id, doc_id=doc_id, file_name=file_name,
        reference=found_reference, title=found_title,
        description=summary.strip(), document_family=found_family,
        parties=_values(parties), topics=_values(topics),
        sheet_names=_values(sheet_names), metadata_date=found_date,
        metadata_date_source=found_date_source, ocr_quality=quality,
        content_hash=hashlib.sha256(full_text.encode("utf-8")).hexdigest() if full_text else "",
    )


class DocumentIndex:
    _instance: "DocumentIndex | None" = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._write_lock = threading.RLock()
                    cls._instance = inst
        return cls._instance

    @property
    def connection(self):
        return get_chunk_store().connection()

    def upsert(self, record: DocumentIndexRecord) -> None:
        if not record.project_id or not record.doc_id:
            raise ValueError("project_id and doc_id are required for document indexing")
        values = [
            record.search_id, record.project_id, record.doc_id, record.file_name,
            record.reference, record.title, record.description, record.document_family,
            json.dumps(record.parties, ensure_ascii=False),
            json.dumps(record.topics, ensure_ascii=False),
            json.dumps(record.sheet_names, ensure_ascii=False),
            record.metadata_date, record.metadata_date_source, record.ocr_quality,
            record.content_hash, record.search_text, datetime.now(timezone.utc).isoformat(),
        ]
        with self._write_lock:
            self.connection.execute(
                "INSERT INTO document_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(search_id) DO UPDATE SET file_name=excluded.file_name,"
                "reference=excluded.reference,title=excluded.title,description=excluded.description,"
                "document_family=excluded.document_family,parties_json=excluded.parties_json,"
                "topics_json=excluded.topics_json,sheet_names_json=excluded.sheet_names_json,"
                "metadata_date=excluded.metadata_date,metadata_date_source=excluded.metadata_date_source,"
                "ocr_quality=excluded.ocr_quality,content_hash=excluded.content_hash,"
                "search_text=excluded.search_text,updated_at=excluded.updated_at",
                values,
            )
            get_chunk_store()._dirty = True
            get_chunk_store()._persist()

    def list_project(self, project_id: str) -> List[DocumentIndexRecord]:
        rows = self.connection.execute(
            "SELECT project_id,doc_id,file_name,reference,title,description,"
            "document_family,parties_json,topics_json,sheet_names_json,metadata_date,"
            "metadata_date_source,ocr_quality,content_hash FROM document_index "
            "WHERE project_id=?", [project_id],
        ).fetchall()
        result: List[DocumentIndexRecord] = []
        for row in rows:
            result.append(DocumentIndexRecord(
                project_id=row[0], doc_id=row[1], file_name=row[2], reference=row[3] or "",
                title=row[4] or "", description=row[5] or "", document_family=row[6] or "other",
                parties=json.loads(row[7] or "[]"), topics=json.loads(row[8] or "[]"),
                sheet_names=json.loads(row[9] or "[]"), metadata_date=row[10] or "",
                metadata_date_source=row[11] or "unknown", ocr_quality=row[12] or "good",
                content_hash=row[13] or "",
            ))
        return result

    def search(
        self, *, project_id: str, topic: str, queries: Sequence[str],
        parties: Sequence[str] = (), limit: int = 100,
    ) -> List[CandidateDocument]:
        query_values = _values([topic, *queries])
        query_blob = _normal(" ".join(query_values))
        tokens = [token for token in query_blob.split() if len(token) >= 3]
        exact_ids = {_normal(match.group(0)) for value in query_values
                     for match in REFERENCE_RE.finditer(value)}
        years = set(re.findall(r"\b(?:19|20)\d{2}\b", query_blob))
        party_terms = [_normal(value) for value in parties if _normal(value)]
        records = self.list_project(project_id)
        tokenized = [_normal(record.search_text).split() for record in records]
        avg_length = (sum(map(len, tokenized)) / len(tokenized)) if tokenized else 1.0
        document_frequency = {
            token: sum(1 for values in tokenized if token in set(values))
            for token in set(tokens)
        }

        def bm25(index: int) -> float:
            values = tokenized[index]
            counts = Counter(values); length = max(1, len(values)); total = 0.0
            for token in set(tokens):
                frequency = counts.get(token, 0)
                if not frequency:
                    continue
                documents = max(1, len(records)); found = document_frequency.get(token, 0)
                inverse = math.log(1 + (documents - found + .5) / (found + .5))
                total += inverse * (frequency * 2.2) / (
                    frequency + 1.2 * (.25 + .75 * length / max(1.0, avg_length))
                )
            return total

        raw_bm25 = [bm25(index) for index in range(len(records))]
        max_bm25 = max(raw_bm25, default=0.0)
        seen_hashes: set[str] = set()
        ranked: List[CandidateDocument] = []
        for record_index, record in enumerate(records):
            title = _normal(record.title)
            search = _normal(record.search_text)
            reference = _normal(record.reference)
            score = 0.0; reasons: List[str] = []
            if exact_ids and any(value and value in {reference, _normal(record.file_name), title}
                                 for value in exact_ids):
                score += 3.0; reasons.append("exact_identifier")
            topic_normal = _normal(topic)
            if topic_normal and title and (topic_normal in title or title in topic_normal):
                score += 2.0; reasons.append("title_phrase")
            token_hits = len({token for token in tokens if token in search})
            if token_hits:
                # True Okapi BM25 over document metadata, normalized so exact
                # identifiers and source-family signals remain dominant.
                lexical_score = 2.0 * raw_bm25[record_index] / max_bm25 if max_bm25 else 0.0
                score += lexical_score
                reasons.append(f"metadata_bm25:{lexical_score:.3f}")
            is_map = any(term in search for term in MAP_TERMS) or (
                record.document_family in RETROSPECTIVE_FAMILIES
            )
            is_primary = any(term in search for term in PRIMARY_TERMS) and not is_map
            if is_map:
                score += 1.5; reasons.append("map_document")
            if is_primary:
                score += 1.5; reasons.append("primary_record")
            if party_terms and any(value in search for value in party_terms):
                score += 1.0; reasons.append("entity_match")
            if years and any(year in record.metadata_date or year in search for year in years):
                score += 1.0; reasons.append("temporal_match")
            if any(term in search for term in CORROBORATION_TERMS):
                score += 1.0; reasons.append("corroboration_match")
            if any(term in search for term in COUNTER_SOURCE_TERMS):
                score += 1.0; reasons.append("counter_source_match")
            if is_map and not is_primary:
                score -= 1.0; reasons.append("hindsight_penalty")
            if record.ocr_quality == "unreadable":
                score -= 2.0; reasons.append("unreadable_penalty")
            if record.content_hash and record.content_hash in seen_hashes:
                score -= 1.5; reasons.append("duplicate_penalty")
            elif record.content_hash:
                seen_hashes.add(record.content_hash)
            if score <= 0:
                continue
            role = "map" if is_map else ("primary" if is_primary else "corroborator")
            ranked.append(CandidateDocument(
                doc_id=record.doc_id, file_name=record.file_name,
                reference=record.reference, title=record.title,
                description=record.description, document_family=record.document_family,
                metadata_date=record.metadata_date,
                metadata_date_source=record.metadata_date_source,
                ocr_quality=record.ocr_quality, score=round(score, 6), role=role,
                reasons=reasons, content_hash=record.content_hash,
            ))
        return sorted(ranked, key=lambda item: (-item.score, item.file_name))[:limit]


def get_document_index() -> DocumentIndex:
    return DocumentIndex()


__all__ = [
    "CandidateDocument", "DocumentIndex", "DocumentIndexRecord",
    "get_document_index", "infer_document_record",
]
