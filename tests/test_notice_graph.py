"""
Unit tests for Notice Extractor and Light Graph (Phase 2).

Run with: pytest tests/test_notice_graph.py -v
"""
import pytest
import sys
import json
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNoticeExtractor:
    """Tests for NoticeExtractor."""

    def test_date_extraction_iso(self):
        """Test ISO date extraction."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        # ISO format
        text = "This letter dated 2024-01-15 confirms..."
        pages = {1: text}

        date, evidence = extractor._extract_date(text, pages)

        assert date == "2024-01-15"
        assert evidence is not None
        assert evidence["field_name"] == "date"

    def test_date_extraction_written(self):
        """Test written date extraction."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        text = "Letter dated January 15, 2024"
        pages = {1: text}

        date, evidence = extractor._extract_date(text, pages)

        assert date is not None
        assert "2024" in date
        assert evidence is not None

    def test_date_extraction_dmy(self):
        """Test DD/MM/YYYY date extraction."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        text = "Dated: 15/01/2024"
        pages = {1: text}

        date, evidence = extractor._extract_date(text, pages)

        assert date == "2024-01-15"

    def test_sender_extraction(self):
        """Test sender extraction."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        text = "From: ABC Construction Ltd\nTo: XYZ Engineering"
        pages = {1: text}

        sender, evidence = extractor._extract_pattern(
            text, extractor.SENDER_PATTERNS, "sender", pages
        )

        assert sender is not None
        assert "ABC Construction" in sender

    def test_recipient_extraction(self):
        """Test recipient extraction."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        text = "From: ABC Construction\nTo: XYZ Engineering Ltd"
        pages = {1: text}

        recipient, evidence = extractor._extract_pattern(
            text, extractor.RECIPIENT_PATTERNS, "recipient", pages
        )

        assert recipient is not None
        assert "XYZ Engineering" in recipient

    def test_subject_extraction(self):
        """Test subject extraction."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        text = "Subject: Notice of Delay - Project Phase 2\nDear Sir,"
        pages = {1: text}

        subject, evidence = extractor._extract_pattern(
            text, extractor.SUBJECT_PATTERNS, "subject", pages
        )

        assert subject is not None
        assert "Delay" in subject

    def test_reference_extraction(self):
        """Test reference number extraction."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        text = "Ref: ABC-001-2024\nYour Ref: XYZ-002\nRegarding project..."
        pages = {1: text}

        refs, evidence = extractor._extract_references(text, pages)

        assert len(refs) >= 1
        assert any("ABC-001" in ref for ref in refs)

    def test_action_extraction(self):
        """Test action keyword extraction."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        text = "We hereby submit our claim for the delay extension."
        pages = {1: text}

        actions, evidence = extractor._extract_actions(text, pages)

        assert "submit" in actions
        assert "claim" in actions
        assert "delay" in actions

    def test_language_detection_english(self):
        """Test English language detection."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        text = "Dear Sir, We are writing to inform you regarding the contract terms."

        lang = extractor._detect_language(text)

        assert lang == "en"

    def test_language_detection_turkish(self):
        """Test Turkish language detection."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        text = "Sayın yetkili, sözleşme şartları ile ilgili bilgilendirme yapıyoruz."

        lang = extractor._detect_language(text)

        assert lang == "tr"

    def test_doc_type_detection(self):
        """Test document type detection."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        letter_text = "Dear Sir, Sincerely yours,"
        notice_text = "NOTICE: We hereby notify you..."
        report_text = "Progress Report - Summary and Findings"

        assert extractor._detect_doc_type(letter_text) == "letter"
        assert extractor._detect_doc_type(notice_text) == "notice"
        assert extractor._detect_doc_type(report_text) == "report"

    def test_full_notice_extraction(self, tmp_path):
        """Test complete notice extraction."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text_by_page = {
            1: """
            Date: 2024-01-15

            From: ABC Construction Ltd
            To: XYZ Engineering

            Subject: Notice of Delay - Project Alpha

            Ref: ABC-2024-001

            Dear Sir,

            We hereby notify you of a delay in the project schedule.
            We request an extension of 30 days.

            Sincerely,
            ABC Construction
            """,
            2: "Additional details on page 2..."
        }

        # Create a temp file for testing
        test_file = tmp_path / "test_letter.pdf"
        test_file.write_text("dummy")

        notice = extractor.extract_notice(
            doc_id="test_doc_001",
            file_path=str(test_file),
            doc_text_by_page=doc_text_by_page,
        )

        assert notice.doc_id == "test_doc_001"
        assert notice.date == "2024-01-15"
        assert "ABC Construction" in notice.sender
        assert "XYZ Engineering" in notice.recipient
        assert "Delay" in notice.subject
        assert len(notice.ref_numbers) > 0
        assert "delay" in notice.actions
        assert notice.doc_type == "notice" or notice.doc_type == "letter"
        assert len(notice.evidence_spans) > 0


class TestLightGraph:
    """Tests for LightGraph."""

    def test_graph_initialization(self, tmp_path):
        """Test graph initialization."""
        from src.light_graph import LightGraph, GRAPH_DIR

        # Use temp directory
        with patch('src.light_graph.GRAPH_FILE', tmp_path / "graph.json"):
            graph = LightGraph()

            assert len(graph.graph.nodes) == 0
            assert len(graph.graph.edges) == 0

    def test_add_notice_to_graph(self, tmp_path):
        """Test adding notice to graph."""
        from src.light_graph import LightGraph
        from src.notice_extractor import NoticeMetadata

        with patch('src.light_graph.GRAPH_FILE', tmp_path / "graph.json"):
            graph = LightGraph()

            notice = NoticeMetadata(
                doc_id="doc_001",
                file_path="/path/to/doc.pdf",
                file_name="doc.pdf",
                date="2024-01-15",
                sender="ABC Corp",
                recipient="XYZ Ltd",
                subject="Test Notice",
                ref_numbers=["REF-001"],
                key_topics=["delay", "extension"],
            )

            graph.add_notice(notice)

            assert "doc_001" in graph.graph.nodes
            node = graph.graph.nodes["doc_001"]
            assert node["date"] == "2024-01-15"
            assert node["sender"] == "ABC Corp"

    def test_reference_edge_creation(self, tmp_path):
        """Test edge creation based on reference overlap."""
        from src.light_graph import LightGraph
        from src.notice_extractor import NoticeMetadata

        with patch('src.light_graph.GRAPH_FILE', tmp_path / "graph.json"):
            graph = LightGraph()

            # Add two notices with shared reference
            notice1 = NoticeMetadata(
                doc_id="doc_001",
                file_path="/path/to/doc1.pdf",
                file_name="doc1.pdf",
                date="2024-01-15",
                sender="ABC Corp",
                ref_numbers=["REF-001", "REF-002"],
                key_topics=["delay"],
            )

            notice2 = NoticeMetadata(
                doc_id="doc_002",
                file_path="/path/to/doc2.pdf",
                file_name="doc2.pdf",
                date="2024-01-20",
                sender="XYZ Ltd",
                ref_numbers=["REF-001", "REF-003"],  # Shares REF-001
                key_topics=["response"],
            )

            graph.add_notice(notice1)
            graph.add_notice(notice2)
            graph.build_edges()

            # Should have a reference edge
            ref_edges = [e for e in graph.graph.edges if e['edge_type'] == 'references']
            assert len(ref_edges) >= 1

    def test_same_party_edge_creation(self, tmp_path):
        """Test edge creation based on party overlap."""
        from src.light_graph import LightGraph
        from src.notice_extractor import NoticeMetadata

        with patch('src.light_graph.GRAPH_FILE', tmp_path / "graph.json"):
            graph = LightGraph()

            notice1 = NoticeMetadata(
                doc_id="doc_001",
                file_path="/path/to/doc1.pdf",
                file_name="doc1.pdf",
                sender="ABC Corp",
                recipient="XYZ Ltd",
                ref_numbers=["A-001"],
                key_topics=["topic1"],
            )

            notice2 = NoticeMetadata(
                doc_id="doc_002",
                file_path="/path/to/doc2.pdf",
                file_name="doc2.pdf",
                sender="XYZ Ltd",  # Was recipient in notice1
                recipient="ABC Corp",  # Was sender in notice1
                ref_numbers=["B-002"],
                key_topics=["topic2"],
            )

            graph.add_notice(notice1)
            graph.add_notice(notice2)
            graph.build_edges()

            party_edges = [e for e in graph.graph.edges if e['edge_type'] == 'same_party']
            assert len(party_edges) >= 1

    def test_timeline_query(self, tmp_path):
        """Test timeline query."""
        from src.light_graph import LightGraph
        from src.notice_extractor import NoticeMetadata

        with patch('src.light_graph.GRAPH_FILE', tmp_path / "graph.json"):
            graph = LightGraph()

            # Add notices with different dates
            for i, date in enumerate(["2024-01-10", "2024-01-15", "2024-01-20"]):
                notice = NoticeMetadata(
                    doc_id=f"doc_{i}",
                    file_path=f"/path/to/doc{i}.pdf",
                    file_name=f"doc{i}.pdf",
                    date=date,
                    sender="ABC Corp",
                    key_topics=["test"],
                    ref_numbers=[f"REF-{i}"],
                )
                graph.add_notice(notice)

            results = graph.timeline()

            assert len(results) == 3
            # Should be sorted by date
            dates = [r['date'] for r in results]
            assert dates == sorted(dates)

    def test_timeline_query_with_filter(self, tmp_path):
        """Test timeline query with date filter."""
        from src.light_graph import LightGraph
        from src.notice_extractor import NoticeMetadata

        with patch('src.light_graph.GRAPH_FILE', tmp_path / "graph.json"):
            graph = LightGraph()

            for i, date in enumerate(["2024-01-10", "2024-01-15", "2024-01-20"]):
                notice = NoticeMetadata(
                    doc_id=f"doc_{i}",
                    file_path=f"/path/to/doc{i}.pdf",
                    file_name=f"doc{i}.pdf",
                    date=date,
                    key_topics=["test"],
                    ref_numbers=[f"REF-{i}"],
                )
                graph.add_notice(notice)

            # Filter by date range
            results = graph.timeline(start_date="2024-01-12", end_date="2024-01-18")

            assert len(results) == 1
            assert results[0]['date'] == "2024-01-15"

    def test_trace_chain(self, tmp_path):
        """Test chain tracing."""
        from src.light_graph import LightGraph
        from src.notice_extractor import NoticeMetadata

        with patch('src.light_graph.GRAPH_FILE', tmp_path / "graph.json"):
            graph = LightGraph()

            # Create a chain of related documents
            notice1 = NoticeMetadata(
                doc_id="doc_001",
                file_path="/path/to/doc1.pdf",
                file_name="doc1.pdf",
                date="2024-01-10",
                ref_numbers=["CHAIN-001"],
                key_topics=["initial"],
            )

            notice2 = NoticeMetadata(
                doc_id="doc_002",
                file_path="/path/to/doc2.pdf",
                file_name="doc2.pdf",
                date="2024-01-15",
                ref_numbers=["CHAIN-001"],  # Same ref
                key_topics=["response"],
            )

            graph.add_notice(notice1)
            graph.add_notice(notice2)
            graph.build_edges()

            chain = graph.trace_chain("doc_001", depth=3)

            assert chain['start'] is not None
            assert chain['start']['doc_id'] == "doc_001"

    def test_explain_link(self, tmp_path):
        """Test link explanation."""
        from src.light_graph import LightGraph
        from src.notice_extractor import NoticeMetadata

        with patch('src.light_graph.GRAPH_FILE', tmp_path / "graph.json"):
            graph = LightGraph()

            notice1 = NoticeMetadata(
                doc_id="doc_001",
                file_path="/path/to/doc1.pdf",
                file_name="doc1.pdf",
                ref_numbers=["SHARED-REF"],
                key_topics=["topic"],
            )

            notice2 = NoticeMetadata(
                doc_id="doc_002",
                file_path="/path/to/doc2.pdf",
                file_name="doc2.pdf",
                ref_numbers=["SHARED-REF"],
                key_topics=["topic"],
            )

            graph.add_notice(notice1)
            graph.add_notice(notice2)
            graph.build_edges()

            explanation = graph.explain_link("doc_001", "doc_002")

            assert len(explanation) >= 1
            # Should explain the reference relationship
            assert any('SHARED-REF' in str(e.get('why', '')) for e in explanation)


class TestRouterTimeline:
    """Tests for timeline query routing."""

    def test_timeline_keyword_detection(self):
        """Test timeline keyword detection."""
        from src.router import TIMELINE_KEYWORDS

        # Should match timeline queries
        timeline_queries = [
            "show me the timeline of events",
            "what is the chronology of notices",
            "who replied to this letter",
            "list all notices",
            "what happened between January and March",
        ]

        for query in timeline_queries:
            query_lower = query.lower()
            matches = sum(1 for kw in TIMELINE_KEYWORDS if kw in query_lower)
            assert matches >= 1, f"Query should match timeline keywords: {query}"

    def test_non_timeline_queries(self):
        """Test that regular queries don't match timeline."""
        from src.router import TIMELINE_KEYWORDS

        regular_queries = [
            "what are the payment terms",
            "calculate the total cost",
            "summarize the contract",
        ]

        for query in regular_queries:
            query_lower = query.lower()
            matches = sum(1 for kw in TIMELINE_KEYWORDS if kw in query_lower)
            assert matches < 2, f"Query should not match timeline: {query}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
