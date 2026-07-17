"""Workflow catalogue integrity."""

from src.workflows import WORKFLOWS, get_spec, is_available
from src.workflows.registry import COMPOSITE_TO_WORKFLOW
from src.workflows.types import WorkflowId, WorkflowStatus


def test_all_workflow_ids_registered():
    # The set equality is the real integrity check (every enum has a spec and
    # vice-versa); the count is a snapshot, bump it when adding a workflow.
    assert set(WORKFLOWS.keys()) == set(WorkflowId)
    assert len(WORKFLOWS) == 18


def test_available_have_delegation_target():
    for wid, spec in WORKFLOWS.items():
        if spec.status in (WorkflowStatus.AVAILABLE, WorkflowStatus.PARTIAL):
            assert spec.target, f"{wid} available but no target"
            assert spec.target.startswith(("composite:", "adapter:"))


def test_planned_offer_a_substitute_or_hint():
    for wid, spec in WORKFLOWS.items():
        if spec.status in (WorkflowStatus.PLANNED, WorkflowStatus.UNAVAILABLE):
            assert spec.substitute is not None or spec.substitute_hint, \
                f"{wid} planned but no substitute/hint"
            # substitute, if set, must itself be a registered available workflow
            if spec.substitute is not None:
                assert is_available(spec.substitute)


def test_composite_map_points_at_available_workflows():
    for cid, wid in COMPOSITE_TO_WORKFLOW.items():
        assert wid in WORKFLOWS
        assert is_available(wid)


def test_get_spec_and_is_available():
    assert get_spec(WorkflowId.DCMA_LATEST).status == WorkflowStatus.AVAILABLE
    assert is_available(WorkflowId.PROGRAMME_INVENTORY)
    assert not is_available(WorkflowId.INTERNAL_EOT_ROADMAP)
