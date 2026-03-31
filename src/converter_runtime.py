"""
Converter Runtime - Per-company converter storage, matching, and safe execution.

Manages saved converter code that transforms company-specific Excel formats
into standardized target schemas. Includes a sandboxed execution environment
with restricted namespace and timeout protection.
"""
import json
import hashlib
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

import pandas as pd

from .config import CONVERTER_REGISTRY_FILE, CONVERTERS_DIR, CONVERTER_CODE_TIMEOUT
from .logger import logger


# ── Converter Data Model ────────────────────────────────────

@dataclass
class ConverterEntry:
    """A saved converter for a specific company format."""
    converter_id: str
    company_id: str
    company_name: str
    target_schema: str
    converter_code: str
    file_name_patterns: List[str] = field(default_factory=list)
    sheet_name_patterns: List[str] = field(default_factory=list)
    column_fingerprint: List[str] = field(default_factory=list)
    sample_files: List[str] = field(default_factory=list)
    test_passed: bool = False
    version: int = 1
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ── Converter Registry ──────────────────────────────────────

class ConverterRegistry:
    """
    Manages per-company converter persistence.
    JSON-file backed, singleton pattern.
    """

    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_path = registry_path or CONVERTER_REGISTRY_FILE
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: Dict[str, ConverterEntry] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        if not self.registry_path.exists():
            try:
                from .gcs_storage import sync_converter_registry_from_gcs
                sync_converter_registry_from_gcs()
            except Exception:
                pass

        if not self.registry_path.exists():
            return

        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            for key, entry_data in data.items():
                self._entries[key] = ConverterEntry(**entry_data)
            logger.info(f"[ConverterReg] Loaded {len(self._entries)} converters")
        except Exception as e:
            logger.warning(f"[ConverterReg] Failed to load registry: {e}")
            self._entries = {}

    def _save_registry(self) -> None:
        try:
            data = {k: asdict(v) for k, v in self._entries.items()}
            self.registry_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                from .gcs_storage import sync_converter_registry_to_gcs
                sync_converter_registry_to_gcs()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"[ConverterReg] Failed to save registry: {e}")

    def register_converter(
        self,
        company_id: str,
        company_name: str,
        target_schema: str,
        converter_code: str,
        sample_file: str = "",
        column_fingerprint: Optional[List[str]] = None,
        file_name_patterns: Optional[List[str]] = None,
        sheet_name_patterns: Optional[List[str]] = None,
        test_passed: bool = False,
    ) -> str:
        converter_id = f"conv_{hashlib.md5(f'{company_id}:{target_schema}'.encode()).hexdigest()[:8]}"
        version = 1
        existing = self._entries.get(company_id)
        if existing:
            version = existing.version + 1

        entry = ConverterEntry(
            converter_id=converter_id,
            company_id=company_id,
            company_name=company_name,
            target_schema=target_schema,
            converter_code=converter_code,
            file_name_patterns=file_name_patterns or [],
            sheet_name_patterns=sheet_name_patterns or [],
            column_fingerprint=column_fingerprint or [],
            sample_files=[sample_file] if sample_file else [],
            test_passed=test_passed,
            version=version,
        )

        self._entries[company_id] = entry
        self._save_registry()
        logger.info(f"[ConverterReg] Registered converter: {company_id} -> {target_schema} (v{version})")
        return converter_id

    def has_active_converter(self, company_id: str) -> bool:
        entry = self._entries.get(company_id)
        return entry is not None and entry.is_active

    def get_active_converter(self, company_id: str) -> Optional[ConverterEntry]:
        entry = self._entries.get(company_id)
        if entry and entry.is_active:
            return entry
        return None

    def list_converters(self) -> List[Dict[str, Any]]:
        return [
            {
                "converter_id": e.converter_id,
                "company_id": e.company_id,
                "company_name": e.company_name,
                "target_schema": e.target_schema,
                "test_passed": e.test_passed,
                "version": e.version,
                "is_active": e.is_active,
                "created_at": e.created_at,
                "sample_files": e.sample_files,
            }
            for e in self._entries.values()
        ]

    def remove_converter(self, converter_id: str) -> None:
        key_to_remove = None
        for key, entry in self._entries.items():
            if entry.converter_id == converter_id:
                key_to_remove = key
                break
        if key_to_remove:
            del self._entries[key_to_remove]
            self._save_registry()
            logger.info(f"[ConverterReg] Removed converter: {converter_id}")

    def match_company(self, file_path: str, df_columns: Optional[List[str]] = None) -> Optional[str]:
        filename = Path(file_path).name.lower()

        for company_id, entry in self._entries.items():
            if not entry.is_active:
                continue
            for pattern in entry.file_name_patterns:
                try:
                    if re.search(pattern, filename, re.IGNORECASE):
                        logger.info(f"[ConverterReg] Matched {filename} -> {company_id} (filename)")
                        return company_id
                except re.error:
                    continue
            if df_columns and entry.column_fingerprint:
                cols_lower = [c.lower().strip() for c in df_columns]
                fingerprint_lower = [c.lower().strip() for c in entry.column_fingerprint]
                matched = sum(1 for fp in fingerprint_lower if fp in cols_lower)
                if len(fingerprint_lower) > 0 and matched / len(fingerprint_lower) >= 0.7:
                    logger.info(f"[ConverterReg] Matched {filename} -> {company_id} (columns)")
                    return company_id

        return None

    def clear_all(self) -> None:
        self._entries.clear()
        self._save_registry()
        logger.info("[ConverterReg] Cleared all converters")


_registry: Optional[ConverterRegistry] = None


def get_converter_registry() -> ConverterRegistry:
    """Get or create ConverterRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ConverterRegistry()
    return _registry


# ── Code Sandbox ────────────────────────────────────────────

ALLOWED_MODULES = {"pandas", "numpy", "re", "datetime", "math"}

DANGEROUS_PATTERNS = [
    r'\bimport\s+os\b',
    r'\bimport\s+sys\b',
    r'\bimport\s+subprocess\b',
    r'\bimport\s+shutil\b',
    r'\bimport\s+socket\b',
    r'\bimport\s+http\b',
    r'\bimport\s+urllib\b',
    r'\bimport\s+requests\b',
    r'\bimport\s+pathlib\b',
    r'\bfrom\s+os\b',
    r'\bfrom\s+sys\b',
    r'\bfrom\s+subprocess\b',
    r'\bopen\s*\(',
    r'\beval\s*\(',
    r'\bexec\s*\(',
    r'\bcompile\s*\(',
    r'\b__import__\s*\(',
    r'\bgetattr\s*\(',
    r'\bsetattr\s*\(',
    r'\bdelattr\s*\(',
    r'\bglobals\s*\(',
    r'\blocals\s*\(',
    r'\bbreakpoint\s*\(',
    r'\bos\.',
    r'\bsys\.',
    r'\bsubprocess\.',
    r'\b__builtins__',
    r'\b__class__',
    r'\b__subclasses__',
]

_COMPILED_PATTERNS = [re.compile(p) for p in DANGEROUS_PATTERNS]


def validate_converter_code(code: str) -> Tuple[bool, Optional[str]]:
    """
    Validate converter code against security denylist.
    Returns (is_safe, error_message) - error_message is None if safe.
    """
    if not code or not code.strip():
        return False, "Empty code"

    for i, pattern in enumerate(_COMPILED_PATTERNS):
        if pattern.search(code):
            return False, f"Unsafe pattern detected: {DANGEROUS_PATTERNS[i]}"

    if "def convert(" not in code and "def convert (" not in code:
        return False, "Code must define a 'def convert(df)' function"

    import_pattern = re.compile(r'(?:from|import)\s+(\w+)')
    for match in import_pattern.finditer(code):
        module = match.group(1)
        if module not in ALLOWED_MODULES and module != "pd" and module != "np":
            return False, f"Disallowed import: {module}"

    return True, None


def execute_converter_code(
    code: str,
    df: pd.DataFrame,
    timeout: int = 0,
) -> pd.DataFrame:
    """
    Execute converter code in a restricted namespace with timeout.
    The code must define a `def convert(df) -> pd.DataFrame` function.
    """
    timeout = timeout or CONVERTER_CODE_TIMEOUT

    is_safe, error = validate_converter_code(code)
    if not is_safe:
        raise ValueError(f"Unsafe converter code: {error}")

    import numpy as np
    import datetime
    import math

    _safe_modules = {
        "pandas": pd,
        "numpy": np,
        "re": re,
        "datetime": datetime,
        "math": math,
    }

    def _safe_import(name, *args, **kwargs):
        if name in _safe_modules:
            return _safe_modules[name]
        raise ImportError(f"Import of '{name}' is not allowed in converter code")

    namespace = {
        "pd": pd,
        "np": np,
        "re": re,
        "datetime": datetime,
        "math": math,
        "__builtins__": {
            "__import__": _safe_import,
            "len": len,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "map": map,
            "filter": filter,
            "sorted": sorted,
            "reversed": reversed,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "None": None,
            "True": True,
            "False": False,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "type": type,
            "print": print,
            "round": round,
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "any": any,
            "all": all,
            "hasattr": hasattr,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "Exception": Exception,
        },
    }

    result_holder = {"df": None, "error": None}

    def _run():
        try:
            exec(code, namespace)
            if "convert" not in namespace:
                result_holder["error"] = "Code did not define a 'convert' function"
                return

            convert_fn = namespace["convert"]
            df_copy = df.copy()
            result = convert_fn(df_copy)

            if not isinstance(result, pd.DataFrame):
                result_holder["error"] = (
                    f"convert() must return pd.DataFrame, got {type(result).__name__}"
                )
                return

            result_holder["df"] = result
        except Exception as e:
            result_holder["error"] = f"Execution error: {type(e).__name__}: {e}"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        logger.error(f"[Sandbox] Code execution timed out after {timeout}s")
        raise TimeoutError(f"Converter code execution timed out after {timeout}s")

    if result_holder["error"]:
        raise RuntimeError(result_holder["error"])

    logger.info(f"[Sandbox] Code executed successfully, "
                f"output shape: {result_holder['df'].shape}")
    return result_holder["df"]
