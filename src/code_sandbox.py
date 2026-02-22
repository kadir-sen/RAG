"""
Code Sandbox - Safe execution environment for LLM-generated converter code.
Validates and executes Python code with restricted namespace and timeout.
"""
import re
import signal
import threading
from typing import Optional, Tuple

import pandas as pd

from .config import CONVERTER_CODE_TIMEOUT
from .logger import logger


# Allowed modules in converter code
ALLOWED_MODULES = {"pandas", "numpy", "re", "datetime", "math"}

# Dangerous patterns that indicate unsafe code
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

    Returns:
        (is_safe, error_message) - error_message is None if safe
    """
    if not code or not code.strip():
        return False, "Empty code"

    # Check for dangerous patterns
    for i, pattern in enumerate(_COMPILED_PATTERNS):
        if pattern.search(code):
            return False, f"Unsafe pattern detected: {DANGEROUS_PATTERNS[i]}"

    # Must define convert function
    if "def convert(" not in code and "def convert (" not in code:
        return False, "Code must define a 'def convert(df)' function"

    # Check for allowed imports only
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

    Args:
        code: Python code string containing convert() function
        df: Input DataFrame (a copy is passed to the code)
        timeout: Execution timeout in seconds (0 = use config default)

    Returns:
        Converted DataFrame

    Raises:
        ValueError: If code is unsafe or doesn't define convert()
        TimeoutError: If execution exceeds timeout
        RuntimeError: If code execution fails
    """
    timeout = timeout or CONVERTER_CODE_TIMEOUT

    # Validate first
    is_safe, error = validate_converter_code(code)
    if not is_safe:
        raise ValueError(f"Unsafe converter code: {error}")

    # Build restricted namespace
    import numpy as np
    import datetime
    import math

    # Safe import function that only allows permitted modules
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

    # Execute code to define the convert function
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
