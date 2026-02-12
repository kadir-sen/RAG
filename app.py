"""
Agentic RAG Chatbot - Modern Dark UI
Clean, minimal, professional interface with dark theme.
"""
import os
import base64
from pathlib import Path

# Load env first
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import streamlit as st
import pandas as pd
import streamlit_authenticator as stauth

# Page config - MUST be first
st.set_page_config(
    page_title="RAG Chatbot",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Authentication ─────────────────────────────────────────
AUTH_CONFIG = {
    "credentials": {
        "usernames": {
            "admin": {
                "email": "admin@company.com",
                "first_name": "Admin",
                "last_name": "User",
                "logged_in": False,
                "password": "$2b$12$aashT0HWtKa0viUSRXAlL.Wd2Ic52tTfp/lHGQOU0SMSU0uHAydPq",
            },
            "user1": {
                "email": "user1@company.com",
                "first_name": "User",
                "last_name": "One",
                "logged_in": False,
                "password": "$2b$12$Kpo/x8Bj2z8AJkA9B5WLmunOjcgW4NenroFGrsyCmGls8QV3UI5RC",
            },
            "user2": {
                "email": "user2@company.com",
                "first_name": "User",
                "last_name": "Two",
                "logged_in": False,
                "password": "$2b$12$Kpo/x8Bj2z8AJkA9B5WLmunOjcgW4NenroFGrsyCmGls8QV3UI5RC",
            },
        }
    },
    "cookie": {
        "name": "rag_chatbot_auth",
        "key": os.getenv("AUTH_COOKIE_KEY", "rag-chatbot-secret-key-2026"),
        "expiry_days": 7,
    },
}

authenticator = stauth.Authenticate(
    AUTH_CONFIG["credentials"],
    AUTH_CONFIG["cookie"]["name"],
    AUTH_CONFIG["cookie"]["key"],
    AUTH_CONFIG["cookie"]["expiry_days"],
)

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

    /* Hide default elements */
    #MainMenu, footer, header {visibility: hidden;}
    .stDeployButton {display: none;}

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
        "show_pdf_viewer": False,
        "pdf_path": None,
        "pdf_page": 1,
        "pdf_highlight": None,
        # OCR settings
        "ocr_mode": "auto",
        "ocr_language": "eng",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


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

        if rag.add_document(file_path, ocr_mode=ocr_mode, ocr_language=ocr_language):
            rag.build_index()
            st.session_state.docs_count += 1
            st.session_state.processed_files.add(key)

            # Get OCR stats
            file_info = rag.file_registry.get(uploaded_file.name, {})
            result["ocr_pages"] = file_info.get("ocr_pages", 0)
            result["success"] = True

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
            else:
                # Fallback to direct loading
                if analyzer.load_file(file_path):
                    st.session_state.tables_count += 1
                    st.session_state.processed_files.add(key)
                    result["success"] = True
        except ImportError:
            # Fallback if table_ingestion not available
            if analyzer.load_file(file_path):
                st.session_state.tables_count += 1
                st.session_state.processed_files.add(key)
                result["success"] = True

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


def render_sidebar():
    """Render sidebar."""
    with st.sidebar:
        st.markdown("## 💬 RAG Chatbot")
        st.caption("Hybrid document & data analysis")

        st.markdown("---")

        # OCR Settings
        st.markdown("### 🔍 OCR Settings")

        ocr_mode = st.selectbox(
            "OCR Mode",
            options=["auto", "force", "off"],
            index=["auto", "force", "off"].index(st.session_state.get("ocr_mode", "auto")),
            help="Auto: OCR only scanned pages | Force: OCR all pages | Off: Text extraction only",
            key="ocr_mode_select",
        )
        st.session_state.ocr_mode = ocr_mode

        ocr_lang = st.selectbox(
            "OCR Language",
            options=["eng", "eng+tur", "tur"],
            index=0,
            help="Select OCR language(s). eng+tur for mixed documents.",
            key="ocr_lang_select",
        )
        st.session_state.ocr_language = ocr_lang

        st.markdown("---")

        # Documents upload
        st.markdown("### 📄 Documents")
        doc_files = st.file_uploader(
            "PDF, DOCX, TXT",
            type=["pdf", "docx", "doc", "txt"],
            accept_multiple_files=True,
            key="doc_upload",
            label_visibility="collapsed",
        )

        if doc_files:
            for f in doc_files:
                result = process_upload(f, "document")
                if result["success"]:
                    info_parts = []
                    if result['ocr_pages'] > 0:
                        info_parts.append(f"{result['ocr_pages']} OCR")
                    if result['tables_extracted'] > 0:
                        info_parts.append(f"{result['tables_extracted']} tables")
                    if result.get('notice_extracted'):
                        info_parts.append("notice")
                    info_str = f" ({', '.join(info_parts)})" if info_parts else ""
                    st.success(f"✓ {f.name}{info_str}")

                    # Show notice summary if extracted
                    if result.get('notice_summary'):
                        ns = result['notice_summary']
                        with st.expander(f"📋 Notice: {f.name}", expanded=False):
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

        st.markdown("### 📊 Data Files")
        data_files = st.file_uploader(
            "Excel, CSV",
            type=["xlsx", "xls", "csv"],
            accept_multiple_files=True,
            key="data_upload",
            label_visibility="collapsed",
        )

        if data_files:
            for f in data_files:
                result = process_upload(f, "data")
                if result["success"]:
                    info_parts = []
                    if result['tables_extracted'] > 0:
                        info_parts.append(f"{result['tables_extracted']} tables")
                    if result['total_rows'] > 0:
                        info_parts.append(f"{result['total_rows']} rows")
                    info_str = f" ({', '.join(info_parts)})" if info_parts else ""
                    st.success(f"✓ {f.name}{info_str}")

        st.markdown("---")

        if st.button("📂 Load Project Files", use_container_width=True):
            with st.spinner("Loading..."):
                docs, tables = load_project_files()
            st.success(f"Loaded {docs} docs, {tables} tables")

        st.markdown("---")

        # Stats
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Documents", st.session_state.docs_count)
        with col2:
            st.metric("Tables", st.session_state.tables_count)

        # Clear button
        if st.session_state.docs_count > 0:
            st.markdown("---")
            if st.button("🗑️ Clear All", use_container_width=True):
                from src.document_rag import get_document_rag
                get_document_rag().clear_index()
                st.session_state.docs_count = 0
                st.session_state.tables_count = 0
                st.session_state.processed_files = set()
                st.session_state.messages = []
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
    """Process user input. Uses dual-LLM if providers available, else single Gemini."""
    from src.router import get_router
    from src.config import LLM_PROVIDERS

    st.session_state.messages.append({
        "role": "user",
        "content": user_input,
    })

    router = get_router()

    if len(LLM_PROVIDERS) >= 2:
        # Dual-LLM mode (Gemini + OpenAI)
        result = router.route_and_execute_dual(user_input)
        answers = result.get("answers", {})
        st.session_state.messages.append({
            "role": "assistant",
            "content": "",
            "dual_answers": answers,
            "query_type": result.get("query_type", ""),
        })
    else:
        # Single-LLM mode (Gemini only)
        result = router.route_and_execute(user_input)
        st.session_state.messages.append({
            "role": "assistant",
            "content": result.get("answer", "No answer"),
            "query_type": result.get("query_type", ""),
            "sources": result.get("sources", []),
            "sql": result.get("sql"),
            "result_data": result.get("result_data"),
        })


def main():
    """Main application with authentication gate."""
    # ── Login gate ──
    try:
        authenticator.login()
    except Exception as e:
        st.error(e)

    if st.session_state.get("authentication_status") is None:
        st.info("Kullanici adi ve sifrenizi girin.")
        return
    if st.session_state.get("authentication_status") is False:
        st.error("Kullanici adi veya sifre hatali.")
        return

    # ── Authenticated ──
    init_session()
    check_api_keys()
    render_sidebar()

    # Logout button in sidebar
    with st.sidebar:
        st.markdown("---")
        st.markdown(f"**{st.session_state.get('name', '')}** olarak giris yapildi")
        authenticator.logout("Cikis Yap")

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
