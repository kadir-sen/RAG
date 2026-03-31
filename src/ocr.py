"""
OCR Module - Detection and extraction pipeline for scanned PDFs.

Combines OCR decision classification (detect which pages need OCR)
and OCR execution (extract text via Tesseract) into a single module.
"""
import os
import hashlib
import json
import time
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
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


# ── OCR Decision Types ──────────────────────────────────────

class OCRDecision(Enum):
    """OCR decision for a page or document."""
    NATIVE = "native"  # Text extraction sufficient
    OCR = "ocr"  # Full OCR needed
    HYBRID = "hybrid"  # Some pages need OCR


@dataclass
class PageAnalysis:
    """Analysis result for a single page."""
    page_number: int
    char_count: int
    alpha_ratio: float
    image_coverage: float
    needs_ocr: bool
    reason: str


@dataclass
class DocumentAnalysis:
    """Analysis result for entire document."""
    file_path: str
    total_pages: int
    native_pages: int
    ocr_pages: int
    decision: OCRDecision
    page_analyses: List[PageAnalysis]


# ── OCR Result Types ────────────────────────────────────────

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


# ── OCR Detector ────────────────────────────────────────────

class OCRDetector:
    """
    Analyzes PDF pages to decide if OCR is needed.
    Uses fast heuristics without actually running OCR.
    """

    def __init__(
        self,
        min_chars: int = OCR_MIN_CHARS_THRESHOLD,
        min_alpha_ratio: float = OCR_MIN_ALPHA_RATIO,
        image_coverage_threshold: float = OCR_IMAGE_COVERAGE_THRESHOLD,
    ):
        self.min_chars = min_chars
        self.min_alpha_ratio = min_alpha_ratio
        self.image_coverage_threshold = image_coverage_threshold

    def analyze_document(self, file_path: str) -> DocumentAnalysis:
        """Analyze entire PDF to decide OCR strategy."""
        path = Path(file_path)
        logger.info(f"[OCRDetector] Analyzing: {path.name}")

        page_analyses = []
        native_pages = 0
        ocr_pages = 0

        try:
            doc = fitz.open(file_path)
            total_pages = len(doc)

            for page_num in range(total_pages):
                page = doc[page_num]
                analysis = self._analyze_page(page, page_num + 1)
                page_analyses.append(analysis)

                if analysis.needs_ocr:
                    ocr_pages += 1
                else:
                    native_pages += 1

            doc.close()

            if ocr_pages == 0:
                decision = OCRDecision.NATIVE
            elif native_pages == 0:
                decision = OCRDecision.OCR
            else:
                decision = OCRDecision.HYBRID

            logger.info(f"[OCRDetector] Decision: {decision.value}")
            logger.info(f"[OCRDetector] Native: {native_pages}, OCR: {ocr_pages}/{total_pages}")

            return DocumentAnalysis(
                file_path=file_path,
                total_pages=total_pages,
                native_pages=native_pages,
                ocr_pages=ocr_pages,
                decision=decision,
                page_analyses=page_analyses,
            )

        except Exception as e:
            logger.error(f"[OCRDetector] Error analyzing document: {e}")
            return DocumentAnalysis(
                file_path=file_path,
                total_pages=0,
                native_pages=0,
                ocr_pages=0,
                decision=OCRDecision.OCR,
                page_analyses=[],
            )

    def _analyze_page(self, page: fitz.Page, page_number: int) -> PageAnalysis:
        """Analyze a single page to determine if OCR is needed."""
        try:
            text = page.get_text("text")
            char_count = len(text)
            alpha_count = sum(1 for c in text if c.isalpha())
            alpha_ratio = alpha_count / char_count if char_count > 0 else 0
            image_coverage = self._calculate_image_coverage(page)

            needs_ocr = False
            reason = "native text sufficient"

            if char_count < self.min_chars:
                needs_ocr = True
                reason = f"too few chars ({char_count} < {self.min_chars})"
            elif alpha_ratio < self.min_alpha_ratio:
                needs_ocr = True
                reason = f"low alpha ratio ({alpha_ratio:.2f} < {self.min_alpha_ratio})"
            elif image_coverage > self.image_coverage_threshold and char_count < 100:
                needs_ocr = True
                reason = f"high image coverage ({image_coverage:.2f}) with little text"

            return PageAnalysis(
                page_number=page_number,
                char_count=char_count,
                alpha_ratio=alpha_ratio,
                image_coverage=image_coverage,
                needs_ocr=needs_ocr,
                reason=reason,
            )

        except Exception as e:
            logger.warning(f"[OCRDetector] Error analyzing page {page_number}: {e}")
            return PageAnalysis(
                page_number=page_number,
                char_count=0,
                alpha_ratio=0,
                image_coverage=1.0,
                needs_ocr=True,
                reason=f"analysis error: {str(e)}",
            )

    def _calculate_image_coverage(self, page: fitz.Page) -> float:
        """Calculate what fraction of the page is covered by images."""
        try:
            page_area = page.rect.width * page.rect.height
            if page_area == 0:
                return 0

            images = page.get_images(full=True)
            image_area = 0

            for img in images:
                try:
                    xref = img[0]
                    img_rects = page.get_image_rects(xref)
                    for rect in img_rects:
                        if rect:
                            image_area += rect.width * rect.height
                except Exception:
                    pass

            return min(1.0, image_area / page_area)

        except Exception:
            return 0

    def needs_ocr_page(self, page: fitz.Page) -> Tuple[bool, str]:
        """Quick check if a single page needs OCR."""
        analysis = self._analyze_page(page, 0)
        return analysis.needs_ocr, analysis.reason

    def get_ocr_pages(self, file_path: str) -> List[int]:
        """Get list of 1-indexed page numbers that need OCR."""
        analysis = self.analyze_document(file_path)
        return [pa.page_number for pa in analysis.page_analyses if pa.needs_ocr]


class OCRMyPDFIntegration:
    """
    Integration with ocrmypdf for generating searchable PDFs.
    Optional enhancement - not required for basic functionality.
    """

    @staticmethod
    def is_available() -> bool:
        """Check if ocrmypdf is available."""
        try:
            import ocrmypdf
            return True
        except ImportError:
            return False

    @staticmethod
    def run_ocr(
        input_path: str,
        output_path: str,
        language: str = "eng",
        pages: Optional[List[int]] = None,
    ) -> bool:
        """Run ocrmypdf on a PDF."""
        try:
            import ocrmypdf

            args = {
                "input_file": input_path,
                "output_file": output_path,
                "language": language,
                "deskew": True,
                "clean": True,
                "skip_text": True,
            }

            if pages:
                args["pages"] = ",".join(str(p) for p in pages)

            ocrmypdf.ocr(**args)
            logger.info(f"[OCRMyPDF] Successfully processed: {Path(input_path).name}")
            return True

        except ImportError:
            logger.warning("[OCRMyPDF] ocrmypdf not installed")
            return False
        except Exception as e:
            logger.error(f"[OCRMyPDF] Error: {e}")
            return False


# ── Convenience Functions (Detector) ────────────────────────

def analyze_pdf(file_path: str) -> DocumentAnalysis:
    """Analyze PDF and return OCR decision."""
    detector = OCRDetector()
    return detector.analyze_document(file_path)


def get_ocr_decision(file_path: str) -> str:
    """Get simple OCR decision string for a PDF."""
    analysis = analyze_pdf(file_path)
    return analysis.decision.value


def needs_any_ocr(file_path: str) -> bool:
    """Check if any page in the PDF needs OCR."""
    analysis = analyze_pdf(file_path)
    return analysis.ocr_pages > 0


# ── OCR Cache ───────────────────────────────────────────────

class OCRCache:
    """Simple file-based cache for OCR results."""

    def __init__(self, cache_dir: str = OCR_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, file_hash: str, page_num: int, dpi: int, lang: str, engine: str) -> str:
        key_parts = f"{file_hash}_{page_num}_{dpi}_{lang}_{engine}"
        return hashlib.md5(key_parts.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{cache_key}.json"

    def get(self, file_hash: str, page_num: int, dpi: int, lang: str, engine: str) -> Optional[OCRResult]:
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
        cache_key = self._get_cache_key(file_hash, page_num, dpi, lang, engine)
        cache_path = self._get_cache_path(cache_key)

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(result), f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to cache OCR result: {e}")


# ── OCR Pipeline ────────────────────────────────────────────

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

        if self.mode != "off" and not TESSERACT_AVAILABLE:
            logger.warning("OCR requested but pytesseract not installed. OCR disabled.")
            self.mode = "off"

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
        with open(pdf_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()[:16]

    def should_ocr_page(self, page: fitz.Page) -> Tuple[bool, dict]:
        """Fast heuristics to determine if a page needs OCR."""
        text = page.get_text().strip()
        char_count = len(text)
        alpha_count = sum(1 for c in text if c.isalpha())
        alpha_ratio = alpha_count / max(char_count, 1)

        image_list = page.get_images(full=True)
        image_count = len(image_list)
        page_area = page.rect.width * page.rect.height
        image_coverage = 0.0

        for img in image_list:
            try:
                img_rects = page.get_image_rects(img[0])
                for rect in img_rects:
                    image_coverage += (rect.width * rect.height) / page_area
            except Exception:
                image_coverage = min(0.8, image_count * 0.3)

        stats = {
            "char_count": char_count,
            "alpha_ratio": round(alpha_ratio, 3),
            "image_count": image_count,
            "image_coverage": round(image_coverage, 3),
        }

        needs_ocr = False
        if char_count < OCR_MIN_CHARS_THRESHOLD:
            needs_ocr = True
            stats["reason"] = "low_char_count"
        elif alpha_ratio < OCR_MIN_ALPHA_RATIO:
            needs_ocr = True
            stats["reason"] = "low_alpha_ratio"
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
        """Extract text from a PDF page using OCR."""
        if not TESSERACT_AVAILABLE:
            return OCRResult(
                text="",
                engine="none",
                warnings=["OCR not available - pytesseract not installed"]
            )

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
            page = doc[page_number - 1]

            mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            img = Image.open(BytesIO(img_data))

            lang = self.language
            try:
                ocr_data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
                text = pytesseract.image_to_string(img, lang=lang)
                confidences = [int(c) for c in ocr_data['conf'] if int(c) > 0]
                if confidences:
                    confidence = round(sum(confidences) / len(confidences) / 100, 3)
            except Exception as e:
                if '+' in lang:
                    warnings.append(f"Language {lang} failed, using eng: {str(e)[:50]}")
                    lang = "eng"
                    text = pytesseract.image_to_string(img, lang=lang)
                else:
                    raise

            doc.close()
            text = self._normalize_text(text)

            if confidence and confidence < 0.5:
                warnings.append(f"Low OCR confidence: {confidence}")

            result = OCRResult(
                text=text,
                confidence=confidence,
                engine=self.engine,
                language=lang,
                warnings=warnings,
            )

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
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line = ' '.join(line.split())
            if line:
                cleaned_lines.append(line)
        return '\n'.join(cleaned_lines)

    def extract_text_auto(self, pdf_path: str) -> List[PageText]:
        """Extract text from all pages with automatic OCR fallback."""
        results = []
        file_hash = self._get_file_hash(pdf_path)

        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        if total_pages > self.max_pages:
            logger.warning(f"   PDF has {total_pages} pages, limiting to {self.max_pages}")
            total_pages = self.max_pages

        ocr_count = 0
        native_count = 0
        failed_count = 0
        total_ocr_time = 0

        for page_num in range(total_pages):
            page = doc[page_num]
            page_number = page_num + 1

            start_time = time.time()
            warnings = []

            native_text = page.get_text().strip()

            if self.mode == "off":
                text = native_text
                method = "native"
                ocr_result = None
                native_count += 1

            elif self.mode == "force":
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

                    if len(ocr_result.text) > len(native_text) * 1.5:
                        text = ocr_result.text
                        method = "ocr"
                    elif len(native_text) > 50 and len(ocr_result.text) > 50:
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

            if not text or len(text) < 10:
                failed_count += 1
                warnings.append("Very little text extracted")

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

            conf_str = f" conf={ocr_result.confidence}" if ocr_result and ocr_result.confidence else ""
            logger.info(f"   [PAGE {page_number}/{total_pages}] method={method} chars={len(text)}{conf_str}")

        doc.close()

        logger.info(f"   ----------------------------------------")
        logger.info(f"   Extraction summary: native={native_count}, ocr={ocr_count}, failed={failed_count}")
        if total_ocr_time > 0:
            logger.info(f"   Total OCR time: {total_ocr_time}ms")

        return results

    def detect_table_like_structure(self, text: str) -> bool:
        """Simple heuristic to detect if text might contain table data."""
        if not text:
            return False
        lines = text.split('\n')
        if len(lines) < 3:
            return False

        tab_count = text.count('\t')
        pipe_count = text.count('|')
        numeric_lines = 0
        for line in lines:
            numbers = sum(1 for word in line.split() if any(c.isdigit() for c in word))
            if numbers >= 3:
                numeric_lines += 1

        if tab_count > 10:
            return True
        if pipe_count > 5:
            return True
        if numeric_lines > len(lines) * 0.5:
            return True

        return False


# ── Singleton ───────────────────────────────────────────────

_ocr_pipeline: Optional[OCRPipeline] = None


def get_ocr_pipeline(
    mode: Optional[str] = None,
    language: Optional[str] = None,
) -> OCRPipeline:
    """Get or create OCR pipeline singleton."""
    global _ocr_pipeline

    if mode or language:
        return OCRPipeline(
            mode=mode or OCR_MODE,
            language=language or OCR_LANG,
        )

    if _ocr_pipeline is None:
        _ocr_pipeline = OCRPipeline()

    return _ocr_pipeline
