"""
Agentic RAG Chatbot - Modern Dark UI
Clean, minimal, professional interface with dark theme.
"""
import os
import base64
import hashlib
import hmac
import time
from datetime import datetime
from pathlib import Path

# Load env first
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import streamlit as st
import pandas as pd
import bcrypt

# Page config - MUST be first
st.set_page_config(
    page_title="RAG Chatbot",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Authentication (session-based, no cookie component) ───
USERS = {
    "admin": {
        "name": "Admin User",
        "password_hash": "$2b$12$aashT0HWtKa0viUSRXAlL.Wd2Ic52tTfp/lHGQOU0SMSU0uHAydPq",
    },
    "user1": {
        "name": "User One",
        "password_hash": "$2b$12$Kpo/x8Bj2z8AJkA9B5WLmunOjcgW4NenroFGrsyCmGls8QV3UI5RC",
    },
    "user2": {
        "name": "User Two",
        "password_hash": "$2b$12$Kpo/x8Bj2z8AJkA9B5WLmunOjcgW4NenroFGrsyCmGls8QV3UI5RC",
    },
}


def _check_password(username: str, password: str) -> bool:
    """Verify password against bcrypt hash."""
    user = USERS.get(username)
    if not user:
        return False
    return bcrypt.checkpw(password.encode(), user["password_hash"].encode())


def _login_form():
    """Render login form and handle authentication."""
    st.markdown("### Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        if _check_password(username, password):
            st.session_state["authentication_status"] = True
            st.session_state["username"] = username
            st.session_state["name"] = USERS[username]["name"]
            st.rerun()
        else:
            st.session_state["authentication_status"] = False


def _logout():
    """Clear session and log out."""
    for key in ["authentication_status", "username", "name",
                "active_conversation_id", "_conversation_store"]:
        st.session_state.pop(key, None)
    st.query_params.clear()
    st.rerun()


# ── Session Token (persistent login across refreshes) ───

def _create_session_token(username: str) -> str:
    """Create HMAC-signed session token: username:expires:signature."""
    from src.config import SESSION_SECRET, SESSION_TTL
    expires = int(time.time()) + SESSION_TTL
    payload = f"{username}:{expires}"
    signature = hmac.new(
        SESSION_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:16]
    return f"{payload}:{signature}"


def _verify_session_token(token: str) -> str | None:
    """Verify token and return username if valid."""
    from src.config import SESSION_SECRET
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        username, expires_str, signature = parts
        if time.time() > int(expires_str):
            return None
        expected = hmac.new(
            SESSION_SECRET.encode(),
            f"{username}:{expires_str}".encode(),
            hashlib.sha256,
        ).hexdigest()[:16]
        if not hmac.compare_digest(signature, expected):
            return None
        return username
    except Exception:
        return None

# Dark theme CSS
st.markdown("""
<style>
    /* Force dark background everywhere */
    .stApp, .main, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background-color: #1a1a2e !important;
    }

    /* Main content area */
    .main .block-container {
        background-color: #1a1a2e !important;
        padding: 1rem 2rem 6rem 2rem;
        max-width: 900px;
        margin: 0 auto;
    }

    /* Hide default elements (keep header for sidebar toggle) */
    #MainMenu, footer {visibility: hidden;}
    .stDeployButton {display: none;}
    [data-testid="stHeader"] {background-color: #1a1a2e !important;}

    /* Sidebar - darker */
    [data-testid="stSidebar"] {
        background-color: #0f0f1a !important;
    }
    [data-testid="stSidebar"] > div:first-child {
        background-color: #0f0f1a !important;
    }
    [data-testid="stSidebar"] * {
        color: #e0e0e0 !important;
    }
    [data-testid="stSidebar"] .stButton button {
        background-color: #2d2d44 !important;
        border: 1px solid #404060 !important;
        color: #e0e0e0 !important;
        border-radius: 8px;
    }
    [data-testid="stSidebar"] .stButton button:hover {
        background-color: #3d3d5c !important;
        border-color: #10a37f !important;
    }

    /* File uploader in sidebar */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] {
        background-color: #1a1a2e !important;
        border: 1px dashed #404060 !important;
        border-radius: 8px;
        padding: 0.5rem;
    }

    /* All text white */
    p, span, label, .stMarkdown, h1, h2, h3, h4, h5, h6 {
        color: #e0e0e0 !important;
    }

    /* Chat input */
    .stChatInput > div {
        background-color: #2d2d44 !important;
        border: 1px solid #404060 !important;
        border-radius: 12px !important;
    }
    .stChatInput input {
        color: #e0e0e0 !important;
        background-color: transparent !important;
    }
    .stChatInput input::placeholder {
        color: #808080 !important;
    }

    /* Expander */
    .streamlit-expanderHeader {
        background-color: #2d2d44 !important;
        color: #e0e0e0 !important;
        border-radius: 8px;
    }
    .streamlit-expanderContent {
        background-color: #1f1f35 !important;
        border: 1px solid #404060 !important;
    }

    /* Metrics */
    [data-testid="stMetric"] {
        background-color: #2d2d44 !important;
        padding: 0.75rem;
        border-radius: 8px;
    }
    [data-testid="stMetricValue"] {
        color: #10a37f !important;
    }

    /* Dataframe */
    .stDataFrame {
        background-color: #2d2d44 !important;
    }

    /* Code blocks */
    .stCodeBlock {
        background-color: #0d0d15 !important;
    }
    code {
        background-color: #2d2d44 !important;
        color: #10a37f !important;
    }

    /* Buttons */
    .stButton > button {
        background-color: #10a37f !important;
        color: white !important;
        border: none !important;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-weight: 500;
    }
    .stButton > button:hover {
        background-color: #0d8a6a !important;
    }

    /* Success/Error messages */
    .stSuccess, .stError, .stWarning, .stInfo {
        background-color: #2d2d44 !important;
        color: #e0e0e0 !important;
    }

    /* Spinner */
    .stSpinner > div {
        border-color: #10a37f !important;
    }

    /* Tabs for dual LLM answers */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #2d2d44 !important;
        border-radius: 8px;
        padding: 0.25rem;
        gap: 0.25rem;
    }
    .stTabs [data-baseweb="tab"] {
        color: #e0e0e0 !important;
        background-color: transparent !important;
        border-radius: 6px;
        padding: 0.5rem 1rem;
    }
    .stTabs [aria-selected="true"] {
        background-color: #404060 !important;
        color: #10a37f !important;
    }
    .stTabs [data-baseweb="tab-panel"] {
        background-color: #1f1f35 !important;
        border: 1px solid #404060 !important;
        border-radius: 0 0 8px 8px;
        padding: 1rem;
    }
</style>
""", unsafe_allow_html=True)


def init_session():
    """Initialize session state."""
    defaults = {
        "messages": [],
        "docs_count": 0,
        "tables_count": 0,
        "initialized": False,
        "processed_files": set(),
        "uploaded_files_log": [],  # [{name, type, time, info}]
        "show_pdf_viewer": False,
        "pdf_path": None,
        "pdf_page": 1,
        "pdf_highlight": None,
        # OCR settings (fixed - English only, auto mode)
        "ocr_mode": "auto",
        "ocr_language": "eng",
        # Conversation management
        "active_conversation_id": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # Ensure user has an active conversation
    if (st.session_state.get("authentication_status")
            and st.session_state.get("active_conversation_id") is None):
        store = _get_conversation_store()
        conversations = store.list_conversations()
        if conversations:
            _switch_conversation(conversations[0].conversation_id)
        else:
            meta = store.create_conversation()
            st.session_state["active_conversation_id"] = meta.conversation_id


def check_api_keys():
    """Validate API keys at startup."""
    from src.config import validate_config

    is_valid, errors = validate_config()
    if not is_valid:
        st.error("⚠️ Configuration Error")
        for e in errors:
            st.warning(e)
        st.code("# Create .env file:\nGOOGLE_API_KEY=your_key\nPINECONE_API_KEY=your_key\nOPENAI_API_KEY=your_key\nANTHROPIC_API_KEY=your_key")
        st.stop()


def save_uploaded_file(uploaded_file, target_dir: Path) -> str:
    """Save uploaded file and return path."""
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / uploaded_file.name
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(file_path)


def process_unified_upload(uploaded_file):
    """Process any file type through unified file router."""
    from src.file_router import route_file, ProcessingResult
    from src.config import DOCUMENTS_DIR, TABLES_DIR, EMAILS_DIR

    ext = Path(uploaded_file.name).suffix.lower()

    # Dedup check
    key = f"{uploaded_file.name}_{uploaded_file.size}"
    if key in st.session_state.processed_files:
        return ProcessingResult(success=False, file_path="", file_type="duplicate")

    # Save to appropriate directory
    if ext in (".pdf", ".docx", ".doc", ".txt"):
        file_path = save_uploaded_file(uploaded_file, DOCUMENTS_DIR)
    elif ext in (".eml", ".msg"):
        file_path = save_uploaded_file(uploaded_file, EMAILS_DIR)
    else:
        file_path = save_uploaded_file(uploaded_file, TABLES_DIR)

    result = route_file(file_path)

    if result.success:
        st.session_state.processed_files.add(key)

        # Log uploaded file for sidebar display
        file_info = {
            "name": uploaded_file.name,
            "type": result.file_type,
            "time": datetime.now().strftime("%H:%M"),
        }
        if result.tables_extracted:
            file_info["tables"] = result.tables_extracted
        if result.total_rows:
            file_info["rows"] = result.total_rows
        if result.ocr_pages:
            file_info["ocr"] = result.ocr_pages
        if result.notice_extracted:
            file_info["notice"] = True
        if result.attachments_processed:
            file_info["attachments"] = result.attachments_processed
        st.session_state.uploaded_files_log.append(file_info)

        # Update counts
        if result.file_type == "document":
            try:
                from src.document_rag import get_document_rag
                rag = get_document_rag()
                stats = rag.pinecone_index.describe_index_stats()
                st.session_state.docs_count = stats.get("total_vector_count", 0)
            except Exception:
                st.session_state.docs_count += 1
        elif result.file_type == "data":
            st.session_state.tables_count += result.tables_extracted or 1
        elif result.file_type == "email":
            try:
                from src.document_rag import get_document_rag
                rag = get_document_rag()
                stats = rag.pinecone_index.describe_index_stats()
                st.session_state.docs_count = stats.get("total_vector_count", 0)
            except Exception:
                st.session_state.docs_count += 1
            if result.tables_extracted > 0:
                st.session_state.tables_count += result.tables_extracted

    return result


def _render_upload_result(filename: str, result):
    """Render upload result feedback in sidebar."""
    info_parts = []

    if result.file_type == "document":
        if result.ocr_pages > 0:
            info_parts.append(f"{result.ocr_pages} OCR")
        if result.tables_extracted > 0:
            info_parts.append(f"{result.tables_extracted} tables")
        if result.notice_extracted:
            info_parts.append("notice")

    elif result.file_type == "email":
        if result.attachments_processed > 0:
            info_parts.append(f"{result.attachments_processed} attachments")
        if result.notice_extracted:
            info_parts.append("notice")

    elif result.file_type == "data":
        if result.tables_extracted > 0:
            info_parts.append(f"{result.tables_extracted} tables")
        if result.total_rows > 0:
            info_parts.append(f"{result.total_rows} rows")
        if result.converter_generated:
            info_parts.append("converter generated")
        elif result.converter_used:
            info_parts.append("converter used")
        if result.target_schema:
            info_parts.append(f"schema: {result.target_schema}")

    info_str = f" ({', '.join(info_parts)})" if info_parts else ""
    st.success(f"✓ {filename}{info_str}")

    # Show notice summary
    if result.notice_summary:
        ns = result.notice_summary
        with st.expander(f"Notice: {filename}", expanded=False):
            if ns.get('date'):
                st.write(f"**Date:** {ns['date']}")
            if ns.get('sender'):
                st.write(f"**From:** {ns['sender'][:50]}")
            if ns.get('recipient'):
                st.write(f"**To:** {ns['recipient'][:50]}")
            if ns.get('subject'):
                st.write(f"**Subject:** {ns['subject'][:80]}")
            if ns.get('actions'):
                st.write(f"**Actions:** {', '.join(ns['actions'][:3])}")

    # Offer template save for data files
    if result.file_type == "data" and not result.converter_used:
        _render_save_template_button(filename)


def process_upload(uploaded_file, file_type: str) -> dict:
    """
    Process an uploaded file.

    Returns:
        dict with keys: success, ocr_pages (for PDFs), tables_extracted, total_rows, notice_extracted
    """
    from src.document_rag import get_document_rag
    from src.data_analyzer_sql import get_data_analyzer
    from src.config import DOCUMENTS_DIR, TABLES_DIR

    result = {
        "success": False,
        "ocr_pages": 0,
        "tables_extracted": 0,
        "total_rows": 0,
        "notice_extracted": False,
        "notice_summary": None,
    }

    key = f"{uploaded_file.name}_{uploaded_file.size}"
    if key in st.session_state.processed_files:
        return result

    if file_type == "document":
        file_path = save_uploaded_file(uploaded_file, DOCUMENTS_DIR)
        rag = get_document_rag()

        # Get OCR settings from session state
        ocr_mode = st.session_state.get("ocr_mode", "auto")
        ocr_language = st.session_state.get("ocr_language", "eng")

        try:
            new_docs = rag.add_document(file_path, ocr_mode=ocr_mode, ocr_language=ocr_language)
        except Exception as e:
            print(f"[Upload] add_document error for {uploaded_file.name}: {e}")
            st.error(f"Error processing {uploaded_file.name}: {e}")
            new_docs = None

        if new_docs:
            try:
                rag.insert_documents(new_docs)
            except Exception as e:
                print(f"[Upload] insert_documents error: {e}")
                st.error(f"Error indexing {uploaded_file.name}: {e}")

            st.session_state.processed_files.add(key)

            # Get OCR stats
            file_info = rag.file_registry.get(uploaded_file.name, {})
            result["ocr_pages"] = file_info.get("ocr_pages", 0)
            result["success"] = True

            # Refresh docs_count from Pinecone (shared truth)
            try:
                stats = rag.pinecone_index.describe_index_stats()
                st.session_state.docs_count = stats.get("total_vector_count", 0)
            except Exception:
                st.session_state.docs_count += 1

            # Extract notice metadata (Phase 2)
            try:
                from src.table_ingestion import extract_document_notice
                from src.document_rag import generate_doc_id

                # Build doc_text_by_page from parsed documents
                doc_text_by_page = {}
                for doc in rag.documents:
                    if doc.metadata.get("file_name") == uploaded_file.name:
                        page_num = doc.metadata.get("page_number", 1)
                        doc_text_by_page[page_num] = doc.text

                if doc_text_by_page:
                    doc_id = generate_doc_id(file_path)
                    notice_summary = extract_document_notice(
                        doc_id=doc_id,
                        file_path=file_path,
                        doc_text_by_page=doc_text_by_page,
                        use_llm=False,  # Regex-only for speed
                    )
                    if notice_summary:
                        result["notice_extracted"] = True
                        result["notice_summary"] = notice_summary
            except Exception as e:
                print(f"[Notice Extraction] Error: {e}")

            # Try table extraction for PDFs
            if uploaded_file.name.lower().endswith('.pdf'):
                try:
                    from src.table_ingestion import ingest_file
                    ingestion_result = ingest_file(file_path)
                    result["tables_extracted"] = ingestion_result.tables_extracted
                    result["total_rows"] = ingestion_result.total_rows

                    # Load extracted tables into analyzer
                    if ingestion_result.tables_extracted > 0:
                        analyzer = get_data_analyzer()
                        analyzer.load_from_catalog()
                except Exception as e:
                    print(f"[Table Extraction] Error: {e}")
    else:
        file_path = save_uploaded_file(uploaded_file, TABLES_DIR)
        analyzer = get_data_analyzer()

        # First try table extraction to parquet
        try:
            from src.table_ingestion import ingest_file
            ingestion_result = ingest_file(file_path)
            result["tables_extracted"] = ingestion_result.tables_extracted
            result["total_rows"] = ingestion_result.total_rows

            # Load from catalog
            if ingestion_result.tables_extracted > 0:
                analyzer.load_from_catalog()
                st.session_state.tables_count += ingestion_result.tables_extracted
                st.session_state.processed_files.add(key)
                result["success"] = True
                print(f"[Data Upload] {uploaded_file.name}: {ingestion_result.tables_extracted} tables, {ingestion_result.total_rows} rows via catalog")
            else:
                # Fallback to direct loading
                if analyzer.load_file(file_path):
                    st.session_state.tables_count += 1
                    st.session_state.processed_files.add(key)
                    result["success"] = True
                    print(f"[Data Upload] {uploaded_file.name}: loaded directly (fallback)")
                else:
                    print(f"[Data Upload] {uploaded_file.name}: ingest returned 0 tables, direct load also failed")
                    st.error(f"Could not extract tables from {uploaded_file.name}")
        except ImportError:
            # Fallback if table_ingestion not available
            if analyzer.load_file(file_path):
                st.session_state.tables_count += 1
                st.session_state.processed_files.add(key)
                result["success"] = True
                print(f"[Data Upload] {uploaded_file.name}: loaded directly (no table_ingestion)")
        except Exception as e:
            print(f"[Data Upload] Error processing {uploaded_file.name}: {e}")
            # Last resort: try direct loading
            try:
                if analyzer.load_file(file_path):
                    st.session_state.tables_count += 1
                    st.session_state.processed_files.add(key)
                    result["success"] = True
                    print(f"[Data Upload] {uploaded_file.name}: loaded directly after error")
                else:
                    st.error(f"Error loading {uploaded_file.name}: {e}")
            except Exception as e2:
                print(f"[Data Upload] Direct load also failed: {e2}")
                st.error(f"Error loading {uploaded_file.name}: {e2}")

    return result


def load_project_files():
    """Load files from project folders."""
    from src.document_rag import get_document_rag
    from src.data_analyzer_sql import get_data_analyzer

    rag = get_document_rag()
    analyzer = get_data_analyzer()
    base = Path(__file__).parent

    doc_count = 0
    data_count = 0

    for folder in base.iterdir():
        if folder.is_dir() and not folder.name.startswith((".", "src", "storage", "__")):
            doc_count += rag.add_documents_from_folder(str(folder))
            data_count += analyzer.load_files_from_folder(str(folder))

    if doc_count > 0:
        rag.build_index()

    st.session_state.docs_count = len(rag.file_registry)
    st.session_state.tables_count = len(analyzer.list_tables())
    st.session_state.initialized = True

    return doc_count, data_count


def _render_save_template_button(file_name: str):
    """Show 'Save as Template' option after successful data file upload."""
    btn_key = f"save_tmpl_{file_name}"
    form_key = f"tmpl_form_{file_name}"

    if st.button("Save as Template", key=btn_key, use_container_width=True):
        st.session_state[f"_show_tmpl_form_{file_name}"] = True

    if st.session_state.get(f"_show_tmpl_form_{file_name}"):
        with st.form(form_key):
            tmpl_name = st.text_input("Template Name", value=f"{Path(file_name).stem} Format")
            tmpl_category = st.selectbox(
                "Category",
                ["dpr", "invoice", "manpower", "progress", "mep", "custom"],
                index=5,
            )
            submitted = st.form_submit_button("Create Template")

        if submitted:
            try:
                from src.config import TABLES_DIR
                from src.excel_table_extractor import ExcelTableExtractor
                from src.template_store import get_template_store

                file_path = str(TABLES_DIR / file_name)
                extractor = ExcelTableExtractor()
                tables = extractor.extract_tables(file_path)

                if tables:
                    from openpyxl import load_workbook
                    wb = load_workbook(file_path, read_only=False, data_only=True)
                    template = extractor.create_template_from_extraction(
                        tables=tables,
                        file_path=file_path,
                        sheet_names=wb.sheetnames,
                        template_name=tmpl_name,
                        category=tmpl_category,
                    )
                    wb.close()

                    store = get_template_store()
                    store.add_template(template)
                    st.success(f"Template '{tmpl_name}' created!")
                    st.session_state.pop(f"_show_tmpl_form_{file_name}", None)
                else:
                    st.warning("No tables found to create template from.")
            except Exception as e:
                st.error(f"Template creation failed: {e}")
                print(f"[Template] Error creating template from {file_name}: {e}")


def _render_template_management():
    """Render template management section in sidebar (admin only)."""
    try:
        from src.template_store import get_template_store
        store = get_template_store()
    except Exception:
        return

    templates = store.list_templates()
    if not templates:
        return

    st.markdown("---")
    st.markdown("### Templates")

    for t in templates:
        tid = t["template_id"]
        with st.expander(f"{t['name']} ({t['category']})", expanded=False):
            st.caption(f"Source: {t['source_file']}")
            st.caption(f"Sheets: {t['sheet_count']} | Matches: {t['match_count']} | v{t['version']}")
            if st.button("Delete", key=f"del_{tid}"):
                store.remove_template(tid)
                st.rerun()


def _render_converter_management():
    """Render converter management section in sidebar (admin only)."""
    try:
        from src.converter_registry import get_converter_registry
        registry = get_converter_registry()
    except Exception:
        return

    converters = registry.list_converters()
    if not converters:
        return

    st.markdown("---")
    st.markdown("### Converters")

    for c in converters:
        cid = c["converter_id"]
        label = f"{c['company_name']} -> {c['target_schema']}"
        with st.expander(label, expanded=False):
            st.caption(f"Version: {c['version']} | Test: {'Pass' if c['test_passed'] else 'Fail'}")
            if c.get("sample_files"):
                st.caption(f"Sample: {', '.join(c['sample_files'][:2])}")
            if st.button("Delete", key=f"del_conv_{cid}"):
                registry.remove_converter(cid)
                st.rerun()


def _gather_uploaded_files() -> list:
    """Gather all uploaded file names from RAG registry + catalog."""
    files = []
    seen = set()

    # Documents from RAG file_registry
    try:
        from src.document_rag import get_document_rag
        rag = get_document_rag()
        for fname, info in rag.file_registry.items():
            if fname not in seen:
                seen.add(fname)
                files.append({
                    "name": fname,
                    "type": "document",
                    "time": "",
                    "ocr": info.get("ocr_pages", 0),
                })
    except Exception:
        pass

    # Data files from catalog
    try:
        from src.catalog import get_catalog
        catalog = get_catalog()
        for entry in catalog.entries.values():
            fname = Path(entry.source_file).name
            if fname not in seen:
                seen.add(fname)
                total_rows = sum(t.row_count for t in entry.tables)
                files.append({
                    "name": fname,
                    "type": "data",
                    "time": "",
                    "tables": len(entry.tables),
                    "rows": total_rows,
                })
    except Exception:
        pass

    return files


def _render_uploaded_files():
    """Render scrollable uploaded files list + Export Excel button in sidebar."""
    # On first call, gather existing files from sources
    if not st.session_state.uploaded_files_log:
        existing = _gather_uploaded_files()
        if existing:
            st.session_state.uploaded_files_log = existing

    files_log = st.session_state.uploaded_files_log
    if not files_log:
        return

    st.markdown("---")
    st.markdown(f"### Uploaded Files ({len(files_log)})")

    # Scrollable container with file names
    file_list_html = ""
    for f in files_log:
        # Icon by type
        icon = {"document": "📄", "email": "📧", "data": "📊"}.get(f["type"], "📁")

        # Info chips
        chips = []
        if f.get("ocr"):
            chips.append(f'{f["ocr"]} OCR')
        if f.get("tables"):
            chips.append(f'{f["tables"]} tbl')
        if f.get("rows"):
            chips.append(f'{f["rows"]} rows')
        if f.get("notice"):
            chips.append("notice")
        if f.get("attachments"):
            chips.append(f'{f["attachments"]} att')
        chip_str = f' <span style="color:#10a37f;font-size:0.7rem;">({", ".join(chips)})</span>' if chips else ""

        time_str = f' <span style="color:#808080;font-size:0.7rem;">{f["time"]}</span>' if f.get("time") else ""

        file_list_html += (
            f'<div style="padding:4px 8px;border-bottom:1px solid #2d2d44;'
            f'font-size:0.82rem;color:#e0e0e0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
            f'{icon} {f["name"]}{chip_str}{time_str}</div>'
        )

    st.markdown(
        f'<div style="max-height:200px;overflow-y:auto;background:#1a1a2e;'
        f'border:1px solid #404060;border-radius:8px;">{file_list_html}</div>',
        unsafe_allow_html=True,
    )

    # Export Excel button
    if st.button("Export Excel", key="export_files_excel", use_container_width=True):
        import io
        rows = []
        for f in files_log:
            rows.append({
                "File Name": f["name"],
                "Type": f["type"],
                "Upload Time": f.get("time", ""),
                "Tables": f.get("tables", ""),
                "Rows": f.get("rows", ""),
                "OCR Pages": f.get("ocr", ""),
                "Notice": "Yes" if f.get("notice") else "",
                "Attachments": f.get("attachments", ""),
            })
        df_export = pd.DataFrame(rows)
        buf = io.BytesIO()
        df_export.to_excel(buf, index=False, sheet_name="Uploaded Files")
        buf.seek(0)
        st.download_button(
            label="Download Excel",
            data=buf,
            file_name=f"uploaded_files_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_files_excel",
        )


def _get_conversation_store():
    """Get ConversationStore for current user (cached in session_state)."""
    username = st.session_state.get("username", "anonymous")
    key = "_conversation_store"
    if key not in st.session_state or st.session_state[key].username != username:
        from src.conversation_store import ConversationStore
        st.session_state[key] = ConversationStore(username)
    return st.session_state[key]


def _switch_conversation(conv_id: str):
    """Load a conversation into session state."""
    store = _get_conversation_store()
    conv = store.get_conversation(conv_id)
    if conv:
        st.session_state["active_conversation_id"] = conv_id
        st.session_state["messages"] = [
            {
                "role": m.role,
                "content": m.content,
                "query_type": m.query_type or "",
                "sources": m.sources or [],
                "sql": m.sql,
                "result_data": m.result_data,
                "dual_answers": m.dual_answers,
            }
            for m in conv.messages
        ]


def render_conversation_sidebar():
    """Render conversation list and management in sidebar."""
    store = _get_conversation_store()

    # New Chat button
    if st.button("+ New Chat", use_container_width=True, key="new_chat"):
        meta = store.create_conversation()
        st.session_state["active_conversation_id"] = meta.conversation_id
        st.session_state["messages"] = []
        st.rerun()

    conversations = store.list_conversations()
    active_id = st.session_state.get("active_conversation_id")

    for conv in conversations:
        is_active = conv.conversation_id == active_id
        col1, col2 = st.columns([0.85, 0.15])

        with col1:
            label = conv.title[:35]
            if len(conv.title) > 35:
                label += "..."
            btn_type = "primary" if is_active else "secondary"
            if st.button(
                label,
                key=f"conv_{conv.conversation_id}",
                use_container_width=True,
                type=btn_type,
            ):
                if not is_active:
                    _switch_conversation(conv.conversation_id)
                    st.rerun()

        with col2:
            if st.button("X", key=f"del_{conv.conversation_id}"):
                store.delete_conversation(conv.conversation_id)
                if active_id == conv.conversation_id:
                    remaining = store.list_conversations()
                    if remaining:
                        _switch_conversation(remaining[0].conversation_id)
                    else:
                        new_meta = store.create_conversation()
                        st.session_state["active_conversation_id"] = new_meta.conversation_id
                        st.session_state["messages"] = []
                st.rerun()

        # Inline rename (admin/user can double-click title)
        if st.session_state.get(f"_renaming_{conv.conversation_id}"):
            new_name = st.text_input(
                "Rename",
                value=conv.title,
                key=f"rename_input_{conv.conversation_id}",
                label_visibility="collapsed",
            )
            if st.button("Save", key=f"save_rename_{conv.conversation_id}"):
                store.rename_conversation(conv.conversation_id, new_name)
                st.session_state.pop(f"_renaming_{conv.conversation_id}", None)
                st.rerun()


def render_sidebar():
    """Render sidebar."""
    with st.sidebar:
        st.markdown("## 💬 RAG Chatbot")
        st.caption("Hybrid document & data analysis")

        st.markdown("---")

        # Conversation management
        render_conversation_sidebar()

        st.markdown("---")

        # Unified file upload
        st.markdown("### 📁 Upload Files")
        all_files = st.file_uploader(
            "All file types",
            type=["pdf", "docx", "doc", "txt", "xlsx", "xls", "csv", "eml", "msg"],
            accept_multiple_files=True,
            key="unified_upload",
            label_visibility="collapsed",
        )

        if all_files:
            progress = st.progress(0, text="Processing files...")
            for i, f in enumerate(all_files):
                progress.progress(
                    (i) / len(all_files),
                    text=f"Processing {f.name} ({i+1}/{len(all_files)})...",
                )
                result = process_unified_upload(f)
                if result.success:
                    _render_upload_result(f.name, result)
                elif result.file_type != "duplicate" and result.error:
                    st.warning(f"Could not process {f.name}: {result.error}")
            progress.progress(1.0, text="All files processed.")
            progress.empty()

        st.markdown("---")

        if st.button("📂 Load Project Files", use_container_width=True):
            with st.spinner("Loading..."):
                docs, tables = load_project_files()
            st.success(f"Loaded {docs} docs, {tables} tables")

        st.markdown("---")

        # Stats - live counts from singletons
        vec_count = st.session_state.docs_count
        try:
            from src.document_rag import get_document_rag
            rag = get_document_rag()
            stats = rag.pinecone_index.describe_index_stats()
            vec_count = stats.get("total_vector_count", 0)
            st.session_state.docs_count = vec_count
        except Exception:
            pass

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Vectors", vec_count)
        with col2:
            st.metric("Tables", st.session_state.tables_count)

        # Uploaded files list (all users can see)
        _render_uploaded_files()

        # Template & converter management (admin only)
        is_admin = st.session_state.get("username") == "admin"
        if is_admin:
            _render_template_management()
            _render_converter_management()

        # Admin-only: Clear all data (Pinecone + notices + graph)
        if is_admin:
            st.markdown("---")
            if st.button("🧹 Clear All Data", use_container_width=True):
                from src.document_rag import get_document_rag
                from src.notice_extractor import NOTICES_DIR
                from src.light_graph import GRAPH_DIR, get_light_graph

                rag = get_document_rag()
                rag.clear_index()

                # Clear notice JSON files
                for f in NOTICES_DIR.glob("*.json"):
                    f.unlink()

                # Clear graph JSON files
                for f in GRAPH_DIR.glob("*.json"):
                    f.unlink()

                # Reset light graph singleton
                graph = get_light_graph()
                graph.graph.nodes = {}
                graph.graph.edges = []
                graph._sync_notices_to_duckdb()

                # Clear table catalog (local + GCS)
                try:
                    from src.catalog import get_catalog
                    get_catalog().clear_all()
                except Exception:
                    pass

                st.session_state.docs_count = 0
                st.session_state.tables_count = 0
                st.session_state.processed_files = set()
                st.session_state.uploaded_files_log = []
                st.session_state.messages = []
                st.session_state["_startup_synced"] = False

                # Reset current conversation
                conv_id = st.session_state.get("active_conversation_id")
                if conv_id:
                    conv_store = _get_conversation_store()
                    conv_store.delete_conversation(conv_id)
                    new_meta = conv_store.create_conversation()
                    st.session_state["active_conversation_id"] = new_meta.conversation_id

                st.rerun()


def render_pdf_viewer():
    """Render PDF page viewer with highlighting."""
    if not st.session_state.show_pdf_viewer:
        return

    file_path = st.session_state.pdf_path
    page_num = st.session_state.pdf_page
    highlight = st.session_state.pdf_highlight

    # Ensure page_num is an integer
    try:
        page_num = int(page_num)
    except (ValueError, TypeError):
        page_num = 1

    print(f"[PDF Viewer] Opening: {file_path}, Page: {page_num}, Highlight: {highlight[:50] if highlight else 'None'}...")

    if not file_path or not os.path.exists(file_path):
        st.error("PDF file not found")
        print(f"[PDF Viewer] ERROR: File not found: {file_path}")
        return

    st.markdown("---")

    # Header
    col1, col2 = st.columns([0.85, 0.15])
    with col1:
        st.markdown(f"### 📄 {Path(file_path).name} - Page {page_num}")
    with col2:
        if st.button("✕ Close"):
            st.session_state.show_pdf_viewer = False
            st.rerun()

    # Show highlighted reference text
    if highlight:
        st.info(f"🔍 **Referenced text:** \"{highlight[:200]}{'...' if len(highlight) > 200 else ''}\"")

    # Render PDF page
    try:
        import fitz

        doc = fitz.open(file_path)
        total_pages = len(doc)
        print(f"[PDF Viewer] Total pages: {total_pages}, Requested page: {page_num}")

        if page_num < 1 or page_num > total_pages:
            print(f"[PDF Viewer] Page out of range, resetting to 1")
            page_num = 1

        page = doc[page_num - 1]  # fitz uses 0-based index
        print(f"[PDF Viewer] Rendering page index: {page_num - 1}")

        # Highlight the reference text with light blue
        highlight_found = False
        if highlight and len(highlight) > 5:
            # Clean up highlight text for search
            clean_highlight = highlight.replace('\n', ' ').replace('  ', ' ').strip()

            # Try multiple search strategies
            search_attempts = []

            # Split into sentences and try each
            sentences = [s.strip() for s in clean_highlight.split('. ') if len(s.strip()) > 10]
            for sent in sentences[:3]:  # Try first 3 sentences
                search_attempts.append(sent[:80])
                search_attempts.append(sent[:50])

            # Also try beginning of full text
            search_attempts.extend([
                clean_highlight[:100],
                clean_highlight[:70],
                clean_highlight[:50],
                clean_highlight[:30],
            ])

            # Remove duplicates while preserving order
            seen = set()
            unique_attempts = []
            for s in search_attempts:
                if s and s not in seen and len(s) > 5:
                    seen.add(s)
                    unique_attempts.append(s)

            print(f"[PDF Viewer] Trying {len(unique_attempts)} search terms...")

            for term in unique_attempts:
                instances = page.search_for(term)
                if instances:
                    print(f"[PDF Viewer] Found {len(instances)} matches for: '{term[:40]}...'")
                    for inst in instances:
                        # Light blue highlight (RGB: 0.6, 0.8, 1.0 - soft blue)
                        annot = page.add_highlight_annot(inst)
                        annot.set_colors(stroke=(0.4, 0.7, 1.0))  # Brighter blue
                        annot.set_opacity(0.4)
                        annot.update()
                    highlight_found = True
                    break

            if not highlight_found:
                print(f"[PDF Viewer] No matches found for any search terms")

        # Render to image at higher resolution for clarity
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        doc.close()

        # Display
        st.image(img_bytes, use_container_width=True)
        st.caption(f"Page {page_num} of {total_pages}")

        if highlight and not highlight_found:
            st.warning("⚠️ Could not locate the exact text on this page for highlighting.")

        # Download
        with open(file_path, "rb") as f:
            st.download_button("⬇️ Download PDF", f, Path(file_path).name, "application/pdf")

    except Exception as e:
        st.error(f"Error rendering PDF: {e}")
        print(f"[PDF Viewer] ERROR: {e}")

    st.markdown("---")


def render_user_message(content: str):
    """Render user message bubble."""
    st.markdown(f"""
    <div style="display: flex; justify-content: flex-end; margin: 1rem 0;">
        <div style="background: linear-gradient(135deg, #10a37f, #0d8a6a);
                    color: white;
                    padding: 1rem 1.25rem;
                    border-radius: 1.25rem 1.25rem 0.25rem 1.25rem;
                    max-width: 80%;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.3);">
            {content}
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_assistant_message(content: str, query_type: str = ""):
    """Render assistant message bubble."""
    # Badge colors
    badge_styles = {
        "document": "background: #1e40af; color: #93c5fd;",
        "data": "background: #166534; color: #86efac;",
        "hybrid": "background: #92400e; color: #fcd34d;",
    }
    badge_style = badge_styles.get(query_type, "")
    badge_html = f'<span style="{badge_style} padding: 0.2rem 0.6rem; border-radius: 1rem; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-bottom: 0.5rem; display: inline-block;">{query_type}</span><br>' if query_type else ""

    st.markdown(f"""
    <div style="display: flex; justify-content: flex-start; margin: 1rem 0;">
        <div style="background: #2d2d44;
                    color: #e0e0e0;
                    padding: 1rem 1.25rem;
                    border-radius: 1.25rem 1.25rem 1.25rem 0.25rem;
                    max-width: 80%;
                    border: 1px solid #404060;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.3);">
            {badge_html}
            {content}
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_sources(sources: list, msg_idx: int):
    """Render sources with view buttons."""
    if not sources:
        return

    with st.expander(f"📚 Sources ({len(sources)})", expanded=False):
        for i, src in enumerate(sources):
            src_type = src.get("type", "")

            if src_type == "structured_data":
                # Data source
                table_name = src.get("table_name", src.get("file_name", "Unknown"))
                rows = src.get("row_count_returned", 0)
                total = src.get("total_rows", 0)
                sql = src.get("sql_query", "")

                st.markdown(f"""
                **📊 {table_name}**
                - Rows returned: {rows} / {total}
                """)
                if sql:
                    st.code(sql, language="sql")

            else:
                # Document source
                file_name = src.get("file_name", "Unknown")
                page = src.get("page_number", 1)
                total_pages = src.get("total_pages", 1)
                highlight = src.get("highlight_text", "")
                file_path = src.get("file_path", "")
                score = src.get("score")

                # Ensure page is an integer
                try:
                    page = int(page)
                except (ValueError, TypeError):
                    page = 1

                print(f"[Sources] Doc: {file_name}, Page: {page}, Path exists: {os.path.exists(file_path) if file_path else False}")

                st.markdown(f"""
                **📄 {file_name}** - Page {page}/{total_pages}
                {f'(Score: {score})' if score else ''}
                """)

                if highlight:
                    st.markdown(f"> *\"{highlight[:200]}{'...' if len(highlight) > 200 else ''}\"*")

                # View button
                if file_path and os.path.exists(file_path) and file_path.lower().endswith('.pdf'):
                    if st.button(f"👁️ View Page {page}", key=f"view_{msg_idx}_{i}"):
                        print(f"[Sources] Button clicked - Setting PDF viewer: path={file_path}, page={page}")
                        st.session_state.show_pdf_viewer = True
                        st.session_state.pdf_path = file_path
                        st.session_state.pdf_page = int(page)  # Ensure integer
                        st.session_state.pdf_highlight = highlight
                        st.rerun()

            st.markdown("---")


def render_provider_answer(answer: dict, provider: str, msg_idx: int, tab_idx: int):
    """Render a single provider's answer inside a tab."""
    if not answer:
        st.warning(f"No response from {provider}")
        return

    # Provider badge
    badge_colors = {
        "gemini": ("background: #4285f4; color: white;", "gemini"),
        "openai": ("background: #10a37f; color: white;", "OpenAI"),
        "claude": ("background: #d97706; color: white;", "Claude"),
    }
    style, label = badge_colors.get(provider, ("background: #555; color: white;", provider))
    st.markdown(
        f'<span style="{style} padding: 0.25rem 0.75rem; border-radius: 1rem; '
        f'font-size: 0.75rem; font-weight: 600;">{label}</span>',
        unsafe_allow_html=True,
    )

    # Answer text
    answer_text = answer.get("answer", answer.get("error", "No answer"))
    st.markdown(answer_text)

    # Sources
    sources = answer.get("sources", [])
    if sources:
        render_sources(sources, msg_idx * 100 + tab_idx)

    # SQL query
    sql = answer.get("sql")
    if sql:
        with st.expander("🔍 SQL Query"):
            st.code(sql, language="sql")

    # Result data
    result_data = answer.get("result_data")
    if result_data:
        with st.expander("📊 Data Results"):
            df = pd.DataFrame(result_data)
            st.dataframe(df, use_container_width=True, hide_index=True)

    # Error
    error = answer.get("error")
    if error and not answer.get("answer"):
        st.error(f"Error: {error}")


def render_dual_answers(msg: dict, idx: int):
    """Render dual-provider answers in tabs."""
    answers = msg.get("dual_answers", {})
    query_type = msg.get("query_type", "")

    # Query type badge
    badge_styles = {
        "document": "background: #1e40af; color: #93c5fd;",
        "data": "background: #166534; color: #86efac;",
        "hybrid": "background: #92400e; color: #fcd34d;",
    }
    badge_style = badge_styles.get(query_type, "")
    if badge_style:
        st.markdown(
            f'<span style="{badge_style} padding: 0.2rem 0.6rem; border-radius: 1rem; '
            f'font-size: 0.7rem; font-weight: 600; text-transform: uppercase;">'
            f'{query_type}</span>',
            unsafe_allow_html=True,
        )

    # Build tabs dynamically from available providers
    from src.config import LLM_PROVIDERS, GEMINI_MODEL, OPENAI_MODEL, ANTHROPIC_MODEL

    provider_labels = {
        "gemini": f"Gemini ({GEMINI_MODEL})",
        "openai": f"OpenAI ({OPENAI_MODEL})",
        "claude": f"Claude ({ANTHROPIC_MODEL})",
    }
    active_providers = [p for p in LLM_PROVIDERS if p in answers]
    if not active_providers:
        active_providers = list(answers.keys())

    tab_names = [provider_labels.get(p, p) for p in active_providers]
    tabs = st.tabs(tab_names)

    for tab, prov in zip(tabs, active_providers):
        with tab:
            render_provider_answer(answers.get(prov, {}), prov, idx, active_providers.index(prov))


def render_message(msg: dict, idx: int):
    """Render a chat message."""
    if msg["role"] == "user":
        render_user_message(msg["content"])
    elif msg.get("dual_answers"):
        render_dual_answers(msg, idx)
    else:
        render_assistant_message(msg["content"], msg.get("query_type", ""))

        # Sources
        sources = msg.get("sources", [])
        if sources:
            render_sources(sources, idx)

        # SQL query
        sql = msg.get("sql")
        if sql:
            with st.expander("🔍 SQL Query"):
                st.code(sql, language="sql")

        # Result data
        result_data = msg.get("result_data")
        if result_data:
            with st.expander("📊 Data Results"):
                df = pd.DataFrame(result_data)
                st.dataframe(df, use_container_width=True, hide_index=True)


def render_welcome():
    """Render welcome screen."""
    st.markdown("# 💬 RAG Chatbot")
    st.markdown("*Ask questions about your documents and data*")

    st.markdown("---")

    # Feature cards using columns
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("""
        ### 📄 Documents
        Search contracts, reports, policies with **page-level citations**
        """)

    with col2:
        st.markdown("""
        ### 📊 Data Analysis
        Calculate, filter, aggregate Excel & CSV with **safe SQL**
        """)

    with col3:
        st.markdown("""
        ### 🔀 Hybrid
        Combine document context with data calculations
        """)

    st.markdown("---")

    st.markdown("### 💡 Example Questions")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        **Document Questions:**
        - What are the payment terms?
        - Summarize the contract liabilities
        - What conditions are mentioned?
        - Sözleşmedeki maddeler nelerdir?
        """)

    with col2:
        st.markdown("""
        **Data Questions:**
        - Calculate total by category
        - What is the average value?
        - Show top 10 by amount
        - Toplam değer nedir?
        """)


def handle_input(user_input: str):
    """Process user input with conversation persistence and chat memory."""
    from src.router import get_router
    from src.config import LLM_PROVIDERS, CHAT_MEMORY_MESSAGES, CHAT_MEMORY_MAX_CHARS
    from src.conversation_store import Message, format_chat_context

    store = _get_conversation_store()
    conv_id = st.session_state.get("active_conversation_id")

    # 1. Save user message to store
    now = datetime.now().isoformat()
    user_msg = Message(role="user", content=user_input, timestamp=now)
    if conv_id:
        store.add_message(conv_id, user_msg)

    # 2. Add to session state for immediate display
    st.session_state.messages.append({
        "role": "user",
        "content": user_input,
    })

    # 3. Build context-augmented query from recent messages
    if conv_id:
        recent = store.get_recent_messages(conv_id, CHAT_MEMORY_MESSAGES)
        # Exclude the just-added user message from context
        context_msgs = recent[:-1] if recent else []
        context = format_chat_context(context_msgs, CHAT_MEMORY_MESSAGES, CHAT_MEMORY_MAX_CHARS)
    else:
        context = ""
    augmented_query = f"{context}\n\nCurrent question: {user_input}" if context else user_input

    # 4. Route and execute
    router = get_router()

    if len(LLM_PROVIDERS) >= 2:
        # Dual-LLM mode
        result = router.route_and_execute_dual(augmented_query)
        answers = result.get("answers", {})
        assistant_dict = {
            "role": "assistant",
            "content": "",
            "dual_answers": answers,
            "query_type": result.get("query_type", ""),
        }
    else:
        # Single-LLM mode
        result = router.route_and_execute(augmented_query)
        assistant_dict = {
            "role": "assistant",
            "content": result.get("answer", "No answer"),
            "query_type": result.get("query_type", ""),
            "sources": result.get("sources", []),
            "sql": result.get("sql"),
            "result_data": result.get("result_data"),
        }

    st.session_state.messages.append(assistant_dict)

    # 5. Save assistant message to store
    if conv_id:
        assistant_msg = Message(
            role="assistant",
            content=assistant_dict.get("content", ""),
            timestamp=datetime.now().isoformat(),
            query_type=assistant_dict.get("query_type"),
            sources=assistant_dict.get("sources"),
            sql=assistant_dict.get("sql"),
            result_data=assistant_dict.get("result_data"),
            dual_answers=assistant_dict.get("dual_answers"),
        )
        store.add_message(conv_id, assistant_msg)

        # 6. Auto-title on first message
        conv_meta = next(
            (c for c in store.list_conversations()
             if c.conversation_id == conv_id), None
        )
        if conv_meta and conv_meta.title == "New Chat":
            store.auto_title(conv_id, user_input)


def main():
    """Main application with authentication gate."""
    # ── Persistent login: restore from session token ──
    params = st.query_params
    token = params.get("session_token")
    if token and not st.session_state.get("authentication_status"):
        username = _verify_session_token(token)
        if username and username in USERS:
            st.session_state["authentication_status"] = True
            st.session_state["username"] = username
            st.session_state["name"] = USERS[username]["name"]

    # ── Login gate ──
    if not st.session_state.get("authentication_status"):
        _login_form()
        if st.session_state.get("authentication_status") is False:
            st.error("Kullanici adi veya sifre hatali.")
        return

    # Set session token in URL (survives refresh)
    if "session_token" not in params:
        st.query_params["session_token"] = _create_session_token(
            st.session_state["username"]
        )

    # ── Authenticated ──
    init_session()
    check_api_keys()

    # Auto-sync shared state on first session (all users get admin's uploads)
    if not st.session_state.get("_startup_synced"):
        try:
            from src.document_rag import get_document_rag
            rag = get_document_rag()
            stats = rag.pinecone_index.describe_index_stats()
            vec_count = stats.get("total_vector_count", 0)
            if vec_count > 0:
                if not rag.index:
                    rag.load_index()
                st.session_state.docs_count = vec_count
                print(f"[Startup] Loaded {vec_count} vectors from Pinecone")

            # Rebuild light graph from saved notices (timeline support)
            from src.light_graph import get_light_graph
            graph = get_light_graph()
            if not graph.graph.nodes:
                graph.rebuild_from_notices()
                if graph.graph.nodes:
                    print(f"[Startup] Rebuilt graph: {len(graph.graph.nodes)} notices")

            # Download tables from GCS (persistent across deploys)
            try:
                from src.gcs_storage import (
                    sync_catalog_from_gcs, sync_all_parquets_from_gcs,
                    sync_user_conversations_from_gcs,
                )
                sync_catalog_from_gcs()
                sync_all_parquets_from_gcs()
                # Sync conversations for current user
                username = st.session_state.get("username")
                if username:
                    sync_user_conversations_from_gcs(username)
            except Exception as gcs_err:
                print(f"[Startup] GCS sync: {gcs_err}")

            # Reload tables from catalog
            from src.data_analyzer_sql import get_data_analyzer
            analyzer = get_data_analyzer()
            if not analyzer.list_tables():
                loaded = analyzer.load_from_catalog()
                if loaded > 0:
                    print(f"[Startup] Reloaded {loaded} tables from catalog")
            st.session_state.tables_count = len(analyzer.list_tables())
        except Exception as e:
            print(f"[Startup] Sync error: {e}")
        st.session_state["_startup_synced"] = True

    render_sidebar()

    # Logout button in sidebar
    with st.sidebar:
        st.markdown("---")
        st.markdown(f"**{st.session_state.get('name', '')}** olarak giris yapildi")
        if st.button("Cikis Yap", use_container_width=True):
            _logout()

    # PDF viewer (if active)
    render_pdf_viewer()

    # Chat area
    if not st.session_state.messages:
        render_welcome()
    else:
        for i, msg in enumerate(st.session_state.messages):
            render_message(msg, i)

    # Chat input
    user_input = st.chat_input("Ask about your documents or data...")

    if user_input:
        with st.spinner("Thinking..."):
            handle_input(user_input)
        st.rerun()


if __name__ == "__main__":
    main()
