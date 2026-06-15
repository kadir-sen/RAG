"""Routing regresyon testleri (LLM-öncelikli mimari).

Network/LLM gerektirmeyen saf birim testleri:
  * _has_strong_data_signal — artık FRONT-LINE override değil; yalnızca
    yürütme-sonrası fallback recovery'de kullanılan saf yardımcı. Açık veri
    kaynağı + agregasyon birlikteyse True, saf doküman/zayıf sorgularda False.
  * _is_greeting — yalnızca tam selam eşleşmesi (≤3 harf yakala-hepsini kaldırıldı).
  * response_builder citation koruması — çıplak refusal'da bastır, nüanslı uzun
    cevapta KORU (test raporunun övdüğü davranış).

NOT: Eski `_signals_conflict` ambiguity-gate'i LLM-öncelikli refactor'da kaldırıldı
(belirsiz data+document sorgularını LLM çözer; bu artık varsayılan davranış).

`QueryRouter` örneklenmiyor (init ağır bağımlılıklar yüklüyor); metodlar hafif bir
stub `self` ile çağrılıyor.
"""

import pytest

from src.router import QueryRouter, _has_strong_data_signal
from backend.services.response_builder import (
    _is_bare_refusal,
    build_chat_response,
)


# ── _has_strong_data_signal (saf fonksiyon, fallback-only) ──────────────────
class TestStrongDataSignal:
    @pytest.mark.parametrize("q", [
        # açık veri kaynağı + agregasyon birlikte → güçlü data sinyali
        "show me the breakdown as a table",
        "summarize the spreadsheet total manpower by trade",
        "from the spreadsheet data, give me the total manpower count grouped by trade",
        "using the manpower production log spreadsheets, total count of workers per trade",
    ])
    def test_explicit_source_plus_aggregation_is_strong(self, q):
        assert _has_strong_data_signal(q.lower()) is True

    @pytest.mark.parametrize("q", [
        # veri kaynağı ismi yok → güçlü sinyal yok (sadece agregasyon yetmez)
        "total crane hours across all blocks",
        "how many steel fixers on site",
        "equipment utilization by block",
        # saf doküman → güçlü sinyal yok
        "what does clause 5 say about liquidated damages",
        "summarize the inspection letter",
        "explain the scope of work",
        "tell me about the project",
    ])
    def test_no_explicit_source_is_not_strong(self, q):
        assert _has_strong_data_signal(q.lower()) is False


# ── _is_greeting daraltma ──────────────────────────────────────────────────
class _StubRouter:
    """`_is_greeting` için minimal self."""
    _is_greeting = QueryRouter._is_greeting
    GREETING_PATTERNS = QueryRouter.GREETING_PATTERNS


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
