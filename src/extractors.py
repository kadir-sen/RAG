"""
Pre-built extractors for known Excel file formats.
Each extractor reads specific sheets/headers and transforms to a target schema.
When a file matches a known pattern, these run directly without LLM.

Supported formats:
  - DPR (Daily Progress Report) xlsx → manpower_production + equipment_log
  - Invoice xls (BREAKUP sheet) → ipc_sample
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from .logger import logger


# ── Pattern matching ─────────────────────────────────────────

def match_extractor(file_path: str) -> Optional[List[Tuple[str, str]]]:
    """
    Match file to pre-built extractors by filename + sheet patterns.

    Returns:
        List of (extractor_name, target_schema) tuples, or None if no match.
        A single file can produce multiple tables (e.g. DPR → manpower + equipment).
    """
    filename = Path(file_path).name
    ext = Path(file_path).suffix.lower()

    # Read sheet names
    sheets = []
    try:
        if ext in (".xlsx", ".xls"):
            xls = pd.ExcelFile(file_path)
            sheets = [s.lower() for s in xls.sheet_names]
    except Exception:
        pass

    matches = []

    # DPR pattern: "DPR YYMMDD.xlsx" with known sheet names
    if re.search(r"DPR\s*\d{6}", filename, re.IGNORECASE) and ext == ".xlsx":
        if any("man power" in s for s in sheets):
            matches.append(("dpr_manpower", "manpower_production"))
        if any("equipment" in s for s in sheets):
            matches.append(("dpr_equipment", "equipment_log"))

    # Invoice pattern: "INVOICE *.xls" with BREAKUP sheet
    if re.search(r"INVOICE", filename, re.IGNORECASE) and ext == ".xls":
        if any("breakup" in s for s in sheets):
            matches.append(("invoice_ipc", "ipc_sample"))

    if matches:
        logger.info(f"[Extractors] Matched {filename} → {[m[0] for m in matches]}")

    return matches if matches else None


def run_extractor(extractor_name: str, file_path: str) -> Optional[pd.DataFrame]:
    """Run a named extractor and return the resulting DataFrame."""
    extractors = {
        "dpr_manpower": extract_dpr_manpower,
        "dpr_equipment": extract_dpr_equipment,
        "invoice_ipc": extract_invoice_ipc,
    }
    fn = extractors.get(extractor_name)
    if fn is None:
        logger.warning(f"[Extractors] Unknown extractor: {extractor_name}")
        return None
    try:
        return fn(file_path)
    except Exception as e:
        logger.error(f"[Extractors] {extractor_name} failed for {Path(file_path).name}: {e}")
        return None


# ── Helper: extract date from DPR Cover Page ────────────────

def _get_dpr_date(file_path: str) -> Optional[str]:
    """Extract date from DPR Cover Page sheet."""
    try:
        cp = pd.read_excel(file_path, sheet_name="Cover Page", header=None)
        for idx in range(len(cp)):
            for col in range(cp.shape[1]):
                val = cp.iloc[idx, col]
                if isinstance(val, pd.Timestamp):
                    return val.strftime("%Y-%m-%d")
                if isinstance(val, str):
                    parsed = pd.to_datetime(val, errors="coerce")
                    if pd.notna(parsed):
                        return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass
    # Fallback: parse from filename  "DPR 180207" → 2018-02-07
    m = re.search(r"DPR\s*(\d{2})(\d{2})(\d{2})", Path(file_path).name, re.IGNORECASE)
    if m:
        yy, mm, dd = m.group(1), m.group(2), m.group(3)
        return f"20{yy}-{mm}-{dd}"
    return None


def _find_sheet(file_path: str, keyword: str) -> Optional[str]:
    """Find exact sheet name containing keyword (case-insensitive)."""
    try:
        xls = pd.ExcelFile(file_path)
        for name in xls.sheet_names:
            if keyword.lower() in name.lower():
                return name
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════
# DPR Manpower → manpower_production
# ══════════════════════════════════════════════════════════════

def extract_dpr_manpower(file_path: str) -> pd.DataFrame:
    """
    Extract manpower data from DPR Excel.
    Sheet: "CWJV - Man power" (or similar containing 'man power')

    Structure:
      Row 4: Main header → S No, Contractor, Designation, Zone names...
      Row 5: Sub header → Road & Utility, NHT Station, Viaduct...
      Row 6: Day/Night header
      Row 7+: Data rows (Contractor, Designation, worker counts per zone pair)

    Target: manpower_production schema
      Date, Block, Floor, Activity Description, Job Description,
      Number of Workers, Quantification, Unit of Measure
    """
    date_str = _get_dpr_date(file_path) or "unknown"

    sheet_name = _find_sheet(file_path, "Man power")
    if not sheet_name:
        raise ValueError("No 'Man power' sheet found")

    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

    if len(raw) < 8:
        raise ValueError(f"Sheet too short: {len(raw)} rows")

    # Parse headers from rows 4, 5, 6
    row4 = raw.iloc[4]  # Zone names
    row5 = raw.iloc[5]  # Sub-area names
    row6 = raw.iloc[6]  # Day / Night

    # Build zone mapping: col_index → (zone, sub_area, shift)
    zone_cols = {}
    current_zone = ""
    current_sub = ""

    for col_idx in range(3, raw.shape[1]):
        # Update zone from row 4 (forward-fill)
        v4 = row4.iloc[col_idx] if col_idx < len(row4) else np.nan
        if pd.notna(v4) and str(v4).strip() not in ("", "-", "NaN"):
            val = str(v4).strip()
            # Skip summary columns
            if val.lower() in ("total", "grand total"):
                current_zone = ""
                continue
            current_zone = val

        if not current_zone:
            continue

        # Update sub-area from row 5
        v5 = row5.iloc[col_idx] if col_idx < len(row5) else np.nan
        if pd.notna(v5) and str(v5).strip() not in ("", "-", "NaN"):
            current_sub = str(v5).strip()

        # Shift from row 6
        v6 = row6.iloc[col_idx] if col_idx < len(row6) else np.nan
        shift = str(v6).strip() if pd.notna(v6) else ""
        if shift.lower() not in ("day", "night"):
            continue

        zone_cols[col_idx] = (current_zone, current_sub, shift)

    # Extract data rows (row 7+)
    records = []
    current_contractor = ""

    for row_idx in range(7, len(raw)):
        row = raw.iloc[row_idx]

        # Contractor (col 1) — forward-fill
        contractor_val = row.iloc[1] if pd.notna(row.iloc[1]) else ""
        if contractor_val and str(contractor_val).strip() not in ("", "-"):
            current_contractor = str(contractor_val).strip()

        if not current_contractor:
            continue

        # Designation (col 2)
        designation = row.iloc[2] if pd.notna(row.iloc[2]) else ""
        designation = str(designation).strip()
        if not designation or designation in ("-", "NaN", "nan"):
            continue

        # Skip summary/total rows
        if designation.lower() in ("total", "grand total", "sub total"):
            continue

        # Aggregate Day + Night per zone+sub_area
        zone_workers = {}  # (zone, sub_area) → total_workers
        for col_idx, (zone, sub_area, shift) in zone_cols.items():
            val = row.iloc[col_idx] if col_idx < len(row) else np.nan
            count = pd.to_numeric(val, errors="coerce")
            if pd.notna(count) and count > 0:
                key = (zone, sub_area)
                zone_workers[key] = zone_workers.get(key, 0) + int(count)

        # Create one record per zone+sub_area
        for (zone, sub_area), workers in zone_workers.items():
            # Clean zone name: "Zone # 1A" → "1A"
            block = re.sub(r"Zone\s*#?\s*", "", zone).strip()
            if not block:
                block = zone

            records.append({
                "Date": date_str,
                "Block": block,
                "Floor": sub_area,
                "Activity Description": f"{current_contractor} - {sub_area}",
                "Job Description": designation,
                "Number of Workers": workers,
                "Quantification": float(workers),
                "Unit of Measure": "person",
            })

    df = pd.DataFrame(records)
    if df.empty:
        raise ValueError("No manpower data extracted")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    logger.info(f"[Extractors] DPR manpower: {len(df)} rows from {Path(file_path).name}")
    return df


# ══════════════════════════════════════════════════════════════
# DPR Equipment → equipment_log
# ══════════════════════════════════════════════════════════════

def extract_dpr_equipment(file_path: str) -> pd.DataFrame:
    """
    Extract equipment data from DPR Excel.
    Sheet: "CWJV & Subcontract Equipments" (or similar containing 'equipment')

    Structure:
      Row ~7: Date
      Row ~9: "MACHINERY SUMMARY" header
      Row ~10: Name | uom | ava.
      Row 11+: Machinery name | nos | count

    Target: equipment_log schema
      Date, Block, Floor, Machinery Name, Estimated Machinery Hours
    """
    date_str = _get_dpr_date(file_path) or "unknown"

    sheet_name = _find_sheet(file_path, "Equipment")
    if not sheet_name:
        raise ValueError("No 'Equipment' sheet found")

    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

    # Find "MACHINERY SUMMARY" row and data start
    data_start = None
    for idx in range(len(raw)):
        for col in range(raw.shape[1]):
            val = raw.iloc[idx, col]
            if pd.notna(val) and "MACHINERY SUMMARY" in str(val).upper():
                data_start = idx + 2  # skip header row after "MACHINERY SUMMARY"
                break
        if data_start is not None:
            break

    if data_start is None:
        # Fallback: try Sheet1 which has contractor equipment
        return _extract_sheet1_equipment(file_path, date_str)

    records = []
    # Name is typically in col 2, availability count in col 6
    name_col = None
    count_col = None

    # Detect header row (one row after MACHINERY SUMMARY)
    header_row = data_start - 1
    for col in range(raw.shape[1]):
        val = raw.iloc[header_row, col] if header_row < len(raw) else None
        if pd.notna(val):
            val_str = str(val).strip().lower()
            if val_str == "name":
                name_col = col
            elif val_str in ("ava.", "ava", "available", "qty", "nos"):
                count_col = col

    if name_col is None:
        name_col = 2
    if count_col is None:
        count_col = 6

    for idx in range(data_start, len(raw)):
        name_val = raw.iloc[idx, name_col] if name_col < raw.shape[1] else np.nan
        count_val = raw.iloc[idx, count_col] if count_col < raw.shape[1] else np.nan

        if pd.isna(name_val) or str(name_val).strip() in ("", "-", "NaN"):
            continue

        name = str(name_val).strip()
        # Skip total/summary rows
        if name.lower() in ("total", "grand total", "sub total"):
            continue

        count = pd.to_numeric(count_val, errors="coerce")
        if pd.isna(count):
            count = 0

        if count > 0:
            records.append({
                "Date": date_str,
                "Block": "All",
                "Floor": "All",
                "Machinery Name": name,
                "Estimated Machinery Hours": float(count),
            })

    df = pd.DataFrame(records)
    if df.empty:
        raise ValueError("No equipment data extracted")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    logger.info(f"[Extractors] DPR equipment: {len(df)} rows from {Path(file_path).name}")
    return df


def _extract_sheet1_equipment(file_path: str, date_str: str) -> pd.DataFrame:
    """Fallback: extract equipment from Sheet1 (Contractor / Equipment / Qty)."""
    try:
        raw = pd.read_excel(file_path, sheet_name="Sheet1", header=None)
    except Exception:
        raise ValueError("No equipment data found in Sheet1")

    records = []
    current_contractor = ""

    for idx in range(1, len(raw)):
        row = raw.iloc[idx]
        # Contractor in col 0
        if pd.notna(row.iloc[0]) and str(row.iloc[0]).strip():
            current_contractor = str(row.iloc[0]).strip()
        # Equipment in col 1, Qty in col 2
        equip = row.iloc[1] if pd.notna(row.iloc[1]) else ""
        qty = pd.to_numeric(row.iloc[2], errors="coerce") if pd.notna(row.iloc[2]) else 0

        if equip and str(equip).strip() and qty > 0:
            records.append({
                "Date": date_str,
                "Block": "All",
                "Floor": "All",
                "Machinery Name": str(equip).strip(),
                "Estimated Machinery Hours": float(qty),
            })

    df = pd.DataFrame(records)
    if df.empty:
        raise ValueError("No equipment data in Sheet1")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df


# ══════════════════════════════════════════════════════════════
# Invoice BREAKUP → ipc_sample
# ══════════════════════════════════════════════════════════════

def extract_invoice_ipc(file_path: str) -> pd.DataFrame:
    """
    Extract IPC data from Invoice Excel BREAKUP sheet.

    Structure (row indices from header=None read):
      Row 5: Main header → No., Manufacturer, Item, Description, Qty,
             Unit Price, Total Price, Material Delivered Quantity,
             PROGRESS %, PROGRESS CLAIM
      Row 6: Sub header → Previous, This Month, Cumulative (for qty & %)
      Row 7+: Data rows

    Target: ipc_sample schema
      Activity Code, Activity Name, Unit, BOQ Qty, Unit Rate,
      Total BOQ Amount, Previous %, Previous Amount, Current %,
      Current Amount, Cumulative %, Cumulative Amount,
      Previous Qty, Current Qty, Cumulative Qty
    """
    raw = pd.read_excel(file_path, sheet_name="BREAKUP", header=None)

    # Find main header row (contains "No." and "Qty")
    header_row = None
    for idx in range(min(10, len(raw))):
        row_vals = [str(v).strip() for v in raw.iloc[idx] if pd.notna(v)]
        if any("No." in v for v in row_vals) and any("Qty" in v for v in row_vals):
            header_row = idx
            break

    if header_row is None:
        raise ValueError("Cannot find BREAKUP header row")

    # Build column mapping from header row
    hdr = raw.iloc[header_row]
    col_map = {}
    for col_idx in range(len(hdr)):
        val = hdr.iloc[col_idx]
        if pd.isna(val):
            continue
        val_str = str(val).strip()

        if val_str == "No.":
            col_map["no"] = col_idx
        elif val_str == "Manufacturer":
            col_map["manufacturer"] = col_idx
        elif val_str == "Item":
            col_map["item"] = col_idx
        elif "Description" in val_str:
            col_map["description"] = col_idx
        elif val_str == "Qty":
            col_map["qty"] = col_idx
        elif "Unit Price" in val_str:
            col_map["unit_price"] = col_idx
        elif "Total Price" in val_str:
            col_map["total_price"] = col_idx
        elif "Material Delivered" in val_str:
            col_map["material_delivered_start"] = col_idx
        elif "PROGRESS %" in val_str:
            col_map["progress_pct_start"] = col_idx
        elif "PROGRESS CLAIM" in val_str:
            col_map["progress_claim_start"] = col_idx

    # Sub-header row (header_row + 1) has Previous / This Month / Cumulative
    # Material Delivered: 3 cols starting at material_delivered_start
    # Progress %: 3 cols starting at progress_pct_start
    # Progress Claim: 3 cols starting at progress_claim_start

    # Data starts at header_row + 2
    data_start = header_row + 2

    records = []
    for idx in range(data_start, len(raw)):
        row = raw.iloc[idx]

        # Only process rows with a numeric No.
        no_val = row.iloc[col_map.get("no", 0)] if "no" in col_map else np.nan
        no_num = pd.to_numeric(no_val, errors="coerce")
        if pd.isna(no_num):
            continue

        # Read core fields
        manufacturer = _safe_str(row, col_map.get("manufacturer"))
        item = _safe_str(row, col_map.get("item"))
        qty = _safe_num(row, col_map.get("qty"))
        unit_price = _safe_num(row, col_map.get("unit_price"))
        total_price = _safe_num(row, col_map.get("total_price"))

        # Activity name: combine item + manufacturer
        activity_name = item
        if manufacturer and manufacturer != item:
            activity_name = f"{item} ({manufacturer})"

        # Material delivered: Previous, This Month, Cumulative
        md_start = col_map.get("material_delivered_start", 99)
        prev_qty = _safe_num(row, md_start)
        curr_qty = _safe_num(row, md_start + 1)
        cum_qty = _safe_num(row, md_start + 2)

        # Progress %: Previous, This Month, Cumulative
        pp_start = col_map.get("progress_pct_start", 99)
        prev_pct = _safe_num(row, pp_start)
        curr_pct = _safe_num(row, pp_start + 1)
        cum_pct = _safe_num(row, pp_start + 2)

        # Progress claim: Previous, This Month, Cumulative
        pc_start = col_map.get("progress_claim_start", 99)
        prev_amt = _safe_num(row, pc_start)
        curr_amt = _safe_num(row, pc_start + 1)
        cum_amt = _safe_num(row, pc_start + 2)

        records.append({
            "Activity Code": str(int(no_num)),
            "Activity Name": activity_name or f"Item {int(no_num)}",
            "Unit": "nos",
            "BOQ Qty": qty,
            "Unit Rate": unit_price,
            "Total BOQ Amount": total_price,
            "Previous %": prev_pct,
            "Previous Amount": prev_amt,
            "Current %": curr_pct,
            "Current Amount": curr_amt,
            "Cumulative %": cum_pct,
            "Cumulative Amount": cum_amt,
            "Previous Qty": prev_qty,
            "Current Qty": curr_qty,
            "Cumulative Qty": cum_qty,
        })

    df = pd.DataFrame(records)
    if df.empty:
        raise ValueError("No IPC data extracted from BREAKUP")

    # Clean numeric columns
    num_cols = ["BOQ Qty", "Unit Rate", "Total BOQ Amount",
                "Previous %", "Previous Amount", "Current %", "Current Amount",
                "Cumulative %", "Cumulative Amount",
                "Previous Qty", "Current Qty", "Cumulative Qty"]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    logger.info(f"[Extractors] Invoice IPC: {len(df)} rows from {Path(file_path).name}")
    return df


# ── Utility functions ────────────────────────────────────────

def _safe_str(row: pd.Series, col_idx: Optional[int]) -> str:
    """Safely get string value from row at column index."""
    if col_idx is None or col_idx >= len(row):
        return ""
    val = row.iloc[col_idx]
    if pd.isna(val):
        return ""
    return str(val).strip()


def _safe_num(row: pd.Series, col_idx: Optional[int]) -> float:
    """Safely get numeric value from row at column index."""
    if col_idx is None or col_idx >= len(row):
        return 0.0
    val = row.iloc[col_idx]
    num = pd.to_numeric(val, errors="coerce")
    return float(num) if pd.notna(num) else 0.0
