"""Configuration and API key management with validation."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# API Keys
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")

# Model settings
GEMINI_MODEL = "gemini-flash-latest"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSION = 768  # MRL-reduced from 3072 default

# Pinecone settings
PINECONE_INDEX_NAME = "agentic-rag"
PINECONE_DIMENSION = EMBEDDING_DIMENSION

# Paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
TABLES_DIR = DATA_DIR / "tables"
STORAGE_DIR = BASE_DIR / "storage"

# Ensure directories exist
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
TABLES_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Chunking settings
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 200

# SQL settings
MAX_SQL_RESULT_ROWS = 200

# OCR Settings
OCR_MODE = os.getenv("OCR_MODE", "auto")  # "auto" | "force" | "off"
OCR_ENGINE = os.getenv("OCR_ENGINE", "tesseract")  # "tesseract" | "paddleocr"
OCR_LANG = os.getenv("OCR_LANG", "eng")  # "eng" | "eng+tur" | etc.
OCR_DPI = int(os.getenv("OCR_DPI", "200"))  # Image rendering DPI
OCR_CACHE_DIR = str(BASE_DIR / ".cache" / "ocr")
OCR_MAX_PAGES_PER_DOC = int(os.getenv("OCR_MAX_PAGES", "500"))

# OCR Detection Thresholds
OCR_MIN_CHARS_THRESHOLD = int(os.getenv("OCR_MIN_CHARS", "30"))  # Min chars to skip OCR
OCR_MIN_ALPHA_RATIO = float(os.getenv("OCR_MIN_ALPHA_RATIO", "0.2"))  # Min letter ratio
OCR_IMAGE_COVERAGE_THRESHOLD = float(os.getenv("OCR_IMAGE_COVERAGE", "0.7"))  # Max image coverage

# Ensure OCR cache directory exists
Path(OCR_CACHE_DIR).mkdir(parents=True, exist_ok=True)

# ── LLM Call Budget & Safety ────────────────────────────────
MAX_LLM_CALLS_PER_QUERY = int(os.getenv("MAX_LLM_CALLS", "4"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT", "30"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))

# ── Cache settings ──────────────────────────────────────────
CACHE_DIR = str(BASE_DIR / "cache")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour default
REDIS_URL = os.getenv("REDIS_URL", "")  # optional Redis backend

# Ensure cache directory
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)

# ── Cost Estimation (USD per 1M tokens) ─────────────────────
LLM_PRICING = {
    "gemini-flash-latest": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.00},
}
EMBEDDING_PRICING = {
    "gemini-embedding-001": 0.00002,  # per embedding
}

# ── Lazy Summary Thresholds ─────────────────────────────────
SQL_LAZY_SUMMARY_MAX_ROWS = int(os.getenv("SQL_LAZY_SUMMARY_MAX_ROWS", "5"))
SQL_LAZY_SUMMARY_MAX_CELLS = int(os.getenv("SQL_LAZY_SUMMARY_MAX_CELLS", "30"))

# ── Planner Guardrails ──────────────────────────────────────
MAX_PLAN_STEPS = int(os.getenv("MAX_PLAN_STEPS", "5"))

# ── Feature Flags ───────────────────────────────────────────
ENABLE_TIMELINE = os.getenv("ENABLE_TIMELINE", "true").lower() == "true"
ENABLE_AB_TESTING = os.getenv("ENABLE_AB_TESTING", "false").lower() == "true"

# ── Notice Extraction ───────────────────────────────────────
NOTICE_LLM_CONFIDENCE_THRESHOLD = float(os.getenv("NOTICE_LLM_THRESHOLD", "0.75"))

# ── A/B Testing ─────────────────────────────────────────────
AB_LOG_DIR = str(BASE_DIR / "logs" / "ab")
Path(AB_LOG_DIR).mkdir(parents=True, exist_ok=True)

# ── Telemetry ───────────────────────────────────────────────
TELEMETRY_LOG_DIR = str(BASE_DIR / "logs" / "telemetry")
Path(TELEMETRY_LOG_DIR).mkdir(parents=True, exist_ok=True)


def validate_config() -> tuple[bool, list[str]]:
    """
    Validate all required configuration.
    Returns (is_valid, list_of_errors).
    """
    errors = []

    if not GOOGLE_API_KEY:
        errors.append("GOOGLE_API_KEY is not set. Add it to your .env file.")
    elif len(GOOGLE_API_KEY) < 20:
        errors.append("GOOGLE_API_KEY appears invalid (too short).")

    if not PINECONE_API_KEY:
        errors.append("PINECONE_API_KEY is not set. Add it to your .env file.")
    elif len(PINECONE_API_KEY) < 20:
        errors.append("PINECONE_API_KEY appears invalid (too short).")

    return len(errors) == 0, errors


def print_config_status():
    """Print configuration status for debugging."""
    print("\n=== Configuration Status ===")
    print(f"GOOGLE_API_KEY: {'✓ Set' if GOOGLE_API_KEY else '✗ Missing'}")
    print(f"PINECONE_API_KEY: {'✓ Set' if PINECONE_API_KEY else '✗ Missing'}")
    print(f"Model: {GEMINI_MODEL}")
    print(f"Embedding: {EMBEDDING_MODEL}")
    print(f"Pinecone Index: {PINECONE_INDEX_NAME}")
    print(f"Data Dir: {DATA_DIR}")
    print("============================\n")


if __name__ == "__main__":
    # Run validation when executed directly
    is_valid, errors = validate_config()
    print_config_status()

    if not is_valid:
        print("❌ Configuration errors:")
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)
    else:
        print("✅ Configuration is valid")
