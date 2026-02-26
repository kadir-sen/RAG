"""
Bootstrap target schemas from formatlar/*.xlsx files.

Reads each Excel file in formatlar/ and creates corresponding
JSON schema files in storage/schemas/.

One-time script: run once, then edit JSONs manually as needed.

Usage:
    python -m scripts.bootstrap_schemas
"""
import json
import sys
from pathlib import Path

import pandas as pd

# Project root
ROOT = Path(__file__).parent.parent
FORMATLAR_DIR = ROOT / "formatlar"
SCHEMAS_DIR = ROOT / "storage" / "schemas"


def infer_dtype(series: pd.Series) -> str:
    """Infer schema dtype from pandas Series."""
    pd_dtype = str(series.dtype)

    if "datetime" in pd_dtype:
        return "date"
    if "int" in pd_dtype:
        return "int"
    if "float" in pd_dtype:
        return "float"
    if "bool" in pd_dtype:
        return "bool"

    # Check if string column looks like dates
    sample = series.dropna().head(5)
    if len(sample) > 0:
        try:
            pd.to_datetime(sample)
            return "date"
        except (ValueError, TypeError):
            pass

    return "string"


def create_schema_from_excel(xlsx_path: Path) -> dict:
    """Create a schema dict from an Excel file."""
    stem = xlsx_path.stem
    schema_id = "_".join(stem.lower().split())

    # Read first sheet to get structure
    xls = pd.ExcelFile(xlsx_path)
    df = pd.read_excel(xlsx_path, sheet_name=xls.sheet_names[0])

    columns = []
    for col in df.columns:
        if col.startswith("_"):
            continue
        col_def = {
            "name": col,
            "dtype": infer_dtype(df[col]),
            "required": True,
            "description": "",
            "aliases": [col.lower().replace(" ", "_")],
        }
        columns.append(col_def)

    schema = {
        "schema_id": schema_id,
        "name": stem,
        "description": f"Auto-generated schema from {xlsx_path.name}",
        "columns": columns,
    }
    return schema


def main():
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)

    xlsx_files = list(FORMATLAR_DIR.glob("*.xlsx"))
    if not xlsx_files:
        print(f"No .xlsx files found in {FORMATLAR_DIR}")
        sys.exit(1)

    for xlsx_path in xlsx_files:
        schema = create_schema_from_excel(xlsx_path)
        out_path = SCHEMAS_DIR / f"{schema['schema_id']}.json"

        if out_path.exists():
            print(f"  SKIP (exists): {out_path.name}")
            continue

        out_path.write_text(
            json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  Created: {out_path.name} ({len(schema['columns'])} columns)")

    print("Done.")


if __name__ == "__main__":
    main()
