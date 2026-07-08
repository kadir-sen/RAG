"""The 5 evaluation fixes: error leak, degraded routing, chronology scope,
SQL fallback, trust-guard fail-open badge."""

from unittest.mock import patch

import pytest

from src.router import QueryRouter
from src.types import QueryType


def _stub_router():
    return QueryRouter.__new__(QueryRouter)


# ── Fix 1 + 4: SQL path never leaks raw provider errors ──────
class TestSqlLeakSanitization:
    def test_sql_except_returns_safe_message(self):
        from src.data_analyzer_sql import get_data_analyzer, SQL_UNAVAILABLE_MSG
        an = get_data_analyzer()
        # Reach the except by making internal work raise a raw 429 after the
        # early "no tables" guard is bypassed via a table stub.
        an.tables = {"t": {"corpus": "demo", "header_metadata": {}}}
        with patch.object(an, "_try_deterministic_shortcut", return_value=None), \
             patch.object(an, "select_table", return_value="t"), \
             patch.object(an, "_generate_sql",
                          side_effect=RuntimeError(
                              "LLM call failed (gemini): 429 You exceeded your "
                              "current quota, billing https://ai.google.dev")):
            out = an.query("total equipment hours", table_name="t")
        answer = out["answer"].lower()
        assert out["answer"] == SQL_UNAVAILABLE_MSG
        for tok in ("429", "quota", "billing", "googleapis"):
            assert tok not in answer
        assert not any("error" in (s or {}) for s in out["sources"])

    def test_budget_error_reraised_not_swallowed(self):
        from src.data_analyzer_sql import get_data_analyzer
        from src.usage_tracker import BudgetExceededError
        an = get_data_analyzer()
        an.tables = {"t": {"corpus": "demo", "header_metadata": {}}}
        with patch.object(an, "_try_deterministic_shortcut", return_value=None), \
             patch.object(an, "select_table", return_value="t"), \
             patch.object(an, "_generate_sql",
                          side_effect=BudgetExceededError("limit")):
            with pytest.raises(BudgetExceededError):
                an.query("total equipment hours", table_name="t")


# ── Fix 2: degraded routing bias ─────────────────────────────
class TestDegradedRouting:
    @pytest.mark.parametrize("q", [
        "who caused the delay in this project?",
        "is the contractor entitled to eot?",
        "who is responsible for the delay days?",
        "is the contractor liable for the blockwork delay?",
    ])
    def test_high_risk_goes_document(self, q):
        d = _stub_router()._classify_high_risk_document(q)
        assert d is not None and d.query_type == QueryType.DOCUMENT

    @pytest.mark.parametrize("q", [
        "peak manpower day",
        "total workers in june",
        "sum of concrete m3 by block",
        "equipment utilization by block",
    ])
    def test_genuine_data_not_hijacked(self, q):
        assert _stub_router()._classify_high_risk_document(q) is None


# ── Fix 3: chronology scope robustness ───────────────────────
class TestChronologyScope:
    @pytest.mark.parametrize("q,title", [
        ("Prepare a detailed chronology for Delayed Blockwork", "Delayed Blockwork"),
        ("the Delayed Blockwork chronology", "Delayed Blockwork"),
        ("Delayed Blockwork's chronology", "Delayed Blockwork"),
        ("Blockwork delay chronology", "Blockwork"),
        ("Prepare chronology for Delayed Blockwork. Use numbered paragraphs, dates.",
         "Delayed Blockwork"),
        ("For the Delayed Access event, prepare the 6.1 section", "Delayed Access"),
    ])
    def test_title_extracted(self, q, title):
        from src.delay_reports.scope import resolve_event_scope
        s = resolve_event_scope(q)
        assert not s.needs_clarification and s.event_title == title

    @pytest.mark.parametrize("q", [
        "Find the main delay events and prepare chronology",
        "the project chronology",
        "prepare a chronology of delays",
    ])
    def test_generic_clarifies(self, q):
        from src.delay_reports.scope import resolve_event_scope
        assert resolve_event_scope(q).needs_clarification

    def test_no_instruction_contamination(self):
        from src.delay_reports.scope import resolve_event_scope
        s = resolve_event_scope(
            "chronology for Delayed Access. Include exhibit references and caveats.")
        assert s.event_title == "Delayed Access"
        assert "include" not in (s.event_title or "").lower()


# ── Fix 5: trust-guard fail-open badge ───────────────────────
class TestTrustGuardFailOpenBadge:
    def test_verifier_outage_surfaces_unverified_badge(self):
        from backend.services.response_builder import _build_trust_guard
        raw = {"trust_guard": {"skipped": True, "skipped_reason": "error",
                               "risk": "high"}}
        info = _build_trust_guard(raw)
        assert info is not None
        assert info.sufficiency_label == "unverified"
        assert info.analyst_review_required is True
        assert any("analyst review" in c.lower() for c in info.caveats)

    def test_benign_skip_no_badge(self):
        from backend.services.response_builder import _build_trust_guard
        for reason, risk in [("risk_below_threshold", "low"),
                             ("route_excluded", "medium"),
                             ("disabled", "high")]:
            raw = {"trust_guard": {"skipped": True, "skipped_reason": reason,
                                   "risk": risk}}
            assert _build_trust_guard(raw) is None

    def test_normal_verdict_maps(self):
        from backend.services.response_builder import _build_trust_guard
        raw = {"trust_guard": {"skipped": False, "sufficiency_label": "verified",
                               "sufficiency": 0.9, "action": "approve",
                               "caveats": [], "analyst_review_required": False}}
        info = _build_trust_guard(raw)
        assert info.sufficiency_label == "verified"
