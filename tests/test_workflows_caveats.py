"""Caveat catalogue + aggregation."""

from src.workflows import caveats as CV


def test_aggregate_dedupes_and_preserves_order():
    out = CV.aggregate(["a", "b", ""], ["b", "c"], [None, "a"])
    assert out == ["a", "b", "c"]


def test_aggregate_handles_empty():
    assert CV.aggregate() == []
    assert CV.aggregate([], [None, ""]) == []


def test_all_constants_are_nonempty_strings():
    names = ["NO_XER", "ONE_XER_ONLY", "LATEST_AMBIGUOUS", "BASELINE_INFERRED",
             "MILESTONE_MAPPING_UNCONFIRMED", "NO_COMPATIBLE_EXCEL",
             "LOW_CONFIDENCE_SCHEMA", "LLM_NARRATIVE_UNAVAILABLE",
             "TRUST_GUARD_UNAVAILABLE", "MOVEMENT_NOT_CAUSATION",
             "DCMA_HEALTH_NOT_DELAY", "CHRONOLOGY_PRELIMINARY",
             "ANALYST_REVIEW_ENTITLEMENT"]
    for n in names:
        val = getattr(CV, n)
        assert isinstance(val, str) and val.strip()


def test_interpretation_limits_never_overclaim():
    assert "not" in CV.MOVEMENT_NOT_CAUSATION.lower()
    assert "not proof" in CV.DCMA_HEALTH_NOT_DELAY.lower()
    assert "analyst" in CV.ANALYST_REVIEW_ENTITLEMENT.lower()
