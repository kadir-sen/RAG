"""Faz 2 — bileşik/çok-adımlı sorgu tespiti birim testleri (network gerektirmez).

`is_multi_step_query` router ve planner tarafından paylaşılır; sıralı zincirleri,
açık bileşik bağlaçları, 'hem ... hem' ve 2+ soru işaretini yakalamalı; basit tek
sorguları ve conversation-history içeren augmented sorguları yanlış tetiklememeli.
"""
import pytest

from src.query_planner import is_multi_step_query as m


class TestMultiStepDetection:
    @pytest.mark.parametrize("q", [
        "What were the crane hours, and also which trades were on site?",
        "Summarize the delay notice and additionally show the actual progress",
        "total crane hours then group by block",
        "What is X? What is Y?",
        "hem ekipman hem işçi sayısını ver",
        "ekipman saatlerini ve ayrıca işçi sayısını göster",
        "compare Q1 month-over-month",
    ])
    def test_multi_step_detected(self, q):
        assert m(q) is True

    @pytest.mark.parametrize("q", [
        "How many workers on Block A?",
        "Compare equipment and manpower for Block A",   # single multi-table, not stacked
        "What does the contract say about delays?",
        "Total hours by equipment type",
        "Which trade has the best productivity?",
    ])
    def test_single_step(self, q):
        assert m(q) is False

    def test_history_does_not_false_trigger(self):
        # Augmented query: history has its own '?'s, current turn is simple.
        augmented = (
            "<CONVERSATION_HISTORY>\n"
            "User: How many workers on Block A?\n"
            "Assistant: [DATA] 245 workers. Was that helpful?\n"
            "</CONVERSATION_HISTORY>\n\n"
            "Current question: and the crane hours?"
        )
        assert m(augmented) is False

    def test_history_with_compound_current_turn(self):
        augmented = (
            "<CONVERSATION_HISTORY>\nUser: hi\n</CONVERSATION_HISTORY>\n\n"
            "Current question: show crane hours, and also the manpower count"
        )
        assert m(augmented) is True

    def test_empty(self):
        assert m("") is False
        assert m(None) is False
