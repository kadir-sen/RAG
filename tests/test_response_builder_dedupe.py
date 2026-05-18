"""Regression tests for the citation/related_docs dedupe fix.

The bug: production Pinecone holds two ingestions of the same source file
(once with a Windows path, once with a Linux container path). Each carries
its own LlamaIndex UUID, so the assistant response surfaced both as
separate references in the timeline and one of them — the one whose path
no longer existed on disk — 404'd in the viewer.

response_builder now:
  1. Dedupes citations + related_docs by ``file_name``.
  2. Remaps every ``doc_id`` to the canonical DocumentRegistry id when a
     matching record exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services import response_builder as rb  # noqa: E402
from backend.services.response_builder import (  # noqa: E402
    _extract_citations_and_related,
)


@pytest.fixture
def fake_registry(monkeypatch):
    """Stub the canonical-id resolver so tests don't have to construct a real
    DocumentRegistry (which would drag in the full document_rag import chain).
    """

    mapping = {
        "FW_ Vingcard.msg": "canonical_msg",
        "DPS Letter_TABH.pdf": "canonical_pdf",
    }

    def _stub(file_name: str, fallback: str) -> str:
        return mapping.get(file_name, fallback)

    monkeypatch.setattr(rb, "_resolve_canonical_doc_id", _stub)
    return mapping


class TestRelatedDocsDedupe:
    def test_duplicate_search_results_collapse_to_one(self, fake_registry):
        sources = [
            {
                "type": "search_result",
                "doc_id": "ingest_a_uuid",
                "file_name": "FW_ Vingcard.msg",
                "date": "2019-05-20",
                "sender": "Paul Thornton",
            },
            {
                "type": "search_result",
                "doc_id": "ingest_b_uuid",  # second ingestion of the same file
                "file_name": "FW_ Vingcard.msg",
                "date": "2019-05-20",
                "sender": "Paul Thornton",
            },
        ]
        _cits, related = _extract_citations_and_related(sources, "file_list")
        assert len(related) == 1
        # The doc_id has been remapped to the registry's canonical id so the
        # viewer can resolve it.
        assert related[0].doc_id == "canonical_msg"
        assert related[0].doc_name == "FW_ Vingcard.msg"

    def test_different_files_are_not_collapsed(self, fake_registry):
        sources = [
            {
                "type": "search_result",
                "doc_id": "x",
                "file_name": "FW_ Vingcard.msg",
            },
            {
                "type": "notice",
                "doc_id": "y",
                "file_name": "DPS Letter_TABH.pdf",
            },
        ]
        _cits, related = _extract_citations_and_related(sources, "file_list")
        assert {r.doc_name for r in related} == {
            "FW_ Vingcard.msg",
            "DPS Letter_TABH.pdf",
        }
        assert {r.doc_id for r in related} == {"canonical_msg", "canonical_pdf"}


class TestCitationsDedupe:
    def test_duplicate_citations_collapse_to_one(self, fake_registry):
        sources = [
            {
                "doc_id": "ingest_a_uuid",
                "file_name": "DPS Letter_TABH.pdf",
                "page_number": 2,
                "text_snippet": "Lorem ipsum",
            },
            {
                "doc_id": "ingest_b_uuid",
                "file_name": "DPS Letter_TABH.pdf",
                "page_number": 2,
                "text_snippet": "Lorem ipsum",
            },
        ]
        citations, _ = _extract_citations_and_related(sources, "document")
        assert len(citations) == 1
        assert citations[0].doc_id == "canonical_pdf"
        assert citations[0].anchor == "page_2"

    def test_unknown_filename_keeps_raw_doc_id(self, fake_registry):
        """When the registry doesn't know the file, fall back to raw id so
        legacy clients (e.g. data-only sources) still surface something."""
        sources = [{
            "doc_id": "raw_uuid_xyz",
            "file_name": "BrandNewFile.pdf",
            "page_number": 1,
        }]
        citations, _ = _extract_citations_and_related(sources, "document")
        assert len(citations) == 1
        assert citations[0].doc_id == "raw_uuid_xyz"


class TestStructuredDataSkipped:
    def test_structured_data_sources_are_dropped(self, fake_registry):
        sources = [
            {"type": "structured_data", "doc_id": "x", "file_name": "x.xlsx"},
            {"type": "search_result", "doc_id": "y", "file_name": "FW_ Vingcard.msg"},
        ]
        citations, related = _extract_citations_and_related(sources, "file_list")
        assert citations == []
        assert len(related) == 1
        assert related[0].doc_name == "FW_ Vingcard.msg"
