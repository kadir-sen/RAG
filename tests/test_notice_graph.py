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


class TestCompoundQueryHandling:
    """Tests for compound query intent parsing, domain concept expansion, and broad search."""

    def test_parse_compound_intent_delay_correspondence(self):
        """Verify 'delay events in correspondence' extracts both semantic and scope."""
        from src.router import QueryRouter

        router = QueryRouter.__new__(QueryRouter)  # skip __init__ for unit test
        result = router._parse_compound_intent("what are the delay events in the correspondence")
        assert result["semantic"] == "delay"
        assert result["scope"] == "correspondence"

    def test_parse_compound_intent_claims_letters(self):
        """Verify 'claims mentioned in the letters' extracts claim + correspondence."""
        from src.router import QueryRouter

        router = QueryRouter.__new__(QueryRouter)
        result = router._parse_compound_intent("what claims are mentioned in the letters")
        assert result["semantic"] == "claim"
        assert result["scope"] == "correspondence"

    def test_parse_compound_intent_approval_notices(self):
        """Verify 'approval related notices' extracts approval + notice."""
        from src.router import QueryRouter

        router = QueryRouter.__new__(QueryRouter)
        result = router._parse_compound_intent("show me approval related notices")
        assert result["semantic"] == "approval"
        assert result["scope"] == "notice"

    def test_parse_compound_intent_single_keyword_no_scope(self):
        """Single-keyword query without scope returns None for scope."""
        from src.router import QueryRouter

        router = QueryRouter.__new__(QueryRouter)
        result = router._parse_compound_intent("what are the delays")
        assert result["semantic"] == "delay"
        assert result["scope"] is None

    def test_parse_compound_intent_no_semantic(self):
        """Query with scope but no semantic returns None for semantic."""
        from src.router import QueryRouter

        router = QueryRouter.__new__(QueryRouter)
        result = router._parse_compound_intent("show all correspondence")
        assert result["semantic"] is None
        assert result["scope"] == "correspondence"

    def test_expand_domain_concepts_delay(self):
        """Verify domain concept expansion for delay-related query."""
        from src.jargon_manager import JargonManager

        jm = JargonManager()
        terms = jm.expand_domain_concepts("what are the delay events")
        assert "delay" in terms
        assert "NOD" in terms
        assert "extension of time" in terms
        assert "EOT" in terms
        assert "postponement" in terms

    def test_expand_domain_concepts_claim(self):
        """Verify domain concept expansion for claim-related query."""
        from src.jargon_manager import JargonManager

        jm = JargonManager()
        terms = jm.expand_domain_concepts("what claims exist")
        assert "claim" in terms
        assert "notice of claim" in terms
        assert "damages" in terms

    def test_expand_domain_concepts_no_match(self):
        """Query with no matching concepts returns empty list."""
        from src.jargon_manager import JargonManager

        jm = JargonManager()
        terms = jm.expand_domain_concepts("hello world")
        assert terms == []

    def test_get_concept_search_terms_combines_sources(self):
        """get_concept_search_terms combines domain concepts and abbreviation expansion."""
        from src.jargon_manager import JargonManager

        jm = JargonManager()
        terms = jm.get_concept_search_terms("what are the delay events in the EOT notice")
        # Should have domain concept terms for "delay"
        assert "NOD" in terms
        assert "postponement" in terms
        # Should also have abbreviation expansion for "EOT"
        assert any("extension of time" in t.lower() for t in terms)

    def test_search_broad_with_scope(self):
        """Test search_broad filters by scope (doc_type)."""
        from src.light_graph import LightGraph

        graph = LightGraph()
        # Add test notices
        graph.graph.nodes = {
            "doc1": {
                "doc_id": "doc1", "date": "2024-01-10", "sender": "A",
                "recipient": "B", "subject": "Notice of Delay for Block A",
                "doc_type": "notice", "direction": "outgoing",
                "file_name": "notice_001.pdf", "topics": "delay, block a",
                "actions": "delay", "ref_numbers": [], "cc_list": [],
            },
            "doc2": {
                "doc_id": "doc2", "date": "2024-01-15", "sender": "B",
                "recipient": "A", "subject": "Monthly Progress Report",
                "doc_type": "report", "direction": "incoming",
                "file_name": "report_001.pdf", "topics": "progress, delay",
                "actions": "progress", "ref_numbers": [], "cc_list": [],
            },
            "doc3": {
                "doc_id": "doc3", "date": "2024-01-20", "sender": "A",
                "recipient": "B", "subject": "Letter regarding delay compensation",
                "doc_type": "letter", "direction": "outgoing",
                "file_name": "letter_001.pdf", "topics": "delay, claim",
                "actions": "claim", "ref_numbers": [], "cc_list": [],
            },
        }
        graph._sync_notices_to_duckdb()

        # Search for delay in correspondence scope (letter, notice, email, transmittal)
        results = graph.search_broad(["delay"], scope="correspondence")

        doc_ids = [r["doc_id"] for r in results]
        assert "doc1" in doc_ids  # notice about delay
        assert "doc3" in doc_ids  # letter about delay
        assert "doc2" not in doc_ids  # report is not correspondence

    def test_search_broad_multi_field(self):
        """Test that search_broad finds terms in subject even if not in actions."""
        from src.light_graph import LightGraph

        graph = LightGraph()
        graph.graph.nodes = {
            "doc1": {
                "doc_id": "doc1", "date": "2024-02-01", "sender": "X",
                "recipient": "Y", "subject": "Extension of Time request",
                "doc_type": "letter", "direction": "outgoing",
                "file_name": "eot_letter.pdf", "topics": "",
                "actions": "request",  # NOT tagged as delay action
                "ref_numbers": [], "cc_list": [],
            },
        }
        graph._sync_notices_to_duckdb()

        results = graph.search_broad(["extension of time", "delay", "EOT"])

        assert len(results) >= 1
        assert results[0]["doc_id"] == "doc1"

    def test_search_broad_empty_terms(self):
        """Empty terms list returns empty results."""
        from src.light_graph import LightGraph

        graph = LightGraph()
        results = graph.search_broad([])
        assert results == []

    def test_build_compound_answer(self):
        """Test _build_compound_answer produces readable output."""
        from src.router import QueryRouter

        router = QueryRouter.__new__(QueryRouter)
        intent = {"semantic": "delay", "scope": "correspondence"}
        matched_docs = [
            {
                "doc_id": "d1", "date": "2024-01-10", "sender": "Contractor A",
                "recipient": "Owner B", "subject": "Notice of Delay",
                "doc_type": "notice", "file_name": "notice_001.pdf", "actions": "delay",
            },
        ]
        rag_result = {"answer": "The contractor notified delay due to weather conditions."}

        answer = router._build_compound_answer("delay events", intent, matched_docs, rag_result)

        assert "1 correspondence" in answer.lower() or "1" in answer
        assert "delay" in answer.lower()
        assert "notice_001.pdf" in answer
        assert "weather conditions" in answer


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
