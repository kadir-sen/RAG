"""Delay-report data contracts.

Reuses programme_tools' ToolResult (single result schema across report
tools) and adds the chronology-specific records. Everything here is a plain
dataclass — JSON-safe via programme_tools.schemas.json_safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Single shared result contract — do NOT fork a second framework.
from ..programme_tools.schemas import (  # noqa: F401  (re-exports)
    STATUS_COMPLETE, STATUS_FAILED, STATUS_PARTIAL,
    ToolResult, failed_result, json_safe,
)


@dataclass
class ScopeResult:
    """Outcome of resolve_event_scope."""
    event_title: Optional[str] = None
    topic_terms: List[str] = field(default_factory=list)
    parties: List[str] = field(default_factory=list)
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    needs_clarification: bool = False
    clarification: str = ""


@dataclass
class EvidenceItem:
    """One retrieved snippet that may contain a dated event."""
    evidence_id: str            # "E1", "E2", ...
    file_name: str
    doc_id: str
    page_number: int
    snippet: str
    doc_date: Optional[str] = None   # ONLY from trusted metadata (demo notices).
                                     # Edinburgh: ALWAYS None (payload date is a
                                     # publication date, never an event date).
    sender: Optional[str] = None     # ditto
    origin: str = "rag"              # "graph" | "rag"


@dataclass
class RegisterEntry:
    """One validated, dated event extracted from an evidence snippet."""
    evidence_id: str
    event_date: str                  # ISO YYYY-MM-DD (validated in-snippet)
    document_date: Optional[str]
    actor: str
    recipient: Optional[str]
    action_verb: str                 # stated | noted | requested | reserved | ...
    issue: str
    impact: Optional[str]
    requested_action: Optional[str]
    reservation_of_rights: bool
    quote: str                       # verbatim excerpt (validated in-snippet)
    support_level: str               # "verified" | "date_only"
    file_name: str
    doc_id: str
    page_number: int


@dataclass
class RegisterResult:
    entries: List[RegisterEntry] = field(default_factory=list)
    unresolved: List[Dict[str, Any]] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    llm_failures: int = 0    # extraction batches lost to LLM outage (not to
                             # validation) — distinguishes "unavailable" from
                             # "nothing validated" in the user-facing result


@dataclass
class ChronologyRow:
    para_no: str                     # "6.1.13"
    date: str                        # ISO date used for ordering
    date_is_document_date: bool      # event date missing → document date used
    entry: RegisterEntry


@dataclass
class ChronologyTable:
    section_base: str
    rows: List[ChronologyRow] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
