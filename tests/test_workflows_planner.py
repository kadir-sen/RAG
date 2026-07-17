"""Deterministic planner triggers."""

import pytest

from src.workflows import plan
from src.workflows.types import WorkflowId, WorkflowStatus


@pytest.mark.parametrize("q,expected", [
    ("What programme files are available for this project?",
     WorkflowId.PROGRAMME_INVENTORY),
    ("List XER files.", WorkflowId.PROGRAMME_INVENTORY),
    ("Run DCMA on the latest programme.", WorkflowId.DCMA_LATEST),
    ("Show milestone movements as a chart.", WorkflowId.MILESTONE_SHIFT_CHART),
    ("Delayed Blockwork's chronology in 6.1 format.",
     WorkflowId.DELAY_CHRONOLOGY_SECTION),
    ("Prepare 6.1 format chronology for Delayed Blockwork.",
     WorkflowId.DELAY_CHRONOLOGY_SECTION),
    ("Create claim chronology section for delayed access.",
     WorkflowId.DELAY_CHRONOLOGY_SECTION),
    ("Create manpower by trade chart.", WorkflowId.SQL_METRIC_CHART),
    ("Show equipment utilization by block.", WorkflowId.SQL_METRIC_CHART),
    ("Make this into a report section.", WorkflowId.CONTEXT_TO_REPORT_SECTION),
    ("Generate a preliminary programme analysis pack.",
     WorkflowId.PRELIMINARY_PROGRAMME_PACK),
    ("Generate the monthly progress report.",
     WorkflowId.MONTHLY_PROGRESS_REPORT),
    ("Monthly progress report for June 2025.",
     WorkflowId.MONTHLY_PROGRESS_REPORT),
    # Wording the registry advertises as a trigger example must actually route.
    ("Monthly progress summary.", WorkflowId.MONTHLY_PROGRESS_REPORT),
    ("Prepare a delay briefing.", WorkflowId.DELAY_BRIEFING),
])
def test_available_triggers(q, expected):
    wp = plan(q.lower())
    assert wp is not None, q
    assert wp.workflow_id == expected
    assert wp.status in (WorkflowStatus.AVAILABLE, WorkflowStatus.PARTIAL)


@pytest.mark.parametrize("q,expected", [
    ("Create internal EOT claim roadmap.", WorkflowId.INTERNAL_EOT_ROADMAP),
])
def test_planned_triggers(q, expected):
    wp = plan(q.lower())
    assert wp is not None, q
    assert wp.workflow_id == expected
    assert wp.status == WorkflowStatus.PLANNED


def test_monthly_and_delay_briefing_are_not_confused():
    """The demo prompt names both 'progress' and 'delay briefing'; it must
    reach the briefing, and the delay-report registry must not swallow it
    into a plain 6.1 chronology on the way."""
    wp = plan("generate a monthly progress and delay briefing for this project.")
    assert wp is not None
    assert wp.workflow_id == WorkflowId.DELAY_BRIEFING


@pytest.mark.parametrize("q", [
    "who caused the delay",
    "is the contractor entitled to an EOT",
    "draft a reply letter to the engineer",
    "summarise this document",
    "what is the project completion date",
    "hello",
])
def test_plain_questions_return_none(q):
    assert plan(q.lower()) is None


def test_chronology_html_mode_vs_plain_mode():
    html = plan("prepare a 6.1 chronology and render it as an html report section")
    assert html.workflow_id == WorkflowId.DELAY_CHRONOLOGY_SECTION
    assert html.params.get("mode") == "html"
    plain = plan("delayed blockwork's chronology in 6.1 format")
    assert plain.params.get("mode") == "plain"


def test_sql_metric_gate_ignores_document_questions():
    # 'equipment' present but it's a contract question → not a SQL metric.
    assert plan("what does the contract say about equipment by the contractor") \
        is None
