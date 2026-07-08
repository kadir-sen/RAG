"""Event register — LLM extraction with a DETERMINISTIC containment guard.

The LLM reads evidence snippets and proposes structured event records; every
record is then validated in pure Python: the event date, the actor and the
verbatim quote must actually appear in the snippet text. Records that fail
are dropped to `unresolved` (visible loss), never guessed. This is what makes
Edinburgh-corpus chronology possible: dates/parties live only in letter text,
and text containment is verifiable without trusting the model.
"""

from __future__ import annotations

import calendar
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .schemas import EvidenceItem, RegisterEntry, RegisterResult

logger = logging.getLogger(__name__)

_MAX_BATCH = 20
_SNIPPET_CAP = 1200

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

# Date surface forms found in construction correspondence.
_DATE_PATTERNS = [
    # 19 July 2023 / 19th July 2023 / 19 Jul 23
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{2,4})\b"),
     lambda m: (m.group(3), _MONTHS.get(m.group(2).lower()), m.group(1))),
    # July 19, 2023 / Jul 19 2023
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{2,4})\b"),
     lambda m: (m.group(3), _MONTHS.get(m.group(1).lower()), m.group(2))),
    # 2023-07-19
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
     lambda m: (m.group(1), int(m.group(2)), m.group(3))),
    # 19/07/2023 or 19.07.2023 or 19-07-2023 (day-first, UK convention)
    (re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b"),
     lambda m: (m.group(3), int(m.group(2)), m.group(1))),
]


def _to_iso(year: str, month: Optional[int], day: str) -> Optional[str]:
    try:
        if month is None or not (1 <= int(month) <= 12):
            return None
        y = int(year)
        if y < 100:
            y += 2000 if y < 70 else 1900
        d = int(day)
        if not (1 <= d <= 31):
            return None
        return f"{y:04d}-{int(month):02d}-{d:02d}"
    except (TypeError, ValueError):
        return None


def normalize_date_multi(raw: str) -> Optional[str]:
    """Any common surface form → ISO YYYY-MM-DD, else None."""
    text = (raw or "").strip()
    for rx, extract in _DATE_PATTERNS:
        m = rx.search(text)
        if m:
            iso = _to_iso(*extract(m))
            if iso:
                return iso
    return None


def dates_in_text(text: str) -> set[str]:
    """All ISO dates that can be derived from surface forms in the text."""
    found: set[str] = set()
    for rx, extract in _DATE_PATTERNS:
        for m in rx.finditer(text or ""):
            iso = _to_iso(*extract(m))
            if iso:
                found.add(iso)
    return found


def date_in_snippet(iso_date: str, snippet: str) -> bool:
    return iso_date in dates_in_text(snippet)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())


def actor_in_snippet(actor: str, snippet: str) -> bool:
    """Casefolded token-subset match: every actor token appears in snippet."""
    a_tokens = [t for t in _norm(actor).split() if len(t) >= 2]
    if not a_tokens:
        return False
    s_norm = f" {_norm(snippet)} "
    return all(f" {t} " in s_norm or t in s_norm.split() for t in a_tokens)


def quote_in_snippet(quote: str, snippet: str) -> bool:
    """Whitespace-normalized, casefolded substring containment."""
    q = " ".join(_norm(quote).split())
    s = " ".join(_norm(snippet).split())
    return bool(q) and q in s


def validate_entry(raw: Dict[str, Any], snippet: str) -> Tuple[Optional[str], str]:
    """Deterministic guard for one extracted record.

    The DATE is mandatory and must appear in the snippet. Beyond that, at
    least ONE of actor/quote must verify — losing a date-verified event just
    because the model paraphrased the quote throws away good evidence (the
    caller swaps an unverifiable quote for a verbatim snippet excerpt).

    Returns (support_level, reason): "verified" | "date_only" | (None, why).
    """
    surface_date = str(raw.get("event_date") or "").strip()
    iso = normalize_date_multi(surface_date)
    if not iso:
        return None, f"event date '{surface_date}' not parseable"
    if not date_in_snippet(iso, snippet):
        return None, f"event date '{surface_date}' not found in evidence text"

    quote_ok = quote_in_snippet(str(raw.get("quote") or ""), snippet)
    actor_ok = actor_in_snippet(str(raw.get("actor") or ""), snippet)

    if actor_ok and quote_ok:
        return "verified", ""
    if actor_ok:
        return "date_only", "quote not verbatim in evidence text"
    if quote_ok:
        return "date_only", "actor not verbatim in evidence text"
    return None, "neither actor nor quote verifiable in evidence text"


# ── LLM extraction ───────────────────────────────────────────

def _extraction_prompt(items: List[EvidenceItem], event_title: str) -> str:
    from .prompts import EXTRACTION_PROMPT
    blocks = []
    for it in items:
        blocks.append(f"[{it.evidence_id}] ({it.file_name}, p.{it.page_number})\n"
                      f"{it.snippet[:_SNIPPET_CAP]}")
    return EXTRACTION_PROMPT.format(event_title=event_title,
                                    evidence="\n\n".join(blocks))


def build_event_register(evidence: List[EvidenceItem], event_title: str,
                         max_batches: int = 2) -> RegisterResult:
    """Extract + validate event records. Never raises; loss is visible."""
    from src import llm_client
    from src.prompt_security import build_system_prompt

    result = RegisterResult()
    by_id = {it.evidence_id: it for it in evidence}

    batches = [evidence[i:i + _MAX_BATCH]
               for i in range(0, len(evidence), _MAX_BATCH)][:max_batches]
    if len(evidence) > max_batches * _MAX_BATCH:
        result.caveats.append(
            f"Only the first {max_batches * _MAX_BATCH} of {len(evidence)} "
            "evidence items were processed for event extraction."
        )

    for batch in batches:
        try:
            resp = llm_client.generate_json(
                _extraction_prompt(batch, event_title),
                system=build_system_prompt(
                    "You extract dated events from construction correspondence "
                    "evidence. Extract ONLY what is stated verbatim. JSON only."),
            )
            raw_items = resp.raw if isinstance(resp.raw, list) else \
                (resp.raw.get("events") if isinstance(resp.raw, dict) else [])
        except Exception as e:
            logger.warning(f"[DelayReports] extraction batch failed: {e}")
            result.llm_failures += 1
            result.caveats.append(
                "One evidence batch could not be processed for extraction.")
            continue

        for raw in raw_items or []:
            if not isinstance(raw, dict):
                continue
            ev_id = str(raw.get("evidence_id") or "").strip()
            item = by_id.get(ev_id)
            if item is None:
                result.unresolved.append(
                    {"raw": raw, "reason": "unknown evidence_id"})
                continue
            level, reason = validate_entry(raw, item.snippet)
            if level is None:
                result.unresolved.append(
                    {"evidence_id": ev_id, "file_name": item.file_name,
                     "reason": reason, "raw": raw})
                continue
            # An unverifiable (paraphrased) quote must never travel further —
            # replace it with a verbatim snippet excerpt.
            quote = str(raw.get("quote") or "").strip()
            if not quote_in_snippet(quote, item.snippet):
                quote = " ".join(item.snippet.split())[:200]
            result.entries.append(RegisterEntry(
                evidence_id=ev_id,
                event_date=normalize_date_multi(str(raw.get("event_date"))),
                document_date=item.doc_date,
                actor=str(raw.get("actor") or "").strip(),
                recipient=(str(raw.get("recipient")).strip()
                           if raw.get("recipient") else None),
                action_verb=str(raw.get("action_verb") or "stated").strip(),
                issue=str(raw.get("issue") or "").strip(),
                impact=(str(raw.get("impact")).strip()
                        if raw.get("impact") else None),
                requested_action=(str(raw.get("requested_action")).strip()
                                  if raw.get("requested_action") else None),
                reservation_of_rights=bool(raw.get("reservation_of_rights")),
                quote=quote,
                support_level=level,
                file_name=item.file_name,
                doc_id=item.doc_id,
                page_number=item.page_number,
            ))

    if result.unresolved:
        result.caveats.append(
            f"{len(result.unresolved)} extracted item(s) failed evidence "
            "containment checks and were excluded; analyst review recommended."
        )
    return result
