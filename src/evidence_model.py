"""Shared evidence contracts for Chronology and Forensic reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class EvidenceItem:
    source_id: str
    doc_id: str
    file_name: str
    title: str = ""
    document_date: str = ""
    page: Optional[int] = None
    kind: str = "document"          # document | email | excel | toolkit
    sender: str = ""
    recipient: str = ""
    subject: str = ""
    sheet: str = ""
    row_from: Optional[int] = None
    row_to: Optional[int] = None
    excerpt: str = ""
    score: float = 0.0

    def footnote_text(self, exhibit_number: int, inference_note: str = "") -> str:
        if self.kind == "email":
            identity = ", ".join(x for x in (
                self.sender and f"from {self.sender}",
                self.recipient and f"to {self.recipient}",
                self.subject and f'subject “{self.subject}”',
                self.document_date,
            ) if x)
        elif self.kind == "excel":
            rows = ""
            if self.row_from is not None:
                rows = f"rows {self.row_from}–{self.row_to or self.row_from}"
            identity = ", ".join(x for x in (self.file_name, self.sheet and f"sheet {self.sheet}", rows) if x)
        else:
            identity = ", ".join(x for x in (
                self.doc_id or self.file_name,
                self.title or self.file_name,
                self.document_date,
                f"p.{self.page}" if self.page else "",
            ) if x)
        note = f"; {inference_note}" if inference_note else ""
        return f"Exhibit {exhibit_number} – {identity}{note}.".replace("..", ".")


@dataclass
class VerifiedClaim:
    text: str
    source_ids: List[str]
    supported: bool = True
    is_inference: bool = False
    inference_basis: str = ""
    confidence: str = "high"
    counter_source_ids: List[str] = field(default_factory=list)
    missing_records: List[str] = field(default_factory=list)


@dataclass
class ChronologyEntry:
    entry_ref: str
    event_date: str
    date_precision: str
    claims: List[VerifiedClaim]
    parties: List[str] = field(default_factory=list)
    event_type: str = "event"
    conflicting_positions: List[str] = field(default_factory=list)

    @property
    def narrative(self) -> str:
        return " ".join(c.text.strip() for c in self.claims if c.supported and c.text.strip())


@dataclass
class ReportAudit:
    footnote_references: int
    footnote_records: int
    unique_source_ids: int
    unresolved_source_ids: List[str] = field(default_factory=list)


def evidence_map(items: List[EvidenceItem]) -> Dict[str, EvidenceItem]:
    return {item.source_id: item for item in items if item.source_id}


__all__ = [
    "ChronologyEntry", "EvidenceItem", "ReportAudit", "VerifiedClaim", "evidence_map",
]
