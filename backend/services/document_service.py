"""Document content serving for the right-panel viewer."""

import asyncio
import base64
from pathlib import Path

from backend.models.responses import DocContent

_DATA_EXTENSIONS = {".xlsx", ".xls", ".csv"}


class DocumentService:

    async def get_content(self, doc_id: str, anchor: str = "") -> DocContent:
        return await asyncio.to_thread(self._get_content_sync, doc_id, anchor)

    def _is_data_file(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in _DATA_EXTENSIONS

    def _get_content_sync(self, doc_id: str, anchor: str) -> DocContent:
        # Guard: empty or whitespace-only doc_id
        if not doc_id or not doc_id.strip():
            return DocContent(type="text", error="No document ID provided")

        # Try data tables (Excel viewer) first — match by doc_id from file_paths
        try:
            from src.data_analyzer_sql import get_data_analyzer
            from src.document_rag import generate_doc_id
            analyzer = get_data_analyzer()
            for table_name, file_path in analyzer.file_paths.items():
                if generate_doc_id(file_path) == doc_id:
                    return self._serve_table_preview(table_name, analyzer)
        except Exception:
            pass

        # Try RAG file registry (match by doc_id hash OR by file_name)
        try:
            from src.document_rag import get_document_rag, generate_doc_id
            rag = get_document_rag()
            for fname, info in rag.file_registry.items():
                stored_doc_id = info.get("doc_id", "")
                # Match by: exact doc_id, file_name, or MD5 hash of file_name
                import hashlib
                fname_hash = hashlib.md5(fname.encode()).hexdigest()[:16]
                if doc_id in (fname, stored_doc_id, fname_hash):
                    file_path = info.get("file_path", "")
                    page = self._parse_anchor_page(anchor)
                    if file_path.lower().endswith(".pdf"):
                        return self._serve_pdf_page(file_path, page)
                    elif self._is_data_file(file_path):
                        return self._serve_excel_file(file_path)
                    else:
                        return self._serve_text_content(file_path)
        except Exception:
            pass

        # Fallback: DocumentRegistry (JSON-backed, survives restarts)
        try:
            from src.document_registry import get_document_registry
            registry = get_document_registry()
            rec = registry.get(doc_id)
            # Also try matching by file_name hash if direct lookup fails
            if not rec:
                import hashlib
                for r in registry.get_all():
                    fname_hash = hashlib.md5(r.file_name.encode()).hexdigest()[:16]
                    if doc_id in (r.file_name, fname_hash):
                        rec = r
                        break
            if rec and rec.file_path:
                page = self._parse_anchor_page(anchor)
                if rec.file_path.lower().endswith(".pdf"):
                    return self._serve_pdf_page(rec.file_path, page)
                elif self._is_data_file(rec.file_path):
                    return self._serve_excel_file(rec.file_path)
                else:
                    return self._serve_text_content(rec.file_path)
        except Exception:
            pass

        return DocContent(type="text", error="Document not found")

    def _parse_anchor_page(self, anchor: str) -> int:
        if anchor.startswith("page_"):
            try:
                return int(anchor.replace("page_", ""))
            except ValueError:
                pass
        return 1

    def _serve_pdf_page(self, file_path: str, page: int) -> DocContent:
        try:
            import fitz
            doc = fitz.open(file_path)
            if page < 1 or page > len(doc):
                page = 1
            pdf_page = doc[page - 1]

            pix = pdf_page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            text = pdf_page.get_text()
            total = len(doc)
            doc.close()

            return DocContent(
                type="pdf",
                file_name=Path(file_path).name,
                page=page,
                total_pages=total,
                image_base64=base64.b64encode(img_bytes).decode(),
                text=text,
            )
        except Exception as e:
            return DocContent(type="pdf", error=str(e))

    def _serve_text_content(self, file_path: str) -> DocContent:
        try:
            fp = Path(file_path)
            # Handle .msg (Outlook) files — binary format, need extract_msg
            if fp.suffix.lower() == ".msg":
                return self._serve_msg_content(file_path)
            text = fp.read_text(encoding="utf-8", errors="replace")[:5000]
            return DocContent(
                type="text",
                file_name=fp.name,
                text=text,
            )
        except Exception as e:
            return DocContent(type="text", error=str(e))

    def _serve_msg_content(self, file_path: str) -> DocContent:
        """Parse .msg (Outlook email) files and return readable text."""
        try:
            import extract_msg
            msg = extract_msg.Message(file_path)
            parts = []
            if msg.subject:
                parts.append(f"Subject: {msg.subject}")
            if msg.sender:
                parts.append(f"From: {msg.sender}")
            if msg.to:
                parts.append(f"To: {msg.to}")
            if msg.date:
                parts.append(f"Date: {msg.date}")
            parts.append("")
            parts.append(msg.body or "(No body)")
            attachments = [att.longFilename or att.shortFilename for att in (msg.attachments or []) if att.longFilename or att.shortFilename]
            if attachments:
                parts.append(f"\nAttachments: {', '.join(attachments)}")
            msg.close()
            return DocContent(
                type="text",
                file_name=Path(file_path).name,
                text="\n".join(parts)[:5000],
            )
        except Exception as e:
            return DocContent(type="text", error=f"Cannot parse email: {e}")

    def _serve_excel_file(self, file_path: str) -> DocContent:
        """Read an Excel/CSV file directly with pandas and return as table."""
        try:
            import pandas as pd
            fp = Path(file_path)
            ext = fp.suffix.lower()
            if ext == ".csv":
                df = pd.read_csv(file_path, nrows=50)
            else:
                df = pd.read_excel(file_path, nrows=50)
            # Get total row count without loading entire file
            if ext == ".csv":
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    total_rows = sum(1 for _ in f) - 1  # minus header
            else:
                df_full_len = len(pd.read_excel(file_path, usecols=[0]))
                total_rows = df_full_len
            return DocContent(
                type="table",
                file_name=fp.name,
                columns=list(df.columns.astype(str)),
                rows=df.fillna("").to_dict("records"),
                total_rows=max(total_rows, len(df)),
            )
        except Exception as e:
            return DocContent(type="table", error=str(e))

    def _serve_table_preview(self, table_name: str, analyzer) -> DocContent:
        try:
            df = analyzer.conn.execute(
                f'SELECT * FROM "{table_name}" LIMIT 50'
            ).fetchdf()
            info = analyzer.tables.get(table_name, {})
            display_name = info.get("file_name", table_name)
            return DocContent(
                type="table",
                file_name=display_name,
                columns=list(df.columns),
                rows=df.to_dict("records"),
                total_rows=info.get("row_count", len(df)),
            )
        except Exception as e:
            return DocContent(type="table", error=str(e))
