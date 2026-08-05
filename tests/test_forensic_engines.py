from pathlib import Path

import pytest

from backend.services.forensic_toolkit.engine import MODULE_DEFINITIONS, VENDOR_ROOT, run_module
from src.forensic_store import UPSTREAM_SHA


def _programmes():
    root = VENDOR_ROOT / "sample" / "revisions"
    return [
        {
            "file_id": f"xer_{index}", "name": path.name,
            "sha256": f"{index:064x}", "file_path": str(path),
        }
        for index, path in enumerate(sorted(root.glob("*.xer")), 1)
    ]


EVENTS = [{
    "event": {
        "event_id": "EV-001", "title": "Test delay", "description": "",
        "date_raised": "2026-07-02", "responsibility_asserted": "",
        "evidence_note": "", "area": "", "discipline": "",
        "project_context": "", "work_package": "",
    },
    "fragnet": [{
        "id": "EV-001-FRAG-01", "name": "Test delay", "duration_days": 5,
        "predecessors": [{"id": "A2000", "type": "FS", "lag_days": 0}],
        "successors": [{"id": "MS1000", "type": "FS", "lag_days": 0}],
        "rationale": "fixture", "assumptions": "", "confidence": "medium",
        "calendar_id": "",
    }],
}]


PARAMETERS = {
    "intake": {}, "dcma": {}, "baseline-critical-path": {},
    "revision-comparison": {}, "out-of-sequence": {}, "float-erosion": {},
    "progress-s-curve": {}, "resource-loading": {}, "sequence-coding": {},
    "hierarchy": {}, "milestone-shift": {}, "progress-transfer": {},
    "as-built-critical-path": {}, "report-assembler": {},
    "as-planned-vs-as-built": {}, "windows-analysis": {},
    "impacted-as-planned": {"events": EVENTS},
    "collapsed-as-built": {"remove_activity_codes": ["A1000"]},
    "time-impact-analysis": {"events": EVENTS},
}


def test_pinned_vendor_revision_and_all_19_native_modules_are_registered():
    assert UPSTREAM_SHA == "bb52fa0a5e41fc2040979b226911b192463701d5"
    assert len(MODULE_DEFINITIONS) == 19
    assert set(MODULE_DEFINITIONS) == set(PARAMETERS)
    assert (VENDOR_ROOT / "dcma" / "xer_parser.py").is_file()
    assert (VENDOR_ROOT / "programme" / "tia.py").is_file()


@pytest.mark.parametrize("module_slug", list(MODULE_DEFINITIONS))
def test_native_module_runs_against_upstream_xer_fixtures(module_slug: str):
    output = run_module(module_slug, _programmes(), PARAMETERS[module_slug], prior_runs=[])
    assert output["module"] == module_slug
    assert output["title"] == MODULE_DEFINITIONS[module_slug]["title"]
    assert len(output["_artifacts"]) >= 2
    assert {artifact["kind"] for artifact in output["_artifacts"]} >= {"json", "excel"}
    assert all(artifact["content"] for artifact in output["_artifacts"])


def test_streamlit_ui_is_not_imported_by_native_engine():
    import sys
    run_module("intake", _programmes(), {})
    assert "streamlit" not in sys.modules
    assert "views" not in sys.modules
