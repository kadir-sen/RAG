"""Input resolver — turns "the latest programme" / "June" / "manpower" into
pinned files/tables from the registry and catalog, with explicit ambiguity.

Rules: one strong candidate → use it; multiple similar → clarification with
options; none → clarification asking for upload. Formal inputs are never
silently guessed. programme_meta is lazily backfilled (one bounded parse per
un-annotated record, cached via the registry itself).
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})


@dataclass
class ResolveOutcome:
    resolved: Dict[str, Any] = field(default_factory=dict)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    needs_confirmation: bool = False
    clarification: str = ""
    options: List[Dict[str, str]] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)


def parse_period(text: str) -> Optional[Tuple[str, str, str]]:
    """'June 2024' / '2024-06' / 'for June' → (date_from, date_to, date_key)."""
    q = (text or "").lower()
    m = re.search(r"\b(20\d{2})-(\d{2})\b", q)
    year = month = None
    if m:
        year, month = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\b(jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|"
                      r"sep\w*|oct\w*|nov\w*|dec\w*)\b(?:\s+(20\d{2}))?", q)
        if m:
            month = _MONTHS.get(m.group(1)[:3])
            year = int(m.group(2)) if m.group(2) else None
    if not month or not (1 <= month <= 12):
        return None
    if year is None:
        return None  # ambiguous year — caller must confirm
    last = calendar.monthrange(year, month)[1]
    return (f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}",
            f"{year:04d}-{month:02d}")


# ── Programme (.xer) resolution ──────────────────────────────

def _programme_records_with_meta() -> List[Dict[str, Any]]:
    """Completed programme records with programme_meta, lazily backfilled."""
    try:
        from src.document_registry import get_document_registry
        registry = get_document_registry()
        recs = [r for r in registry.get_completed()
                if getattr(r, "file_type", "") == "programme"]
    except Exception as e:
        logger.warning(f"[Resolver] registry unavailable: {e}")
        return []

    from src.file_router import PROGRAMME_PARSER_VERSION, build_programme_meta
    out = []
    for r in recs:
        meta = dict(getattr(r, "programme_meta", None) or {})
        if meta.get("parse_error"):
            continue  # known-bad file: never a candidate
        if meta.get("parser_version") != PROGRAMME_PARSER_VERSION:
            # Lazy one-time backfill (bounded: only records in this corpus's
            # programme set; result persisted so it never re-parses).
            try:
                from src.programme_tools.vendor.dcma import parse_xer
                from pathlib import Path
                data = parse_xer(Path(r.file_path).read_bytes())
                meta = build_programme_meta(data)
            except Exception as e:
                meta = {"parser_version": PROGRAMME_PARSER_VERSION,
                        "parse_error": str(e)[:200]}
            try:
                registry.set_programme_meta(r.doc_id, meta)
            except Exception:
                pass
            if meta.get("parse_error"):
                continue
        out.append({"doc_id": r.doc_id, "file_name": r.file_name,
                    "file_path": r.file_path, "status": r.status,
                    "meta": meta})
    return out


def resolve_xer(want: str = "latest",
                period_end: Optional[str] = None) -> ResolveOutcome:
    """want: 'latest' | 'baseline' | 'pair' | 'all'."""
    recs = _programme_records_with_meta()
    o = ResolveOutcome()
    if not recs:
        o.missing.append("programme_files")
        o.needs_confirmation = True
        o.clarification = ("No programme (.xer) files are available. Please "
                           "upload a Primavera P6 export first.")
        return o

    dated = sorted([r for r in recs if r["meta"].get("data_date")],
                   key=lambda r: r["meta"]["data_date"])
    undated = [r for r in recs if not r["meta"].get("data_date")]
    if undated:
        o.caveats.append(f"{len(undated)} programme file(s) without a data "
                         "date were excluded from automatic selection.")

    def _opt(r):
        return {"label": f"{r['file_name']} (data date "
                         f"{(r['meta'].get('data_date') or '?')[:10]})",
                "value": f"use {r['file_name']}"}

    if want == "all":
        o.resolved["xer_records"] = dated or recs
        return o

    if want == "latest":
        pool = dated
        if period_end:
            in_period = [r for r in dated
                         if r["meta"]["data_date"][:10] <= period_end]
            pool = in_period or dated
        if not pool:
            o.missing.append("dated_programme")
            o.needs_confirmation = True
            o.clarification = ("None of the programme files carry a data "
                               "date; please tell me which file to use.")
            o.options = [_opt(r) for r in recs[:6]]
            return o
        top = pool[-1]
        peers = [r for r in pool
                 if r["meta"]["data_date"][:10] == top["meta"]["data_date"][:10]]
        if len(peers) > 1:
            o.needs_confirmation = True
            o.clarification = ("Multiple programmes share the latest data "
                               "date — which one should I use?")
            o.options = [_opt(r) for r in peers]
            o.candidates = peers
            return o
        o.resolved["current_xer"] = top
        return o

    if want == "baseline":
        flagged = [r for r in recs
                   if r["meta"].get("programme_type") == "baseline"]
        if len(flagged) == 1:
            o.resolved["baseline_xer"] = flagged[0]
            return o
        if len(flagged) > 1:
            o.needs_confirmation = True
            o.clarification = "Multiple files are flagged as baseline — which one?"
            o.options = [_opt(r) for r in flagged]
            return o
        if dated:
            o.resolved["baseline_xer"] = dated[0]
            o.caveats.append(
                "Baseline inferred from the earliest data date — please "
                "confirm this is the contract baseline.")
            return o
        o.missing.append("baseline_programme")
        o.clarification = "No baseline programme could be identified."
        o.needs_confirmation = True
        return o

    if want == "pair":
        base = resolve_xer("baseline")
        cur = resolve_xer("latest", period_end)
        o.caveats = base.caveats + cur.caveats
        if base.needs_confirmation or cur.needs_confirmation:
            src = base if base.needs_confirmation else cur
            o.needs_confirmation = True
            o.clarification = src.clarification
            o.options = src.options
            o.missing = base.missing + cur.missing
            return o
        b, c = base.resolved.get("baseline_xer"), cur.resolved.get("current_xer")
        if b and c and b["doc_id"] == c["doc_id"]:
            o.missing.append("second_programme_revision")
            o.needs_confirmation = True
            o.clarification = ("Only one dated programme revision exists; a "
                               "comparison needs at least two.")
            return o
        o.resolved.update(base.resolved)
        o.resolved.update(cur.resolved)
        return o

    o.missing.append(want)
    return o


# ── Excel table + period resolution ──────────────────────────

_SCHEMA_KEYWORDS = {
    "manpower_production": r"manpower|workers?|trade|labou?r|workforce",
    "equipment_log": r"equipment|machin\w+|crane|utili[sz]ation",
    "ipc_sample": r"\bipc\b|payment|progress\s*%|boq|certificate",
}


def detect_schema(query: str) -> Optional[str]:
    q = (query or "").lower()
    for schema, pat in _SCHEMA_KEYWORDS.items():
        if re.search(pat, q):
            return schema
    return None


def resolve_schema_tables(schema_id: str, corpus: str = "") -> ResolveOutcome:
    """Base tables carrying a canonical schema, independent of any query.

    Never asks for confirmation: an absent schema is reported via `missing` and
    an empty table list. A multi-section report needs to drop one section to a
    caveat, not stop and ask — and a clarification block would be worse than
    stopping, since it is exclusive and would delete the rest of the report
    (backend.models.blocks.validate_blocks).

    The schema verdict itself is read, not computed: schema_profiler assigned
    header_metadata.target_schema at ingest and left it unset when it was not
    confident enough to map the headers.
    """
    o = ResolveOutcome()
    o.resolved["schema"] = schema_id
    try:
        from src.data_analyzer_sql import get_data_analyzer
        analyzer = get_data_analyzer()
        allowed = analyzer.get_tables_for_corpus(corpus or None)
        tables = []
        for name, info in analyzer.tables.items():
            if allowed is not None and name not in allowed:
                continue
            if info.get("is_grouped") or info.get("is_combined"):
                continue
            if name.endswith("_clean") or name.endswith("_raw") or \
                    name.startswith("_unified_"):
                continue
            hm = info.get("header_metadata") or {}
            if hm.get("target_schema") == schema_id:
                tables.append(name)
    except Exception as e:
        logger.warning(f"[Resolver] analyzer unavailable: {e}")
        tables = []

    if tables:
        o.resolved["tables"] = tables
    else:
        o.missing.append(schema_id)
    return o


def resolve_table_period(query: str, corpus: str = "") -> ResolveOutcome:
    """Find the base tables for the schema implied by the query + a period."""
    o = ResolveOutcome()
    schema = detect_schema(query)
    if schema is None:
        o.needs_confirmation = True
        o.clarification = ("Which data should I chart — manpower, equipment "
                           "or IPC/progress?")
        o.options = [{"label": l, "value": v} for l, v in
                     [("Manpower by trade", "bar chart of manpower by trade"),
                      ("Equipment hours", "bar chart of equipment hours"),
                      ("IPC progress", "chart of ipc progress")]]
        return o
    o.resolved["schema"] = schema

    found = resolve_schema_tables(schema, corpus)
    tables = found.resolved.get("tables") or []
    if not tables:
        o.missing.append(schema)
        o.needs_confirmation = True
        o.clarification = (f"No {schema.replace('_', ' ')} tables are loaded. "
                           "Please upload the Excel file first.")
        return o
    o.resolved["tables"] = tables

    period = parse_period(query)
    if period:
        o.resolved["period"] = {"date_from": period[0], "date_to": period[1],
                                "date_key": period[2]}
    elif re.search(r"\b(jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|"
                   r"sep\w*|oct\w*|nov\w*|dec\w*)\b", (query or "").lower()):
        # Month named without a year — never guess for formal output.
        o.needs_confirmation = True
        o.clarification = "Which year do you mean for that month?"
        return o
    return o
