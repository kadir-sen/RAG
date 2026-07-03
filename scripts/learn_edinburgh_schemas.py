"""Pre-learn the schema/header semantics of the Edinburgh Excel corpus.

The 122 Excel evidence files are heterogeneous financial workbooks (cost
breakdowns, GMP workbooks, QRA, risk registers, forecasts) — unlike the demo's
three fixed schemas, each is its own shape. Before ingest we therefore *learn*
each file's structure: headers, inferred dtypes, and a column→meaning map (via
the construction jargon dictionary). The report lets a human eyeball what will
become queryable and flags files that need attention (junk headers, empty
sheets, multi-table sheets) — and the same per-column meaning is what feeds the
catalog enrichment / SQL column-validation at ingest time.

This is a READ-ONLY diagnosis — it writes a report, it does not ingest.

Run:
    PYTHONPATH=. python scripts/learn_edinburgh_schemas.py
    PYTHONPATH=. python scripts/learn_edinburgh_schemas.py --dir data/edinburgh_tram/excels --report data/edinburgh_tram/excel_schema_report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

UNNAMED_RE = re.compile(r"^(unnamed|column)[\s:_]*\d*$", re.IGNORECASE)
FINANCIAL_HINTS = ("cost", "price", "total", "amount", "budget", "forecast", "value",
                   "£", "gbp", "rate", "qty", "quantity", "risk", "gmp", "boq", "ipc",
                   "variance", "actual", "estimate", "contingency", "fee")


def _infer_dtype(series: pd.Series) -> str:
    dt = str(series.dtype)
    if "datetime" in dt:
        return "date"
    if "int" in dt:
        return "int"
    if "float" in dt:
        return "float"
    if "bool" in dt:
        return "bool"
    sample = series.dropna().astype(str).head(8)
    if len(sample):
        # numeric-looking strings (currency / thousands separators)
        nums = sum(bool(re.fullmatch(r"[-+]?[£$€]?[\d,]*\.?\d+%?", s.strip())) for s in sample)
        if nums >= max(1, int(0.7 * len(sample))):
            return "numeric_str"
        try:
            pd.to_datetime(sample, errors="raise")
            return "date"
        except (ValueError, TypeError):
            pass
    return "string"


def _header_quality(cols: list[str]) -> dict[str, Any]:
    n = len(cols)
    junk = sum(1 for c in cols if not str(c).strip() or UNNAMED_RE.match(str(c).strip()))
    return {"cols": n, "junk_headers": junk,
            "junk_ratio": round(junk / n, 2) if n else 1.0}


def _diagnose_sheet(df: pd.DataFrame, jargon) -> dict[str, Any]:
    cols = [str(c) for c in df.columns]
    quality = _header_quality(cols)
    columns = []
    fin_signals = 0
    for c in cols:
        norm, meaning = ("", None)
        try:
            norm, meaning = jargon.normalize_column_name(c)
        except Exception:
            pass
        low = c.lower()
        is_fin = any(h in low for h in FINANCIAL_HINTS)
        fin_signals += is_fin
        columns.append({
            "name": c,
            "dtype": _infer_dtype(df[c]) if c in df.columns else "string",
            "meaning": meaning or "",          # jargon expansion ("EOT" -> "Extension of Time")
            "normalized": norm,
            "financial": is_fin,
        })
    return {
        "rows": int(len(df)),
        "cols": quality["cols"],
        "junk_ratio": quality["junk_ratio"],
        "financial_cols": fin_signals,
        "columns": columns,
        # A sheet is "clean tabular" if it has real headers and at least one row.
        "clean_tabular": quality["junk_ratio"] <= 0.4 and len(df) >= 1 and quality["cols"] >= 2,
    }


def _read_sheets(path: Path) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    try:
        xls = pd.ExcelFile(path)  # engine auto: openpyxl (.xlsx) / xlrd (.xls)
    except Exception as e:
        raise RuntimeError(f"open failed: {e}")
    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(path, sheet_name=sheet)
            if not df.empty:
                out[sheet] = df
        except Exception as e:
            out[f"{sheet} (UNREADABLE)"] = pd.DataFrame({"_error": [str(e)[:120]]})
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", default="data/edinburgh_tram/excels")
    p.add_argument("--report", default="data/edinburgh_tram/excel_schema_report.json")
    args = p.parse_args()

    base = (ROOT / args.dir).resolve()
    files = sorted([f for f in base.glob("*") if f.suffix.lower() in (".xls", ".xlsx")]) \
        if base.exists() else []
    if not files:
        print(f"No Excel files in {base}", file=sys.stderr)
        return 2

    from src.jargon_manager import get_jargon_manager
    jargon = get_jargon_manager()

    reports: list[dict[str, Any]] = []
    n_clean = n_unreadable = n_attention = 0
    all_meanings: dict[str, str] = {}
    for f in files:
        try:
            sheets = _read_sheets(f)
        except Exception as e:
            n_unreadable += 1
            reports.append({"file": f.name, "ext": f.suffix.lower(), "error": str(e), "sheets": []})
            print(f"  ✗ {f.name}: {e}")
            continue
        sheet_reports = []
        for name, df in sheets.items():
            d = _diagnose_sheet(df, jargon)
            d["sheet"] = name
            sheet_reports.append(d)
            for col in d["columns"]:
                if col["meaning"]:
                    all_meanings[col["name"]] = col["meaning"]
        clean = any(s.get("clean_tabular") for s in sheet_reports)
        n_clean += clean
        if not clean:
            n_attention += 1
        reports.append({"file": f.name, "ext": f.suffix.lower(),
                        "sheet_count": len(sheet_reports), "any_clean": clean,
                        "sheets": sheet_reports})
        flag = "✓" if clean else "⚠"
        tops = ", ".join(f"{s['sheet']}({s['rows']}r×{s['cols']}c"
                         f"{',fin' if s['financial_cols'] else ''})" for s in sheet_reports[:3])
        print(f"  {flag} {f.name}  [{tops}]")

    out = (ROOT / args.report).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "scanned_dir": str(base),
        "total_files": len(files),
        "clean_tabular_files": n_clean,
        "needs_attention": n_attention,
        "unreadable": n_unreadable,
        "distinct_jargon_meanings": len(all_meanings),
        "files": reports,
    }, indent=2, default=str), encoding="utf-8")

    print(f"\n{'-'*60}")
    print(f"Files scanned:        {len(files)}")
    print(f"Clean tabular:        {n_clean}")
    print(f"Needs attention:      {n_attention}")
    print(f"Unreadable:           {n_unreadable}")
    print(f"Jargon meanings hit:  {len(all_meanings)}  (e.g. {dict(list(all_meanings.items())[:5])})")
    print(f"Report:               {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
