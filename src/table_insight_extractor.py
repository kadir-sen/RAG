"""
Table Insight Extractor - Pandas-based automatic insight generation.
Extracts narrative, stats, anomalies, and metadata from converted DataFrames.
No LLM calls — pure pandas analysis.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd
import numpy as np

from .logger import logger
from .table_normalizer import parse_mixed_datetime


# Schema display names
SCHEMA_DISPLAY = {
    "equipment_log": "Equipment Log",
    "ipc_sample": "IPC (Interim Progress Certificate)",
    "manpower_production": "Manpower Production Log",
}



def extract_table_insight(
    df: pd.DataFrame,
    file_path: str,
    target_schema: str,
) -> Dict[str, Any]:
    """
    Extract insight from a converted DataFrame.

    Args:
        df: Converted DataFrame (already in target schema format)
        file_path: Original source file path
        target_schema: Schema ID (equipment_log, ipc_sample, manpower_production)

    Returns:
        Dict with narrative, stats, anomalies, etc.
    """
    insight = {
        "target_schema": target_schema,
        "schema_display": SCHEMA_DISPLAY.get(target_schema, target_schema),
        "source_file": Path(file_path).name,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": list(df.columns),
    }

    # Date analysis
    date_info = _extract_date_info(df)
    insight["date_range"] = date_info.get("date_range")
    insight["months"] = date_info.get("months", [])

    # Block/Floor analysis
    insight["unique_blocks"] = _get_unique_values(df, ["Block", "block", "blok"])
    insight["unique_floors"] = _get_unique_values(df, ["Floor", "floor", "kat"])

    # Company name from filename
    insight["company_name"] = _extract_company_name(file_path)

    # Build narrative
    insight["narrative"] = _build_narrative(insight)

    # Schema-specific stats
    insight["stats"] = _extract_schema_stats(df, target_schema)

    # Anomaly detection
    insight["anomalies"] = _detect_anomalies(df, target_schema)

    # Data quality
    insight["completeness_score"] = _compute_completeness(df)
    insight["null_percentage"] = _compute_null_percentages(df)

    # Jargon from columns
    insight["jargon_map"] = _extract_jargon(df)

    logger.info(f"[TableInsight] {insight['narrative']}")
    if insight["anomalies"]:
        logger.info(f"[TableInsight] Anomalies: {len(insight['anomalies'])}")

    return insight


def _extract_date_info(df: pd.DataFrame) -> Dict[str, Any]:
    """Extract date range and monthly breakdown."""
    date_cols = [c for c in df.columns if "date" in c.lower()]

    for col in date_cols:
        dates = parse_mixed_datetime(df[col]).dropna()
        if dates.empty:
            continue

        min_d, max_d = dates.min(), dates.max()
        months = sorted(dates.dt.to_period("M").unique().astype(str).tolist())

        if min_d.month == max_d.month and min_d.year == max_d.year:
            date_range = min_d.strftime("%B %Y")
        else:
            date_range = f"{min_d.strftime('%B %Y')} - {max_d.strftime('%B %Y')}"

        return {"date_range": date_range, "months": months}

    return {}


def _get_unique_values(df: pd.DataFrame, col_candidates: List[str]) -> List[str]:
    """Get unique values from the first matching column."""
    for col in col_candidates:
        if col in df.columns:
            vals = df[col].dropna().unique()
            return [str(v) for v in vals[:20] if str(v).strip()]
    return []


def _extract_company_name(file_path: str) -> str:
    """Try to extract company/project name from filename."""
    stem = Path(file_path).stem

    # Remove common suffixes
    for suffix in ["_equipment", "_manpower", "_ipc", "_log", "_report",
                   "_data", "_template", "_sample"]:
        stem = re.sub(suffix, "", stem, flags=re.IGNORECASE)

    # Remove date patterns
    stem = re.sub(r'\d{4}[-_]\d{2}[-_]\d{2}', '', stem)
    stem = re.sub(r'\d{4}[-_]\d{2}', '', stem)
    stem = re.sub(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*[-_]?\d{2,4}',
                  '', stem, flags=re.IGNORECASE)

    # Clean up
    stem = re.sub(r'[-_]+', ' ', stem).strip()
    stem = re.sub(r'\s+', ' ', stem)

    return stem if len(stem) > 2 else ""


def _build_narrative(insight: Dict) -> str:
    """Build a human-readable narrative from insight data."""
    parts = []

    if insight.get("company_name"):
        parts.append(insight["company_name"])

    parts.append(SCHEMA_DISPLAY.get(insight["target_schema"], insight["target_schema"]))

    if insight.get("date_range"):
        parts.append(insight["date_range"])

    parts.append(f"{insight['row_count']} rows")

    return " - ".join(parts)


def _extract_schema_stats(df: pd.DataFrame, schema_id: str) -> Dict[str, Any]:
    """Extract schema-specific statistics."""
    if schema_id == "equipment_log":
        return _stats_equipment(df)
    elif schema_id == "manpower_production":
        return _stats_manpower(df)
    elif schema_id == "ipc_sample":
        return _stats_ipc(df)
    return {}


def _stats_equipment(df: pd.DataFrame) -> Dict[str, Any]:
    """Equipment log specific stats."""
    stats = {}

    # Machinery name distribution
    mach_col = _find_col(df, ["Machinery Name", "machinery_name", "machine", "ekipman"])
    if mach_col:
        vc = df[mach_col].dropna().value_counts()
        stats["top_machinery"] = vc.head(5).to_dict()
        stats["unique_machinery_count"] = int(vc.shape[0])

    # Total hours
    hours_col = _find_col(df, ["Estimated Machinery Hours", "estimated_machinery_hours",
                                "hours", "saat"])
    if hours_col:
        numeric = pd.to_numeric(df[hours_col], errors="coerce")
        stats["total_hours"] = round(float(numeric.sum()), 2)
        stats["avg_hours_per_record"] = round(float(numeric.mean()), 2)

    # Blocks covered
    block_col = _find_col(df, ["Block", "block", "blok"])
    if block_col:
        stats["blocks_covered"] = int(df[block_col].dropna().nunique())

    return stats


def _stats_manpower(df: pd.DataFrame) -> Dict[str, Any]:
    """Manpower production log specific stats."""
    stats = {}

    # Total workers
    workers_col = _find_col(df, ["Number of Workers", "number_of_workers",
                                  "workers", "headcount"])
    if workers_col:
        numeric = pd.to_numeric(df[workers_col], errors="coerce")
        stats["total_workers"] = int(numeric.sum())
        stats["avg_workers_per_record"] = round(float(numeric.mean()), 2)

    # Top activities
    activity_col = _find_col(df, ["Activity Description", "activity_description",
                                   "activity", "task"])
    if activity_col:
        vc = df[activity_col].dropna().value_counts()
        stats["top_activities"] = vc.head(5).to_dict()
        stats["unique_activities"] = int(vc.shape[0])

    # Top job types
    job_col = _find_col(df, ["Job Description", "job_description", "trade", "job"])
    if job_col:
        vc = df[job_col].dropna().value_counts()
        stats["top_job_types"] = vc.head(5).to_dict()

    # Total quantification
    qty_col = _find_col(df, ["Quantification", "quantification", "quantity", "output"])
    if qty_col:
        numeric = pd.to_numeric(df[qty_col], errors="coerce")
        stats["total_quantity"] = round(float(numeric.sum()), 2)

    return stats


def _stats_ipc(df: pd.DataFrame) -> Dict[str, Any]:
    """IPC specific stats."""
    stats = {}

    # Total BOQ amount
    boq_col = _find_col(df, ["Total BOQ Amount", "total_boq_amount", "total_amount",
                              "contract_amount"])
    if boq_col:
        numeric = pd.to_numeric(df[boq_col], errors="coerce")
        stats["total_boq_amount"] = round(float(numeric.sum()), 2)

    # Activity count
    code_col = _find_col(df, ["Activity Code", "activity_code", "code", "item_code"])
    if code_col:
        stats["activity_count"] = int(df[code_col].dropna().nunique())

    # Cumulative progress
    cum_col = _find_col(df, ["Cumulative %", "cumulative_pct", "cum_percent",
                              "total_progress"])
    if cum_col:
        numeric = pd.to_numeric(df[cum_col], errors="coerce").dropna()
        if not numeric.empty:
            stats["max_cumulative_pct"] = round(float(numeric.max()), 2)
            stats["avg_cumulative_pct"] = round(float(numeric.mean()), 2)

    # Current period amount
    curr_col = _find_col(df, ["Current Amount", "current_amount", "curr_amount"])
    if curr_col:
        numeric = pd.to_numeric(df[curr_col], errors="coerce")
        stats["current_period_amount"] = round(float(numeric.sum()), 2)

    # Unit rate range
    rate_col = _find_col(df, ["Unit Rate", "unit_rate", "rate", "price"])
    if rate_col:
        numeric = pd.to_numeric(df[rate_col], errors="coerce").dropna()
        if not numeric.empty:
            stats["min_unit_rate"] = round(float(numeric.min()), 2)
            stats["max_unit_rate"] = round(float(numeric.max()), 2)

    return stats


def _detect_anomalies(df: pd.DataFrame, schema_id: str) -> List[str]:
    """Detect anomalies and data quality issues."""
    anomalies = []

    # 1. Zero values in numeric columns that shouldn't be zero
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        zero_count = int((df[col] == 0).sum())
        if zero_count > 0 and zero_count < len(df):
            anomalies.append(f"{col}: {zero_count} rows with zero values")

    # 2. Single-entry categories (potential outliers)
    category_cols = _get_category_columns(df, schema_id)
    for col in category_cols:
        if col not in df.columns:
            continue
        vc = df[col].dropna().value_counts()
        singles = vc[vc == 1]
        if 0 < len(singles) <= 3:
            names = list(singles.index)
            anomalies.append(f"{col}: {names} only 1 record each")

    # 3. Date gaps > 7 days
    date_cols = [c for c in df.columns if "date" in c.lower()]
    for col in date_cols:
        dates = parse_mixed_datetime(df[col]).dropna().sort_values()
        if len(dates) > 1:
            gaps = dates.diff().dt.days
            big_gaps = gaps[gaps > 7]
            if len(big_gaps) > 0:
                anomalies.append(f"{len(big_gaps)} date gaps detected (>7 days)")

    # 4. High null percentage columns
    for col in df.columns:
        null_pct = df[col].isna().mean()
        if 0 < null_pct > 0.3:
            anomalies.append(f"{col}: {null_pct*100:.0f}% null values")

    return anomalies[:10]  # Limit to 10 anomalies


def _get_category_columns(df: pd.DataFrame, schema_id: str) -> List[str]:
    """Get category columns for anomaly detection based on schema."""
    if schema_id == "equipment_log":
        return ["Block", "block", "Machinery Name", "machinery_name"]
    elif schema_id == "manpower_production":
        return ["Block", "block", "Job Description", "job_description"]
    elif schema_id == "ipc_sample":
        return ["Activity Code", "activity_code", "Unit", "unit"]
    return []


def _compute_completeness(df: pd.DataFrame) -> float:
    """Compute overall data completeness score (0.0 - 1.0)."""
    if df.empty:
        return 0.0
    total_cells = df.shape[0] * df.shape[1]
    non_null_cells = df.notna().sum().sum()
    return round(float(non_null_cells / total_cells), 3) if total_cells > 0 else 0.0


def _compute_null_percentages(df: pd.DataFrame) -> Dict[str, float]:
    """Compute per-column null percentage."""
    if df.empty:
        return {}
    return {col: round(float(df[col].isna().mean()), 3) for col in df.columns}


def _extract_jargon(df: pd.DataFrame) -> Dict[str, str]:
    """Extract jargon/abbreviation explanations for column names."""
    try:
        from .jargon_manager import get_jargon_manager
        jargon = get_jargon_manager()
        result = {}
        for col in df.columns:
            # Check column name and parts
            for word in re.split(r'[\s_]+', col):
                expanded = jargon.expand(word.upper())
                if expanded and expanded.upper() != word.upper():
                    result[word] = expanded
        return result
    except Exception:
        return {}


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Find first matching column from candidates."""
    df_cols_lower = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand in df.columns:
            return cand
        if cand.lower() in df_cols_lower:
            return df_cols_lower[cand.lower()]
    return None


def build_column_mapping(
    source_df: pd.DataFrame,
    converted_df: pd.DataFrame,
    target_schema: str,
) -> pd.DataFrame:
    """
    Build a column mapping table showing source → target conversion.
    Used by debug_app.py for visual display.
    """
    try:
        from .schema_converter import get_target_schemas
        registry = get_target_schemas()
        schema = registry.get_schema(target_schema)
    except Exception:
        schema = None

    rows = []
    target_cols = set(c.lower().strip() for c in converted_df.columns)

    if schema:
        for col_def in schema.columns:
            # Find which source column mapped to this target
            source_match = _find_source_match(source_df, col_def)
            in_output = col_def.name in converted_df.columns or col_def.name.lower() in target_cols

            rows.append({
                "Target Column": col_def.name,
                "Type": col_def.dtype,
                "Required": "Yes" if col_def.required else "No",
                "Source Column": source_match or "—",
                "Status": "✅" if in_output else "❌",
            })
    else:
        for col in converted_df.columns:
            rows.append({
                "Target Column": col,
                "Type": str(converted_df[col].dtype),
                "Required": "—",
                "Source Column": "—",
                "Status": "✅",
            })

    return pd.DataFrame(rows)


def _find_source_match(source_df: pd.DataFrame, col_def) -> Optional[str]:
    """Find which source column likely maps to a target column definition."""
    source_cols_lower = {c.lower().strip(): c for c in source_df.columns}
    check_names = [col_def.name.lower()] + [a.lower() for a in col_def.aliases]

    for name in check_names:
        if name in source_cols_lower:
            return source_cols_lower[name]

    return None
