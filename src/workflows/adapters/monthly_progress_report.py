"""monthly_progress_report workflow — MVP.

Assembles the progress picture the loaded data actually supports: data
inventory, manpower (by trade/block/month), equipment utilisation (by
block/month), IPC certified amounts, and a production curve. Runs only what is
there; a missing schema costs its own section and a caveat, never the report.

Reporting only. Nothing here says anything about causation, entitlement or
responsibility — progress and delay are different questions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.orchestration.helpers import md_block, table_block
from src.orchestration.viz import bar_chart_from_table, chart_guard, line_chart_from_table

from .. import caveats as CV
from ..blocks import corpus_id, finalize_blocks
from ..metrics import data_inventory, run_metric
from ..types import (
    RESULT_PARTIAL, RESULT_SUCCESS, RESULT_UNAVAILABLE, WorkflowId,
    WorkflowResult,
)

logger = logging.getLogger(__name__)

PROGRESS_NOT_ENTITLEMENT = (
    "This is a progress record only; it is not an assessment of delay, "
    "causation, entitlement or responsibility.")

# (metric_id, heading, chart kind). Order is the report's order.
_BAR_SECTIONS: List[Tuple[str, str]] = [
    ("manpower_by_trade", "Manpower by trade"),
    ("manpower_by_block", "Manpower by block"),
    ("equipment_hours_by_block", "Equipment utilisation by block"),
    ("equipment_hours_by_machine", "Equipment utilisation by machine"),
    ("ipc_cumulative_by_activity", "IPC certified amount by activity"),
]
_LINE_SECTIONS: List[Tuple[str, str, bool]] = [
    # (metric_id, heading, cumulative)
    ("manpower_by_month", "Manpower trend by month", False),
    ("equipment_hours_by_month", "Equipment hours by month", False),
    ("production_by_month", "Cumulative recorded production", True),
]


def _bar_section(metric_id: str, heading: str, corpus: str,
                 period: Optional[dict], guards: Dict[str, str],
                 fallbacks: List[str]) -> Tuple[List[dict], List[str]]:
    table, reason = run_metric(metric_id, corpus, period)
    if table is None:
        return [], ([reason] if reason else [])

    blocks: List[dict] = [md_block(f"### {heading}", f"h-{metric_id}")]
    caveats: List[str] = []
    chart, note = bar_chart_from_table(table, table["columns"][0],
                                       table["columns"][1], table["title"])
    if note:
        caveats.append(note)
    if chart:
        violations = chart_guard(chart, {"table": table,
                                         "category_col": table["columns"][0],
                                         "value_col": table["columns"][1]},
                                 table["title"])
        if violations:
            logger.warning(f"[MonthlyReport] chart_guard failed for "
                           f"{metric_id}: {violations}")
            guards["chart_guard"] = "failed"
            fallbacks.append(f"chart→table ({metric_id})")
        else:
            guards.setdefault("chart_guard", "passed")
            chart["block_id"] = f"chart-{metric_id}"
            blocks.append(chart)
    blocks.append(table_block(table, f"table-{metric_id}"))
    return blocks, caveats


def _line_section(metric_id: str, heading: str, cumulative: bool, corpus: str,
                  period: Optional[dict], guards: Dict[str, str],
                  fallbacks: List[str]) -> Tuple[List[dict], List[str]]:
    # A monthly trend is meaningless filtered to a single month.
    table, reason = run_metric(metric_id, corpus, period=None)
    if table is None:
        return [], ([reason] if reason else [])

    title = table["title"]
    blocks: List[dict] = [md_block(f"### {heading}", f"h-{metric_id}")]
    caveats: List[str] = []
    chart, reason = line_chart_from_table(
        table, table["columns"][0], table["columns"][1], title,
        series_name=table["columns"][1], cumulative=cumulative)
    if chart:
        violations = chart_guard(chart, {"table": table,
                                         "x_col": table["columns"][0],
                                         "y_col": table["columns"][1],
                                         "cumulative": cumulative}, title)
        if violations:
            logger.warning(f"[MonthlyReport] chart_guard failed for "
                           f"{metric_id}: {violations}")
            guards["chart_guard"] = "failed"
            fallbacks.append(f"chart→table ({metric_id})")
        else:
            guards.setdefault("chart_guard", "passed")
            chart["block_id"] = f"chart-{metric_id}"
            blocks.append(chart)
    blocks.append(table_block(table, f"table-{metric_id}"))
    return blocks, caveats


def run(query: str, router: Any = None, doc_ids: Optional[List[str]] = None,
        period: Optional[dict] = None) -> WorkflowResult:
    wid = WorkflowId.MONTHLY_PROGRESS_REPORT
    corpus = corpus_id()

    if period is None:
        from src.orchestration.resolver import parse_period
        parsed = parse_period(query or "")
        if parsed:
            period = {"date_from": parsed[0], "date_to": parsed[1],
                      "date_key": parsed[2]}

    blocks: List[dict] = []
    caveats: List[str] = []
    guards: Dict[str, str] = {"sql_guard": "passed"}  # execute_raw_sql validates
    fallbacks: List[str] = []
    sections: List[str] = []

    # 1. What data is actually here. Reported first so a thin report is
    #    self-explanatory rather than looking like a broken one.
    inv_table, inv_caveats = data_inventory(corpus)
    caveats.extend(inv_caveats)
    if inv_table is not None:
        blocks.append(md_block("### Data inventory", "h-inventory"))
        blocks.append(table_block(inv_table, "table-inventory"))
        sections.append("data inventory")

    # 2. Metric sections — each independent; a missing one becomes a caveat.
    for metric_id, heading in _BAR_SECTIONS:
        bs, cs = _bar_section(metric_id, heading, corpus, period, guards,
                              fallbacks)
        blocks.extend(bs)
        caveats.extend(cs)
        if bs:
            sections.append(heading.lower())

    for metric_id, heading, cumulative in _LINE_SECTIONS:
        bs, cs = _line_section(metric_id, heading, cumulative, corpus, period,
                              guards, fallbacks)
        blocks.extend(bs)
        caveats.extend(cs)
        if bs:
            sections.append(heading.lower())

    if not sections or (len(sections) == 1 and sections[0] == "data inventory"):
        text = ("A monthly progress report needs manpower, equipment or IPC "
                "data. None of the loaded tables map to those schemas — upload "
                "the progress workbooks, or confirm their column mapping if "
                "they are already uploaded.")
        return WorkflowResult(
            workflow_id=wid, status=RESULT_UNAVAILABLE, answer=text,
            blocks=[md_block(text, "empty")],
            caveats=caveats,
            substitute=WorkflowId.PRELIMINARY_PROGRAMME_PACK.value)

    period_label = f" — {period['date_key']}" if period else ""
    lead = (f"**Monthly progress report{period_label}** — compiled from: "
            + ", ".join(s for s in sections if s != "data inventory") + ".")
    blocks = [md_block(lead, "lead")] + blocks

    # IPC amounts are cumulative-to-date within one certificate, and the
    # period comes from the sheet name rather than a date column — so the
    # figure is "as at the latest certificate", not "this month's work".
    if any("ipc" in s for s in sections):
        caveats.append("IPC figures are taken from the latest certificate only "
                       "and are cumulative to its date, not work done in the "
                       "reporting period; the period is derived from the sheet "
                       "name, as IPC tables carry no date column.")
    if period:
        caveats.append(f"Monthly figures cover {period['date_key']}; trend "
                       "charts show the full loaded history.")

    caveats = CV.aggregate(caveats, [PROGRESS_NOT_ENTITLEMENT])
    blocks = finalize_blocks(blocks, guards, False, fallbacks, caveats)
    # Partial whenever a section dropped out — the caveats say which.
    complete = len(sections) >= len(_BAR_SECTIONS) + len(_LINE_SECTIONS) + 1
    return WorkflowResult(
        workflow_id=wid, status=RESULT_SUCCESS if complete else RESULT_PARTIAL,
        blocks=blocks, answer=lead, caveats=caveats, validation=guards)
