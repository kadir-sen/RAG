"""Upload pipeline tests for .xer programme files."""

from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "xer"


class TestExtensionMaps:
    def test_file_service_map(self):
        from backend.services.file_service import EXTENSION_MAP
        from src.config import PROGRAMME_DIR
        assert EXTENSION_MAP[".xer"] == ("programme", PROGRAMME_DIR)

    def test_file_router_map(self):
        from src.file_router import EXTENSION_MAP
        assert EXTENSION_MAP[".xer"] == "programme"


class TestProcessProgramme:
    def test_valid_xer_succeeds(self):
        from src.file_router import _process_programme
        result = _process_programme(str(sorted(FIXTURES.glob("*.xer"))[0]))
        assert result.success is True
        assert result.file_type == "programme"

    def test_corrupt_xer_errors(self, tmp_path):
        from src.file_router import _process_programme
        bad = tmp_path / "junk.xer"
        bad.write_text("definitely not an xer")
        result = _process_programme(str(bad))
        assert result.success is False
        assert "XER" in (result.error or "")

    def test_route_file_dispatches_programme(self, tmp_path):
        """route_file registers the .xer and marks it completed without any
        chunking/embedding side effects."""
        from src import file_router

        src_file = sorted(FIXTURES.glob("*.xer"))[0]
        target = tmp_path / src_file.name
        target.write_bytes(src_file.read_bytes())

        class FakeRecord:
            doc_id = "test-doc-id"

        class FakeRegistry:
            def __init__(self):
                self.completed = None
                self.error = None
            def register(self, **kw):
                assert kw["file_type"] == "programme"
                return FakeRecord()
            def mark_completed(self, doc_id, **kw):
                self.completed = doc_id
            def mark_error(self, doc_id, msg):
                self.error = (doc_id, msg)

        fake = FakeRegistry()
        with patch("src.document_registry.get_document_registry",
                   return_value=fake), \
             patch("src.document_rag.generate_doc_id",
                   return_value="test-doc-id"):
            result = file_router.route_file(str(target))
        assert result.success is True
        assert fake.completed == "test-doc-id"
        assert fake.error is None
