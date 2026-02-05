"""
Structured logging for the Agentic RAG Chatbot.
Provides colored console output and structured event logging.
Includes secret redaction for security.
"""
import logging
import re
import sys
import time
from datetime import datetime
from typing import Optional
from functools import wraps


# Patterns for sensitive data redaction
REDACTION_PATTERNS = [
    # Credit card numbers (13-19 digits, possibly with spaces/dashes)
    (r'\b(?:\d{4}[-\s]?){3,4}\d{1,4}\b', '[CARD_REDACTED]'),
    # API keys (common patterns)
    (r'\b[A-Za-z0-9_-]{32,}\b', lambda m: m.group()[:8] + '...' if len(m.group()) > 40 else m.group()),
    # Email addresses (partial redaction)
    (r'\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b', r'\1[at]\2'),
    # Phone numbers (Turkish format)
    (r'\b(?:\+90|0)?[\s-]?5\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b', '[PHONE_REDACTED]'),
    # CVV (3-4 digits near card context)
    (r'\b(?:cvv|cvc|cvv2|security code)[:\s]*\d{3,4}\b', '[CVV_REDACTED]'),
    # OTP codes
    (r'\b(?:otp|verification code|dogrulama kodu)[:\s]*\d{4,8}\b', '[OTP_REDACTED]'),
]


def redact_secrets(text: str) -> str:
    """Redact sensitive information from log messages."""
    if not text:
        return text

    result = text
    for pattern, replacement in REDACTION_PATTERNS:
        if callable(replacement):
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        else:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output."""

    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.now().strftime('%H:%M:%S')
        # Apply secret redaction
        message = redact_secrets(record.getMessage())
        return f"{color}{self.BOLD}[{timestamp}]{self.RESET} {color}{message}{self.RESET}"


def setup_logger(name: str = "rag_chatbot", level: int = logging.DEBUG) -> logging.Logger:
    """Setup and return a configured logger."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Console handler with UTF-8 encoding for Windows
    import io
    utf8_stream = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    console = logging.StreamHandler(utf8_stream)
    console.setLevel(level)
    console.setFormatter(ColoredFormatter())
    logger.addHandler(console)

    return logger


# Global logger
logger = setup_logger()


# Convenience functions
def log_separator(title: str = ""):
    """Log a visual separator."""
    if title:
        logger.info(f"{'='*20} {title} {'='*20}")
    else:
        logger.info("=" * 50)


def log_document_processing(file_name: str, status: str, details: str = ""):
    """Log document processing event."""
    icon = "📄" if ".pdf" in file_name.lower() else "📊" if any(x in file_name.lower() for x in ['.xlsx', '.csv']) else "📝"
    msg = f"{icon} [{file_name}] {status}"
    if details:
        msg += f" | {details}"
    logger.info(msg)


def log_query(query: str, query_type: str):
    """Log query classification."""
    icons = {"document": "📚", "data": "📊", "hybrid": "🔀"}
    icon = icons.get(query_type.lower(), "❓")
    short_query = query[:50] + "..." if len(query) > 50 else query
    logger.info(f"🔍 Query: '{short_query}'")
    logger.info(f"{icon} Type: {query_type.upper()}")


def log_retrieval(num_sources: int, top_source: str = ""):
    """Log retrieval results."""
    logger.info(f"📥 Retrieved {num_sources} source(s)")
    if top_source:
        logger.info(f"   Top: {top_source}")


def log_pinecone(action: str, details: str = ""):
    """Log Pinecone operations."""
    logger.info(f"🌲 Pinecone: {action}")
    if details:
        logger.info(f"   {details}")


def log_llm(action: str, model: str = ""):
    """Log LLM operations."""
    logger.info(f"🤖 LLM: {action}")
    if model:
        logger.info(f"   Model: {model}")


def log_sql(action: str, query: str = "", exec_time: float = 0):
    """Log SQL operations."""
    logger.info(f"🔷 SQL: {action}")
    if query:
        short = query[:80] + "..." if len(query) > 80 else query
        logger.info(f"   Query: {short}")
    if exec_time:
        logger.info(f"   Time: {exec_time:.3f}s")


def timed(func):
    """Decorator to log function execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        logger.debug(f"⏱️ {func.__name__} took {elapsed:.3f}s")
        return result
    return wrapper


def log_ocr(action: str, details: str = ""):
    """Log OCR operations."""
    logger.info(f"🔍 OCR: {action}")
    if details:
        logger.info(f"   {details}")


def log_ocr_summary(
    total_pages: int,
    native_pages: int,
    ocr_pages: int,
    failed_pages: int,
    total_time_ms: int = 0,
):
    """Log OCR processing summary."""
    logger.info(f"   ========================================")
    logger.info(f"   OCR Summary:")
    logger.info(f"   - Total pages: {total_pages}")
    logger.info(f"   - Native extraction: {native_pages}")
    logger.info(f"   - OCR extraction: {ocr_pages}")
    if failed_pages > 0:
        logger.warning(f"   - Failed/empty: {failed_pages}")
    if total_time_ms > 0:
        logger.info(f"   - OCR time: {total_time_ms}ms")
    logger.info(f"   ========================================")
