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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Model settings
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")  # claude-sonnet-4-20250514 or claude-3-5-sonnet-20241022
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSION = 768  # MRL-reduced from 3072 default (also bge-base-en-v1.5 native dim)

# Embedding provider (all bge-base-en-v1.5, 768-dim → matches EMBEDDING_DIMENSION):
#   "gemini"    — cloud, paid.
#   "local"     — sentence-transformers + torch; fast on M4/GPU, ~1 GB RAM (bulk ingest).
#   "fastembed" — ONNX (no torch), low RAM (~0.6 GB); server default for the 2 GB box.
# local & fastembed are wire-compatible (same model + query instruction), so docs can
# be ingested with "local" on the Mac and queried with "fastembed" on the server.
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "gemini").lower()
LOCAL_EMBEDDING_MODEL = os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "auto")  # "auto" | "mps" | "cpu" | "cuda"

# Dual-LLM providers (built dynamically from available keys)
# Gemini is always available (primary), others added if keys present
LLM_PROVIDERS = ["gemini"]
if OPENAI_API_KEY:
    LLM_PROVIDERS.append("openai")
if ANTHROPIC_API_KEY:
    LLM_PROVIDERS.append("claude")

# Dual-provider fan-out (calls every provider in LLM_PROVIDERS per query) is a
# major cost multiplier and its compare-UI is currently not surfaced to users.
# Keep it OFF unless explicitly enabled, even when multiple keys are present.
ENABLE_DUAL_PROVIDER = os.getenv("ENABLE_DUAL_PROVIDER", "false").lower() in ("1", "true", "yes")

# ── Extended thinking / reasoning (Phase 3) ─────────────────
# Reasoning is enabled ONLY on hallucination-prone steps: SQL generation and
# hybrid synthesis. Routing thinking is OFF by default to protect demo latency.
# Budgets are in tokens (provider-specific): Gemini 2.5 thinking_budget, Claude
# extended-thinking budget_tokens (Claude requires >= 1024 and temperature == 1).
ENABLE_THINKING = os.getenv("ENABLE_THINKING", "true").lower() in ("1", "true", "yes")
THINKING_BUDGET_SQL = int(os.getenv("THINKING_BUDGET_SQL", "1024"))
THINKING_BUDGET_SYNTHESIS = int(os.getenv("THINKING_BUDGET_SYNTHESIS", "1024"))
THINKING_BUDGET_ROUTING = int(os.getenv("THINKING_BUDGET_ROUTING", "0"))

# ── Hybrid retrieval (RAG güçlendirme — Phase 1) ────────────
# Dense vector + lexical (DuckDB FTS/BM25) candidates fused via Reciprocal Rank
# Fusion, with a document-keyword boost, then an optional LLM rerank. All
# toggleable; when OFF the original pure-dense path runs unchanged.
ENABLE_HYBRID_RETRIEVAL = os.getenv("ENABLE_HYBRID_RETRIEVAL", "true").lower() in ("1", "true", "yes")
ENABLE_RERANK = os.getenv("ENABLE_RERANK", "true").lower() in ("1", "true", "yes")
RAG_CANDIDATE_K = int(os.getenv("RAG_CANDIDATE_K", "30"))   # per-retriever candidate pool
RAG_RERANK_K = int(os.getenv("RAG_RERANK_K", "15"))         # candidates sent to the reranker
RAG_FINAL_K = int(os.getenv("RAG_FINAL_K", "6"))            # chunks kept for synthesis
RRF_K = int(os.getenv("RRF_K", "60"))                       # RRF damping constant

# Pinecone settings
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "hybrid-rag")
PINECONE_DIMENSION = EMBEDDING_DIMENSION

# ── Vector Store Backend Selection ──────────────────────────
# "pinecone" (default, current production) | "qdrant" (self-hosted, AWS demo)
# Pinecone path is unchanged; Qdrant is opt-in via env var only.
VECTOR_STORE_BACKEND = os.getenv("VECTOR_STORE_BACKEND", "pinecone").lower()

# Qdrant settings (only used when VECTOR_STORE_BACKEND=qdrant)
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "constructioniq")

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

# Ingestion toggles — turn off expensive per-PDF steps for fast bulk embedding
# runs (e.g. large correspondence corpora). Table extraction (pdfplumber, page by
# page) is ~7x the per-doc cost and adds little on letters/emails; disable it for
# the bulk vector pass and run it later only where tables matter.
INGEST_EXTRACT_TABLES = os.getenv("INGEST_EXTRACT_TABLES", "true").lower() in ("1", "true", "yes")
# Notice extraction feeds the light_graph, which re-saves the whole graph JSON per
# document (O(n²) over a big corpus). Disable for the bulk vector pass; build the
# event-timeline / graph in a dedicated optimized batch afterward (Faz 2).
INGEST_EXTRACT_NOTICES = os.getenv("INGEST_EXTRACT_NOTICES", "true").lower() in ("1", "true", "yes")

# SQL settings
MAX_UI_DISPLAY_ROWS = 5000  # Only for UI payload truncation, never for SQL LIMIT

# OCR Settings
OCR_MODE = os.getenv("OCR_MODE", "auto")  # "auto" | "force" | "off"
OCR_ENGINE = os.getenv("OCR_ENGINE", "tesseract")  # "tesseract" | "paddleocr"
OCR_LANG = os.getenv("OCR_LANG", "eng")  # English-only (all documents are English)
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
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-flash-latest": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.00},
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    # Claude
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-20250514": {"input": 0.80, "output": 4.00},
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

# ── Template-Based Extraction ──────────────────────────────
TEMPLATE_FILE = STORAGE_DIR / "parquet" / "templates.json"
TEMPLATE_CONFIDENCE_THRESHOLD = float(os.getenv("TEMPLATE_THRESHOLD", "0.85"))
TEMPLATE_REVIEW_THRESHOLD = float(os.getenv("TEMPLATE_REVIEW_THRESHOLD", "0.70"))

# ── Chat Memory ───────────────────────────────────────────
CHAT_MEMORY_MESSAGES = int(os.getenv("CHAT_MEMORY_MESSAGES", "10"))
CHAT_MEMORY_MAX_CHARS = int(os.getenv("CHAT_MEMORY_MAX_CHARS", "12000"))

# ── Conversations ─────────────────────────────────────────
CONVERSATIONS_DIR = STORAGE_DIR / "conversations"
CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

# ── Email Processing ────────────────────────────────────────
EMAILS_DIR = DATA_DIR / "emails"
EMAILS_DIR.mkdir(parents=True, exist_ok=True)

# ── Format Converter ────────────────────────────────────────
CONVERTERS_DIR = STORAGE_DIR / "converters"
CONVERTERS_DIR.mkdir(parents=True, exist_ok=True)
CONVERTER_REGISTRY_FILE = CONVERTERS_DIR / "registry.json"
SCHEMAS_DIR = STORAGE_DIR / "schemas"
SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
CONVERTER_CONFIDENCE_THRESHOLD = float(os.getenv("CONVERTER_THRESHOLD", "0.6"))
CONVERTER_CODE_TIMEOUT = int(os.getenv("CONVERTER_TIMEOUT", "30"))

# ── Notice Extraction ───────────────────────────────────────
NOTICE_LLM_CONFIDENCE_THRESHOLD = float(os.getenv("NOTICE_LLM_THRESHOLD", "0.75"))

# ── Document Review ────────────────────────────────────────
ENABLE_REVIEW = os.getenv("ENABLE_REVIEW", "true").lower() == "true"
REVIEW_HIGH_THRESHOLD = float(os.getenv("REVIEW_HIGH_THRESHOLD", "0.7"))
REVIEW_LOW_THRESHOLD = float(os.getenv("REVIEW_LOW_THRESHOLD", "0.3"))
REVIEW_SESSIONS_DIR = STORAGE_DIR / "review_sessions"
REVIEW_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
REVIEW_ACCURACY_THRESHOLD = float(os.getenv("REVIEW_ACCURACY_THRESHOLD", "0.8"))
REVIEW_SAMPLE_SIZE = int(os.getenv("REVIEW_SAMPLE_SIZE", "10"))

# ── A/B Testing ─────────────────────────────────────────────
AB_LOG_DIR = str(BASE_DIR / "logs" / "ab")
Path(AB_LOG_DIR).mkdir(parents=True, exist_ok=True)

# ── Telemetry ───────────────────────────────────────────────
TELEMETRY_LOG_DIR = str(BASE_DIR / "logs" / "telemetry")
Path(TELEMETRY_LOG_DIR).mkdir(parents=True, exist_ok=True)


def normalize_stored_paths():
    """Auto-fix Windows paths in JSON registry files at startup.
    Ensures the app works in Docker/Linux regardless of where files were originally indexed."""
    import re as _re
    import logging
    _log = logging.getLogger("app")
    app_root = str(BASE_DIR)  # e.g. /app
    # Known Windows prefixes that should map to app_root
    _WIN_PREFIXES = [
        r"C:\\projects\\ML_project\\",
        r"C:/projects/ML_project/",
        r"C:\\\\projects\\\\ML_project\\\\",
    ]
    count = 0
    for search_dir in [STORAGE_DIR, DATA_DIR]:
        if not search_dir.exists():
            continue
        for json_file in search_dir.rglob("*.json"):
            try:
                raw = json_file.read_text(encoding="utf-8")
            except Exception:
                continue
            original = raw
            for prefix in _WIN_PREFIXES:
                raw = raw.replace(prefix, app_root + "/")
            # Fix remaining backslashes in paths
            raw = raw.replace("\\\\", "/")
            raw = raw.replace("\\", "/")
            # Collapse double slashes (but not in http://)
            raw = _re.sub(r'(?<!:)//', '/', raw)
            if raw != original:
                json_file.write_text(raw, encoding="utf-8")
                count += 1
    if count:
        _log.info(f"[PathNorm] Fixed Windows paths in {count} JSON files")


# Run path normalization at import time (startup)
normalize_stored_paths()


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

    # Pinecone is required only when it is the active backend.
    if VECTOR_STORE_BACKEND == "pinecone":
        if not PINECONE_API_KEY:
            errors.append("PINECONE_API_KEY is not set. Add it to your .env file.")
        elif len(PINECONE_API_KEY) < 20:
            errors.append("PINECONE_API_KEY appears invalid (too short).")
    elif VECTOR_STORE_BACKEND == "qdrant":
        if not QDRANT_URL:
            errors.append("QDRANT_URL is not set (e.g. http://qdrant:6333).")
    else:
        errors.append(
            f"Unknown VECTOR_STORE_BACKEND={VECTOR_STORE_BACKEND!r} "
            f"(expected 'pinecone' or 'qdrant')."
        )

    # Optional providers – warn but don't block startup
    if not OPENAI_API_KEY:
        import logging
        logging.warning("OPENAI_API_KEY is not set. OpenAI provider will be unavailable.")

    if not ANTHROPIC_API_KEY:
        import logging
        logging.warning("ANTHROPIC_API_KEY is not set. Claude provider will be unavailable.")

    return len(errors) == 0, errors


def print_config_status():
    """Print configuration status for debugging."""
    print("\n=== Configuration Status ===")
    print(f"GOOGLE_API_KEY: {'✓ Set' if GOOGLE_API_KEY else '✗ Missing'}")
    print(f"PINECONE_API_KEY: {'✓ Set' if PINECONE_API_KEY else '✗ Missing'}")
    print(f"OPENAI_API_KEY: {'✓ Set' if OPENAI_API_KEY else '✗ Missing'}")
    print(f"ANTHROPIC_API_KEY: {'✓ Set' if ANTHROPIC_API_KEY else '✗ Missing'}")
    print(f"Model: {GEMINI_MODEL}")
    print(f"OpenAI Model: {OPENAI_MODEL}")
    print(f"Claude Model: {ANTHROPIC_MODEL}")
    print(f"Embedding: {EMBEDDING_MODEL}")
    print(f"Vector Backend: {VECTOR_STORE_BACKEND}")
    if VECTOR_STORE_BACKEND == "pinecone":
        print(f"Pinecone Index: {PINECONE_INDEX_NAME}")
    elif VECTOR_STORE_BACKEND == "qdrant":
        print(f"Qdrant URL: {QDRANT_URL}")
        print(f"Qdrant Collection: {QDRANT_COLLECTION}")
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
