"""programme.comparison adapter — Revision Comparison / Change Log (Module 6).

Diffs two programme revisions like a Claim Digger: added/deleted/renamed
activities, duration/logic/lag/constraint/calendar changes, and — the
forensically loaded category — retrospective changes to actual dates. All
deterministic; the LLM never touches the diff.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ToolResult, failed_result, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.comparison"

_DETAIL_CAP = 100


def _earlier_later(inv, data_by_name):
    """(old, new) as (label, XerData); old is the earlier programme."""
    dated = [r for r in inv.revisions if r.data_date is not None]
    if len(dated) >= 2:
        dated.sort(key=lambda r: r.data_date)
        old, new = dated[0], dated[-1]
    elif len(inv.revisions) >= 2:
        old, new = inv.revisions[0], inv.revisions[-1]
    else:
        return None, None
    if old.file_name == new.file_name:
        return None, None
    return ((old.label, data_by_name[old.file_name]),
            (new.label, data_by_name[new.file_name]))


def run(records: List[Dict[str, Any]],
        baseline_file: Optional[str] = None) -> AdapterOutput:
    from ..vendor.programme import build_inventory
    from ..vendor.programme.comparison import compare_revisions

    files = load_xer_files(records)
    data_by_name = dict(files)
    inv = build_inventory(files, baseline_file=baseline_file)

    (old, new) = _earlier_later(inv, data_by_name)
    if old is None:
        return failed_result(
            TOOL_ID, "Revision comparison needs two distinct programme "
                     "revisions to diff."), []
    old_label, old_data = old
    new_label, new_data = new
    cmp = compare_revisions(old_data, new_data, old_label, new_label)

    # 1. Change-category summary (only the non-zero rows).
    counts = [(k, v) for k, v in cmp.category_counts.items() if v]
    tables = [{
        "title": f"Change summary — {old_label} → {new_label}",
        "columns": ["Change category", "Count"],
        "rows": [[k, v] for k, v in counts] or [["No differences detected", 0]],
    }]

    # 2. Retrospective actual-date changes — the forensically critical detail.
    if cmp.actual_date_changes:
        tables.append({
            "title": "Retrospective actual-date changes (contemporaneity risk)",
            "columns": ["Activity", "Name", "Was", "Now", "Δ days"],
            "rows": [[c.task_code, c.name, c.old_value, c.new_value,
                      f"{c.delta_days:+.0f}" if c.delta_days is not None else "—"]
                     for c in cmp.actual_date_changes[:_DETAIL_CAP]],
        })

    # 3. Logic changes (added + removed), the driver of most sequence disputes.
    logic_rows = ([["added", lc.pred_code, lc.succ_code, lc.link_type,
                    f"{lc.lag_days:+.0f}d"] for lc in cmp.logic_added]
                  + [["removed", lc.pred_code, lc.succ_code, lc.link_type,
                      f"{lc.lag_days:+.0f}d"] for lc in cmp.logic_removed])
    if logic_rows:
        tables.append({
            "title": "Logic changes",
            "columns": ["Change", "Predecessor", "Successor", "Type", "Lag"],
            "rows": logic_rows[:_DETAIL_CAP],
        })

    # 4. Duration changes, largest first.
    if cmp.duration_changes:
        tables.append({
            "title": "Original-duration changes",
            "columns": ["Activity", "Name", "Was", "Now", "Δ days"],
            "rows": [[c.task_code, c.name, c.old_value, c.new_value,
                      f"{c.delta_days:+.0f}" if c.delta_days is not None else "—"]
                     for c in cmp.duration_changes[:_DETAIL_CAP]],
        })

    flag = (f" including {len(cmp.actual_date_changes)} retrospective "
            "actual-date change(s) — a contemporaneity concern"
            if cmp.actual_date_changes else "")
    summary = (f"{cmp.total_changes} change(s) between {old_label} and "
               f"{new_label}{flag}.")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        charts=[],
        warnings=list(inv.warnings) + list(cmp.warnings),
        caveats=list(cmp.caveats),
        requires_analyst_review=True,
        raw={"old": old_label, "new": new_label,
             "category_counts": cmp.category_counts,
             "actual_date_changes": json_safe(cmp.actual_date_changes)},
    )
    result._engine_ctx = {"result": cmp}
    return result, []
