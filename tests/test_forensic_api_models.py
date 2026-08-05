import pytest
from pydantic import ValidationError

from backend.api.forensic import RunCreate


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
