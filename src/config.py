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
# Cheap tier for low-value reasoning (classification, scope detection, table
# selection, small-result summaries, answer-verification). Half the flash price
# (see LLM_PRICING). High-value steps (SQL generation, synthesis) stay on GEMINI_MODEL.
GEMINI_MODEL_LITE = os.getenv("GEMINI_MODEL_LITE", "gemini-2.5-flash-lite")
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
# "api" — hosted copy of the SAME bge model via an OpenAI-compatible
# /embeddings endpoint (DeepInfra, Together, HF router...). Frees the ~600 MB
# the in-process ONNX model costs on the 2 GB server; wire-compatible with the
# existing corpus (same model + same query instruction, only runs remotely).
EMBEDDING_API_URL = os.getenv("EMBEDDING_API_URL", "")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
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
# Extended thinking adds reasoning tokens (and seconds) to every synthesis call.
# Off by default: on a small/contended server the latency cost outweighs the
# marginal quality gain. Re-enable per-deploy via ENABLE_THINKING=true.
ENABLE_THINKING = os.getenv("ENABLE_THINKING", "false").lower() in ("1", "true", "yes")
THINKING_BUDGET_SQL = int(os.getenv("THINKING_BUDGET_SQL", "1024"))
THINKING_BUDGET_SYNTHESIS = int(os.getenv("THINKING_BUDGET_SYNTHESIS", "1024"))
THINKING_BUDGET_ROUTING = int(os.getenv("THINKING_BUDGET_ROUTING", "0"))

# ── Hybrid retrieval (RAG güçlendirme — Phase 1) ────────────
# Dense vector + lexical (DuckDB FTS/BM25) candidates fused via Reciprocal Rank
# Fusion, with a document-keyword boost, then an optional LLM rerank. All
# toggleable; when OFF the original pure-dense path runs unchanged.
# Route mechanical/structural LLM steps (decompose, rerank — classification is
# already lite) to GEMINI_MODEL_LITE: same model family, ~3-5x cheaper + faster.
ENABLE_LITE_TIER = os.getenv("ENABLE_LITE_TIER", "true").lower() in ("1", "true", "yes")
# Run the independent doc-side and data-side legs of a hybrid query concurrently.
ENABLE_PARALLEL_RETRIEVAL = os.getenv("ENABLE_PARALLEL_RETRIEVAL", "true").lower() in ("1", "true", "yes")
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

# Max heavy indexing jobs (OCR + embed) running at once. Several PDFs uploaded
# together would otherwise spawn parallel OCR/embedding in the threadpool and
# blow CPU/RAM on a small (2 GB) box. Extra files queue and show "queued".
INGEST_MAX_CONCURRENCY = int(os.getenv("INGEST_MAX_CONCURRENCY", "2"))

# SQL settings
MAX_UI_DISPLAY_ROWS = 5000  # Only for UI payload truncation, never for SQL LIMIT

# OCR Settings
OCR_MODE = os.getenv("OCR_MODE", "auto")  # "auto" | "force" | "off"
OCR_ENGINE = os.getenv("OCR_ENGINE", "tesseract")  # "tesseract" | "paddleocr"
# Pages of a scanned PDF are OCR'd in parallel (each tesseract call releases the
# GIL via its subprocess). Capped by CPU count in code. Combined with the ingest
# semaphore this bounds total parallel OCR on a small box.
OCR_MAX_WORKERS = int(os.getenv("OCR_MAX_WORKERS", "4"))
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
# SOFT budget (not a hard cap): once a single query has made this many real
# (non-cache) LLM calls, further calls are degraded to the cheap tier + no
# thinking rather than blocked — answers are never dropped, runaway cost is bled
# out. 4 was unrealistic (a complex HYBRID query legitimately makes 10-15 calls);
# 8 lets normal multi-step queries through and only bites pathological ones.
MAX_LLM_CALLS_PER_QUERY = int(os.getenv("MAX_LLM_CALLS", "8"))
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

# ── ReAct agent (bounded tool-using loop for complex multi-step queries) ──
# ON by default: complex/multi-step queries (and HYBRID / low-confidence ones)
# route to the agent instead of the fixed planner. REACT_MAX_ITERATIONS caps the
# tool/decide loop; the llm_client soft budget (MAX_LLM_CALLS_PER_QUERY) is the
# secondary backstop. ROUTE_AGENT_CONF: below this classifier confidence a
# multi-part query is sent to the agent (it self-corrects better than a guess).
ENABLE_REACT_AGENT = os.getenv("ENABLE_REACT_AGENT", "true").lower() in ("1", "true", "yes")
REACT_MAX_ITERATIONS = int(os.getenv("REACT_MAX_ITERATIONS", "5"))
ROUTE_AGENT_CONF = float(os.getenv("ROUTE_AGENT_CONF", "0.55"))
# Wall-clock safety cap (seconds): between iterations the agent stops taking new
# steps once exceeded and synthesizes from what it has. Bounds rare provider-
# contention spikes (a multi-tool run stacking slow LLM calls) so a single query
# can't run for minutes. The per-call LLM timeout still applies within a step.
REACT_TIME_BUDGET_SEC = float(os.getenv("REACT_TIME_BUDGET_SEC", "90"))

# ── Negative-answer auto-escalation ─────────────────────────
# A shallow route that lands on "that isn't in the corpus" gets re-run through
# the ReAct agent when the cheap verifier says the question IS answerable
# (WEAK, not OFFTOPIC). This exists because the system's failure mode is the
# false negative, not the hallucination: it denies the corpus in the same
# confident register it uses when it is right, and a denial doesn't invite the
# reader to check.
#
# The second pass is not merely longer, it searches a DIFFERENT space: the
# shallow document path retrieves once at top_k=10 through an LLM-derived
# doc_type/project payload filter, while the agent's tools retrieve unfiltered
# at top_k=24 and issue several differently-worded searches. Over-tight scope is
# where these negatives come from, so widening it is the point.
#
# Budgets are deliberately separate from the first-class agent's: this is a
# second pass stacked on a query that has already spent its latency.
# ESCALATION_LLM_BUDGET is the one that actually binds — ReActAgent stops on the
# TRACE's cumulative call count, and the first pass has already burned ~5 of
# MAX_LLM_CALLS_PER_QUERY(8), so without extra headroom an escalated run would
# be shallower than the pass it was sent to rescue. Note llm_client's own soft
# cap still degrades everything past 8 calls to the lite tier, so this headroom
# buys cheap-tier calls, which is the right trade on a 2 GB box.
#
# Set ENABLE_NEGATIVE_ESCALATION=false to switch the whole behaviour off.
ENABLE_NEGATIVE_ESCALATION = os.getenv("ENABLE_NEGATIVE_ESCALATION", "true").lower() in ("1", "true", "yes")
ESCALATION_MAX_ITERATIONS = int(os.getenv("ESCALATION_MAX_ITERATIONS", "4"))
ESCALATION_TIME_BUDGET_SEC = float(os.getenv("ESCALATION_TIME_BUDGET_SEC", "45"))
ESCALATION_LLM_BUDGET = int(os.getenv("ESCALATION_LLM_BUDGET", "16"))

# ── Feature Flags ───────────────────────────────────────────
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


# ── Windows-path normalization (opt-in, structure-preserving) ──────────────
# This used to run at import time — on every process start — and rewrote every
# JSON file under storage/ and data/ as RAW TEXT ("\\" -> "/"). Because it never
# parsed the JSON it destroyed the escapes the format is built on: \" became /"
# and the file stopped parsing, \n became /n. 97 files under storage/ and 11
# under data/ were unparseable when this was found, including more than half of
# one account's chat history — that, not any storage loss, is what "history
# resets on every deploy" was. See src/json_repair.py for the damage and the
# recovery.
#
# It exists to fix registry entries indexed on a Windows host
# (C:\projects\ML_project\data\...). There are none left: every file_path in
# document_registry.json and parquet/catalog.json is already POSIX, and
# DocumentService._resolve_path already rescues a Windows-style path by basename
# search at read time. So this is OFF by default; NORMALIZE_STORED_PATHS=1 runs
# it.
#
# The rewrite now works on the PARSED document — only string *values*, only
# under path-bearing keys, only in a fixed list of registry files. Structural
# corruption is impossible by construction: json.loads in, json.dumps out. And
# storage/conversations/** is not in the list at all; it is user prose and holds
# no path this application owns.
NORMALIZE_STORED_PATHS = os.getenv("NORMALIZE_STORED_PATHS", "false").lower() in ("1", "true", "yes")

_PATH_KEYS = frozenset({
    "file_path", "source_file", "path", "local_path", "source_path", "output_path",
})


def _normalize_path_value(value: str) -> str:
    """Map a Windows absolute path onto this installation's root."""
    from pathlib import PureWindowsPath
    posix = PureWindowsPath(value).as_posix()
    for marker in ("/data/", "/storage/"):
        idx = posix.find(marker)
        if idx != -1:
            return str(BASE_DIR) + posix[idx:]
    return posix


def _normalize_node(node):
    """Rewrite path-shaped values under path keys. Returns (node, changed)."""
    import re as _re
    win_abs = _re.compile(r"^[A-Za-z]:[\\/]")
    changed = False
    if isinstance(node, dict):
        for key, val in node.items():
            if isinstance(val, str) and key in _PATH_KEYS and win_abs.match(val):
                new = _normalize_path_value(val)
                if new != val:
                    node[key] = new
                    changed = True
            else:
                _, sub = _normalize_node(val)
                changed = changed or sub
    elif isinstance(node, list):
        for item in node:
            _, sub = _normalize_node(item)
            changed = changed or sub
    return node, changed


def normalize_stored_paths() -> int:
    """Normalize Windows absolute paths in the registry files. Returns files changed."""
    import json as _json
    import logging
    _log = logging.getLogger("app")
    targets = [
        STORAGE_DIR / "document_registry.json",
        STORAGE_DIR / "parquet" / "catalog.json",
        CONVERTER_REGISTRY_FILE,
    ]
    count = 0
    for target in targets:
        if not target.exists():
            continue
        try:
            data = _json.loads(target.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning(f"[PathNorm] skipping unparseable {target}: {exc}")
            continue
        data, changed = _normalize_node(data)
        if not changed:
            continue
        tmp = target.with_name(target.name + ".pathnorm.tmp")
        tmp.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        count += 1
    if count:
        _log.info(f"[PathNorm] normalized Windows paths in {count} registry file(s)")
    return count


if NORMALIZE_STORED_PATHS:
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
