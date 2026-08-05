import pytest
from pydantic import ValidationError

from backend.api.forensic import (
    ExtractEventsAction, GenerateNarrativeAction, RunCreate,
    SourceSelectionUpdate, WorkspaceStatePatch,
)
from backend.services.forensic_toolkit.parity import MODULE_PARITY, parity_fingerprint


def test_module_parameters_are_discriminated_and_reject_unknown_fields():
    value = RunCreate.model_validate({
        "parameters": {"kind": "progress-s-curve", "weight_scheme": "duration"},
    })
    assert value.parameters.kind == "progress-s-curve"
    with pytest.raises(ValidationError):
        RunCreate.model_validate({
            "parameters": {"kind": "progress-s-curve", "weight_scheme": "duration",
                           "unvalidated_option": True},
        })


def test_tia_requires_structured_event_and_fragnet():
    with pytest.raises(ValidationError):
        RunCreate.model_validate({"parameters": {"kind": "time-impact-analysis", "events": []}})


def test_source_selection_and_workspace_state_reject_untyped_fields():
    value = SourceSelectionUpdate.model_validate({
        "expected_version": 2,
        "sources": [{"source_id": "doc-1", "selected_scope": {"sheet": "Data", "row_from": 2}}],
    })
    assert value.sources[0].selected_scope.sheet == "Data"
    with pytest.raises(ValidationError):
        WorkspaceStatePatch.model_validate({
            "expected_version": 1,
            "umbrella": {"rounds": [{"round_number": 1, "instruction": "Review",
                                       "unexpected": "not allowed"}]},
        })


def test_parity_manifest_covers_all_upstream_navigation_modules():
    expected = {
        "intake", "dcma", "baseline-critical-path", "revision-comparison",
        "out-of-sequence", "float-erosion", "progress-s-curve", "resource-loading",
        "sequence-coding", "hierarchy", "milestone-shift", "progress-transfer",
        "as-built-critical-path", "report-assembler", "as-planned-vs-as-built",
        "windows-analysis", "impacted-as-planned", "collapsed-as-built",
        "time-impact-analysis",
    }
    assert set(MODULE_PARITY) == expected
    assert len(parity_fingerprint()) == 64
    assert MODULE_PARITY["time-impact-analysis"]["steps"][-1].startswith("⑦")


def test_ai_action_payloads_are_typed_and_bounded():
    extraction = ExtractEventsAction.model_validate({
        "action": "extract_events", "expected_version": 3,
        "source_ids": ["doc-1"], "query": "utility diversion notices",
    })
    assert extraction.source_ids == ["doc-1"]
    narrative = GenerateNarrativeAction.model_validate({
        "action": "generate_narrative", "expected_version": 3,
        "run_id": "frun_123", "analyst_instructions": "Keep it factual.",
    })
    assert narrative.run_id == "frun_123"
    with pytest.raises(ValidationError):
        ExtractEventsAction.model_validate({
            "action": "extract_events", "expected_version": 1,
            "source_ids": [],
        })
