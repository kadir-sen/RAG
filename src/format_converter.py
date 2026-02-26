"""
Format Converter - LLM agent that generates Python converter code
for transforming company-specific Excel formats into standardized schemas.

Main entry point for the data conversion pipeline.
All LLM calls go through llm_client.py (caching, cost tracking, retries).
"""
import json
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

import pandas as pd

from .config import CONVERTER_CONFIDENCE_THRESHOLD
from .converter_registry import get_converter_registry, ConverterEntry
from .target_schemas import get_target_schemas, TargetSchema
from .code_sandbox import validate_converter_code, execute_converter_code
from .logger import logger


@dataclass
class ConversionResult:
    """Result of a format conversion attempt."""
    success: bool
    df: Optional[pd.DataFrame] = None
    target_schema: Optional[str] = None
    converter_id: Optional[str] = None
    company_id: Optional[str] = None
    validation_errors: List[str] = field(default_factory=list)
    generated: bool = False  # True if converter was newly generated


class FormatConverter:
    """
    LLM-powered format converter.
    Detects company format, generates converter code, and transforms data.
    """

    def __init__(self):
        self.registry = get_converter_registry()
        self.schemas = get_target_schemas()

    def process_excel(self, file_path: str) -> Optional[ConversionResult]:
        """
        Main entry point: try to convert an Excel/CSV file.

        Flow:
        1. Read sample data from file
        2. Match company (filename + column fingerprint)
        3. If matched → run saved converter
        4. If not → detect target schema → generate converter
        5. If nothing works → return None (fallback to existing pipeline)
        """
        try:
            # Read sample data
            sample_df = self._read_sample(file_path)
            if sample_df is None or sample_df.empty:
                logger.info("[FormatConverter] Could not read sample data, skipping")
                return None

            # Check if schemas are defined
            available_schemas = self.schemas.list_schemas()
            if not available_schemas:
                logger.info("[FormatConverter] No target schemas defined, skipping")
                return None

            # Try to match existing company converter
            df_columns = list(sample_df.columns)
            company_id = self.registry.match_company(file_path, df_columns)

            if company_id:
                result = self._run_saved_converter(file_path, company_id)
                if result and result.success:
                    return result
                logger.warning(f"[FormatConverter] Saved converter failed for {company_id}, "
                               "trying generation")

            # Detect target schema
            schema_result = self._detect_target_schema(file_path, sample_df)
            if not schema_result:
                logger.info("[FormatConverter] No matching target schema found")
                return None

            schema_id, confidence = schema_result
            if confidence < CONVERTER_CONFIDENCE_THRESHOLD:
                logger.info(f"[FormatConverter] Schema confidence too low: "
                            f"{confidence:.2f} < {CONVERTER_CONFIDENCE_THRESHOLD}")
                return None

            # Generate converter
            result = self._generate_converter(file_path, sample_df, schema_id)
            return result

        except Exception as e:
            logger.error(f"[FormatConverter] Error processing {file_path}: {e}")
            return None

    def _read_sample(self, file_path: str) -> Optional[pd.DataFrame]:
        """Read sample data from file (all sheets concatenated, up to 20 rows)."""
        ext = Path(file_path).suffix.lower()
        try:
            if ext == ".csv":
                df = pd.read_csv(file_path, nrows=20)
            elif ext in (".xlsx", ".xls"):
                xls = pd.ExcelFile(file_path)
                if len(xls.sheet_names) == 1:
                    df = pd.read_excel(file_path, nrows=20)
                else:
                    # Multi-sheet: concat all with _sheet_name column
                    frames = []
                    for sheet in xls.sheet_names:
                        sdf = pd.read_excel(file_path, sheet_name=sheet, nrows=20)
                        if not sdf.empty:
                            sdf["_sheet_name"] = sheet
                            frames.append(sdf)
                    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            else:
                return None

            # Skip completely empty DataFrames
            if df.empty or len(df.columns) == 0:
                return None

            return df
        except Exception as e:
            logger.warning(f"[FormatConverter] Cannot read sample from {file_path}: {e}")
            return None

    def _read_file(self, file_path: str) -> Optional[pd.DataFrame]:
        """Read full file (all sheets concatenated for xlsx)."""
        ext = Path(file_path).suffix.lower()
        try:
            if ext == ".csv":
                return pd.read_csv(file_path)
            elif ext in (".xlsx", ".xls"):
                xls = pd.ExcelFile(file_path)
                if len(xls.sheet_names) == 1:
                    return pd.read_excel(file_path)
                # Multi-sheet: concat all with _sheet_name column
                frames = []
                for sheet in xls.sheet_names:
                    sdf = pd.read_excel(file_path, sheet_name=sheet)
                    if not sdf.empty:
                        sdf["_sheet_name"] = sheet
                        frames.append(sdf)
                return pd.concat(frames, ignore_index=True) if frames else None
            return None
        except Exception as e:
            logger.warning(f"[FormatConverter] Cannot read file {file_path}: {e}")
            return None

    def _detect_target_schema(
        self, file_path: str, sample_df: pd.DataFrame
    ) -> Optional[Tuple[str, float]]:
        """
        Use LLM to detect which target schema matches this file.

        Returns:
            (schema_id, confidence) or None
        """
        from .llm_client import generate_json

        available = self.schemas.get_all_descriptions()
        if available == "No target schemas defined.":
            return None

        # Build file description
        columns_info = []
        for col in sample_df.columns:
            dtype = str(sample_df[col].dtype)
            sample_vals = sample_df[col].dropna().head(3).tolist()
            columns_info.append(f"  - {col} (dtype: {dtype}, samples: {sample_vals})")

        file_desc = (
            f"File: {Path(file_path).name}\n"
            f"Rows: {len(sample_df)}\n"
            f"Columns ({len(sample_df.columns)}):\n" + "\n".join(columns_info)
        )

        prompt = f"""Analyze this Excel/CSV file and determine which target schema it should be converted to.

SOURCE FILE:
{file_desc}

AVAILABLE TARGET SCHEMAS:
{available}

Return a JSON object with:
- "schema_id": the matching schema ID (or null if no match)
- "confidence": float 0.0 to 1.0
- "reasoning": brief explanation

If the file doesn't clearly match any schema, set schema_id to null and confidence to 0.0.
"""

        system = "You are a data format analyst. Match source data to target schemas accurately."

        try:
            resp = generate_json(prompt, system=system, cache_key=None, ttl_s=300)
            parsed = resp.raw if isinstance(resp.raw, dict) else json.loads(resp.text)

            schema_id = parsed.get("schema_id")
            confidence = float(parsed.get("confidence", 0.0))

            if schema_id and self.schemas.get_schema(schema_id):
                logger.info(f"[FormatConverter] Detected schema: {schema_id} "
                            f"(confidence: {confidence:.2f})")
                return (schema_id, confidence)
            return None
        except Exception as e:
            logger.warning(f"[FormatConverter] Schema detection failed: {e}")
            return None

    def _generate_converter(
        self,
        file_path: str,
        sample_df: pd.DataFrame,
        target_schema_id: str,
    ) -> Optional[ConversionResult]:
        """
        Generate converter code using LLM, test it, and save if successful.

        Uses self-correction pattern: try once, if fails, retry with error context.
        """
        from .llm_client import generate_text

        schema = self.schemas.get_schema(target_schema_id)
        if not schema:
            return None

        # Build source description
        source_desc = self._build_source_description(sample_df)
        target_desc = schema.to_prompt_description()

        prompt = self._build_generation_prompt(source_desc, target_desc)
        system = (
            "You are a Python data engineer specializing in construction project data. "
            "Write clean, correct pandas code. "
            "Always define: def convert(df: pd.DataFrame) -> pd.DataFrame. "
            "Only use pandas, numpy, re, datetime, math. "
            "Handle missing values gracefully. Return a clean DataFrame. "
            "If the input has a '_sheet_name' column, it means data was concatenated "
            "from multiple Excel sheets - preserve or transform this column as needed. "
            "Common construction terms: BOQ, IPC, MEP, DPR, VO, EOT."
        )

        # Attempt 1
        code = self._extract_code(generate_text(prompt, system=system, temperature=0.1).text)
        if not code:
            logger.warning("[FormatConverter] LLM did not produce valid code")
            return None

        result = self._test_converter(code, file_path, schema)
        if result and result.success:
            self._save_converter(file_path, sample_df, target_schema_id, code)
            result.generated = True
            return result

        # Attempt 2: self-correction
        error_msg = "; ".join(result.validation_errors) if result else "Code execution failed"
        logger.info(f"[FormatConverter] Attempt 1 failed: {error_msg}. Retrying with correction.")

        retry_prompt = f"""{prompt}

PREVIOUS ATTEMPT FAILED with this error:
{error_msg}

Fix the code and try again. The previous code was:
```python
{code}
```
"""
        code2 = self._extract_code(generate_text(retry_prompt, system=system, temperature=0.2).text)
        if not code2:
            return None

        result2 = self._test_converter(code2, file_path, schema)
        if result2 and result2.success:
            self._save_converter(file_path, sample_df, target_schema_id, code2)
            result2.generated = True
            return result2

        logger.warning("[FormatConverter] Both attempts failed, returning None for fallback")
        return None

    def _build_source_description(self, df: pd.DataFrame) -> str:
        """Build a detailed description of the source DataFrame."""
        lines = [f"Source DataFrame: {len(df)} rows x {len(df.columns)} columns", ""]
        for col in df.columns:
            dtype = str(df[col].dtype)
            non_null = df[col].notna().sum()
            samples = df[col].dropna().head(3).tolist()
            lines.append(f"  Column: '{col}' | dtype: {dtype} | non-null: {non_null}/{len(df)} | samples: {samples}")
        return "\n".join(lines)

    def _build_generation_prompt(self, source_desc: str, target_desc: str) -> str:
        """Build the code generation prompt."""
        return f"""Write a Python function that converts the source Excel data to the target schema.

SOURCE FORMAT:
{source_desc}

TARGET FORMAT:
{target_desc}

Requirements:
1. Define exactly: def convert(df: pd.DataFrame) -> pd.DataFrame
2. Map source columns to target columns (rename, transform as needed)
3. Handle date parsing with pd.to_datetime(errors='coerce')
4. Convert numeric columns with pd.to_numeric(errors='coerce')
5. Strip whitespace from string columns
6. Drop completely empty rows
7. Return only the target columns
8. Import only: pandas as pd, numpy as np, re, datetime, math

Return ONLY the Python code, wrapped in ```python``` markers.
"""

    def _extract_code(self, llm_response: str) -> Optional[str]:
        """Extract Python code from LLM response."""
        import re as _re

        # Try to find code block
        match = _re.search(r'```(?:python)?\s*\n(.*?)```', llm_response, _re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fallback: look for def convert
        if "def convert(" in llm_response:
            lines = llm_response.split("\n")
            code_lines = []
            in_func = False
            for line in lines:
                if "def convert(" in line:
                    in_func = True
                if in_func:
                    code_lines.append(line)
            return "\n".join(code_lines) if code_lines else None

        return None

    def _test_converter(
        self, code: str, file_path: str, schema: TargetSchema
    ) -> Optional[ConversionResult]:
        """Test converter code against actual file data."""
        result = ConversionResult(success=False, target_schema=schema.schema_id)

        # Validate code safety
        is_safe, error = validate_converter_code(code)
        if not is_safe:
            result.validation_errors.append(f"Unsafe code: {error}")
            return result

        # Read full file (multi-sheet aware)
        try:
            df = self._read_file(file_path)
            if df is None or df.empty:
                result.validation_errors.append("Cannot read file or file is empty")
                return result
        except Exception as e:
            result.validation_errors.append(f"Cannot read file: {e}")
            return result

        # Execute
        try:
            converted_df = execute_converter_code(code, df)
        except Exception as e:
            result.validation_errors.append(f"Execution error: {e}")
            return result

        # Validate against schema
        validation = schema.validate(converted_df)
        if not validation.valid:
            result.validation_errors = validation.errors
            return result

        result.success = True
        result.df = converted_df
        logger.info(f"[FormatConverter] Converter test passed: "
                     f"{converted_df.shape[0]} rows, {converted_df.shape[1]} cols")
        return result

    def _save_converter(
        self,
        file_path: str,
        sample_df: pd.DataFrame,
        target_schema_id: str,
        code: str,
    ) -> None:
        """Save a successful converter to the registry."""
        filename = Path(file_path).stem
        # Use filename as company_id (can be refined later by admin)
        company_id = "".join(c if c.isalnum() else "_" for c in filename).lower()[:40]

        self.registry.register_converter(
            company_id=company_id,
            company_name=filename,
            target_schema=target_schema_id,
            converter_code=code,
            sample_file=Path(file_path).name,
            column_fingerprint=list(sample_df.columns),
            test_passed=True,
        )

    def _run_saved_converter(
        self, file_path: str, company_id: str
    ) -> Optional[ConversionResult]:
        """Run a saved converter from the registry."""
        entry = self.registry.get_active_converter(company_id)
        if not entry:
            return None

        result = ConversionResult(
            success=False,
            target_schema=entry.target_schema,
            converter_id=entry.converter_id,
            company_id=company_id,
        )

        # Read file (multi-sheet aware)
        try:
            df = self._read_file(file_path)
            if df is None or df.empty:
                result.validation_errors.append("Cannot read file or file is empty")
                return result
        except Exception as e:
            result.validation_errors.append(f"Cannot read file: {e}")
            return result

        # Execute saved converter
        try:
            converted_df = execute_converter_code(entry.converter_code, df)
        except Exception as e:
            result.validation_errors.append(f"Saved converter failed: {e}")
            return result

        # Validate
        schema = self.schemas.get_schema(entry.target_schema)
        if schema:
            validation = schema.validate(converted_df)
            if not validation.valid:
                result.validation_errors = validation.errors
                return result

        result.success = True
        result.df = converted_df
        logger.info(f"[FormatConverter] Saved converter ran successfully: "
                     f"{company_id} -> {entry.target_schema}")
        return result


# Module-level instance
_converter: Optional[FormatConverter] = None


def get_format_converter() -> FormatConverter:
    """Get or create FormatConverter singleton."""
    global _converter
    if _converter is None:
        _converter = FormatConverter()
    return _converter
