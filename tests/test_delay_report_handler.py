"""Handler orchestration with mocked LLM/retrieval + response mapping."""

from unittest.mock import patch

import pytest

from src.delay_reports import handler as h
from src.delay_reports.schemas import EvidenceItem, RegisterEntry, RegisterResult
from backend.services.response_builder import build_chat_response

SNIPPET_1 = ("On 19 July 2023, JAMED raised concerns about delayed access to "
             "several buildings, including CC2 and CM1.")
SNIPPET_2 = ("On 20 July 2023, JAMED forwarded an email from BBI-AGC JV, who "
             "provided updated access dates for some buildings.")


def _evidence():
    return [
        EvidenceItem("E1", "L1.pdf", "L1.pdf", 3, SNIPPET_1),
        EvidenceItem("E2", "L2.pdf", "L2.pdf", 1, SNIPPET_2),
    ]


def _register():
    return RegisterResult(entries=[
        RegisterEntry("E1", "2023-07-19", None, "JAMED", "BBI-AGC JV", "raised",
                      "delayed access to buildings", None, None, False,
                      "raised concerns about delayed access", "verified",
                      "L1.pdf", "L1.pdf", 3),
        RegisterEntry("E2", "2023-07-20", None, "JAMED", "BBI-AGC JV", "forwarded",
                      "updated access dates", None, None, False,
                      "forwarded an email", "verified", "L2.pdf", "L2.pdf", 1),
    ])


class TestHandler:
    def test_clarification_when_no_event_named(self):
        out = h.run_event_chronology("Find main delay events and prepare chronology")
        assert out["clarification"] is True
        assert "name the delay event" in out["answer"]
        assert out["query_type"] == "delay_report"

    def test_clarification_when_no_evidence(self):
        with patch.object(h, "retrieve_evidence", return_value=[]):
            out = h.run_event_chronology(
                "Prepare detailed chronology for Delayed Blockwork")
        assert out["clarification"] is True
        assert "Delayed Blockwork" in out["answer"]

    def test_failed_result_when_nothing_validates(self):
        empty = RegisterResult(unresolved=[{"evidence_id": "E1",
                                            "file_name": "L1.pdf",
                                            "reason": "date not found"}],
                               caveats=["1 item excluded"])
        with patch.object(h, "retrieve_evidence", return_value=_evidence()), \
             patch.object(h, "build_event_register", return_value=empty):
            out = h.run_event_chronology(
                "Prepare detailed chronology for Delayed Blockwork")
        art = out["programme_artifact"]
        assert art["status"] == "failed"
        assert art["requires_analyst_review"] is True
        assert "passed evidence validation" in art["summary"]

    def test_llm_outage_reported_as_unavailable_not_validation_failure(self):
        outage = RegisterResult(llm_failures=2,
                                caveats=["One evidence batch could not be "
                                         "processed for extraction."])
        with patch.object(h, "retrieve_evidence", return_value=_evidence()), \
             patch.object(h, "build_event_register", return_value=outage):
            out = h.run_event_chronology(
                "Prepare detailed chronology for Delayed Blockwork")
        art = out["programme_artifact"]
        assert art["status"] == "failed"
        assert "temporarily unavailable" in art["summary"]
        assert "validation" not in art["summary"]

    def test_happy_path_with_fallback_narrative(self, tmp_path, monkeypatch):
        # LLM narrative unavailable → deterministic fallback still ships,
        # audit trail records llm_unavailable, events.db gets rows.
        import src.event_timeline as et
        monkeypatch.setattr(et, "EVENTS_DIR", tmp_path, raising=False)
        monkeypatch.setattr(et, "EVENTS_DB", tmp_path / "events.db", raising=False)
        et.EventTimeline._instance = None
        et._instance = None

        with patch.object(h, "retrieve_evidence", return_value=_evidence()), \
             patch.object(h, "build_event_register", return_value=_register()), \
             patch.object(h, "draft_event_narrative",
                          side_effect=RuntimeError("429")):
            out = h.run_event_chronology(
                "Prepare detailed chronology for Delayed Access")

        art = out["programme_artifact"]
        assert art["status"] == "complete"
        assert art["validation"]["narrative_guard"]["status"] == "llm_unavailable"
        assert "6.1.1 On 19 July 2023, JAMED" in out["answer"]
        assert "(L1.pdf, p.3)" in out["answer"]
        # chronology table present
        assert art["tables"][0]["columns"][0] == "¶"
        assert len(art["tables"][0]["rows"]) == 2
        # clickable sources — untyped so the response builder maps them to
        # Citations (page-anchored, matching the "(file, p.N)" paragraph refs)
        assert "type" not in out["sources"][0]
        assert out["sources"][0]["page_number"] == 3
        from backend.services.response_builder import build_chat_response
        resp = build_chat_response(out)
        assert len(resp.citations) == 2
        assert resp.citations[0].anchor == "page_3"
        # events.db write-back
        try:
            rows = et.get_event_timeline().timeline(event_type="delay")
            assert len(rows) == 2
        finally:
            et.EventTimeline._instance = None
            et._instance = None

    def test_guarded_narrative_approved(self):
        good = ("6.1.1 On 19 July 2023, JAMED raised concerns regarding "
                "delayed access to buildings. (L1.pdf, p.3)\n\n"
                "6.1.2 On 20 July 2023, JAMED forwarded updated access dates. "
                "(L2.pdf, p.1)")
        with patch.object(h, "retrieve_evidence", return_value=_evidence()), \
             patch.object(h, "build_event_register", return_value=_register()), \
             patch.object(h, "draft_event_narrative", return_value=good), \
             patch("src.delay_reports.guard.check_grounding_llm",
                   return_value=[]):
            out = h.run_event_chronology(
                "Prepare detailed chronology for Delayed Access")
        art = out["programme_artifact"]
        assert art["validation"]["narrative_guard"]["status"] == "approved"
        assert out["answer"] == good

    def test_write_back_failure_non_fatal(self):
        with patch.object(h, "retrieve_evidence", return_value=_evidence()), \
             patch.object(h, "build_event_register", return_value=_register()), \
             patch.object(h, "draft_event_narrative",
                          side_effect=RuntimeError("429")), \
             patch("src.event_timeline.get_event_timeline",
                   side_effect=RuntimeError("db locked")):
            out = h.run_event_chronology(
                "Prepare detailed chronology for Delayed Access")
        assert out["programme_artifact"]["status"] == "complete"


class TestResponseMapping:
    def test_intent_and_artifact_passthrough(self):
        raw = {"query_type": "delay_report", "answer": "6.1.1 On ...",
               "sources": [],
               "programme_artifact": {"tool_id": "delay_reports.event_chronology",
                                      "status": "complete", "tables": []}}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "programme_result"
        assert resp.programme_artifact["tool_id"] == "delay_reports.event_chronology"

    def test_clarification_renders_as_answer(self):
        raw = {"query_type": "delay_report", "clarification": True,
               "answer": "Please name the delay event.", "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "answer"
        assert resp.programme_artifact is None
