"""
Schema Converter - Target schema registry and format conversion pipeline.

Defines standardized output formats for data conversion (Equipment Log, IPC,
Manpower Production). Incoming Excel/CSV files are matched against known schemas,
columns are renamed/typed, and data is validated — all without LLM calls.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

import pandas as pd

from .config import SCHEMAS_DIR
from .logger import logger
from .table_normalizer import parse_mixed_datetime


# ── Schema Definitions ──────────────────────────────────────

@dataclass
class ColumnDef:
    """Definition of a single column in a target schema."""
    name: str
    dtype: str  # "string" | "float" | "int" | "date" | "bool"
    required: bool = True
    description: str = ""
    aliases: List[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of validating a DataFrame against a schema."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    matched_columns: int = 0
    total_required: int = 0


@dataclass
class TargetSchema:
    """A target schema that source data gets converted into."""
    schema_id: str
    name: str
    description: str
    columns: List[ColumnDef] = field(default_factory=list)

    def validate(self, df: pd.DataFrame) -> ValidationResult:
        """Validate a DataFrame against this schema."""
        result = ValidationResult(valid=True)

        df_cols_lower = {c.lower().strip(): c for c in df.columns}
        required_cols = [c for c in self.columns if c.required]
        result.total_required = len(required_cols)

        for col_def in required_cols:
            found = col_def.name.lower() in df_cols_lower
            if not found:
                for alias in col_def.aliases:
                    if alias.lower() in df_cols_lower:
                        found = True
                        break
            if found:
                result.matched_columns += 1
            else:
                result.errors.append(f"Missing required column: {col_def.name}")
                result.valid = False

        for col_def in self.columns:
            if not col_def.required:
                col_lower = col_def.name.lower()
                if col_lower in df_cols_lower:
                    result.matched_columns += 1

        return result

    def to_prompt_description(self) -> str:
        """Format schema as text description for LLM prompts."""
        lines = [f"Target Schema: {self.name}"]
        lines.append(f"Description: {self.description}")
        lines.append(f"Schema ID: {self.schema_id}")
        lines.append("")
        lines.append("Columns:")
        for col in self.columns:
            req = "REQUIRED" if col.required else "optional"
            desc = f" - {col.description}" if col.description else ""
            aliases = f" (aliases: {', '.join(col.aliases)})" if col.aliases else ""
            lines.append(f"  - {col.name} ({col.dtype}, {req}){desc}{aliases}")
        return "\n".join(lines)


# ── Schema Registry ─────────────────────────────────────────

class TargetSchemaRegistry:
    """
    Registry for target schemas.
    Loads schemas from storage/schemas/*.json files.
    """

    def __init__(self, schemas_dir: Optional[Path] = None):
        self.schemas_dir = schemas_dir or SCHEMAS_DIR
        self.schemas_dir.mkdir(parents=True, exist_ok=True)
        self._schemas: Dict[str, TargetSchema] = {}
        self._load_schemas()

    def _load_schemas(self) -> None:
        for json_file in self.schemas_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                columns = [ColumnDef(**c) for c in data.get("columns", [])]
                schema = TargetSchema(
                    schema_id=data["schema_id"],
                    name=data["name"],
                    description=data.get("description", ""),
                    columns=columns,
                )
                self._schemas[schema.schema_id] = schema
                logger.info(f"[Schemas] Loaded schema: {schema.schema_id}")
            except Exception as e:
                logger.warning(f"[Schemas] Failed to load {json_file.name}: {e}")

    def list_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "schema_id": s.schema_id,
                "name": s.name,
                "description": s.description,
                "column_count": len(s.columns),
            }
            for s in self._schemas.values()
        ]

    def get_schema(self, schema_id: str) -> Optional[TargetSchema]:
        return self._schemas.get(schema_id)

    def register_schema(self, schema: TargetSchema) -> None:
        self._schemas[schema.schema_id] = schema
        self._save_schema(schema)
        logger.info(f"[Schemas] Registered schema: {schema.schema_id}")

    def _save_schema(self, schema: TargetSchema) -> None:
        data = {
            "schema_id": schema.schema_id,
            "name": schema.name,
            "description": schema.description,
            "columns": [asdict(c) for c in schema.columns],
        }
        path = self.schemas_dir / f"{schema.schema_id}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def remove_schema(self, schema_id: str) -> None:
        if schema_id in self._schemas:
            del self._schemas[schema_id]
            path = self.schemas_dir / f"{schema_id}.json"
            if path.exists():
                path.unlink()
            logger.info(f"[Schemas] Removed schema: {schema_id}")

    def get_all_descriptions(self) -> str:
        if not self._schemas:
            return "No target schemas defined."
        return "\n\n---\n\n".join(
            s.to_prompt_description() for s in self._schemas.values()
        )


_registry: Optional[TargetSchemaRegistry] = None


def get_target_schemas() -> TargetSchemaRegistry:
    """Get or create TargetSchemaRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = TargetSchemaRegistry()
    return _registry


# ── Format Converter ────────────────────────────────────────

@dataclass
class ConversionResult:
    """Result of a format conversion attempt."""
    success: bool
    df: Optional[pd.DataFrame] = None
    target_schema: Optional[str] = None
    converter_id: Optional[str] = None
    company_id: Optional[str] = None
    validation_errors: List[str] = field(default_factory=list)
    generated: bool = False
    sheet_name: Optional[str] = None


class FormatConverter:
    """
    Direct schema validator for Excel/CSV files.
    All incoming files are expected to match one of the 3 target schemas.
    Multi-sheet files produce one result per sheet.
    """

    def __init__(self):
        self.schemas = get_target_schemas()

    def process_excel(self, file_path: str) -> List[ConversionResult]:
        """
        Process an Excel/CSV file. Returns a list of ConversionResults
        (one per matched sheet). Empty list if nothing matches.
        """
        results = []

        # Step 1: Pre-built extractors (DPR, legacy Invoice)
        try:
            from .extractors import match_extractor, run_extractor

            matches = match_extractor(file_path)
            if matches:
                for extractor_name, target_schema in matches:
                    df = run_extractor(extractor_name, file_path)
                    if df is not None and not df.empty:
                        logger.info(f"[FormatConverter] Pre-built extractor: "
                                    f"{extractor_name} -> {target_schema}")
                        results.append(ConversionResult(
                            success=True,
                            df=df,
                            target_schema=target_schema,
                            converter_id=f"builtin_{extractor_name}",
                            generated=False,
                        ))
                if results:
                    return results
        except Exception as e:
            logger.info(f"[FormatConverter] Pre-built extractor check skipped: {e}")

        # Step 2: Direct schema validation
        try:
            sheets = self._read_sheets(file_path)
        except Exception as e:
            logger.warning(f"[FormatConverter] Cannot read {file_path}: {e}")
            return []

        if not sheets:
            return []

        for sheet_name, df in sheets.items():
            if df.empty or len(df.columns) == 0:
                continue

            schema_id = self._match_schema(df)
            if not schema_id:
                logger.info(f"[FormatConverter] Sheet '{sheet_name}' — no schema match "
                            f"(columns: {list(df.columns)[:5]}...)")
                continue

            clean_df = self._cast_types(df, schema_id)
            clean_df = clean_df.dropna(how="all")

            if clean_df.empty:
                continue

            validation_warnings = self._validate_schema_data(clean_df, schema_id)
            if validation_warnings:
                for w in validation_warnings:
                    logger.warning(f"[FormatConverter] {sheet_name}: {w}")

            # Preserve sheet name as a column for period filtering
            if sheet_name and '_sheet_name' not in clean_df.columns:
                clean_df['_sheet_name'] = sheet_name

            logger.info(f"[FormatConverter] Sheet '{sheet_name}' -> {schema_id} "
                        f"({len(clean_df)} rows)")

            results.append(ConversionResult(
                success=True,
                df=clean_df,
                target_schema=schema_id,
                converter_id=f"direct_{schema_id}",
                company_id=sheet_name,
                sheet_name=sheet_name,
                generated=False,
                validation_errors=validation_warnings,
            ))

        return results

    def _read_sheets(self, file_path: str) -> dict:
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            return {"Sheet1": pd.read_csv(file_path)}
        elif ext in (".xlsx", ".xls"):
            xls = pd.ExcelFile(file_path)
            sheets = {}
            for sheet in xls.sheet_names:
                try:
                    df = pd.read_excel(file_path, sheet_name=sheet)
                    if not df.empty:
                        sheets[sheet] = df
                except Exception as e:
                    logger.warning(f"[FormatConverter] Cannot read sheet '{sheet}': {e}")
            return sheets
        return {}

    def _match_schema(self, df: pd.DataFrame) -> Optional[str]:
        df_cols = {c.lower().strip() for c in df.columns}
        best_match = None
        best_ratio = 0.0

        for schema_info in self.schemas.list_schemas():
            schema = self.schemas.get_schema(schema_info["schema_id"])
            if not schema:
                continue
            required = [c for c in schema.columns if c.required]
            if not required:
                continue

            matched = 0
            for col_def in required:
                if col_def.name.lower() in df_cols:
                    matched += 1
                elif any(alias.lower() in df_cols for alias in col_def.aliases):
                    matched += 1

            ratio = matched / len(required)
            if ratio >= 0.7 and ratio > best_ratio:
                best_ratio = ratio
                best_match = schema.schema_id

        return best_match

    def _cast_types(self, df: pd.DataFrame, schema_id: str) -> pd.DataFrame:
        schema = self.schemas.get_schema(schema_id)
        if not schema:
            return df
        df = df.copy()

        for col_def in schema.columns:
            col_name = col_def.name
            actual_col = None
            for c in df.columns:
                if c.lower().strip() == col_name.lower():
                    actual_col = c
                    break
            if actual_col is None:
                for alias in col_def.aliases:
                    for c in df.columns:
                        if c.lower().strip() == alias.lower():
                            actual_col = c
                            break
                    if actual_col:
                        break

            if actual_col is None:
                continue

            if actual_col != col_name:
                df = df.rename(columns={actual_col: col_name})

            if col_def.dtype == "date":
                df[col_name] = parse_mixed_datetime(df[col_name])
            elif col_def.dtype == "float":
                df[col_name] = pd.to_numeric(df[col_name], errors="coerce")
            elif col_def.dtype == "int":
                df[col_name] = pd.to_numeric(df[col_name], errors="coerce")
            elif col_def.dtype == "string":
                df[col_name] = df[col_name].astype(str).str.strip()
                df[col_name] = df[col_name].replace({"nan": "", "None": ""})

        return df

    _SCHEMA_VALIDATIONS = {
        "equipment_log": [
            ("Estimated Machinery Hours", ">=0", "Hours must be non-negative"),
        ],
        "manpower_production": [
            ("Number of Workers", ">0", "Worker count must be positive"),
            ("Quantification", ">=0", "Quantity must be non-negative"),
        ],
        "ipc_sample": [
            ("Cumulative %", "0-150", "Cumulative % should be 0-150"),
            ("Unit Rate", ">=0", "Unit Rate must be non-negative"),
            ("Total BOQ Amount", ">=0", "Total BOQ must be non-negative"),
        ],
    }

    def _validate_schema_data(self, df: pd.DataFrame, schema_id: str) -> List[str]:
        rules = self._SCHEMA_VALIDATIONS.get(schema_id, [])
        warnings = []
        for col_name, rule, message in rules:
            if col_name not in df.columns:
                continue
            series = pd.to_numeric(df[col_name], errors="coerce").dropna()
            if series.empty:
                continue

            bad_count = 0
            if rule == ">=0":
                bad_count = (series < 0).sum()
            elif rule == ">0":
                bad_count = (series <= 0).sum()
            elif rule == "0-150":
                bad_count = ((series < 0) | (series > 150)).sum()

            if bad_count > 0:
                warnings.append(f"{message}: {bad_count} invalid values in '{col_name}'")
        return warnings


_converter: Optional[FormatConverter] = None


def get_format_converter() -> FormatConverter:
    """Get or create FormatConverter singleton."""
    global _converter
    if _converter is None:
        _converter = FormatConverter()
    return _converter
