"""
Tests for Phase 5: Table Normalization, OCR Notice Extraction, DuckDB Light Graph,
and Phase 2 Document Agent.

Run with: pytest tests/test_phase5.py -v
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Table Normalizer Tests ────────────────────────────────────────


class TestTableNormalizer:
    """Tests for src/table_normalizer.py"""

    def test_detect_total_rows_english(self):
        """Detects 'Total' and 'Year Total' rows."""
        from src.table_normalizer import detect_total_rows

        df = pd.DataFrame({
            "Month": ["January", "February", "Total", "March", "Year Total"],
            "Value": [10, 20, 30, 15, 45],
        })

        mask = detect_total_rows(df)
        assert mask.sum() == 2
        assert mask.iloc[2]  # "Total"
        assert mask.iloc[4]  # "Year Total"
        assert not mask.iloc[0]

    def test_parse_month_from_string_english(self):
        """Parses English month names."""
        from src.table_normalizer import _parse_month_from_string

        assert _parse_month_from_string("January") == 1
        assert _parse_month_from_string("feb") == 2
        assert _parse_month_from_string("December") == 12
        assert _parse_month_from_string("09") == 9
        assert _parse_month_from_string("2025-03") == 3

    def test_parse_year_from_string(self):
        """Extracts 4-digit years."""
        from src.table_normalizer import _parse_year_from_string

        assert _parse_year_from_string("2025") == 2025
        assert _parse_year_from_string("Year 2024 data") == 2024
        assert _parse_year_from_string("no year") is None
        assert _parse_year_from_string("1899") is None  # too old

    def test_normalize_table_manpower_like(self):
        """Full normalization on manpower-like data with totals."""
        from src.table_normalizer import normalize_table, get_clean_df

        df = pd.DataFrame({
            "Month": ["January", "February", "March", "Q1 Total",
                       "April", "May", "June", "Q2 Total", "Year Total"],
            "Workers": [100, 110, 105, 315, 120, 125, 130, 375, 690],
            "Year": [2024, 2024, 2024, 2024, 2024, 2024, 2024, 2024, 2024],
        })

        normalized, report = normalize_table(df, "manpower")

        assert report.table_name == "manpower"
        assert report.total_rows_detected == 3  # Q1, Q2, Year
        assert report.months_detected == 6  # Jan-Jun
        assert report.has_month_column  # "Month" col detected
        assert report.clean_row_count == 6  # 9 - 3 totals

        clean = get_clean_df(normalized)
        assert len(clean) == 6
        assert clean["Workers"].sum() == 690  # matches year total

    def test_normalize_table_no_totals(self):
        """Tables without totals return everything as clean."""
        from src.table_normalizer import normalize_table, get_clean_df

        df = pd.DataFrame({
            "Item": ["A", "B", "C"],
            "Count": [1, 2, 3],
        })

        normalized, report = normalize_table(df, "simple")

        assert report.total_rows_detected == 0
        assert report.clean_row_count == 3

        clean = get_clean_df(normalized)
        assert len(clean) == 3

    def test_date_key_generation(self):
        """date_key is correctly built as YYYY-MM."""
        from src.table_normalizer import normalize_table

        df = pd.DataFrame({
            "Period": ["January 2024", "February 2024", "March 2024"],
            "Value": [10, 20, 30],
        })

        normalized, report = normalize_table(df, "dated")

        assert report.months_detected >= 3
        assert report.years_detected >= 3

        keys = normalized["date_key"].dropna().tolist()
        assert "2024-01" in keys
        assert "2024-02" in keys

    def test_find_month_column_by_name(self):
        """Finds month column by keyword in column name."""
        from src.table_normalizer import _find_month_column

        df = pd.DataFrame({
            "Month Name": ["Jan", "Feb"],
            "Value": [1, 2],
        })

        assert _find_month_column(df) == "Month Name"

    def test_find_month_column_by_content(self):
        """Finds month column by sampling content values."""
        from src.table_normalizer import _find_month_column

        df = pd.DataFrame({
            "Period": ["January", "February", "March", "April"],
            "Amount": [10, 20, 30, 40],
        })

        result = _find_month_column(df)
        assert result == "Period"


# ── Notice Extractor OCR + Fuzzy Tests ─────────────────────────────


class TestOCRCleanup:
    """Tests for OCR post-processing."""

    def test_dehyphenation(self):
        """Joins hyphen-split words across lines."""
        from src.notice_extractor import ocr_cleanup

        text = "The con-\ntractor submitted"
        cleaned = ocr_cleanup(text)
        assert "contractor" in cleaned

    def test_whitespace_normalization(self):
        """Collapses multiple spaces and normalizes line endings."""
        from src.notice_extractor import ocr_cleanup

        text = "Hello   world\r\n\r\nNext    paragraph\r\n"
        cleaned = ocr_cleanup(text)
        assert "  " not in cleaned
        assert "\r" not in cleaned

    def test_excessive_blank_lines(self):
        """Reduces more than 2 blank lines to 2."""
        from src.notice_extractor import ocr_cleanup

        text = "Line 1\n\n\n\n\nLine 2"
        cleaned = ocr_cleanup(text)
        assert "\n\n\n" not in cleaned
        assert "Line 1" in cleaned
        assert "Line 2" in cleaned


class TestFuzzyLabelMatching:
    """Tests for fuzzy header label matching."""

    def test_exact_match(self):
        """Exact labels match their canonical names."""
        from src.notice_extractor import _fuzzy_match_label

        assert _fuzzy_match_label("date") == "date"
        assert _fuzzy_match_label("from") == "from"
        assert _fuzzy_match_label("subject") == "subject"
        assert _fuzzy_match_label("cc") == "cc"

    def test_ocr_typo_match(self):
        """OCR-typo labels match via fuzzy."""
        from src.notice_extractor import _fuzzy_match_label

        assert _fuzzy_match_label("dae") == "date"
        assert _fuzzy_match_label("frorn") == "from"
        assert _fuzzy_match_label("subjeet") == "subject"

    def test_no_match_for_garbage(self):
        """Garbage strings return None."""
        from src.notice_extractor import _fuzzy_match_label

        assert _fuzzy_match_label("xyz123") is None
        assert _fuzzy_match_label("") is None
        assert _fuzzy_match_label("x") is None

    def test_fuzzy_label_fallback_in_extraction(self):
        """Fuzzy fallback fills fields that regex missed."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {
            1: """
            Dae: 15/01/2024
            Frorn: ABC Construction
            Subjeet: Notice of Delay

            Dear Sir, we notify you of a delay.
            Sincerely,
            """,
        }

        notice = extractor.extract_notice(
            doc_id="ocr_test",
            file_path="test.pdf",
            doc_text_by_page=doc_text,
        )

        assert notice.date is not None
        assert "2024" in notice.date
        assert notice.sender is not None
        assert notice.subject is not None


# ── Phase 2: Enhanced Notice Extraction Tests ────────────────────


class TestDateExtraction:
    """Tests for improved date extraction patterns."""

    def test_2digit_year_format(self):
        """DD.MM.YY format common in TABH documents."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Date: 15.01.24\nFrom: TCI Engineering\nSubject: Test"}
        notice = extractor.extract_notice("dt1", "test.pdf", doc_text)
        assert notice.date == "2024-01-15"

    def test_written_date_format(self):
        """Written English date: 15th January 2024."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Date: 15th January 2024\nFrom: TCI\nSubject: Test"}
        notice = extractor.extract_notice("dt2", "test.pdf", doc_text)
        assert notice.date == "2024-01-15"

    def test_short_month_date(self):
        """Short month format: 15-Jan-2024."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Date: 15-Jan-2024\nFrom: TCI\nSubject: Test"}
        notice = extractor.extract_notice("dt3", "test.pdf", doc_text)
        assert notice.date == "2024-01-15"

    def test_date_label_priority(self):
        """Date near 'Date:' label takes priority over random dates in text."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Invoice #12345 dated 01.01.2020\nDate: 15.06.2024\nFrom: TCI\nSubject: Test"}
        notice = extractor.extract_notice("dt4", "test.pdf", doc_text)
        assert notice.date == "2024-06-15"


class TestSignatureExtraction:
    """Tests for signature block sender extraction."""

    def test_kind_regards_signature(self):
        """Extracts sender from Kind Regards signature block."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: """Subject: Test Letter

        Dear Mr. Smith,

        We hereby notify you of the delay.

        Kind Regards,

        John Anderson
        Project Manager
        TCI Engineering LLC
        """}

        notice = extractor.extract_notice("sig1", "test.pdf", doc_text)
        assert notice.sender is not None
        assert "John" in notice.sender or "Anderson" in notice.sender

    def test_best_regards_signature(self):
        """Extracts sender from Best Regards block."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: """Subject: Progress Report

        Please find attached the weekly progress report.

        Best Regards,

        Ahmed Hassan
        Senior Site Engineer
        """}

        notice = extractor.extract_notice("sig2", "test.pdf", doc_text)
        assert notice.sender is not None
        assert "Ahmed" in notice.sender or "Hassan" in notice.sender


class TestRecipientExtraction:
    """Tests for improved recipient extraction."""

    def test_dear_mr_pattern(self):
        """Extracts recipient from 'Dear Mr. X' salutation."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: """Date: 15.01.2024
        Subject: Delay Notice

        Dear Mr. Smith,

        We wish to notify you...

        Regards,
        John Anderson
        """}

        notice = extractor.extract_notice("rec1", "test.pdf", doc_text)
        assert notice.recipient is not None
        assert "Smith" in notice.recipient

    def test_attention_pattern(self):
        """Extracts recipient from Attention: field."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Date: 01.02.2024\nAttention: Mr. Robert Johnson\nSubject: Test\nDear Sir,\nContent here."}
        notice = extractor.extract_notice("rec2", "test.pdf", doc_text)
        assert notice.recipient is not None
        assert "Robert" in notice.recipient or "Johnson" in notice.recipient


class TestReferenceExtraction:
    """Tests for TABH reference number patterns."""

    def test_tabh_reference_format(self):
        """Extracts TABH-LTR-TCI-BMM-0001 format references."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Ref: TABH-LTR-TCI-BMM-0045\nDate: 15.01.2024\nSubject: Test"}
        notice = extractor.extract_notice("ref1", "test.pdf", doc_text)
        assert any("TABH-LTR-TCI-BMM-0045" in r for r in notice.ref_numbers)

    def test_mvp_reference_format(self):
        """Extracts MVP/BM/DD.MM.YY format."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Our Ref: MVP/BM/15.01.24\nDate: 15.01.2024\nSubject: Test"}
        notice = extractor.extract_notice("ref2", "test.pdf", doc_text)
        assert len(notice.ref_numbers) > 0

    def test_bmdxb_reference_format(self):
        """Extracts BMDXB-SUBCONLET-XXXXXX format."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Ref: BMDXB-SUBCONLET-123456\nDate: 01.02.2024\nSubject: Test"}
        notice = extractor.extract_notice("ref3", "test.pdf", doc_text)
        assert any("BMDXB" in r for r in notice.ref_numbers)


class TestProjectNameExtraction:
    """Tests for project name detection."""

    def test_tabh_project_detection(self):
        """Detects TABH project name in text."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: """Date: 01.01.2024
        Subject: The Address Boulevard Hotel - Delay Notice

        Dear Sir,
        We refer to the above project...
        """}

        notice = extractor.extract_notice("pn1", "test.pdf", doc_text)
        assert notice.project_name is not None
        assert "Address" in notice.project_name or "TABH" in notice.project_name


class TestExpandedActions:
    """Tests for expanded action keyword detection."""

    def test_construction_specific_actions(self):
        """Detects construction-specific actions."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: """Subject: Handover Notice
        We confirm the handover of the completed works.
        An inspection was conducted on site.
        The interim payment certificate is attached.
        A variation order has been issued.
        """}

        notice = extractor.extract_notice("act1", "test.pdf", doc_text)
        assert 'handover' in notice.actions
        assert 'inspect' in notice.actions
        assert 'payment' in notice.actions
        assert 'variation' in notice.actions


class TestDocTypeDetection:
    """Tests for document type detection."""

    def test_letter_detection(self):
        """Detects letters from salutation/closing."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Dear Mr. Smith,\nContent here.\nKind Regards,\nJohn"}
        notice = extractor.extract_notice("doc1", "test.pdf", doc_text)
        assert notice.doc_type == "letter"

    def test_dpr_detection(self):
        """Detects DPR documents."""
        from src.notice_extractor import NoticeExtractor

        extractor = NoticeExtractor()

        doc_text = {1: "Daily Progress Report\nManpower: 45\nWeather condition: Clear\nEquipment on site: Crane, Excavator"}
        notice = extractor.extract_notice("doc2", "test.pdf", doc_text)
        assert notice.doc_type == "dpr"


# ── Document Agent Tests ──────────────────────────────────────────


class TestEntityExtraction:
    """Tests for entity extraction."""

    def test_person_extraction(self):
        """Extracts person names from text."""
        from src.document_agent import EntityExtractor

        extractor = EntityExtractor()
        text = "Dear Mr. John Smith,\nWe are writing regarding the contract."
        entities = extractor.extract_entities(text, "test_doc")
        persons = [e for e in entities if e.entity_type == "person"]
        assert len(persons) >= 1
        assert any("Smith" in p.value for p in persons)

    def test_amount_extraction(self):
        """Extracts monetary amounts."""
        from src.document_agent import EntityExtractor

        extractor = EntityExtractor()
        text = "The total amount is AED 1,500,000.00 for the project."
        entities = extractor.extract_entities(text, "test_doc")
        amounts = [e for e in entities if e.entity_type == "amount"]
        assert len(amounts) >= 1
        assert any("1,500,000" in a.value for a in amounts)

    def test_duration_extraction(self):
        """Extracts duration mentions."""
        from src.document_agent import EntityExtractor

        extractor = EntityExtractor()
        text = "The delay is estimated at 45 calendar days."
        entities = extractor.extract_entities(text, "test_doc")
        durations = [e for e in entities if e.entity_type == "duration"]
        assert len(durations) >= 1
        assert any("45" in d.value for d in durations)


class TestClaimExtraction:
    """Tests for claim extraction."""

    def test_delay_claim(self):
        """Extracts delay claims."""
        from src.document_agent import ClaimExtractor

        extractor = ClaimExtractor()
        text = "We hereby notify you of a delay in the completion of the MEP works due to late material delivery."
        claims = extractor.extract_claims(text, "test_doc")
        delay_claims = [c for c in claims if c.claim_type == "delay"]
        assert len(delay_claims) >= 1

    def test_responsibility_claim(self):
        """Extracts responsibility/liability claims."""
        from src.document_agent import ClaimExtractor

        extractor = ClaimExtractor()
        text = "Without prejudice to our rights under the contract, we formally notify you of the above matter."
        claims = extractor.extract_claims(text, "test_doc")
        resp_claims = [c for c in claims if c.claim_type == "responsibility"]
        assert len(resp_claims) >= 1


class TestRelationshipExtraction:
    """Tests for document relationship extraction."""

    def test_shared_reference_relationship(self):
        """Documents with shared references are linked."""
        from src.document_agent import RelationshipExtractor

        extractor = RelationshipExtractor()
        notices = [
            {'doc_id': 'a', 'ref_numbers': ['REF-001'], 'sender': '', 'recipient': '',
             'subject': '', 'referenced_docs': [], 'file_name': 'a.pdf'},
            {'doc_id': 'b', 'ref_numbers': ['REF-001'], 'sender': '', 'recipient': '',
             'subject': '', 'referenced_docs': [], 'file_name': 'b.pdf'},
        ]
        rels = extractor.extract_relationships(notices)
        assert len(rels) >= 1
        assert rels[0].relationship_type == 'references'

    def test_reply_relationship(self):
        """Reply pattern (A->B then B->A) detected."""
        from src.document_agent import RelationshipExtractor

        extractor = RelationshipExtractor()
        notices = [
            {'doc_id': 'a', 'ref_numbers': [], 'sender': 'Alice Corp', 'recipient': 'Bob Ltd',
             'subject': 'Delay notice', 'date': '2024-01-01', 'referenced_docs': [], 'file_name': 'a.pdf'},
            {'doc_id': 'b', 'ref_numbers': [], 'sender': 'Bob Ltd', 'recipient': 'Alice Corp',
             'subject': 'Response to delay', 'date': '2024-01-15', 'referenced_docs': [], 'file_name': 'b.pdf'},
        ]
        rels = extractor.extract_relationships(notices)
        reply_rels = [r for r in rels if r.relationship_type == 'reply_to']
        assert len(reply_rels) >= 1


class TestProjectAnalyzer:
    """Tests for project-level analysis."""

    def test_party_map_building(self):
        """Builds correct party map from notices."""
        from src.document_agent import ProjectAnalyzer

        analyzer = ProjectAnalyzer()
        notices = [
            {'sender': 'TCI Engineering', 'recipient': 'BMM', 'date': '2024-01-01',
             'doc_id': 'a', 'actions': [], 'subject': '', 'project_name': 'TABH'},
            {'sender': 'TCI Engineering', 'recipient': 'DPS', 'date': '2024-01-15',
             'doc_id': 'b', 'actions': [], 'subject': '', 'project_name': 'TABH'},
            {'sender': 'BMM', 'recipient': 'TCI Engineering', 'date': '2024-01-20',
             'doc_id': 'c', 'actions': [], 'subject': '', 'project_name': 'TABH'},
        ]
        parties = analyzer._build_party_map(notices)
        assert 'TCI Engineering' in parties
        assert parties['TCI Engineering']['sent'] == 2

    def test_key_issue_detection(self):
        """Detects key issues from document actions."""
        from src.document_agent import ProjectAnalyzer

        analyzer = ProjectAnalyzer()
        notices = [
            {'actions': ['delay', 'claim'], 'subject': 'Delay notice', 'doc_id': 'a'},
            {'actions': ['delay'], 'subject': 'Extension request', 'doc_id': 'b'},
            {'actions': ['payment'], 'subject': 'Invoice #5', 'doc_id': 'c'},
        ]
        issues = analyzer._detect_key_issues(notices)
        assert 'delay' in issues or 'contractual_dispute' in issues


# ── Jargon Manager New Terms Tests ────────────────────────────────


class TestNewJargonTerms:
    """Tests for newly added construction domain terms."""

    def test_tabh_project_terms(self):
        """TABH project-specific terms are available."""
        from src.jargon_manager import JargonManager

        jm = JargonManager()
        assert jm.expand('TABH') == 'The Address Boulevard Hotel'
        assert jm.expand('DPR') == 'Daily Progress Report'
        assert jm.expand('NOC') == 'No Objection Certificate'
        assert jm.expand('CCTV') == 'Closed Circuit Television'
        assert jm.expand('DEWA') == 'Dubai Electricity and Water Authority'
        assert jm.expand('UAE') == 'United Arab Emirates'

    def test_construction_terms(self):
        """Construction-specific terms exist."""
        from src.jargon_manager import JargonManager

        jm = JargonManager()
        assert jm.expand('T&C') == 'Terms and Conditions'
        assert jm.expand('QHSE') == 'Quality Health Safety and Environment'
        assert jm.expand('NCN') == 'Non-Conformance Notice'
        assert jm.expand('LTR') == 'Letter'


# ── Light Graph DuckDB Tests ──────────────────────────────────────


class TestLightGraphDuckDB:
    """Tests for DuckDB-backed correspondence table in LightGraph."""

    def _make_graph(self, tmp_path):
        """Helper to create a graph with test notices."""
        from src.light_graph import LightGraph
        from src.notice_extractor import NoticeMetadata

        with patch('src.light_graph.GRAPH_FILE', tmp_path / "graph.json"):
            graph = LightGraph()

            notices = [
                NoticeMetadata(
                    doc_id="doc_001", file_path="doc1.pdf", file_name="doc1.pdf",
                    date="2024-01-10", sender="ABC Corp", recipient="XYZ Ltd",
                    subject="Notice of Delay", doc_type="notice",
                    ref_numbers=["REF-001"], key_topics=["delay"],
                ),
                NoticeMetadata(
                    doc_id="doc_002", file_path="doc2.pdf", file_name="doc2.pdf",
                    date="2024-01-20", sender="XYZ Ltd", recipient="ABC Corp",
                    subject="Response to Delay Notice", doc_type="letter",
                    ref_numbers=["REF-001"], key_topics=["delay", "response"],
                ),
                NoticeMetadata(
                    doc_id="doc_003", file_path="doc3.pdf", file_name="doc3.pdf",
                    date="2024-02-05", sender="ABC Corp", recipient="DEF Inc",
                    subject="Payment Claim", doc_type="notice",
                    ref_numbers=["REF-002"], key_topics=["payment", "claim"],
                ),
            ]

            for n in notices:
                graph.add_notice(n)
            graph.build_edges()

            return graph

    def test_notices_table_created(self, tmp_path):
        """DuckDB notices table is created and populated."""
        graph = self._make_graph(tmp_path)

        result = graph._db.execute("SELECT COUNT(*) FROM notices").fetchone()
        assert result[0] == 3

    def test_sql_query_letters_from(self, tmp_path):
        """SQL shortcut: 'letters from ABC Corp'."""
        graph = self._make_graph(tmp_path)

        result = graph._try_timeline_sql("letters from abc corp")
        assert result is not None
        assert "2" in result["answer"]
        assert result["method"] == "sql_direct"

    def test_sql_query_how_many_notices(self, tmp_path):
        """SQL shortcut: 'how many notices'."""
        graph = self._make_graph(tmp_path)

        result = graph._try_timeline_sql("how many notices are there?")
        assert result is not None
        assert "3" in result["answer"]

    def test_sql_query_latest_notice(self, tmp_path):
        """SQL shortcut: 'latest notice'."""
        graph = self._make_graph(tmp_path)

        result = graph._try_timeline_sql("show me the latest notice")
        assert result is not None
        assert "2024-02-05" in result["answer"]

    def test_sql_no_match_falls_through(self, tmp_path):
        """Non-matching queries return None."""
        graph = self._make_graph(tmp_path)

        result = graph._try_timeline_sql("what is the meaning of life?")
        assert result is None

    def test_smart_timeline_uses_sql_first(self, tmp_path):
        """smart_timeline_answer tries SQL before LLM."""
        graph = self._make_graph(tmp_path)

        result = graph.smart_timeline_answer("how many documents are there?")
        assert result is not None
        assert "3" in result["answer"]
        assert result.get("method") == "sql_direct"

    def test_correspondence_between(self, tmp_path):
        """correspondence_between returns correct docs."""
        graph = self._make_graph(tmp_path)

        results = graph.correspondence_between("ABC", "XYZ")
        assert len(results) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
