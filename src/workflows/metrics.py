"""Deterministic metric catalogue for reporting workflows.

Generalises runners._SQL_TEMPLATES from "one metric, one chart" to a named,
whitelisted set a multi-section report can compose.

No LLM anywhere in this module. The SQL is ours: category columns and
aggregations are frozen in _METRICS and the only caller-supplied value is a
metric_id looked up in that dict, exactly like programme_tools._ADAPTERS. An
unknown metric_id returns a reason, never a query.

Schema resolution is not this module's job either — it happened at ingest, where
schema_profiler fuzzy-matched the workbook's headers to a canonical schema and
refused to guess below its confidence bar. We only read the verdict
(header_metadata.target_schema) via resolve_schema_tables.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Tables scanned per metric — same bound as runners.sql_metric_chart.
_MAX_TABLES = 12


@dataclass(frozen=True)
class MetricSpec:
    """One deterministic metric. Column names are frozen, quoted identifiers."""
    metric_id: str
    schema_id: str
    category_col: str        # quoted identifier, e.g. '"Job Description"'
    value_sql: str           # aggregation over quoted identifiers
    title: str
    value_label: str
    # date_key only exists on the normalizer's _clean view, so metrics that
    # break down or filter by month cannot fall back to the base table.
    requires_clean: bool = False
    # Order categories by value (ranking) or by category (time series).
    order_by_category: bool = False
    # Read only the newest table for the schema instead of summing them all.
    # Required for cumulative-to-date figures: each IPC certificate already
    # contains every earlier one, so adding certificates together counts the
    # same work repeatedly.
    latest_only: bool = False


_METRICS: Dict[str, MetricSpec] = {
    # ── Manpower ─────────────────────────────────────────────
    "manpower_by_trade": MetricSpec(
        "manpower_by_trade", "manpower_production", '"Job Description"',
        'SUM(TRY_CAST("Number of Workers" AS DOUBLE))',
        "Manpower by trade", "Total workers"),
    "manpower_by_block": MetricSpec(
        "manpower_by_block", "manpower_production", '"Block"',
        'SUM(TRY_CAST("Number of Workers" AS DOUBLE))',
        "Manpower by block", "Total workers"),
    "manpower_by_month": MetricSpec(
        "manpower_by_month", "manpower_production", '"date_key"',
        'SUM(TRY_CAST("Number of Workers" AS DOUBLE))',
        "Manpower by month", "Total workers",
        requires_clean=True, order_by_category=True),

    # ── Equipment ────────────────────────────────────────────
    "equipment_hours_by_machine": MetricSpec(
        "equipment_hours_by_machine", "equipment_log", '"Machinery Name"',
        'ROUND(SUM(TRY_CAST("Estimated Machinery Hours" AS DOUBLE)), 2)',
        "Equipment hours by machine", "Total hours"),
    "equipment_hours_by_block": MetricSpec(
        "equipment_hours_by_block", "equipment_log", '"Block"',
        'ROUND(SUM(TRY_CAST("Estimated Machinery Hours" AS DOUBLE)), 2)',
        "Equipment hours by block", "Total hours"),
    "equipment_hours_by_month": MetricSpec(
        "equipment_hours_by_month", "equipment_log", '"date_key"',
        'ROUND(SUM(TRY_CAST("Estimated Machinery Hours" AS DOUBLE)), 2)',
        "Equipment hours by month", "Total hours",
        requires_clean=True, order_by_category=True),

    # ── IPC / progress ───────────────────────────────────────
    # ipc_sample has no Date column of its own (storage/schemas/ipc_sample.json);
    # the normalizer derives date_key from the sheet name ("IPC_Apr_2025"), so
    # each certificate lands on exactly one month. Its amounts are
    # cumulative-to-date, hence latest_only: summing certificates would count
    # the same work once per certificate. There is deliberately no monthly IPC
    # series — some months carry two certificates, so a per-month total cannot
    # be formed without knowing which supersedes which.
    "ipc_cumulative_by_activity": MetricSpec(
        "ipc_cumulative_by_activity", "ipc_sample", '"Activity Name"',
        'ROUND(SUM(TRY_CAST("Cumulative Amount" AS DOUBLE)), 2)',
        "Certified amount to date by activity", "Cumulative amount",
        latest_only=True),

    # ── Physical production (the only real progress time series) ──
    "production_by_month": MetricSpec(
        "production_by_month", "manpower_production", '"date_key"',
        'SUM(TRY_CAST("Quantification" AS DOUBLE))',
        "Recorded production by month", "Quantity",
        requires_clean=True, order_by_category=True),
}


def metric_ids() -> List[str]:
    return list(_METRICS)


def get_spec(metric_id: str) -> Optional[MetricSpec]:
    return _METRICS.get(metric_id)


def _analyzer():
    from src.data_analyzer_sql import get_data_analyzer
    return get_data_analyzer()


def _table_period(analyzer, table: str) -> Optional[str]:
    """The single date_key a table's rows carry, or None if absent/mixed."""
    if f"{table}_clean" not in analyzer.tables:
        return None
    df, err = analyzer.execute_raw_sql(
        f'SELECT DISTINCT "date_key" AS k FROM "{table}_clean" '
        f'WHERE "date_key" IS NOT NULL')
    if err or df is None or len(df) != 1:
        return None
    return str(df.iloc[0]["k"])


def _latest_table(analyzer, tables: List[str]) -> Tuple[Optional[str], str]:
    """Newest table by derived period. Returns (table|None, reason).

    Refuses to choose when the newest period holds more than one table: two
    certificates for the same month is a real ambiguity about which supersedes
    which, and formal figures are not silently guessed here.
    """
    dated = [(p, t) for t in tables if (p := _table_period(analyzer, t))]
    if not dated:
        return None, "no table carries a recognisable period"
    newest = max(p for p, _ in dated)
    at_newest = [t for p, t in dated if p == newest]
    if len(at_newest) > 1:
        return None, (f"{len(at_newest)} certificates share the latest period "
                      f"({newest}); which one supersedes the other is not "
                      "recorded, so no figure was taken")
    return at_newest[0], newest


def run_metric(metric_id: str, corpus: str = "",
               period: Optional[Dict[str, Any]] = None,
               ) -> Tuple[Optional[dict], str]:
    """Compute one metric. Returns (data_table dict | None, reason).

    reason is a human-readable explanation whenever the table is None — it is
    written into the report's caveats rather than surfaced as an error, so a
    missing schema costs one section, not the whole report.
    """
    spec = _METRICS.get(metric_id)
    if spec is None:
        # Whitelist dispatch: nothing outside _METRICS can produce SQL.
        return None, f"unknown metric '{metric_id}'"

    from src.orchestration.resolver import resolve_schema_tables

    outcome = resolve_schema_tables(spec.schema_id, corpus)
    tables = outcome.resolved.get("tables") or []
    if not tables:
        return None, (f"No {spec.schema_id.replace('_', ' ')} data is loaded; "
                      f"{spec.title.lower()} is omitted.")

    try:
        analyzer = _analyzer()
    except Exception as e:                                  # pragma: no cover
        logger.warning(f"[Metrics] analyzer unavailable: {e}")
        return None, f"{spec.title} unavailable (data engine not ready)."

    note = ""
    if spec.latest_only:
        latest, reason = _latest_table(analyzer, tables)
        if latest is None:
            return None, f"{spec.title} omitted: {reason}."
        tables, note = [latest], reason

    where = ""
    if period and period.get("date_key") and not spec.latest_only:
        # date_key is derived by the normalizer, not user text; still, it only
        # ever reaches SQL as a literal we format from a parsed period.
        where = f" WHERE \"date_key\" = '{period['date_key']}'"

    import pandas as pd

    frames = []
    skipped_no_clean = 0
    for t in tables[:_MAX_TABLES]:
        has_clean = f"{t}_clean" in analyzer.tables
        if spec.requires_clean and not has_clean:
            skipped_no_clean += 1
            continue
        view = f'"{t}_clean"' if has_clean else f'"{t}"'
        # date_key/is_total_row only exist on _clean.
        use_where = where if has_clean else ""
        extra = ' AND "is_total_row" = false' if (has_clean and use_where) \
            else (' WHERE "is_total_row" = false' if has_clean else "")
        sql = (f"SELECT {spec.category_col} AS category, "
               f"{spec.value_sql} AS value "
               f"FROM {view}{use_where}{extra} "
               f"GROUP BY {spec.category_col}")
        df, err = analyzer.execute_raw_sql(sql)
        if err:
            logger.debug(f"[Metrics] {metric_id} skipped {t}: {err}")
            continue
        if df is not None and not df.empty:
            frames.append(df)

    if not frames:
        if skipped_no_clean:
            return None, (f"{spec.title} needs a recognised date column; the "
                          f"loaded {spec.schema_id.replace('_', ' ')} tables "
                          "have none.")
        return None, (f"No {spec.schema_id.replace('_', ' ')} rows found"
                      + (f" for {period['date_key']}" if period else "")
                      + f"; {spec.title.lower()} is omitted.")

    merged = pd.concat(frames)
    merged = merged[merged["category"].notna()]
    if merged.empty:
        return None, f"No labelled rows to report for {spec.title.lower()}."
    merged = merged.groupby("category", as_index=False)["value"].sum()
    merged = merged.sort_values(
        "category" if spec.order_by_category else "value",
        ascending=bool(spec.order_by_category))

    if spec.latest_only:
        # The period is the certificate's own, not the report's filter.
        title = f"{spec.title} — as at {note}"
    else:
        title = spec.title + (f" — {period['date_key']}" if period else "")
    table = {
        "title": title,
        "columns": [spec.category_col.strip('"'), spec.value_label],
        "rows": [[str(r.category), float(r.value)] for r in merged.itertuples()],
    }
    return table, ""


# ── Project data inventory (Excel side) ──────────────────────

def data_inventory(corpus: str = "") -> Tuple[Optional[dict], List[str]]:
    """What reportable data is actually loaded. Returns (data_table, caveats).

    This is the Excel half of a project inventory; programme_tools' inventory
    adapter covers .xer only (registry's PROJECT_DATA_INVENTORY still calls the
    Excel listing "Sprint 2" — this is it).
    """
    caveats: List[str] = []
    try:
        analyzer = _analyzer()
    except Exception as e:                                  # pragma: no cover
        logger.warning(f"[Metrics] analyzer unavailable: {e}")
        return None, ["The data engine is not ready; no data inventory."]

    from src.orchestration.resolver import resolve_schema_tables

    # One row per schema, not per table: a project routinely carries dozens of
    # monthly workbooks per schema, and listing each one buries the answer to
    # "what data do we have" under near-identical rows.
    rows: List[List[Any]] = []
    for schema_id in sorted({s.schema_id for s in _METRICS.values()}):
        outcome = resolve_schema_tables(schema_id, corpus)
        tables = outcome.resolved.get("tables") or []
        if not tables:
            continue
        files, total_rows, periods, dated = set(), 0, [], 0
        for t in tables:
            info = analyzer.tables.get(t, {})
            src = info.get("source_file") or info.get("file_name") or t
            files.add(os.path.basename(str(src)))
            total_rows += int(info.get("row_count", 0) or 0)
            if f"{t}_clean" in analyzer.tables:
                dated += 1
                df, err = analyzer.execute_raw_sql(
                    f'SELECT MIN("date_key") AS a, MAX("date_key") AS b '
                    f'FROM "{t}_clean" WHERE "date_key" IS NOT NULL')
                if not err and df is not None and not df.empty:
                    a, b = df.iloc[0]["a"], df.iloc[0]["b"]
                    if a:
                        periods.extend([str(a), str(b or a)])
        if periods:
            lo, hi = min(periods), max(periods)
            period_range = lo if lo == hi else f"{lo} → {hi}"
        else:
            period_range = "—"
        rows.append([
            schema_id.replace("_", " "),
            len(files),
            len(tables),
            total_rows,
            period_range,
            "all" if dated == len(tables) else (f"{dated}/{len(tables)}"
                                                if dated else "none"),
        ])

    if not rows:
        return None, ["No recognised manpower, equipment or IPC tables are "
                      "loaded for this project."]

    # Tables whose headers the profiler could not confidently map never get a
    # target_schema, so they are invisible above. Say so rather than let the
    # inventory read as "this is everything you uploaded".
    try:
        from src.learning.schema_memory import pending_confirmations
        pending = pending_confirmations(corpus or None)
        if pending:
            caveats.append(
                f"{len(pending)} uploaded table(s) are awaiting schema "
                "confirmation and were excluded from this report.")
    except Exception as e:
        logger.debug(f"[Metrics] pending confirmations unavailable: {e}")

    table = {
        "title": "Project data inventory",
        "columns": ["Data", "Files", "Tables", "Rows", "Period range",
                    "Dated"],
        "rows": rows,
    }
    return table, caveats
