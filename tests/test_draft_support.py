"""Email reply-draft enrichment: intent detection + corpus-scoped supporting
facts injected into the draft context."""
from backend.services.chat_orchestrator import ChatOrchestrator


def _orch():
    return ChatOrchestrator.__new__(ChatOrchestrator)


def test_draft_intent_detection():
    o = _orch()
    assert o._is_draft_intent("draft a reply to the contractor")
    assert o._is_draft_intent("write a response regarding the EOT claim")
    assert o._is_draft_intent("reply to TIE about the cost overrun")
    assert not o._is_draft_intent("what is the total cost?")
    assert not o._is_draft_intent("summarize these emails")


def test_draft_support_builds_grounding_block(monkeypatch):
    """Supporting facts are corpus-scoped retrieve-only excerpts, deduped by
    (file, page), formatted as a citable grounding block."""
    o = _orch()

    class _RAG:
        def query(self, q, top_k=12, synthesize=True, project_id=""):
            assert synthesize is False  # retrieve-only (no synthesis LLM)
            assert project_id == "project-a"
            return {"sources": [
                {"file_name": "contract.pdf", "page_number": 80, "highlight_text": "clause 80 risk"},
                {"file_name": "contract.pdf", "page_number": 80, "highlight_text": "dup"},  # deduped
                {"file_name": "audit.pdf", "page_number": 3, "text_snippet": "cost overrun noted"},
            ]}

    import src.document_rag as dr
    monkeypatch.setattr(dr, "get_document_rag", lambda: _RAG())
    block = o._build_draft_support_context(
        "reply about the cost overrun", project_id="project-a",
    )
    assert "SUPPORTING FACTS" in block
    assert "contract.pdf p.80" in block and "audit.pdf p.3" in block
    assert block.count("- [") == 2  # the duplicate (contract.pdf p.80) collapsed


def test_draft_support_empty_when_no_sources(monkeypatch):
    o = _orch()

    class _RAG:
        def query(self, q, top_k=12, synthesize=True, project_id=""):
            return {"sources": []}

    import src.document_rag as dr
    monkeypatch.setattr(dr, "get_document_rag", lambda: _RAG())
    assert o._build_draft_support_context("reply", project_id="project-a") == ""


def test_draft_support_graceful_on_error(monkeypatch):
    o = _orch()
    import src.document_rag as dr

    def boom():
        raise RuntimeError("rag down")

    monkeypatch.setattr(dr, "get_document_rag", boom)
    assert o._build_draft_support_context(
        "reply", project_id="project-a",
    ) == ""  # never raises
