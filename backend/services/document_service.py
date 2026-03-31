"""Document content serving for the right-panel viewer."""

import asyncio
import base64
from pathlib import Path

from backend.models.responses import DocContent


class DocumentService:

    async def get_content(self, doc_id: str, anchor: str = "") -> DocContent:
        return await asyncio.to_thread(self._get_content_sync, doc_id, anchor)

    def _get_content_sync(self, doc_id: str, anchor: str) -> DocContent:
        # Try RAG file registry
        try:
            from src.document_rag import get_document_rag
            rag = get_document_rag()
            for fname, info in rag.file_registry.items():
                if doc_id in (fname, info.get("doc_id", "")):
                    file_path = info.get("file_path", "")
                    page = self._parse_anchor_page(anchor)
                    if file_path.lower().endswith(".pdf"):
                        return self._serve_pdf_page(file_path, page)
                    else:
                        return self._serve_text_content(file_path)
        except Exception:
            pass

        # Try data tables (Excel viewer) — match by doc_id from file_paths
        try:
            from src.data_analyzer_sql import get_data_analyzer
            from src.document_rag import generate_doc_id
            analyzer = get_data_analyzer()
            for table_name, file_path in analyzer.file_paths.items():
                if generate_doc_id(file_path) == doc_id:
                    return self._serve_table_preview(table_name, analyzer)
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
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")[:5000]
            return DocContent(
                type="text",
                file_name=Path(file_path).name,
                text=text,
            )
        except Exception as e:
            return DocContent(type="text", error=str(e))

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
