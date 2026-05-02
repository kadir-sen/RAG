#!/usr/bin/env python3
"""
Validate registered target schemas against real Excel/CSV files.

Usage:
    python3 scripts/validate_schemas.py
    python3 scripts/validate_schemas.py --path data/tables --verbose
    python3 scripts/validate_schemas.py --report data/schema_validation_report.json

Output:
    - Per-file: best matched schema, ratio, sheet count, row count
    - Per-schema: matching file count, average ratio, files
    - JSON report saved for programmatic consumption (admin UI)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.schema_converter import get_format_converter, get_target_schemas  # noqa: E402
from src.extractors import match_extractor  # noqa: E402


SCHEMA_IDS_DEFAULT = ["manpower_production", "equipment_log", "ipc_sample"]


def _read_sheets(file_path: Path) -> dict[str, pd.DataFrame]:
    ext = file_path.suffix.lower()
    if ext == ".csv":
        return {"Sheet1": pd.read_csv(file_path)}
    if ext in (".xlsx", ".xls"):
        xls = pd.ExcelFile(file_path)
        out = {}
        for sheet in xls.sheet_names:
            try:
                df = pd.read_excel(file_path, sheet_name=sheet)
                if not df.empty:
                    out[sheet] = df
            except Exception as e:
                print(f"  ! Cannot read sheet {sheet!r}: {e}", file=sys.stderr)
        return out
    return {}


def _match_against_schema(df: pd.DataFrame, schema) -> dict[str, Any]:
    df_cols = {str(c).lower().strip() for c in df.columns}
    required = [c for c in schema.columns if c.required]
    optional = [c for c in schema.columns if not c.required]
    matched_required: list[str] = []
    missing_required: list[str] = []
    for col_def in required:
        if col_def.name.lower() in df_cols:
            matched_required.append(col_def.name)
        elif any(a.lower() in df_cols for a in col_def.aliases):
            matched_required.append(col_def.name)
        else:
            missing_required.append(col_def.name)
    matched_optional = sum(
        1 for c in optional
        if c.name.lower() in df_cols or any(a.lower() in df_cols for a in c.aliases)
    )
    ratio = (len(matched_required) / len(required)) if required else 0.0
    return {
        "schema_id": schema.schema_id,
        "ratio": round(ratio, 3),
        "matched_required": matched_required,
        "missing_required": missing_required,
        "matched_optional": matched_optional,
        "total_required": len(required),
    }


def _diagnose_file(file_path: Path, schemas, verbose: bool) -> dict[str, Any]:
    extractor_matches = match_extractor(str(file_path))
    sheets = _read_sheets(file_path)
    sheet_reports = []
    for name, df in sheets.items():
        per_schema = [_match_against_schema(df, schemas.get_schema(sid))
                      for sid in SCHEMA_IDS_DEFAULT
                      if schemas.get_schema(sid)]
        best = max(per_schema, key=lambda r: r["ratio"]) if per_schema else None
        will_match = bool(best and best["ratio"] >= 0.7)
        sheet_reports.append({
            "sheet": name,
            "rows": int(len(df)),
            "cols": int(len(df.columns)),
            "columns": [str(c) for c in df.columns] if verbose else None,
            "best_schema": best["schema_id"] if best else None,
            "best_ratio": best["ratio"] if best else 0.0,
            "missing_required": best["missing_required"] if best else [],
            "will_register": will_match,
            "all_matches": per_schema,
        })
    any_register = any(s["will_register"] for s in sheet_reports)
    return {
        "file": file_path.name,
        "path": str(file_path),
        "extractor_matches": extractor_matches,
        "sheets": sheet_reports,
        "will_register": any_register or bool(extractor_matches),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--path", default="data/tables", help="Directory to scan")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--report", default="data/schema_validation_report.json")
    args = p.parse_args()

    base = (ROOT / args.path).resolve()
    if not base.exists():
        print(f"ERROR: path not found: {base}", file=sys.stderr)
        sys.exit(2)

    files = sorted(
        [f for f in base.iterdir() if f.suffix.lower() in (".xlsx", ".xls", ".csv")]
    )
    if not files:
        print(f"No Excel/CSV files in {base}")
        sys.exit(0)

    schemas = get_target_schemas()
    registered = [s["schema_id"] for s in schemas.list_schemas()]
    print(f"Registered schemas: {registered}")
    print(f"Scanning {len(files)} files in {base}\n")

    reports: list[dict[str, Any]] = []
    for f in files:
        rep = _diagnose_file(f, schemas, args.verbose)
        reports.append(rep)
        flag = "✓" if rep["will_register"] else "✗"
        if rep["sheets"]:
            best_per_sheet = ", ".join(
                f"{s['sheet']}->{s['best_schema'] or '-'}({s['best_ratio']})"
                for s in rep["sheets"]
            )
        else:
            best_per_sheet = "no readable sheets"
        extra = f"  extractor={rep['extractor_matches']}" if rep["extractor_matches"] else ""
        print(f"  {flag} {f.name}  [{best_per_sheet}]{extra}")

    # Summary
    total = len(reports)
    will = sum(1 for r in reports if r["will_register"])
    print(f"\n{'-' * 60}")
    print(f"Total files: {total}")
    print(f"Will register: {will}")
    print(f"Will NOT register: {total - will}")

    schema_counts: dict[str, int] = {}
    for r in reports:
        for s in r["sheets"]:
            if s["will_register"] and s["best_schema"]:
                schema_counts[s["best_schema"]] = schema_counts.get(s["best_schema"], 0) + 1
    print("\nPer-schema sheet matches:")
    for sid in registered:
        print(f"  {sid}: {schema_counts.get(sid, 0)} sheets")

    # Persist
    out_path = (ROOT / args.report).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "scanned_path": str(base),
        "total_files": total,
        "will_register": will,
        "schema_counts": schema_counts,
        "files": reports,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nReport saved: {out_path}")


if __name__ == "__main__":
    main()
