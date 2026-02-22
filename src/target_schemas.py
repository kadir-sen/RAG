"""
Target Schemas - Define standardized output formats for data conversion.
Each company's Excel files get converted to one of these target schemas.
Schemas are stored as JSON files in storage/schemas/ directory.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

import pandas as pd

from .config import SCHEMAS_DIR
from .logger import logger


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
            # Check column exists (by name or alias)
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

        # Check optional columns
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
        """Load all schemas from JSON files."""
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
        """List all available schemas."""
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
        """Get a schema by ID."""
        return self._schemas.get(schema_id)

    def register_schema(self, schema: TargetSchema) -> None:
        """Register a new schema and save to disk."""
        self._schemas[schema.schema_id] = schema
        self._save_schema(schema)
        logger.info(f"[Schemas] Registered schema: {schema.schema_id}")

    def _save_schema(self, schema: TargetSchema) -> None:
        """Save a schema to JSON file."""
        data = {
            "schema_id": schema.schema_id,
            "name": schema.name,
            "description": schema.description,
            "columns": [asdict(c) for c in schema.columns],
        }
        path = self.schemas_dir / f"{schema.schema_id}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def remove_schema(self, schema_id: str) -> None:
        """Remove a schema."""
        if schema_id in self._schemas:
            del self._schemas[schema_id]
            path = self.schemas_dir / f"{schema_id}.json"
            if path.exists():
                path.unlink()
            logger.info(f"[Schemas] Removed schema: {schema_id}")

    def get_all_descriptions(self) -> str:
        """Get all schema descriptions for LLM prompts."""
        if not self._schemas:
            return "No target schemas defined."
        return "\n\n---\n\n".join(
            s.to_prompt_description() for s in self._schemas.values()
        )


# Singleton
_registry: Optional[TargetSchemaRegistry] = None


def get_target_schemas() -> TargetSchemaRegistry:
    """Get or create TargetSchemaRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = TargetSchemaRegistry()
    return _registry
