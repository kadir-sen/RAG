"""Chronology table — pure Python ordering and paragraph numbering."""

from __future__ import annotations

from datetime import date
from typing import List

from .schemas import ChronologyRow, ChronologyTable, RegisterResult


def _human_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
        return f"{d.day} {d.strftime('%B')} {d.year}"
    except (TypeError, ValueError):
        return iso or "unknown date"


def build_chronology_table(register: RegisterResult, section_base: str = "6.1",
                           start_index: int = 1) -> ChronologyTable:
    """Sort validated entries by event date (fallback: document date, with a
    caveat) and assign consecutive '<base>.<n>' paragraph numbers."""
    table = ChronologyTable(section_base=section_base,
                            caveats=list(register.caveats))

    dated: List[tuple[str, bool, object]] = []
    for e in register.entries:
        if e.event_date:
            dated.append((e.event_date, False, e))
        elif e.document_date:
            dated.append((e.document_date, True, e))
        # entries with neither never reach here (register validation requires
        # an in-snippet event date), but guard defensively anyway.

    dated.sort(key=lambda t: (t[0], t[2].file_name, t[2].page_number))

    doc_date_used = 0
    for i, (sort_date, is_doc_date, entry) in enumerate(dated):
        if is_doc_date:
            doc_date_used += 1
        table.rows.append(ChronologyRow(
            para_no=f"{section_base}.{start_index + i}",
            date=sort_date,
            date_is_document_date=is_doc_date,
            entry=entry,
        ))
    if doc_date_used:
        table.caveats.append(
            f"{doc_date_used} paragraph(s) use the document date because no "
            "explicit event date was stated."
        )
    return table


def table_as_tool_rows(table: ChronologyTable) -> list[list]:
    """Rows for the ToolResult chronology table (UI rendering)."""
    out = []
    for r in table.rows:
        e = r.entry
        out.append([
            r.para_no,
            _human_date(r.date) + (" (doc date)" if r.date_is_document_date else ""),
            e.actor,
            e.recipient or "—",
            (e.issue[:120] + "…") if len(e.issue) > 120 else e.issue,
            e.requested_action or ("reserved rights" if e.reservation_of_rights else "—"),
            f"{e.file_name}, p.{e.page_number}",
            e.support_level,
        ])
    return out


TABLE_COLUMNS = ["¶", "Date", "Actor", "Recipient", "Issue",
                 "Request/Reservation", "Source", "Support"]
