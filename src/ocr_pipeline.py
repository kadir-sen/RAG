"""
OCR Pipeline Module for Agentic RAG Chatbot.
Handles text extraction from scanned PDFs and image-based pages.
"""
import os
import hashlib
import json
import time
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass, asdict
from io import BytesIO

import fitz  # PyMuPDF

# OCR imports (optional - graceful degradation)
try:
    import pytesseract
    from PIL import Image
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

from .config import (
    OCR_MODE,
    OCR_ENGINE,
    OCR_LANG,
    OCR_DPI,
    OCR_CACHE_DIR,
    OCR_MAX_PAGES_PER_DOC,
    OCR_MIN_CHARS_THRESHOLD,
    OCR_MIN_ALPHA_RATIO,
    OCR_IMAGE_COVERAGE_THRESHOLD,
)
from .logger import logger


@dataclass
class OCRResult:
    """Result from OCR extraction."""
    text: str
    confidence: Optional[float] = None
    engine: str = "tesseract"
    language: str = "eng"
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@dataclass
class PageText:
    """Extracted text from a single page."""
    page_number: int
    text: str
    extraction_method: str  # "native" | "ocr" | "native+ocr"
    char_count: int
    word_count: int
    ocr_engine: Optional[str] = None
    ocr_language: Optional[str] = None
    ocr_confidence: Optional[float] = None
    ocr_time_ms: Optional[int] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class OCRCache:
    """Simple file-based cache for OCR results."""

    def __init__(self, cache_dir: str = OCR_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, file_hash: str, page_num: int, dpi: int, lang: str, engine: str) -> str:
        """Generate unique cache key."""
        key_parts = f"{file_hash}_{page_num}_{dpi}_{lang}_{engine}"
        return hashlib.md5(key_parts.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get path to cache file."""
        return self.cache_dir / f"{cache_key}.json"

    def get(self, file_hash: str, page_num: int, dpi: int, lang: str, engine: str) -> Optional[OCRResult]:
        """Retrieve cached OCR result."""
        cache_key = self._get_cache_key(file_hash, page_num, dpi, lang, engine)
        cache_path = self._get_cache_path(cache_key)

        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return OCRResult(**data)
            except Exception:
                return None
        return None

    def set(self, file_hash: str, page_num: int, dpi: int, lang: str, engine: str, result: OCRResult):
        """Store OCR result in cache."""
        cache_key = self._get_cache_key(file_hash, page_num, dpi, lang, engine)
        cache_path = self._get_cache_path(cache_key)

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(result), f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to cache OCR result: {e}")


class OCRPipeline:
    """
    OCR Pipeline for extracting text from scanned/image PDFs.
    Supports auto-detection, caching, and multiple OCR engines.
    """

    def __init__(
        self,
        mode: str = OCR_MODE,
        engine: str = OCR_ENGINE,
        language: str = OCR_LANG,
        dpi: int = OCR_DPI,
        max_pages: int = OCR_MAX_PAGES_PER_DOC,
    ):
        self.mode = mode  # "auto" | "force" | "off"
        self.engine = engine
        self.language = language
        self.dpi = dpi
        self.max_pages = max_pages
        self.cache = OCRCache()

        # Validate OCR availability
        if self.mode != "off" and not TESSERACT_AVAILABLE:
            logger.warning("OCR requested but pytesseract not installed. OCR disabled.")
            self.mode = "off"

        # Setup Tesseract path for Windows
        if TESSERACT_AVAILABLE:
            self._setup_tesseract()

    def _setup_tesseract(self):
        """Configure Tesseract path for Windows."""
        tesseract_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            "/usr/bin/tesseract",  # Linux/Docker
        ]
        for path in tesseract_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                logger.info(f"   Tesseract found: {path}")
                break

    def _get_file_hash(self, pdf_path: str) -> str:
        """Get hash of PDF file for caching."""
        with open(pdf_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()[:16]

    def should_ocr_page(self, page: fitz.Page) -> Tuple[bool, dict]:
        """
        Fast heuristics to determine if a page needs OCR.

        Returns:
            (needs_ocr: bool, stats: dict)
        """
        # Extract native text
        text = page.get_text().strip()
        char_count = len(text)

        # Calculate alpha ratio (letters vs total chars)
        alpha_count = sum(1 for c in text if c.isalpha())
        alpha_ratio = alpha_count / max(char_count, 1)

        # Check for images
        image_list = page.get_images(full=True)
        image_count = len(image_list)

        # Calculate image coverage (approximate)
        page_area = page.rect.width * page.rect.height
        image_coverage = 0.0

        for img in image_list:
            try:
                # Get image bbox if available
                img_rects = page.get_image_rects(img[0])
                for rect in img_rects:
                    image_coverage += (rect.width * rect.height) / page_area
            except Exception:
                # Estimate based on count
                image_coverage = min(0.8, image_count * 0.3)

        stats = {
            "char_count": char_count,
            "alpha_ratio": round(alpha_ratio, 3),
            "image_count": image_count,
            "image_coverage": round(image_coverage, 3),
        }

        # Decision logic
        needs_ocr = False

        # Rule 1: Very little text
        if char_count < OCR_MIN_CHARS_THRESHOLD:
            needs_ocr = True
            stats["reason"] = "low_char_count"

        # Rule 2: Low alpha ratio (might be garbled/encoded)
        elif alpha_ratio < OCR_MIN_ALPHA_RATIO:
            needs_ocr = True
            stats["reason"] = "low_alpha_ratio"

        # Rule 3: Large image coverage with little text
        elif image_coverage > OCR_IMAGE_COVERAGE_THRESHOLD and char_count < 200:
            needs_ocr = True
            stats["reason"] = "image_dominant"

        return needs_ocr, stats

    def extract_text_with_ocr(
        self,
        pdf_path: str,
        page_number: int,
        file_hash: Optional[str] = None,
    ) -> OCRResult:
        """
        Extract text from a PDF page using OCR.

        Args:
            pdf_path: Path to PDF file
            page_number: 1-indexed page number
            file_hash: Optional pre-computed file hash for caching

        Returns:
            OCRResult with extracted text
        """
        if not TESSERACT_AVAILABLE:
            return OCRResult(
                text="",
                engine="none",
                warnings=["OCR not available - pytesseract not installed"]
            )

        # Check cache
        if file_hash is None:
            file_hash = self._get_file_hash(pdf_path)

        cached = self.cache.get(file_hash, page_number, self.dpi, self.language, self.engine)
        if cached:
            logger.info(f"   [PAGE {page_number}] OCR cache hit")
            return cached

        warnings = []
        confidence = None

        try:
            doc = fitz.open(pdf_path)
            page = doc[page_number - 1]  # 0-indexed

            # Render page to image
            mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image
            img_data = pix.tobytes("png")
            img = Image.open(BytesIO(img_data))

            # Run OCR
            lang = self.language
            try:
                # Try with configured language
                ocr_data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
                text = pytesseract.image_to_string(img, lang=lang)

                # Calculate average confidence
                confidences = [int(c) for c in ocr_data['conf'] if int(c) > 0]
                if confidences:
                    confidence = round(sum(confidences) / len(confidences) / 100, 3)

            except Exception as e:
                # Fallback to English only
                if '+' in lang:
                    warnings.append(f"Language {lang} failed, using eng: {str(e)[:50]}")
                    lang = "eng"
                    text = pytesseract.image_to_string(img, lang=lang)
                else:
                    raise

            doc.close()

            # Clean up text
            text = self._normalize_text(text)

            # Low confidence warning
            if confidence and confidence < 0.5:
                warnings.append(f"Low OCR confidence: {confidence}")

            result = OCRResult(
                text=text,
                confidence=confidence,
                engine=self.engine,
                language=lang,
                warnings=warnings,
            )

            # Cache result
            self.cache.set(file_hash, page_number, self.dpi, self.language, self.engine, result)

            return result

        except Exception as e:
            logger.error(f"   OCR failed for page {page_number}: {e}")
            return OCRResult(
                text="",
                engine=self.engine,
                language=self.language,
                warnings=[f"OCR error: {str(e)[:100]}"]
            )

    def _normalize_text(self, text: str) -> str:
        """Clean up OCR output text."""
        if not text:
            return ""

        # Remove excessive whitespace
        lines = text.split('\n')
        cleaned_lines = []

        for line in lines:
            # Collapse multiple spaces
            line = ' '.join(line.split())
            if line:
                cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def extract_text_auto(self, pdf_path: str) -> List[PageText]:
        """
        Extract text from all pages with automatic OCR fallback.

        Returns:
            List of PageText objects, one per page
        """
        results = []
        file_hash = self._get_file_hash(pdf_path)

        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        # Safety limit
        if total_pages > self.max_pages:
            logger.warning(f"   PDF has {total_pages} pages, limiting to {self.max_pages}")
            total_pages = self.max_pages

        # Stats for summary
        ocr_count = 0
        native_count = 0
        failed_count = 0
        total_ocr_time = 0

        for page_num in range(total_pages):
            page = doc[page_num]
            page_number = page_num + 1  # 1-indexed

            start_time = time.time()
            warnings = []

            # Get native text first
            native_text = page.get_text().strip()

            # Determine extraction method
            if self.mode == "off":
                # Native only
                text = native_text
                method = "native"
                ocr_result = None
                native_count += 1

            elif self.mode == "force":
                # Force OCR on all pages
                ocr_result = self.extract_text_with_ocr(pdf_path, page_number, file_hash)
                text = ocr_result.text
                method = "ocr"
                warnings.extend(ocr_result.warnings)
                ocr_count += 1
                total_ocr_time += int((time.time() - start_time) * 1000)

            else:  # auto mode
                needs_ocr, stats = self.should_ocr_page(page)

                if needs_ocr:
                    ocr_result = self.extract_text_with_ocr(pdf_path, page_number, file_hash)
                    ocr_time = int((time.time() - start_time) * 1000)
                    total_ocr_time += ocr_time

                    # Decide: use OCR, native, or merge
                    if len(ocr_result.text) > len(native_text) * 1.5:
                        # OCR got significantly more text
                        text = ocr_result.text
                        method = "ocr"
                    elif len(native_text) > 50 and len(ocr_result.text) > 50:
                        # Both have content, prefer native but note OCR available
                        text = native_text
                        method = "native+ocr"
                    elif ocr_result.text:
                        text = ocr_result.text
                        method = "ocr"
                    else:
                        text = native_text
                        method = "native"

                    warnings.extend(ocr_result.warnings)
                    ocr_count += 1
                else:
                    text = native_text
                    method = "native"
                    ocr_result = None
                    native_count += 1

            # Check for failed extraction
            if not text or len(text) < 10:
                failed_count += 1
                warnings.append("Very little text extracted")

            # Build PageText
            page_text = PageText(
                page_number=page_number,
                text=text,
                extraction_method=method,
                char_count=len(text),
                word_count=len(text.split()) if text else 0,
                ocr_engine=self.engine if method in ("ocr", "native+ocr") else None,
                ocr_language=self.language if method in ("ocr", "native+ocr") else None,
                ocr_confidence=ocr_result.confidence if ocr_result else None,
                ocr_time_ms=total_ocr_time if method == "ocr" else None,
                warnings=warnings,
            )

            results.append(page_text)

            # Log progress
            conf_str = f" conf={ocr_result.confidence}" if ocr_result and ocr_result.confidence else ""
            logger.info(f"   [PAGE {page_number}/{total_pages}] method={method} chars={len(text)}{conf_str}")

        doc.close()

        # Summary log
        logger.info(f"   ----------------------------------------")
        logger.info(f"   Extraction summary: native={native_count}, ocr={ocr_count}, failed={failed_count}")
        if total_ocr_time > 0:
            logger.info(f"   Total OCR time: {total_ocr_time}ms")

        return results

    def detect_table_like_structure(self, text: str) -> bool:
        """
        Simple heuristic to detect if text might contain table data.

        Returns:
            True if text shows table-like patterns
        """
        if not text:
            return False

        lines = text.split('\n')
        if len(lines) < 3:
            return False

        # Check for aligned patterns
        tab_count = text.count('\t')
        pipe_count = text.count('|')

        # Check for repeated numeric patterns
        numeric_lines = 0
        for line in lines:
            numbers = sum(1 for word in line.split() if any(c.isdigit() for c in word))
            if numbers >= 3:
                numeric_lines += 1

        # Heuristics
        if tab_count > 10:
            return True
        if pipe_count > 5:
            return True
        if numeric_lines > len(lines) * 0.5:
            return True

        return False


# Singleton instance
_ocr_pipeline: Optional[OCRPipeline] = None


def get_ocr_pipeline(
    mode: Optional[str] = None,
    language: Optional[str] = None,
) -> OCRPipeline:
    """Get or create OCR pipeline singleton."""
    global _ocr_pipeline

    # If custom settings, create new instance
    if mode or language:
        return OCRPipeline(
            mode=mode or OCR_MODE,
            language=language or OCR_LANG,
        )

    # Return singleton
    if _ocr_pipeline is None:
        _ocr_pipeline = OCRPipeline()

    return _ocr_pipeline
