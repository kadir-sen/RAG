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

ALL_MONTHS = {**MONTH_MAP_EN}

# ── Total-row tokens ────────────────────────────────────────

TOTAL_TOKENS = [
    "total", "grand total",
    "year total",
    "subtotal", "sub total",
    "monthly total",
    "yearly total",
    "overall", "summary",
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


def parse_mixed_datetime(series: pd.Series) -> pd.Series:
    """
    Parse mixed date formats safely without enforcing a single locale.

    Supported examples:
    - 2.01.2025              (day-first dotted)
    - 2027-06-21 0:00:00     (ISO datetime)
    - 09/18/2027             (US month/day)
    - 01-Jan-2025            (DD-MMM-YYYY)
    - 01/Jan/2025            (DD/MMM/YYYY)
    - 2025/01/15             (YYYY/MM/DD)
    - 01 January 2025        (DD Month YYYY)
    - 1737849600              (epoch seconds)
    """
    if series is None or len(series) == 0:
        return pd.to_datetime(series, errors="coerce")

    # Normalize textual null-like values before parsing.
    text = series.astype(str).str.strip().replace({
        "": None, "nan": None, "NaN": None, "None": None, "NaT": None,
    })

    def _parse_one(value):
        if value is None:
            return pd.NaT

        s = str(value).strip()
        if not s:
            return pd.NaT

        # Dotted dates are commonly day-first (e.g. 2.01.2025).
        if re.match(r"^\d{1,2}\.\d{1,2}\.\d{4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$", s):
            return pd.to_datetime(s, errors="coerce", dayfirst=True)

        # DD-MMM-YYYY or DD/MMM/YYYY (e.g. 01-Jan-2025, 01/Jan/2025)
        if re.match(r"^\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{4}$", s):
            parsed = pd.to_datetime(s, errors="coerce", dayfirst=True)
            if not pd.isna(parsed):
                return parsed

        # DD Month YYYY or DD MMM YYYY (e.g. 01 January 2025, 01 Jan 2025)
        if re.match(r"^\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}$", s):
            parsed = pd.to_datetime(s, errors="coerce", dayfirst=True)
            if not pd.isna(parsed):
                return parsed

        # YYYY/MM/DD (e.g. 2025/01/15)
        if re.match(r"^\d{4}/\d{1,2}/\d{1,2}$", s):
            parsed = pd.to_datetime(s, errors="coerce", format="%Y/%m/%d")
            if not pd.isna(parsed):
                return parsed

        # Epoch timestamps (numeric, > 1 billion = post-2001)
        if re.match(r"^\d{10,13}$", s):
            try:
                ts = int(s)
                unit = 'ms' if ts > 1e12 else 's'
                return pd.to_datetime(ts, unit=unit)
            except (ValueError, OverflowError):
                pass

        # First attempt month-first/ISO-friendly parse.
        parsed = pd.to_datetime(s, errors="coerce", dayfirst=False)
        if not pd.isna(parsed):
            return parsed

        # If first token is >12, this must be day-first for slash/dash forms.
        token_match = re.match(r"^(?P<a>\d{1,2})[/-](?P<b>\d{1,2})[/-](?P<c>\d{2,4})(?:\s+.*)?$", s)
        if token_match:
            first = int(token_match.group("a"))
            if first > 12:
                return pd.to_datetime(s, errors="coerce", dayfirst=True)

        # Final fallback.
        return pd.to_datetime(s, errors="coerce", dayfirst=True)

    return text.apply(_parse_one)


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
    month_col_keywords = ["month", "period"]

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
    year_col_keywords = ["year"]

    for col in df.columns:
        col_lower = str(col).lower()
        for kw in year_col_keywords:
            if kw in col_lower:
                return col

    return None


def _find_date_column(df: pd.DataFrame) -> Optional[str]:
    """Find a column that contains date values (datetime type or parseable strings)."""
    date_keywords = ["date", "tarih"]
    # First: column name heuristic
    for col in df.columns:
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in date_keywords):
            return col
    # Second: check for datetime dtype columns
    for col in df.select_dtypes(include=["datetime", "datetime64"]).columns:
        return col
    # Third: try parsing object columns that look like dates
    for col in df.select_dtypes(include=["object"]).columns:
        try:
            sample = df[col].dropna().head(20)
            parsed = parse_mixed_datetime(sample)
            if parsed.notna().sum() >= min(10, len(sample) * 0.5):
                return col
        except Exception:
            continue
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

    # 3.45 Fallback: extract month/year from _sheet_name column
    if not df["month_num"].notna().any() and '_sheet_name' in df.columns:
        import re as _re
        _month_map = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }

        def _month_from_sheet(name):
            name_lower = str(name).lower()
            for abbr, num in _month_map.items():
                if abbr in name_lower:
                    return num
            return None

        df['month_num'] = df['_sheet_name'].apply(_month_from_sheet).astype("Int64")
        if df['month_num'].notna().any():
            report.month_source = f"sheet_name:{df['_sheet_name'].iloc[0]}" if len(df) > 0 else "none"
            report.months_detected = int(df['month_num'].notna().sum())
            # Year extraction from sheet name
            first_sheet = str(df['_sheet_name'].iloc[0]) if len(df) > 0 else ''
            year_match = _re.search(r'20\d{2}', first_sheet)
            if year_match and not df['year'].notna().any():
                df['year'] = int(year_match.group())
                report.years_detected = len(df)

    # 3.5 Fallback: extract month/year from date-type columns
    if not df["month_num"].notna().any():
        _date_col = _find_date_column(df)
        if _date_col is not None:
            dates = parse_mixed_datetime(df[_date_col])
            valid_mask = dates.notna()
            if valid_mask.sum() >= len(df) * 0.5:
                df.loc[valid_mask, "month_num"] = dates[valid_mask].dt.month.astype("Int64")
                report.month_source = f"date:{_date_col}"
                report.months_detected = int(df["month_num"].notna().sum())
                if not df["year"].notna().any():
                    df.loc[valid_mask, "year"] = dates[valid_mask].dt.year.astype("Int64")
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
