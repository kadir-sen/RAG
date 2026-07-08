"""Chart-block builders + Chart Guard.

Charts are rendered CLIENT-side from data; these builders derive chart data
1:1 from a source table (ToolResult table dict or column/value lists), and
the guard independently re-verifies the derivation — an LLM never touches
chart values or labels, and titles come from specs/user slots only.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_FLOAT_TOL = 1e-9


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def bar_chart_from_table(table: Dict[str, Any], category_col: str,
                         value_col: str, title: str,
                         max_bars: int = 20) -> Tuple[Optional[dict], str]:
    """Build a bar ChartBlock dict from a data_table-shaped dict.

    Returns (block|None, reason). Values are copied verbatim from the table.
    """
    cols = table.get("columns") or []
    if category_col not in cols or value_col not in cols:
        return None, f"columns '{category_col}'/'{value_col}' not in table"
    ci, vi = cols.index(category_col), cols.index(value_col)
    categories: List[str] = []
    values: List[float] = []
    for row in table.get("rows") or []:
        v = _num(row[vi])
        if v is None:
            continue
        categories.append(str(row[ci]))
        values.append(v)
    if not categories:
        return None, "no numeric rows to chart"
    dropped = 0
    if len(categories) > max_bars:
        dropped = len(categories) - max_bars
        categories, values = categories[:max_bars], values[:max_bars]
    block = {
        "type": "chart", "block_id": "", "chart_type": "bar",
        "title": title, "x_label": category_col, "y_label": value_col,
        "categories": categories, "values": values,
    }
    return block, (f"{dropped} categories beyond the top {max_bars} omitted"
                   if dropped else "")


def line_chart_from_series(series: List[Dict[str, Any]], title: str,
                           x_label: str = "", y_label: str = "") -> Optional[dict]:
    """Wrap already-structured series (e.g. milestone shift ToolResult charts)
    into a line ChartBlock dict — values passed through verbatim."""
    if not series:
        return None
    return {
        "type": "chart", "block_id": "", "chart_type": "line",
        "title": title, "x_label": x_label, "y_label": y_label,
        "series": series,
    }


# ── Chart Guard ──────────────────────────────────────────────

def chart_guard(block: dict, source: Dict[str, Any],
                allowed_title: str) -> List[str]:
    """Deterministically verify a chart block against its source.

    source: {"table": data_table dict, "category_col","value_col"} for bar,
            {"series": [...]} for line.
    Returns violation strings; empty = passed.
    """
    violations: List[str] = []
    if block.get("title") != allowed_title:
        violations.append("chart title does not come from the approved spec/slot")

    if block.get("chart_type") == "bar":
        table = source.get("table") or {}
        cols = table.get("columns") or []
        ccol, vcol = source.get("category_col"), source.get("value_col")
        if ccol not in cols or vcol not in cols:
            return violations + ["source columns missing for verification"]
        ci, vi = cols.index(ccol), cols.index(vcol)
        src_pairs = []
        for row in table.get("rows") or []:
            v = _num(row[vi])
            if v is not None:
                src_pairs.append((str(row[ci]), v))
        cats = block.get("categories") or []
        vals = block.get("values") or []
        if len(cats) != len(vals):
            violations.append("categories/values length mismatch")
            return violations
        src_prefix = src_pairs[:len(cats)]
        if [c for c, _ in src_prefix] != cats:
            violations.append("chart categories do not match source labels/order")
        else:
            for ((_, sv), bv) in zip(src_prefix, vals):
                if abs(sv - float(bv)) > _FLOAT_TOL:
                    violations.append("chart values diverge from source data")
                    break
        if len(cats) > len(src_pairs):
            violations.append("chart contains categories beyond the source")

    elif block.get("chart_type") == "line":
        src_series = source.get("series") or []
        blk_series = block.get("series") or []
        src_by_name = {s.get("name"): s for s in src_series}
        for s in blk_series:
            src = src_by_name.get(s.get("name"))
            if src is None:
                violations.append(f"invented series '{s.get('name')}'")
                continue
            if s.get("points") != src.get("points"):
                violations.append(f"series '{s.get('name')}' points diverge from source")
    else:
        violations.append(f"unknown chart_type '{block.get('chart_type')}'")

    return violations
