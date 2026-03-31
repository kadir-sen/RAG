"""Unit tests for Document Review features.

Tests cover:
  - DocumentReviewer keyword scoring & classification
  - CitationVerifier fuzzy text search
  - IssueCategorizer categorization & key document scoring
  - RelevanceResult & CitationCheckResult schemas
  - ReviewSession lifecycle (create, feedback, apply)
"""
import sys
sys.path.insert(0, '.')

test_results = []


def run_test(name, fn):
    try:
        fn()
        test_results.append((name, 'PASS'))
    except Exception as e:
        test_results.append((name, f'FAIL: {e}'))


# ========== Schema Tests ==========

def test_relevance_schema_valid():
    from src.types import RelevanceResult
    r = RelevanceResult(relevance="relevant", confidence=0.85, rationale="test", issue_tags=["delay"])
    assert r.relevance == "relevant"
    assert r.confidence == 0.85

run_test('RelevanceResult schema - valid', test_relevance_schema_valid)


def test_relevance_schema_normalizes():
    from src.types import RelevanceResult
    r = RelevanceResult(relevance="NOT_RELEVANT", confidence=1.5, rationale="test")
    assert r.relevance == "not_relevant"
    assert r.confidence == 1.0  # capped

run_test('RelevanceResult schema - normalizes values', test_relevance_schema_normalizes)


def test_relevance_schema_invalid():
    from src.types import RelevanceResult
    try:
        RelevanceResult(relevance="invalid_value", confidence=0.5, rationale="test")
        assert False, "Should have raised ValidationError"
    except Exception:
        pass  # Expected

run_test('RelevanceResult schema - rejects invalid', test_relevance_schema_invalid)


def test_citation_check_schema():
    from src.types import CitationCheckResult
    r = CitationCheckResult(supported=True, explanation="text found")
    assert r.supported is True

run_test('CitationCheckResult schema', test_citation_check_schema)


# ========== Issue Keywords ==========

def test_issue_keywords_coverage():
    from src.document_reviewer import ISSUE_KEYWORDS
    assert 'delay' in ISSUE_KEYWORDS
    assert 'payment_dispute' in ISSUE_KEYWORDS
    assert 'quality_concern' in ISSUE_KEYWORDS
    assert 'safety_issue' in ISSUE_KEYWORDS
    assert 'scope_change' in ISSUE_KEYWORDS
    assert 'communication_gap' in ISSUE_KEYWORDS
    assert 'contractual_dispute' in ISSUE_KEYWORDS
    assert len(ISSUE_KEYWORDS) == 7

run_test('Issue keywords - 7 categories defined', test_issue_keywords_coverage)


# ========== DocumentReviewer keyword scoring ==========

def test_reviewer_keyword_score_high():
    from src.document_reviewer import DocumentReviewer
    from src.notice_extractor import NoticeMetadata

    notice = NoticeMetadata(
        doc_id="test1",
        file_path="/tmp/test.pdf",
        file_name="test.pdf",
        subject="Extension of Time for Delay in Construction",
        actions=["delay", "extension of time"],
        key_topics=["delay claim", "schedule slippage"],
    )

    reviewer = DocumentReviewer()
    score, tags, evidence = reviewer._keyword_score(notice, "which documents relate to delay claims?")
    assert score > 0.5, f"Expected high score, got {score}"
    assert 'delay' in tags, f"Expected 'delay' in tags, got {tags}"

run_test('DocumentReviewer keyword score - high relevance', test_reviewer_keyword_score_high)


def test_reviewer_keyword_score_low():
    from src.document_reviewer import DocumentReviewer
    from src.notice_extractor import NoticeMetadata

    notice = NoticeMetadata(
        doc_id="test2",
        file_path="/tmp/test2.pdf",
        file_name="test2.pdf",
        subject="Meeting Minutes - Weekly Progress",
        actions=["discuss", "review"],
        key_topics=["progress meeting"],
    )

    reviewer = DocumentReviewer()
    score, tags, evidence = reviewer._keyword_score(notice, "which documents relate to safety incidents?")
    assert score < 0.3, f"Expected low score, got {score}"

run_test('DocumentReviewer keyword score - low relevance', test_reviewer_keyword_score_low)


def test_reviewer_classify_relevant():
    from src.document_reviewer import DocumentReviewer
    from src.notice_extractor import NoticeMetadata

    notice = NoticeMetadata(
        doc_id="test3",
        file_path="/tmp/test3.pdf",
        file_name="delay_notice.pdf",
        subject="Notice of Delay - Block A Construction",
        actions=["delay", "extension of time", "instruct"],
        key_topics=["delay", "critical path", "schedule"],
        deadlines=[{"date": "2024-06-30", "context": "completion deadline"}],
        evidence_spans=[{"page": 1, "snippet": "Extension of time claim", "field_name": "action", "confidence": 0.9}],
    )

    reviewer = DocumentReviewer()
    result = reviewer.classify_document(notice, "delay claims")
    assert result.relevance == "relevant", f"Expected relevant, got {result.relevance}"
    assert result.confidence > 0.5
    assert len(result.rationale) > 0

run_test('DocumentReviewer classify - relevant document', test_reviewer_classify_relevant)


def test_reviewer_classify_not_relevant():
    from src.document_reviewer import DocumentReviewer
    from src.notice_extractor import NoticeMetadata

    notice = NoticeMetadata(
        doc_id="test4",
        file_path="/tmp/test4.pdf",
        file_name="transmittal.pdf",
        subject="Transmittal of Drawings Batch 5",
        actions=["transmit"],
        key_topics=["drawings"],
    )

    reviewer = DocumentReviewer()
    result = reviewer.classify_document(notice, "safety incidents and hazard reports")
    assert result.relevance == "not_relevant", f"Expected not_relevant, got {result.relevance}"

run_test('DocumentReviewer classify - not relevant document', test_reviewer_classify_not_relevant)


def test_reviewer_to_dict():
    from src.document_reviewer import ReviewResult
    r = ReviewResult(
        doc_id="d1", file_name="test.pdf", relevance="relevant",
        confidence=0.9, rationale="test", citations=[], issue_tags=["delay"],
        review_question="q",
    )
    d = r.to_dict()
    assert d["doc_id"] == "d1"
    assert d["relevance"] == "relevant"
    assert isinstance(d, dict)

run_test('ReviewResult.to_dict()', test_reviewer_to_dict)


# ========== CitationVerifier ==========

def test_citation_fuzzy_search_exact():
    from src.document_reviewer import CitationVerifier
    verifier = CitationVerifier()
    found, score = verifier._fuzzy_text_search(
        "The contractor shall complete the works by June 2024",
        "Page content includes: The contractor shall complete the works by June 2024. Additional text follows."
    )
    assert found is True
    assert score >= 0.85

run_test('CitationVerifier fuzzy search - exact match', test_citation_fuzzy_search_exact)


def test_citation_fuzzy_search_no_match():
    from src.document_reviewer import CitationVerifier
    verifier = CitationVerifier()
    found, score = verifier._fuzzy_text_search(
        "The weather was sunny and pleasant today",
        "Payment shall be made within 30 days of invoice receipt."
    )
    assert found is False

run_test('CitationVerifier fuzzy search - no match', test_citation_fuzzy_search_no_match)


def test_citation_fuzzy_search_partial():
    from src.document_reviewer import CitationVerifier
    verifier = CitationVerifier()
    found, score = verifier._fuzzy_text_search(
        "Extension of time claim for Block A",
        "We hereby submit an extension of time claim for Block A construction per clause 8.4."
    )
    assert found is True
    assert score > 0.5

run_test('CitationVerifier fuzzy search - partial match', test_citation_fuzzy_search_partial)


def test_citation_fuzzy_empty():
    from src.document_reviewer import CitationVerifier
    verifier = CitationVerifier()
    found, score = verifier._fuzzy_text_search("", "Some page text")
    assert found is False
    assert score == 0.0

run_test('CitationVerifier fuzzy search - empty input', test_citation_fuzzy_empty)


# ========== IssueCategorizer ==========

def test_categorizer_delay():
    from src.document_reviewer import IssueCategorizer
    from src.notice_extractor import NoticeMetadata

    notice = NoticeMetadata(
        doc_id="cat1",
        file_path="/tmp/cat1.pdf",
        file_name="delay_notice.pdf",
        doc_type="notice",
        subject="Delay Notification",
        actions=["delay", "extension of time"],
        key_topics=["delay", "schedule"],
        deadlines=[{"date": "2024-12-31", "context": "completion"}],
    )

    cat = IssueCategorizer()
    result = cat.categorize_document(notice)
    assert "delay" in result.categories, f"Expected 'delay' in {result.categories}"
    assert result.primary_category == "delay"

run_test('IssueCategorizer - delay category', test_categorizer_delay)


def test_categorizer_multi_category():
    from src.document_reviewer import IssueCategorizer
    from src.notice_extractor import NoticeMetadata

    notice = NoticeMetadata(
        doc_id="cat2",
        file_path="/tmp/cat2.pdf",
        file_name="claim_letter.pdf",
        doc_type="letter",
        subject="Delay Claim and Payment Dispute",
        actions=["delay", "claim", "payment"],
        key_topics=["delay claim", "payment dispute", "without prejudice"],
    )

    cat = IssueCategorizer()
    result = cat.categorize_document(notice)
    assert len(result.categories) >= 2, f"Expected >= 2 categories, got {result.categories}"

run_test('IssueCategorizer - multi-category document', test_categorizer_multi_category)


def test_categorizer_key_document_score():
    from src.document_reviewer import IssueCategorizer
    from src.notice_extractor import NoticeMetadata

    # Formal notice with deadlines and multiple actions = high key doc score
    notice = NoticeMetadata(
        doc_id="key1",
        file_path="/tmp/key1.pdf",
        file_name="formal_notice.pdf",
        doc_type="notice",
        subject="Notice of Claim - USD 500,000 Delay Damages",
        actions=["delay", "claim", "payment", "instruct"],
        key_topics=["delay", "payment", "claim"],
        deadlines=[
            {"date": "2024-06-30", "context": "response deadline"},
            {"date": "2024-12-31", "context": "completion deadline"},
        ],
        referenced_docs=["ref_001", "ref_002"],
    )

    cat = IssueCategorizer()
    result = cat.categorize_document(notice)
    assert result.is_key_document is True, f"Expected key document, score={result.key_document_score}"
    assert result.key_document_score >= 0.6
    assert len(result.key_reasons) >= 2

run_test('IssueCategorizer - key document detection', test_categorizer_key_document_score)


def test_categorizer_low_key_score():
    from src.document_reviewer import IssueCategorizer
    from src.notice_extractor import NoticeMetadata

    # Transmittal with minimal metadata = low key doc score
    notice = NoticeMetadata(
        doc_id="low1",
        file_path="/tmp/low1.pdf",
        file_name="transmittal.pdf",
        doc_type="transmittal",
        subject="Drawing Transmittal",
        actions=["transmit"],
        key_topics=["drawings"],
    )

    cat = IssueCategorizer()
    result = cat.categorize_document(notice)
    assert result.key_document_score < 0.6, f"Expected low score, got {result.key_document_score}"

run_test('IssueCategorizer - low key document score', test_categorizer_low_key_score)


# ========== Config ==========

def test_review_config():
    from src.config import (
        ENABLE_REVIEW, REVIEW_HIGH_THRESHOLD, REVIEW_LOW_THRESHOLD,
        REVIEW_SESSIONS_DIR, REVIEW_ACCURACY_THRESHOLD, REVIEW_SAMPLE_SIZE,
    )
    assert isinstance(ENABLE_REVIEW, bool)
    assert 0 < REVIEW_LOW_THRESHOLD < REVIEW_HIGH_THRESHOLD < 1.0
    assert REVIEW_ACCURACY_THRESHOLD > 0
    assert REVIEW_SAMPLE_SIZE > 0
    assert REVIEW_SESSIONS_DIR.exists()

run_test('Review config values', test_review_config)


# ========== ReviewSession ==========

def test_review_session_create():
    from src.review_session import ReviewSession
    session = ReviewSession(
        session_id="test123",
        review_question="delay claims",
        status="develop",
        sample_size=5,
    )
    assert session.session_id == "test123"
    assert session.status == "develop"
    assert session.accuracy is None

run_test('ReviewSession dataclass creation', test_review_session_create)


def test_review_feedback():
    from src.review_session import ReviewFeedback
    fb = ReviewFeedback(
        doc_id="d1",
        predicted_relevance="relevant",
        human_label="relevant",
        is_correct=True,
    )
    assert fb.is_correct is True

    fb2 = ReviewFeedback(
        doc_id="d2",
        predicted_relevance="relevant",
        human_label="not_relevant",
        is_correct=False,
    )
    assert fb2.is_correct is False

run_test('ReviewFeedback dataclass', test_review_feedback)


def test_session_manager_lifecycle():
    """Test create -> feedback -> accuracy calculation."""
    import tempfile
    import os
    from pathlib import Path
    from src.review_session import ReviewSessionManager, ReviewSession

    # Use temp dir for session files
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = ReviewSessionManager()
        original_dir = mgr.sessions_dir
        mgr.sessions_dir = Path(tmpdir)

        # Create a session manually (without needing actual notices)
        session = ReviewSession(
            session_id="lifecycle_test",
            review_question="test question",
            status="develop",
            sample_size=3,
            sample_results=[
                {"doc_id": "a", "file_name": "a.pdf", "relevance": "relevant", "confidence": 0.9, "rationale": "test", "citations": [], "issue_tags": [], "review_question": "test"},
                {"doc_id": "b", "file_name": "b.pdf", "relevance": "not_relevant", "confidence": 0.8, "rationale": "test", "citations": [], "issue_tags": [], "review_question": "test"},
                {"doc_id": "c", "file_name": "c.pdf", "relevance": "borderline", "confidence": 0.5, "rationale": "test", "citations": [], "issue_tags": [], "review_question": "test"},
            ],
            total_documents=10,
        )
        mgr._save_session(session)

        # Load it back
        loaded = mgr.get_session("lifecycle_test")
        assert loaded is not None
        assert loaded.review_question == "test question"
        assert len(loaded.sample_results) == 3

        # Record feedback
        mgr.record_feedback("lifecycle_test", "a", "relevant")  # correct
        mgr.record_feedback("lifecycle_test", "b", "not_relevant")  # correct

        updated = mgr.get_session("lifecycle_test")
        assert updated.status == "validate"
        assert len(updated.feedback) == 2
        assert updated.accuracy == 1.0  # 2/2 correct

        # Record incorrect feedback
        mgr.record_feedback("lifecycle_test", "c", "relevant")  # predicted borderline, human says relevant

        updated2 = mgr.get_session("lifecycle_test")
        assert len(updated2.feedback) == 3
        # 2 correct (a, b) + 1 incorrect (c) = 2/3 = 0.666...
        assert 0.6 < updated2.accuracy < 0.7

        # List sessions
        sessions = mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "lifecycle_test"

        # Delete
        assert mgr.delete_session("lifecycle_test") is True
        assert mgr.get_session("lifecycle_test") is None

        # Restore
        mgr.sessions_dir = original_dir

run_test('ReviewSessionManager lifecycle', test_session_manager_lifecycle)


def test_can_apply_thresholds():
    """Test that apply requires sufficient feedback and accuracy."""
    import tempfile
    from pathlib import Path
    from src.review_session import ReviewSessionManager, ReviewSession

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = ReviewSessionManager()
        original_dir = mgr.sessions_dir
        mgr.sessions_dir = Path(tmpdir)

        session = ReviewSession(
            session_id="apply_test",
            review_question="test",
            status="validate",
            sample_size=4,
            sample_results=[
                {"doc_id": f"d{i}", "file_name": f"d{i}.pdf", "relevance": "relevant",
                 "confidence": 0.9, "rationale": "t", "citations": [], "issue_tags": [], "review_question": "t"}
                for i in range(4)
            ],
            total_documents=20,
        )
        mgr._save_session(session)

        # No feedback yet
        can, reason = mgr.can_apply("apply_test")
        assert can is False
        assert "No feedback" in reason

        # Add 1 feedback (< 50%)
        mgr.record_feedback("apply_test", "d0", "relevant")
        can, reason = mgr.can_apply("apply_test")
        assert can is False
        assert "50%" in reason

        # Add more feedback (>= 50% but accuracy 50%)
        mgr.record_feedback("apply_test", "d1", "not_relevant")  # incorrect
        can, reason = mgr.can_apply("apply_test")
        assert can is False
        assert "Accuracy" in reason or "below" in reason.lower()

        # Make all correct
        mgr.record_feedback("apply_test", "d1", "relevant")  # fix
        mgr.record_feedback("apply_test", "d2", "relevant")
        can, reason = mgr.can_apply("apply_test")
        assert can is True

        mgr.sessions_dir = original_dir

run_test('can_apply threshold checks', test_can_apply_thresholds)


# ========== RESULTS ==========

print(f"\n{'='*60}")
print(f"  Document Review Test Results")
print(f"{'='*60}")

passed = sum(1 for _, r in test_results if r == 'PASS')
failed = sum(1 for _, r in test_results if r != 'PASS')

for name, result in test_results:
    icon = 'PASS' if result == 'PASS' else 'FAIL'
    print(f"  [{icon}] {name}")
    if result != 'PASS':
        print(f"         {result}")

print(f"\n  Total: {len(test_results)} | Passed: {passed} | Failed: {failed}")
print(f"{'='*60}\n")

if failed > 0:
    sys.exit(1)
