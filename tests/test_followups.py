"""Follow-up wiring (post Sprint A–D).

  * forensic scope → rerank hints (entities/date_range) reach retrieval;
  * rag.query threads rerank_hints down to the deterministic reranker;
  * the optional LLM decomposer is always re-validated (invented skills rejected).
"""

import pytest


class TestForensicHintConstruction:
    """delay_reports.retrieve_evidence must derive entity/date hints from scope
    and pass them to rag.query."""

    def test_scope_becomes_rerank_hints(self, monkeypatch):
        import src.delay_reports.retrieval as retr
        from src.delay_reports.schemas import ScopeResult

        captured = {}

        class _FakeRag:
            def query(self, q, **kw):
                captured.update(kw)
                return {"sources": []}

        monkeypatch.setattr("src.document_rag.get_document_rag",
                            lambda: _FakeRag())
        # demo path also hits light_graph; make it a no-op
        monkeypatch.setattr("src.light_graph.get_light_graph",
                            lambda: (_ for _ in ()).throw(RuntimeError("skip")),
                            raising=False)

        scope = ScopeResult(event_title="Crane breakdown",
                            topic_terms=["crane", "breakdown"],
                            date_from="2024-03-01", date_to="2024-03-31")
        retr.retrieve_evidence(scope, corpus="edinburgh", doc_ids=None)

        hints = captured.get("rerank_hints")
        assert hints is not None
        assert hints["entities"] == ["crane", "breakdown"]
        assert hints["date_range"] == ("2024-03-01", "2024-03-31")

    def test_no_dates_no_date_range(self, monkeypatch):
        import src.delay_reports.retrieval as retr
        from src.delay_reports.schemas import ScopeResult

        captured = {}

        class _FakeRag:
            def query(self, q, **kw):
                captured.update(kw)
                return {"sources": []}

        monkeypatch.setattr("src.document_rag.get_document_rag", lambda: _FakeRag())
        scope = ScopeResult(event_title="X", topic_terms=["x"])
        retr.retrieve_evidence(scope, corpus="edinburgh", doc_ids=None)
        hints = captured.get("rerank_hints") or {}
        assert "date_range" not in hints
        assert hints.get("entities") == ["x"]


class TestHintThreading:
    """_hybrid_query must pass the hints through to rerank_candidates."""

    def _bare_rag(self):
        from src.document_rag import DocumentRAG
        r = DocumentRAG.__new__(DocumentRAG)
        return r

    def test_hints_reach_reranker(self, monkeypatch):
        r = self._bare_rag()
        cands = [
            {"key": "a::1", "file_name": "a.pdf", "doc_id": "a",
             "page_number": 1, "text": "crane breakdown", "dense_score": 0.8},
            {"key": "b::1", "file_name": "b.pdf", "doc_id": "b",
             "page_number": 1, "text": "safety induction", "dense_score": 0.7},
        ]
        monkeypatch.setattr(r, "_dense_candidates",
                            lambda *a, **k: cands, raising=False)
        monkeypatch.setattr(r, "_node_to_source", lambda nd: nd, raising=False)
        monkeypatch.setattr(r, "_report_reading", lambda s: None, raising=False)
        # demo corpus → lexical lane skipped (fewer stubs), rerank still runs
        monkeypatch.setattr("src.document_rag._current_user_corpus",
                            lambda: "demo")

        seen = {}

        def _fake_rerank(query, candidates, **kw):
            seen.update(kw)
            return candidates

        monkeypatch.setattr("src.rag.rerank_candidates", _fake_rerank)
        # force rerank branch: ENABLE_RERANK off so only deterministic runs
        monkeypatch.setattr("src.config.ENABLE_RERANK", False, raising=False)

        r._hybrid_query(
            question="crane breakdown", raw_question="crane breakdown",
            top_k=2, synthesize=False,
            rerank_hints={"entities": ["crane"],
                          "date_range": ("2024-03-01", "2024-03-31"),
                          "doc_types": ["notice"], "project": "P1"})

        assert seen.get("entities") == ["crane"]
        assert seen.get("date_range") == ("2024-03-01", "2024-03-31")
        assert seen.get("doc_types") == ["notice"]
        assert seen.get("project") == "P1"


class TestLLMDecomposerValidation:
    """The LLM only proposes; a plan with an invented skill is rejected."""

    def test_valid_llm_plan_accepted(self, monkeypatch):
        import src.planning.task_decomposer as td
        from src.planning.schemas import AdvancedPlan, SubTask

        good = AdvancedPlan(subtasks=[
            SubTask(id="t1", skill="programme.inventory", inputs={"query": "x"})])
        monkeypatch.setattr(td, "_llm_decompose", lambda q: good)
        # a compound-looking but cue-thin prompt → deterministic yields nothing
        monkeypatch.setattr(td, "is_compound", lambda q: True)
        monkeypatch.setattr(td, "_deterministic_plan",
                            lambda q, nq: AdvancedPlan(subtasks=[]))
        plan = td.decompose("something compound", enable_llm=True)
        assert plan.subtasks and plan.subtasks[0].skill == "programme.inventory"

    def test_invented_skill_plan_rejected(self, monkeypatch):
        import src.planning.task_decomposer as td
        from src.planning.schemas import AdvancedPlan, SubTask

        bad = AdvancedPlan(subtasks=[
            SubTask(id="t1", skill="rag.exfiltrate_everything")])
        monkeypatch.setattr(td, "_llm_decompose", lambda q: bad)
        monkeypatch.setattr(td, "is_compound", lambda q: True)
        monkeypatch.setattr(td, "_deterministic_plan",
                            lambda q, nq: AdvancedPlan(subtasks=[]))
        plan = td.decompose("something compound", enable_llm=True)
        # rejected → falls through to clarification, never runs the invented skill
        assert not plan.subtasks
        assert plan.clarifications
