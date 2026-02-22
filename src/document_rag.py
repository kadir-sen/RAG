"""
Document RAG module with proper page-level citations.
Each PDF page is stored as a separate document with metadata.
Supports OCR for scanned PDFs.
"""
import os
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Any

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from pinecone import Pinecone, ServerlessSpec

from llama_index.core import (
    VectorStoreIndex,
    Document,
    StorageContext,
    Settings,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.vector_stores.pinecone import PineconeVectorStore
from llama_index.llms.gemini import Gemini
from llama_index.embeddings.google_genai import GoogleGenAIEmbedding

from .config import (
    GOOGLE_API_KEY,
    PINECONE_API_KEY,
    GEMINI_MODEL,
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
    PINECONE_INDEX_NAME,
    PINECONE_DIMENSION,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    OCR_MODE,
    OCR_LANG,
)
from .logger import logger, log_document_processing, log_pinecone, log_llm, log_separator, log_ocr_summary
from .ocr_pipeline import get_ocr_pipeline, OCRPipeline


def generate_doc_id(file_path: str) -> str:
    """Generate a stable document ID from file path."""
    return hashlib.md5(file_path.encode()).hexdigest()[:16]



class DocumentRAG:
    """
    Handles document indexing and retrieval using Pinecone.
    Each PDF page is stored separately with proper metadata for citations.
    """

    def __init__(self):
        """Initialize the Document RAG system."""
        log_separator("Initializing Document RAG")
        self._setup_llm()
        self._setup_pinecone()
        self.index: Optional[VectorStoreIndex] = None
        self.documents: List[Document] = []
        self.file_registry: Dict[str, Dict[str, Any]] = {}  # Track indexed files
        logger.info("✅ Document RAG initialized successfully")

    def _setup_llm(self):
        """Configure LLM and embedding models."""
        log_llm("Setting up Gemini LLM and embeddings", GEMINI_MODEL)
        Settings.llm = Gemini(api_key=GOOGLE_API_KEY, model=GEMINI_MODEL)
        Settings.embed_model = GoogleGenAIEmbedding(
            api_key=GOOGLE_API_KEY,
            model_name=EMBEDDING_MODEL,
            embedding_config={"output_dimensionality": EMBEDDING_DIMENSION},
        )
        Settings.node_parser = SentenceSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
        )
        logger.info(f"   Chunk size: {CHUNK_SIZE}, Overlap: {CHUNK_OVERLAP}")

    def _setup_pinecone(self):
        """Initialize Pinecone vector store."""
        log_pinecone("Connecting to Pinecone...")
        self.pc = Pinecone(api_key=PINECONE_API_KEY)

        existing_indexes = [idx.name for idx in self.pc.list_indexes()]
        logger.info(f"   Existing indexes: {existing_indexes}")

        if PINECONE_INDEX_NAME not in existing_indexes:
            log_pinecone(f"Creating new index: {PINECONE_INDEX_NAME}")
            self.pc.create_index(
                name=PINECONE_INDEX_NAME,
                dimension=PINECONE_DIMENSION,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
            logger.info(f"   Dimension: {PINECONE_DIMENSION}, Metric: cosine")
        else:
            log_pinecone(f"Using existing index: {PINECONE_INDEX_NAME}")

        self.pinecone_index = self.pc.Index(PINECONE_INDEX_NAME)
        self.vector_store = PineconeVectorStore(pinecone_index=self.pinecone_index)

        stats = self.pinecone_index.describe_index_stats()
        logger.info(f"   Total vectors: {stats.get('total_vector_count', 0)}")

    def _delete_file_vectors(self, file_name: str):
        """Delete existing vectors for a file before re-indexing."""
        doc_id = generate_doc_id(file_name)
        try:
            # Delete vectors with matching doc_id metadata
            # Note: This requires Pinecone metadata filtering
            self.pinecone_index.delete(
                filter={"doc_id": {"$eq": doc_id}}
            )
            logger.info(f"   Cleared existing vectors for: {file_name}")
        except Exception as e:
            # Pinecone free tier might not support metadata filtering for delete
            logger.info(f"   Could not filter-delete (new file or free tier): {file_name}")

    def parse_pdf_by_pages(
        self,
        file_path: str,
        ocr_mode: Optional[str] = None,
        ocr_language: Optional[str] = None,
    ) -> List[Document]:
        """
        Parse PDF page-by-page with OCR support for scanned pages.
        Each page becomes a separate Document with metadata for citations.

        Args:
            file_path: Path to PDF file
            ocr_mode: Override OCR mode ("auto", "force", "off")
            ocr_language: Override OCR language ("eng", "eng+tur", etc.)

        Returns:
            List of Document objects, one per page
        """
        documents = []
        path = Path(file_path)
        file_name = path.name

        # Initialize OCR pipeline with settings
        ocr = get_ocr_pipeline(
            mode=ocr_mode or OCR_MODE,
            language=ocr_language or OCR_LANG,
        )

        try:
            logger.info(f"   Parsing PDF: {file_name}")
            logger.info(f"   OCR mode: {ocr.mode}, language: {ocr.language}")
            logger.info(f"   ----------------------------------------")

            # Use OCR pipeline for extraction
            page_results = ocr.extract_text_auto(file_path)
            total_pages = len(page_results)

            # Stats for summary
            native_count = 0
            ocr_count = 0
            failed_count = 0
            total_ocr_time = 0

            for page_text in page_results:
                text = page_text.text
                method = page_text.extraction_method

                # Track stats
                if method == "native":
                    native_count += 1
                elif method in ("ocr", "native+ocr"):
                    ocr_count += 1
                    if page_text.ocr_time_ms:
                        total_ocr_time += page_text.ocr_time_ms

                if not text or len(text) < 10:
                    failed_count += 1
                    continue

                # Build metadata
                page_metadata = {
                    "file_name": file_name,
                    "file_path": str(file_path),
                    "file_type": ".pdf",
                    "page_number": page_text.page_number,
                    "total_pages": total_pages,
                    "doc_id": generate_doc_id(file_path),
                    "extraction_method": method,
                }

                # Add OCR metadata if applicable
                if page_text.ocr_engine:
                    page_metadata["ocr_engine"] = page_text.ocr_engine
                if page_text.ocr_language:
                    page_metadata["ocr_language"] = page_text.ocr_language
                if page_text.ocr_confidence is not None:
                    page_metadata["ocr_confidence"] = page_text.ocr_confidence

                # Check for table-like content
                if ocr.detect_table_like_structure(text):
                    page_metadata["table_hint"] = True

                page_doc = Document(
                    text=text,
                    metadata=page_metadata,
                )
                documents.append(page_doc)

            # Log summary
            log_ocr_summary(
                total_pages=total_pages,
                native_pages=native_count,
                ocr_pages=ocr_count,
                failed_pages=failed_count,
                total_time_ms=total_ocr_time,
            )

            logger.info(f"   RESULT: {len(documents)} page documents created")

            if len(documents) == 0:
                logger.warning(f"   WARNING: No text extracted from PDF!")
                if ocr.mode == "off":
                    logger.warning(f"   TIP: Try enabling OCR mode for scanned PDFs")

        except Exception as e:
            logger.error(f"   Error parsing PDF: {e}")
            import traceback
            logger.error(traceback.format_exc())

        return documents

    def parse_docx(self, file_path: str) -> List[Document]:
        """Parse Word document into documents."""
        documents = []
        path = Path(file_path)
        file_name = path.name

        try:
            doc = DocxDocument(file_path)
            full_text = "\n\n".join([para.text for para in doc.paragraphs if para.text.strip()])

            if full_text:
                documents.append(Document(
                    text=full_text,
                    metadata={
                        "file_name": file_name,
                        "file_path": str(file_path),
                        "file_type": ".docx",
                        "page_number": 1,
                        "total_pages": 1,
                        "doc_id": generate_doc_id(file_path),
                    },
                ))
            logger.info(f"   Parsed DOCX: {len(full_text)} characters")

        except Exception as e:
            logger.error(f"   Error parsing DOCX: {e}")

        return documents

    def parse_txt(self, file_path: str) -> List[Document]:
        """Parse text file into documents."""
        documents = []
        path = Path(file_path)
        file_name = path.name

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read().strip()

            if text:
                documents.append(Document(
                    text=text,
                    metadata={
                        "file_name": file_name,
                        "file_path": str(file_path),
                        "file_type": ".txt",
                        "page_number": 1,
                        "total_pages": 1,
                        "doc_id": generate_doc_id(file_path),
                    },
                ))
            logger.info(f"   Parsed TXT: {len(text)} characters")

        except Exception as e:
            logger.error(f"   Error parsing TXT: {e}")

        return documents

    def add_document(
        self,
        file_path: str,
        ocr_mode: Optional[str] = None,
        ocr_language: Optional[str] = None,
    ) -> Optional[List[Document]]:
        """
        Parse a document and return new Document objects.

        Args:
            file_path: Path to document file
            ocr_mode: OCR mode ("auto", "force", "off") - only for PDFs
            ocr_language: OCR language ("eng", "eng+tur") - only for PDFs

        Returns:
            List of new Document objects, or None if failed
        """
        path = Path(file_path)
        file_name = path.name
        extension = path.suffix.lower()

        log_document_processing(file_name, "Processing", f"Type: {extension}")

        # Delete existing vectors for this file (prevent duplicates)
        self._delete_file_vectors(file_name)

        # Parse based on file type
        if extension == ".pdf":
            new_docs = self.parse_pdf_by_pages(file_path, ocr_mode, ocr_language)
        elif extension in [".docx", ".doc"]:
            new_docs = self.parse_docx(file_path)
        elif extension == ".txt":
            new_docs = self.parse_txt(file_path)
        else:
            logger.warning(f"   Unsupported file type: {extension}")
            return None

        if new_docs:
            self.documents.extend(new_docs)

            # Count OCR pages
            ocr_pages = sum(1 for d in new_docs if d.metadata.get("extraction_method") in ("ocr", "native+ocr"))

            self.file_registry[file_name] = {
                "file_path": str(file_path),
                "file_type": extension,
                "page_count": len(new_docs),
                "ocr_pages": ocr_pages,
                "doc_id": generate_doc_id(file_path),
            }
            log_document_processing(file_name, "Added", f"{len(new_docs)} pages ({ocr_pages} OCR)")
            return new_docs

        return None

    def add_document_from_pages(
        self,
        file_path: str,
        page_texts: Dict[int, str],
        metadata: Optional[Dict] = None,
    ) -> Optional[List[Document]]:
        """
        Create Document objects from pre-parsed page texts (e.g., email body).

        Args:
            file_path: Original file path (for metadata)
            page_texts: Dict mapping page_number -> text content
            metadata: Additional metadata to attach to each document

        Returns:
            List of Document objects, or None if empty
        """
        path = Path(file_path)
        file_name = path.name

        # Delete existing vectors for this file
        self._delete_file_vectors(file_name)

        new_docs = []
        for page_num, text in sorted(page_texts.items()):
            if not text or not text.strip():
                continue
            doc_meta = {
                "file_name": file_name,
                "file_path": str(file_path),
                "file_type": path.suffix.lower(),
                "page_number": page_num,
                "total_pages": len(page_texts),
                "doc_id": generate_doc_id(file_path),
            }
            if metadata:
                doc_meta.update(metadata)

            new_docs.append(Document(text=text.strip(), metadata=doc_meta))

        if new_docs:
            self.documents.extend(new_docs)
            self.file_registry[file_name] = {
                "file_path": str(file_path),
                "file_type": path.suffix.lower(),
                "page_count": len(new_docs),
                "ocr_pages": 0,
                "doc_id": generate_doc_id(file_path),
            }
            log_document_processing(file_name, "Added", f"{len(new_docs)} pages (from pages)")
            return new_docs

        return None

    def add_documents_from_folder(self, folder_path: str) -> int:
        """Add all supported documents from a folder."""
        count = 0
        supported = {".pdf", ".docx", ".doc", ".txt"}
        folder = Path(folder_path)

        if not folder.exists():
            logger.warning(f"Folder not found: {folder_path}")
            return 0

        log_separator(f"Scanning: {folder.name}")

        for file_path in folder.rglob("*"):
            if file_path.suffix.lower() in supported:
                if self.add_document(str(file_path)):
                    count += 1

        logger.info(f"📁 Added {count} documents from {folder.name}")
        return count

    def build_index(self) -> bool:
        """Build vector index from documents."""
        if not self.documents:
            logger.warning("No documents to index")
            return False

        log_separator("Building Vector Index")
        logger.info(f"Indexing {len(self.documents)} document(s)...")

        try:
            # Use default namespace for all documents (simpler, allows cross-file search)
            storage_context = StorageContext.from_defaults(vector_store=self.vector_store)

            # Build index from all documents
            self.index = VectorStoreIndex.from_documents(
                self.documents,
                storage_context=storage_context,
                show_progress=True
            )

            log_pinecone("Index built successfully")
            stats = self.pinecone_index.describe_index_stats()
            logger.info(f"   Total vectors: {stats.get('total_vector_count', 0)}")
            return True
        except Exception as e:
            logger.error(f"Error building index: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def insert_documents(self, new_docs: List[Document]) -> bool:
        """
        Add new documents to existing Pinecone index incrementally.
        Avoids full rebuild - only embeds and uploads the new documents.
        """
        if not new_docs:
            return False

        # Ensure index exists (load from Pinecone or build fresh)
        if not self.index:
            if not self.load_index():
                # No existing index - need full build for the first time
                return self.build_index()

        log_separator("Incremental Index Update")
        logger.info(f"Inserting {len(new_docs)} new document(s) into existing index...")

        try:
            for doc in new_docs:
                self.index.insert(doc)

            stats = self.pinecone_index.describe_index_stats()
            logger.info(f"   Total vectors after insert: {stats.get('total_vector_count', 0)}")
            return True
        except Exception as e:
            logger.error(f"Error inserting documents: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Fallback to full rebuild
            logger.info("Falling back to full index rebuild...")
            return self.build_index()

    def load_index(self) -> bool:
        """Load existing index from Pinecone."""
        try:
            log_pinecone("Loading existing index...")
            self.vector_store = PineconeVectorStore(pinecone_index=self.pinecone_index)
            self.index = VectorStoreIndex.from_vector_store(self.vector_store)
            stats = self.pinecone_index.describe_index_stats()
            logger.info(f"   Loaded {stats.get('total_vector_count', 0)} vectors")
            return True
        except Exception as e:
            logger.error(f"Could not load index: {e}")
            return False

    def query(self, question: str, top_k: int = 5) -> dict:
        """Query documents with proper page-level citations."""
        log_separator("Document Query")
        logger.info(f"🔍 Question: {question[:100]}...")

        if not self.index:
            if not self.load_index():
                return {
                    "answer": "No documents indexed. Please upload documents first.",
                    "sources": [],
                }

        logger.info(f"   Retrieving top {top_k} matches...")
        query_engine = self.index.as_query_engine(similarity_top_k=top_k)
        response = query_engine.query(question)

        # Extract sources with proper metadata (no regex!)
        sources = []
        seen = set()

        for i, node in enumerate(response.source_nodes, 1):
            meta = node.metadata
            # Debug: print all metadata keys and values
            logger.info(f"   Source {i} RAW metadata: {meta}")

            file_name = meta.get("file_name", "Unknown")
            file_path = meta.get("file_path", "")
            score = round(node.score, 3) if node.score else None

            # Ensure page numbers are integers
            try:
                page_num = int(meta.get("page_number", 1))
            except (ValueError, TypeError):
                page_num = 1

            try:
                total_pages = int(meta.get("total_pages", 1))
            except (ValueError, TypeError):
                total_pages = 1

            logger.info(f"   Source {i} EXTRACTED: file={file_name}, page={page_num}, total={total_pages}")

            # Dedupe by file+page
            key = f"{file_name}_{page_num}"
            if key in seen:
                continue
            seen.add(key)

            # Extract highlight (first 2-3 sentences)
            text = node.text.strip()
            sentences = text.replace('\n', ' ').split('. ')
            highlight = '. '.join(sentences[:3])
            if len(sentences) > 3:
                highlight += '...'

            sources.append({
                "file_name": file_name,
                "file_path": file_path,
                "page_number": page_num,
                "total_pages": total_pages,
                "score": score,
                "text_snippet": text[:500] + "..." if len(text) > 500 else text,
                "highlight_text": highlight[:300],
            })

        logger.info(f"✅ Found {len(sources)} unique sources")
        return {"answer": str(response), "sources": sources}

    def _extract_sources(self, response) -> list:
        """Extract sources from a LlamaIndex query response."""
        sources = []
        seen = set()

        for i, node in enumerate(response.source_nodes, 1):
            meta = node.metadata
            file_name = meta.get("file_name", "Unknown")
            file_path = meta.get("file_path", "")
            score = round(node.score, 3) if node.score else None

            try:
                page_num = int(meta.get("page_number", 1))
            except (ValueError, TypeError):
                page_num = 1

            try:
                total_pages = int(meta.get("total_pages", 1))
            except (ValueError, TypeError):
                total_pages = 1

            key = f"{file_name}_{page_num}"
            if key in seen:
                continue
            seen.add(key)

            text = node.text.strip()
            sentences = text.replace('\n', ' ').split('. ')
            highlight = '. '.join(sentences[:3])
            if len(sentences) > 3:
                highlight += '...'

            sources.append({
                "file_name": file_name,
                "file_path": file_path,
                "page_number": page_num,
                "total_pages": total_pages,
                "score": score,
                "text_snippet": text[:500] + "..." if len(text) > 500 else text,
                "highlight_text": highlight[:300],
            })

        return sources

    def query_with_provider(self, question: str, provider: str, top_k: int = 5) -> dict:
        """Query documents using a specific LLM provider for answer synthesis."""
        from .llm_client import create_llm

        logger.info(f"[DocumentRAG] Query with provider={provider}: {question[:80]}...")

        if not self.index:
            if not self.load_index():
                return {
                    "answer": "No documents indexed. Please upload documents first.",
                    "sources": [],
                }

        llm, model_name = create_llm(provider)
        logger.info(f"   Using {provider}/{model_name} for synthesis...")

        query_engine = self.index.as_query_engine(
            similarity_top_k=top_k,
            llm=llm,
        )
        response = query_engine.query(question)
        sources = self._extract_sources(response)

        logger.info(f"   [{provider}] Found {len(sources)} sources")
        return {"answer": str(response), "sources": sources}

    def query_dual(self, question: str, top_k: int = 5) -> dict:
        """Query with both OpenAI and Claude in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .config import LLM_PROVIDERS

        results = {}

        def _query_provider(prov):
            return prov, self.query_with_provider(question, prov, top_k)

        with ThreadPoolExecutor(max_workers=len(LLM_PROVIDERS)) as executor:
            futures = {executor.submit(_query_provider, p): p for p in LLM_PROVIDERS}
            for future in as_completed(futures):
                try:
                    prov, result = future.result()
                    results[prov] = result
                except Exception as e:
                    prov = futures[future]
                    logger.error(f"   [{prov}] Query failed: {e}")
                    results[prov] = {
                        "answer": f"Error from {prov}: {e}",
                        "sources": [],
                    }

        return results

    def get_page_content(self, file_path: str, page_num: int) -> Optional[str]:
        """Get full content of a specific page for preview."""
        try:
            doc = fitz.open(file_path)
            if 1 <= page_num <= len(doc):
                text = doc[page_num - 1].get_text()
                doc.close()
                return text
            doc.close()
        except Exception as e:
            logger.error(f"Error reading page: {e}")
        return None

    def clear_index(self):
        """Clear all vectors from the index."""
        try:
            log_pinecone("Clearing entire index...")
            self.pinecone_index.delete(delete_all=True)
            self.documents = []
            self.file_registry = {}
            self.index = None
            logger.info("✅ Index cleared")
        except Exception as e:
            logger.error(f"Error clearing index: {e}")

    def clear_file(self, file_name: str):
        """Clear vectors for a specific file."""
        doc_id = generate_doc_id(file_name)
        try:
            self.pinecone_index.delete(filter={"doc_id": {"$eq": doc_id}})
            if file_name in self.file_registry:
                del self.file_registry[file_name]
            self.documents = [d for d in self.documents if d.metadata.get("file_name") != file_name]
            logger.info(f"Cleared: {file_name}")
        except Exception as e:
            logger.error(f"Error clearing file: {e}")

    def get_index_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        stats = self.pinecone_index.describe_index_stats()
        return {
            "total_vectors": stats.get("total_vector_count", 0),
            "files_indexed": len(self.file_registry),
            "files": list(self.file_registry.keys()),
        }


# Singleton
_document_rag: Optional[DocumentRAG] = None


def get_document_rag() -> DocumentRAG:
    """Get or create DocumentRAG singleton."""
    global _document_rag
    if _document_rag is None:
        _document_rag = DocumentRAG()
    return _document_rag
