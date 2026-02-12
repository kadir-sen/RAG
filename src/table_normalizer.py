"""
Table Normalizer - Detects total/subtotal rows and extracts month/year info.
Produces _clean (no totals) and _raw views for correct analytics.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .logger import logger


# ── Month mappings ───────────────────────────────────────────

MONTH_MAP_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

MONTH_MAP_TR = {
    "ocak": 1, "subat": 2, "şubat": 2, "mart": 3, "nisan": 4,
    "mayis": 5, "mayıs": 5, "haziran": 6, "temmuz": 7,
    "agustos": 8, "ağustos": 8, "eylul": 9, "eylül": 9,
    "ekim": 10, "kasim": 11, "kasım": 11, "aralik": 12, "aralık": 12,
}

ALL_MONTHS = {**MONTH_MAP_EN, **MONTH_MAP_TR}

# ── Total-row tokens ────────────────────────────────────────

TOTAL_TOKENS = [
    "total", "toplam", "grand total", "genel toplam",
    "year total", "yıl toplam", "yil toplam",
    "subtotal", "sub total", "ara toplam",
    "monthly total", "aylık toplam", "aylik toplam",
    "yearly total", "yıllık toplam", "yillik toplam",
    "overall", "genel", "summary",
]


@dataclass
class NormalizationReport:
    """Report from normalizing a table."""
    table_name: str
    total_rows_detected: int = 0
    months_detected: int = 0
    years_detected: int = 0
    has_month_column: bool = False
    has_year_column: bool = False
    month_source: str = ""  # "column:<name>" | "label:<name>" | "none"
    clean_row_count: int = 0
    raw_row_count: int = 0


def _cell_to_str(val) -> str:
    """Safely convert any cell value to lowercase string."""
    if pd.isna(val):
        return ""
    return str(val).strip().lower()


def detect_total_rows(df: pd.DataFrame) -> pd.Series:
    """
    Return a boolean Series indicating total/subtotal rows.
    A row is marked total if ANY string cell contains a total token.
    """
    mask = pd.Series(False, index=df.index)

    for idx, row in df.iterrows():
        for val in row:
            cell = _cell_to_str(val)
            if not cell:
                continue
            for token in TOTAL_TOKENS:
                if token in cell:
                    mask.at[idx] = True
                    break
            if mask.at[idx]:
                break

    return mask


def _parse_month_from_string(text: str) -> Optional[int]:
    """Try to extract a month number from a string."""
    text = text.strip().lower()

    # Direct month name match
    for name, num in ALL_MONTHS.items():
        if name in text:
            return num

    # Numeric month: "09", "9"
    m = re.match(r'^(\d{1,2})$', text)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 12:
            return val

    # ISO-like: "2025-09" or "2025/09"
    m = re.search(r'(\d{4})[-/](\d{1,2})', text)
    if m:
        val = int(m.group(2))
        if 1 <= val <= 12:
            return val

    return None


def _parse_year_from_string(text: str) -> Optional[int]:
    """Try to extract a 4-digit year from a string."""
    m = re.search(r'((?:19|20)\d{2})', text.strip())
    if m:
        return int(m.group(1))
    return None


def _find_month_column(df: pd.DataFrame) -> Optional[str]:
    """
    Find a column that likely holds month names or numbers.
    Returns column name or None.
    """
    month_col_keywords = ["month", "ay", "period", "donem", "dönem"]

    # First try: column name heuristic
    for col in df.columns:
        col_lower = str(col).lower()
        for kw in month_col_keywords:
            if kw in col_lower:
                return col

    # Second try: check non-numeric columns for month content
    for col in df.select_dtypes(include=["object"]).columns:
        sample = df[col].dropna().head(20)
        month_hits = 0
        for val in sample:
            if _parse_month_from_string(str(val)) is not None:
                month_hits += 1
        if month_hits >= 3:
            return col

    return None


def _find_year_column(df: pd.DataFrame) -> Optional[str]:
    """Find a column that likely holds year values."""
    year_col_keywords = ["year", "yil", "yıl"]

    for col in df.columns:
        col_lower = str(col).lower()
        for kw in year_col_keywords:
            if kw in col_lower:
                return col

    return None


def _find_label_column(df: pd.DataFrame) -> Optional[str]:
    """Find the first string/object column that likely contains row labels."""
    for col in df.select_dtypes(include=["object"]).columns:
        non_null = df[col].dropna()
        if len(non_null) > 0:
            return col
    # Fallback: first column
    if len(df.columns) > 0:
        return df.columns[0]
    return None


def normalize_table(
    df: pd.DataFrame,
    table_name: str = "",
) -> Tuple[pd.DataFrame, NormalizationReport]:
    """
    Normalize a DataFrame by detecting totals and extracting month/year.

    Returns:
        (normalized_df with added columns, NormalizationReport)
    """
    report = NormalizationReport(table_name=table_name, raw_row_count=len(df))

    # Work on a copy
    df = df.copy()

    # 1. Detect total rows
    df["is_total_row"] = detect_total_rows(df)
    report.total_rows_detected = int(df["is_total_row"].sum())

    # 2. Extract month_num
    df["month_num"] = pd.Series(dtype="Int64", index=df.index)
    month_col = _find_month_column(df)

    if month_col is not None:
        report.has_month_column = True
        report.month_source = f"column:{month_col}"
        for idx, val in df[month_col].items():
            m = _parse_month_from_string(_cell_to_str(val))
            if m is not None:
                df.at[idx, "month_num"] = m
    else:
        # Try from label column
        label_col = _find_label_column(df)
        if label_col is not None:
            for idx, val in df[label_col].items():
                m = _parse_month_from_string(_cell_to_str(val))
                if m is not None:
                    df.at[idx, "month_num"] = m
            if df["month_num"].notna().any():
                report.month_source = f"label:{label_col}"

    report.months_detected = int(df["month_num"].notna().sum())

    # 3. Extract year
    year_col = _find_year_column(df)  # find before adding "year" column
    df["year"] = pd.Series(dtype="Int64", index=df.index)

    if year_col is not None:
        report.has_year_column = True
        for idx, val in df[year_col].items():
            y = _parse_year_from_string(_cell_to_str(val))
            if y is not None:
                df.at[idx, "year"] = y
    else:
        # Try extracting from label/month column
        source_col = month_col or _find_label_column(df)
        if source_col is not None:
            for idx, val in df[source_col].items():
                y = _parse_year_from_string(_cell_to_str(val))
                if y is not None:
                    df.at[idx, "year"] = y

    report.years_detected = int(df["year"].notna().sum())

    # 4. Build date_key "YYYY-MM"
    df["date_key"] = None
    mask = df["month_num"].notna()
    if df["year"].notna().any():
        both = mask & df["year"].notna()
        if both.any():
            df.loc[both, "date_key"] = (
                df.loc[both, "year"].astype(int).astype(str)
                + "-"
                + df.loc[both, "month_num"].astype(int).astype(str).str.zfill(2)
            )

    report.clean_row_count = int((~df["is_total_row"]).sum())

    logger.info(
        f"[TableNormalizer] {table_name}: "
        f"{report.total_rows_detected} total rows, "
        f"{report.months_detected} months, "
        f"clean={report.clean_row_count}/{report.raw_row_count}"
    )

    return df, report


def get_clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """Get DataFrame with total rows removed."""
    if "is_total_row" in df.columns:
        return df[~df["is_total_row"]].copy()
    return df.copy()


def get_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    """Get the full DataFrame including total rows."""
    return df.copy()
