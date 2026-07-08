"""Narrative drafting for the chronology section.

The LLM sees ONLY the chronology rows (dates, actors, issues, quotes,
source refs) — never raw retrieval or its own knowledge. The deterministic
fallback renders the same rows without any LLM, so the section always ships.
"""

from __future__ import annotations

import logging
import re
from typing import List

from .chronology import ChronologyTable, _human_date

logger = logging.getLogger(__name__)

_HEDGE = {
    "stated": "stated", "noted": "noted", "informed": "informed",
    "requested": "requested", "raised": "raised concerns regarding",
    "forwarded": "forwarded", "proposed": "proposed", "reserved": "reserved",
    "notified": "notified", "instructed": "instructed", "submitted": "submitted",
}


def _rows_block(table: ChronologyTable) -> str:
    lines: List[str] = []
    for r in table.rows:
        e = r.entry
        parts = [
            f"para_no={r.para_no}",
            f"date={_human_date(r.date)}" + (" (document date)" if r.date_is_document_date else ""),
            f"actor={e.actor}",
            f"recipient={e.recipient or '-'}",
            f"verb={e.action_verb}",
            f"issue={e.issue}",
        ]
        if e.impact:
            parts.append(f"impact={e.impact}")
        if e.requested_action:
            parts.append(f"requested={e.requested_action}")
        if e.reservation_of_rights:
            parts.append("reserved_rights=yes")
        parts.append(f'quote="{e.quote}"')
        parts.append(f"source=({e.file_name}, p.{e.page_number})")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def deterministic_fallback(table: ChronologyTable, event_title: str) -> str:
    """LLM-free rendering — correct by construction, passes the guard."""
    lines = [f"## {event_title}", ""]
    for r in table.rows:
        e = r.entry
        verb = _HEDGE.get(e.action_verb, "stated")
        issue = e.issue.rstrip(".")
        # "Correspondence regarding X" as the issue would render as
        # "stated regarding Correspondence regarding X" — strip the wrapper.
        issue = re.sub(r"^(correspondence|an?\s+email|a\s+letter)\s+"
                       r"(regarding|about|re|concerning)\s+", "", issue,
                       flags=re.IGNORECASE)
        # Extraction often returns a full sentence as the issue ("X sent an
        # email regarding Y"); prefixing "actor stated regarding" then reads
        # as stuttering duplication — use the sentence directly instead.
        issue_is_sentence = bool(
            issue.lower().startswith(e.actor.lower()[:12])
            or re.search(
                r"\b(sent|forwarded|raised|requested|informed|noted|stated|"
                r"emailed|replied|proposed)\b", issue.lower())
        )
        if issue_is_sentence:
            sent = f"{r.para_no} On {_human_date(r.date)}, {issue}."
        else:
            sent = f"{r.para_no} On {_human_date(r.date)}, {e.actor} {verb}"
            if e.recipient and e.action_verb in ("informed", "notified",
                                                 "forwarded", "submitted"):
                sent += f" {e.recipient}"
            sent += f" regarding {issue}."
        if e.impact:
            sent += f" It was stated that {e.impact.rstrip('.')}."
        if e.requested_action:
            sent += f" It requested {e.requested_action.rstrip('.')}."
        elif e.reservation_of_rights:
            sent += " It reserved its rights to claim time and cost."
        sent += f" ({e.file_name}, p.{e.page_number})"
        lines.append(sent)
        lines.append("")
    if table.caveats:
        lines.append("**Caveats:**")
        lines += [f"- {c}" for c in table.caveats]
    return "\n".join(lines).strip()


def draft_event_narrative(table: ChronologyTable, event_title: str,
                          rewrite_note: str = "") -> str:
    """One main-model call constrained to the rows. Raises to caller on LLM
    failure (handler falls back deterministically). rewrite_note carries
    guard violations into the single retry attempt."""
    from src import llm_client
    from src.prompt_security import build_system_prompt
    from .prompts import NARRATIVE_PROMPT

    if not table.rows:
        return deterministic_fallback(table, event_title)

    example_para = table.rows[0].para_no
    cause_categories = {r.entry.issue.split(":")[0].strip().lower()
                        for r in table.rows if ":" in r.entry.issue}
    cause_intro_rule = (
        "Open with a one-paragraph i/ii/iii cause-category breakdown built "
        "ONLY from the rows' issues." if len(cause_categories) >= 3 else
        "Do not add an intro paragraph — start directly with the first "
        "numbered paragraph."
    )

    prompt = NARRATIVE_PROMPT.format(
        event_title=event_title,
        example_para=example_para,
        cause_intro_rule=cause_intro_rule,
        rows=_rows_block(table),
    )
    if rewrite_note:
        prompt += ("\n\nYOUR PREVIOUS DRAFT WAS REJECTED for these violations "
                   "— fix ALL of them without adding any new facts:\n"
                   + rewrite_note)
    resp = llm_client.generate_text(
        prompt,
        system=build_system_prompt(
            "You draft forensic delay-claim chronology narratives strictly "
            "from supplied structured rows. English."),
        temperature=0.1,
        max_tokens=2000,
    )
    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError("empty narrative")
    if table.caveats and "Caveats" not in text:
        text += "\n\n**Caveats:**\n" + "\n".join(f"- {c}" for c in table.caveats)
    return f"## {event_title}\n\n{text}" if not text.startswith("#") else text
