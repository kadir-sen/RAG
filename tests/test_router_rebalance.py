"""Faz 2 — deterministik↔LLM yeniden dengeleme regresyon testleri.

Network/LLM gerektirmeyen saf birim testleri:
  * _signals_conflict — belirsiz (data+document) sorgular LLM'e devredilmeli,
    net sorgular deterministik kalmalı.
  * _is_greeting — yalnızca tam selam eşleşmesi (≤3 harf yakala-hepsini kaldırıldı).
  * response_builder citation koruması — çıplak refusal'da bastır, nüanslı uzun
    cevapta KORU (test raporunun övdüğü davranış).

`QueryRouter` örneklenmiyor (init ağır bağımlılıklar yüklüyor); metodlar hafif bir
stub `self` ile çağrılıyor.
"""

import pytest

from src.router import QueryRouter
from backend.services.response_builder import (
    _is_bare_refusal,
    build_chat_response,
)


# ── _signals_conflict (stub'lı) ────────────────────────────────────────────
class _StubRouter:
    """`_signals_conflict` ve `_is_greeting` için minimal self.

    `_schema_data_boost` 0 döndürür (yüklü tablo yok), böylece çelişki kararı
    yalnızca strong-data işareti + data-keyword sayısına dayanır — bu set için
    yeterli ve deterministik."""
    _has_document_intent = staticmethod(QueryRouter._has_document_intent)
    _signals_conflict = QueryRouter._signals_conflict
    _is_greeting = QueryRouter._is_greeting
    GREETING_PATTERNS = QueryRouter.GREETING_PATTERNS

    def _schema_data_boost(self, _q):
        return 0


def conflict(q: str) -> bool:
    return _StubRouter()._signals_conflict(q.lower())


class TestSignalsConflict:
    @pytest.mark.parametrize("q", [
        # data sinyali + açık doc-intent ifadesi ("show me the" / "what does ... show")
        # → belirsiz → LLM yolu
        "what is the total number of workers by trade? show me the breakdown as a table",
        "what does the manpower log show about trade distribution",
        "summarize the spreadsheet total manpower by trade",
    ])
    def test_ambiguous_data_plus_doc_phrasing_defers_to_llm(self, q):
        assert conflict(q) is True

    @pytest.mark.parametrize("q", [
        "what does clause 5 say about liquidated damages",
        "summarize the inspection letter",
        "explain the scope of work",
        "tell me about the project",
    ])
    def test_pure_document_queries_not_conflicting(self, q):
        assert conflict(q) is False

    @pytest.mark.parametrize("q", [
        # doc-intent yok → çelişki yok → deterministik hızlı yol (DATA).
        # Q4/Q10 ifadeleri de buraya girer: "give me"/"what is" doc-intent değil.
        "total crane hours across all blocks",
        "how many steel fixers on site",
        "equipment utilization by block",
        "from the spreadsheet data, give me the total manpower count grouped by trade",
        "using the manpower production log spreadsheets, total count of workers per trade",
    ])
    def test_pure_data_queries_not_conflicting(self, q):
        assert conflict(q) is False


# ── _is_greeting daraltma ──────────────────────────────────────────────────
class TestGreetingTightening:
    def greet(self, q):
        return _StubRouter()._is_greeting(q)

    @pytest.mark.parametrize("q", ["hi", "hello", "good morning", "thanks", "Merhaba!"])
    def test_real_greetings_match(self, q):
        assert self.greet(q) is True

    @pytest.mark.parametrize("q", ["the", "hmm", "boq", "rfi", "noc", "yes", "no", "ok"])
    def test_short_words_no_longer_misfire(self, q):
        # Eski "≤3 harf isalpha" yakala-hepsini bu gerçek sorguları selam sanıyordu.
        assert self.greet(q) is False


# ── Citation koruması (2.5) ────────────────────────────────────────────────
class TestCitationPreservation:
    def test_bare_refusal_is_flagged(self):
        assert _is_bare_refusal("The provided context does not contain that information.") is True
        assert _is_bare_refusal("") is True

    def test_nuanced_long_answer_not_bare_refusal(self):
        long_answer = (
            "No document directly states the exact figure, but the TABH Security "
            "Control Room inspection report (July 2016) and the follow-up emails "
            "discuss the air-conditioning and power issues in detail, indicating "
            "they remained unresolved as of November 2016 across both referenced "
            "sources. See the inspection report and correspondence for specifics."
        )
        assert _is_bare_refusal(long_answer) is False

    def test_nuanced_answer_keeps_citations(self):
        long_answer = (
            "No document directly states the exact total figure, however the TABH "
            "Security Control Room inspection report from July 2016 and the related "
            "follow-up correspondence both discuss the air-conditioning and power "
            "issues in detail. Read together, these sources indicate the problems "
            "remained unresolved as of November 2016, so review both for the full "
            "picture before drawing a conclusion on the matter."
        )
        resp = build_chat_response({
            "query_type": "document",
            "answer": long_answer,
            "sources": [{
                "doc_id": "doc-1", "file_name": "inspection_report.pdf",
                "page_number": 3, "text_snippet": "AC and power issues...",
            }],
        })
        assert len(resp.citations) == 1  # KORUNDU

    def test_bare_refusal_drops_citations(self):
        resp = build_chat_response({
            "query_type": "document",
            "answer": 'The provided context does not contain information related to "ZZZ".',
            "sources": [{
                "doc_id": "doc-1", "file_name": "unrelated.msg",
                "page_number": 1, "text_snippet": "noise",
            }],
        })
        assert resp.citations == []
