"""Routing regression — workflow-grade asks claim the WORKFLOW route and never
fall to DATA/DOCUMENT; planned asks return a helpful workflow answer."""

import pytest

from src.router import QueryRouter
from src.types import QueryType


def _router():
    return QueryRouter.__new__(QueryRouter)


@pytest.mark.parametrize("q,expected_id", [
    ("what programme files are available", "programme_inventory"),
    ("run dcma on the latest programme", "dcma_latest"),
    ("show milestone movements as a chart", "milestone_shift_chart"),
    ("delayed blockwork's chronology in 6.1 format", "delay_chronology_section"),
    ("prepare 6.1 format chronology for delayed blockwork",
     "delay_chronology_section"),
    ("show equipment utilization by block", "sql_metric_chart"),
    ("create manpower by trade chart", "sql_metric_chart"),
    ("create notice compliance matrix", "notice_compliance_matrix"),
    ("create internal eot roadmap", "internal_eot_roadmap"),
    ("generate preliminary delay claim report pack",
     "preliminary_delay_claim_pack"),
])
def test_workflow_grade_asks_route_to_workflow(q, expected_id):
    d = _router()._classify_workflow(q)
    assert d is not None, q
    assert d.query_type == QueryType.WORKFLOW
    assert d.metadata["id"] == expected_id


@pytest.mark.parametrize("q", [
    "delayed blockwork's chronology in 6.1 format",
    "what programme files are available",
    "run dcma on the latest programme",
    "show equipment utilization by block",
])
def test_workflow_grade_asks_never_data_or_document(q):
    d = _router()._classify_workflow(q)
    assert d is not None
    assert d.query_type not in (QueryType.DATA, QueryType.DOCUMENT)


@pytest.mark.parametrize("q", [
    "summarise this document",
    "what does the report say about safety",
    "who was responsible for the delay",
])
def test_plain_questions_not_claimed_by_workflow(q):
    assert _router()._classify_workflow(q) is None
