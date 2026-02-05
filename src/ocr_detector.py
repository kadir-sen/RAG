"""
OCR Decision Classifier for PDFs.
Determines whether pages need OCR based on text extractability and quality.
"""
import fitz  # PyMuPDF
from pathlib import Path
from typing import Tuple, List, Optional
from dataclasses import dataclass
from enum import Enum

from .logger import logger
from .config import (
    OCR_MIN_CHARS_THRESHOLD,
    OCR_MIN_ALPHA_RATIO,
    OCR_IMAGE_COVERAGE_THRESHOLD,
)


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
        """
        Initialize OCR detector.

        Args:
            min_chars: Minimum character count to skip OCR
            min_alpha_ratio: Minimum ratio of alphabetic characters
            image_coverage_threshold: Max image coverage before OCR needed
        """
        self.min_chars = min_chars
        self.min_alpha_ratio = min_alpha_ratio
        self.image_coverage_threshold = image_coverage_threshold

    def analyze_document(self, file_path: str) -> DocumentAnalysis:
        """
        Analyze entire PDF to decide OCR strategy.

        Args:
            file_path: Path to PDF file

        Returns:
            DocumentAnalysis with per-page decisions
        """
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

            # Decide overall strategy
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
                decision=OCRDecision.OCR,  # Default to OCR on error
                page_analyses=[],
            )

    def _analyze_page(self, page: fitz.Page, page_number: int) -> PageAnalysis:
        """
        Analyze a single page to determine if OCR is needed.

        Args:
            page: PyMuPDF page object
            page_number: 1-indexed page number

        Returns:
            PageAnalysis with decision
        """
        try:
            # Extract text
            text = page.get_text("text")

            # Calculate metrics
            char_count = len(text)
            alpha_count = sum(1 for c in text if c.isalpha())
            alpha_ratio = alpha_count / char_count if char_count > 0 else 0

            # Calculate image coverage
            image_coverage = self._calculate_image_coverage(page)

            # Decision logic
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
        """
        Calculate what fraction of the page is covered by images.

        Args:
            page: PyMuPDF page object

        Returns:
            Float between 0 and 1 representing image coverage
        """
        try:
            page_area = page.rect.width * page.rect.height
            if page_area == 0:
                return 0

            images = page.get_images(full=True)
            image_area = 0

            for img in images:
                try:
                    # Get image bounding box
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
        """
        Quick check if a single page needs OCR.

        Args:
            page: PyMuPDF page object

        Returns:
            Tuple of (needs_ocr, reason)
        """
        analysis = self._analyze_page(page, 0)
        return analysis.needs_ocr, analysis.reason

    def get_ocr_pages(self, file_path: str) -> List[int]:
        """
        Get list of page numbers that need OCR.

        Args:
            file_path: Path to PDF file

        Returns:
            List of 1-indexed page numbers requiring OCR
        """
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
        """
        Run ocrmypdf on a PDF.

        Args:
            input_path: Path to input PDF
            output_path: Path for output PDF
            language: OCR language
            pages: Specific pages to OCR (None = all)

        Returns:
            True if successful
        """
        try:
            import ocrmypdf

            args = {
                "input_file": input_path,
                "output_file": output_path,
                "language": language,
                "deskew": True,
                "clean": True,
                "skip_text": True,  # Skip pages that already have text
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


# Convenience functions
def analyze_pdf(file_path: str) -> DocumentAnalysis:
    """
    Analyze PDF and return OCR decision.

    Args:
        file_path: Path to PDF file

    Returns:
        DocumentAnalysis with decision
    """
    detector = OCRDetector()
    return detector.analyze_document(file_path)


def get_ocr_decision(file_path: str) -> str:
    """
    Get simple OCR decision string for a PDF.

    Args:
        file_path: Path to PDF file

    Returns:
        "native", "ocr", or "hybrid"
    """
    analysis = analyze_pdf(file_path)
    return analysis.decision.value


def needs_any_ocr(file_path: str) -> bool:
    """
    Check if any page in the PDF needs OCR.

    Args:
        file_path: Path to PDF file

    Returns:
        True if at least one page needs OCR
    """
    analysis = analyze_pdf(file_path)
    return analysis.ocr_pages > 0
