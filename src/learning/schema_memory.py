"""Schema memory — the read/confirm API over the (already-persistent) schema
profiler and catalog.

The learning is not new inference: `SchemaProfiler.profile()` already prefers a
previously-confirmed mapping (keyed by normalized header signature) and the
`SchemaCatalog` already applies per-column overrides. What was missing is a
*caller* — nothing ever confirmed a mapping, so the reuse store stayed empty.
This module is that caller: an admin/user confirmation flows through here into
`persist_mapping` / `mark_mapping_confirmed`, and every later upload with the
same headers resolves identically (`source="persisted"`), which is what makes
`resolve_table_period` pick the table up.

Never invents a schema: confirmation only records a human decision; suggestion
only surfaces the deterministic profiler result. Low confidence → the caller is
told to confirm, never silently assigned.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Mapping-status labels (mirror data_catalog.excel_metadata semantics).
STATUS_CONFIDENT = "confident"
STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
STATUS_RAW_ONLY = "raw_only"


def _status_for(schema_id: Optional[str], needs_conf: bool) -> str:
    if schema_id and not needs_conf:
        return STATUS_CONFIDENT
    if schema_id and needs_conf:
        return STATUS_NEEDS_CONFIRMATION
    return STATUS_RAW_ONLY


def suggest_for_columns(columns: List[str]) -> Dict[str, Any]:
    """Deterministic profiler suggestion for a set of raw headers.

    Returns schema_id/confidence/column_map/status + `source` ("persisted" when
    a confirmed mapping already exists). Never raises."""
    try:
        from ..schema_profiler import get_profiler
        r = get_profiler().profile(list(columns or []))
        return {
            "schema_id": r.schema_id,
            "confidence": r.confidence,
            "column_map": dict(r.column_map),
            "matched_required": list(r.matched_required),
            "missing_required": list(r.missing_required),
            "needs_confirmation": bool(r.needs_clarification),
            "candidates": [{"schema_id": s, "coverage": c}
                           for s, c in r.candidates],
            "source": r.source,
            "status": _status_for(r.schema_id, r.needs_clarification),
        }
    except Exception as e:
        logger.debug(f"[SchemaMemory] suggest failed: {e}")
        return {"schema_id": None, "confidence": 0.0, "column_map": {},
                "needs_confirmation": True, "source": "computed",
                "status": STATUS_RAW_ONLY}


def is_confirmed(columns: List[str]) -> bool:
    """True when these exact headers already resolve from a confirmed mapping."""
    try:
        from ..schema_profiler import get_profiler
        return get_profiler().profile(list(columns or [])).source == "persisted"
    except Exception:
        return False


def confirm_schema_mapping(columns: List[str], schema_id: str,
                           column_map: Optional[Dict[str, str]] = None
                           ) -> Dict[str, Any]:
    """Record a human-confirmed header-set → schema decision.

    After this, any upload with the same normalized header signature resolves to
    `schema_id` with `source="persisted"` (which makes the table resolvable in
    `resolve_table_period`). Returns {ok, signature, schema_id}. Never raises."""
    cols = [c for c in (columns or []) if str(c).strip()]
    if not cols or not schema_id:
        return {"ok": False, "reason": "columns and schema_id required"}
    try:
        from ..schema_profiler import ProfileResult, get_profiler
        prof = get_profiler()
        # Start from the computed profile so column_map/required stay coherent,
        # then override the schema decision with the human's choice.
        base = prof.profile(cols)
        result = ProfileResult(
            schema_id=schema_id,
            confidence=1.0,
            column_map=column_map or base.column_map,
            matched_required=base.matched_required
            if base.schema_id == schema_id else [],
            missing_required=base.missing_required
            if base.schema_id == schema_id else [],
            needs_clarification=False,
            source="persisted",
        )
        prof.persist_mapping(cols, result)
        return {"ok": True, "signature": prof._signature(cols),
                "schema_id": schema_id}
    except Exception as e:
        logger.warning(f"[SchemaMemory] confirm_schema_mapping failed: {e}")
        return {"ok": False, "reason": str(e)[:200]}


def confirm_column(table_id: str, raw_column: str, canonical_concept: str,
                   source: str = "user_confirmed") -> Dict[str, Any]:
    """Record a per-column concept override for one table. Never raises."""
    if not table_id or not raw_column or not canonical_concept:
        return {"ok": False, "reason": "table_id, raw_column, concept required"}
    try:
        from ..data_catalog.schema_catalog import get_schema_catalog
        get_schema_catalog().mark_mapping_confirmed(
            table_id, raw_column, canonical_concept, source=source)
        return {"ok": True, "table_id": table_id, "raw_column": raw_column}
    except Exception as e:
        logger.warning(f"[SchemaMemory] confirm_column failed: {e}")
        return {"ok": False, "reason": str(e)[:200]}


def pending_confirmations(corpus_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tables whose schema mapping is low-confidence and awaits confirmation."""
    try:
        from ..data_catalog.schema_catalog import get_schema_catalog
        return get_schema_catalog().get_low_confidence_mappings(corpus_id)
    except Exception as e:
        logger.debug(f"[SchemaMemory] pending_confirmations failed: {e}")
        return []
