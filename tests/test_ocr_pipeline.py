"""
Unit tests for OCR Pipeline.

Run with: pytest tests/test_ocr_pipeline.py -v
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestShouldOcrPage:
    """Tests for should_ocr_page heuristics."""

    @pytest.fixture
    def ocr_pipeline(self):
        """Create OCR pipeline for testing."""
        # Mock OCR availability
        with patch('src.ocr_pipeline.TESSERACT_AVAILABLE', True):
            from src.ocr_pipeline import OCRPipeline
            pipeline = OCRPipeline(mode="auto")
            return pipeline

    def test_empty_page_needs_ocr(self, ocr_pipeline):
        """Empty page should trigger OCR."""
        page = Mock()
        page.get_text.return_value = ""
        page.get_images.return_value = []

        needs_ocr, stats = ocr_pipeline.should_ocr_page(page)

        assert needs_ocr is True
        assert stats["char_count"] == 0

    def test_short_text_needs_ocr(self, ocr_pipeline):
        """Very short text should trigger OCR."""
        page = Mock()
        page.get_text.return_value = "Hello"  # Only 5 chars
        page.get_images.return_value = []

        needs_ocr, stats = ocr_pipeline.should_ocr_page(page)

        assert needs_ocr is True
        assert stats["char_count"] == 5

    def test_normal_text_no_ocr(self, ocr_pipeline):
        """Normal text page should not need OCR."""
        page = Mock()
        page.get_text.return_value = "This is a normal page with plenty of text content. " * 10
        page.get_images.return_value = []

        needs_ocr, stats = ocr_pipeline.should_ocr_page(page)

        assert needs_ocr is False
        assert stats["char_count"] > 100

    def test_low_alpha_ratio_needs_ocr(self, ocr_pipeline):
        """Page with mostly non-alpha chars should trigger OCR."""
        page = Mock()
        page.get_text.return_value = "123456789012345678901234567890@@@@@@@@@@"  # Low alpha ratio
        page.get_images.return_value = []

        needs_ocr, stats = ocr_pipeline.should_ocr_page(page)

        assert needs_ocr is True
        assert stats["alpha_ratio"] < 0.2


class TestDetectTableStructure:
    """Tests for table detection heuristics."""

    @pytest.fixture
    def ocr_pipeline(self):
        with patch('src.ocr_pipeline.TESSERACT_AVAILABLE', True):
            from src.ocr_pipeline import OCRPipeline
            return OCRPipeline(mode="auto")

    def test_detect_tab_separated_table(self, ocr_pipeline):
        """Detect table with tab separators."""
        text = "Name\tAge\tCity\nJohn\t25\tNY\nJane\t30\tLA\n" * 5

        assert ocr_pipeline.detect_table_like_structure(text) is True

    def test_detect_pipe_separated_table(self, ocr_pipeline):
        """Detect table with pipe separators."""
        text = "| Name | Age | City |\n| John | 25 | NY |\n| Jane | 30 | LA |"

        assert ocr_pipeline.detect_table_like_structure(text) is True

    def test_detect_numeric_table(self, ocr_pipeline):
        """Detect table with many numbers."""
        text = "Q1 100 200 300\nQ2 150 250 350\nQ3 200 300 400\nQ4 250 350 450"

        assert ocr_pipeline.detect_table_like_structure(text) is True

    def test_no_table_in_prose(self, ocr_pipeline):
        """Normal prose should not be detected as table."""
        text = "This is a normal paragraph with some text. It doesn't have any table structure."

        assert ocr_pipeline.detect_table_like_structure(text) is False

    def test_empty_text_no_table(self, ocr_pipeline):
        """Empty text should not be detected as table."""
        assert ocr_pipeline.detect_table_like_structure("") is False
        assert ocr_pipeline.detect_table_like_structure(None) is False


class TestOCRCache:
    """Tests for OCR caching."""

    def test_cache_miss_returns_none(self, tmp_path):
        """Cache miss should return None."""
        from src.ocr_pipeline import OCRCache

        cache = OCRCache(cache_dir=str(tmp_path / "ocr_cache"))
        result = cache.get("hash123", 1, 200, "eng", "tesseract")

        assert result is None

    def test_cache_set_and_get(self, tmp_path):
        """Cache should store and retrieve results."""
        from src.ocr_pipeline import OCRCache, OCRResult

        cache = OCRCache(cache_dir=str(tmp_path / "ocr_cache"))

        # Store result
        result = OCRResult(
            text="Hello World",
            confidence=0.95,
            engine="tesseract",
            language="eng",
            warnings=[],
        )
        cache.set("hash123", 1, 200, "eng", "tesseract", result)

        # Retrieve result
        cached = cache.get("hash123", 1, 200, "eng", "tesseract")

        assert cached is not None
        assert cached.text == "Hello World"
        assert cached.confidence == 0.95

    def test_different_params_different_cache(self, tmp_path):
        """Different params should have separate cache entries."""
        from src.ocr_pipeline import OCRCache, OCRResult

        cache = OCRCache(cache_dir=str(tmp_path / "ocr_cache"))

        # Store with eng
        result_eng = OCRResult(text="English text", engine="tesseract", language="eng")
        cache.set("hash123", 1, 200, "eng", "tesseract", result_eng)

        # Store with tur
        result_tur = OCRResult(text="Turkish text", engine="tesseract", language="tur")
        cache.set("hash123", 1, 200, "tur", "tesseract", result_tur)

        # Retrieve separately
        cached_eng = cache.get("hash123", 1, 200, "eng", "tesseract")
        cached_tur = cache.get("hash123", 1, 200, "tur", "tesseract")

        assert cached_eng.text == "English text"
        assert cached_tur.text == "Turkish text"


class TestOCRModeOff:
    """Tests for OCR off mode."""

    def test_ocr_off_skips_ocr(self):
        """OCR off mode should never use OCR."""
        with patch('src.ocr_pipeline.TESSERACT_AVAILABLE', True):
            from src.ocr_pipeline import OCRPipeline

            pipeline = OCRPipeline(mode="off")

            assert pipeline.mode == "off"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
