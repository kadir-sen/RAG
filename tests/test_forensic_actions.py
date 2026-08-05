from pathlib import Path
from types import SimpleNamespace

from backend.services.forensic_toolkit.actions import ForensicActionService
from backend.services.forensic_toolkit.engine import VENDOR_ROOT
from src.forensic_store import ForensicStore


def _workspace(store: ForensicStore, root: Path):
    xer = root / "baseline.xer"
    xer.write_text("ERMHDR\n%T\tPROJECT\n%T\tTASK\n", encoding="utf-8")
    programme, _ = store.add_programme(
        project_id="p1", username="owner", file_name=xer.name,
        file_path=str(xer), size_bytes=xer.stat().st_size, sha256="a" * 64,
    )
    return store.create_workspace(
        project_id="p1", username="owner", name="Analysis",
        programme_ids=[programme["file_id"]], settings={},
    )


class _Audit:
    def finish(self, *_args, **_kwargs):
        return None


def test_tia_event_extraction_keeps_only_verbatim_evidence(tmp_path: Path, monkeypatch):
    import backend.services.forensic_toolkit.actions as action_module

    store = ForensicStore(tmp_path / "forensic.db")
    workspace = _workspace(store, tmp_path)
    monkeypatch.setattr(
        action_module.ForensicSourceService, "evidence_documents",
        lambda *_args, **_kwargs: [("notice.pdf", "Access was unavailable from 5 May 2026.")],
    )
    monkeypatch.setattr(action_module.ForensicActionService, "_start_audit",
                        staticmethod(lambda *_args, **_kwargs: "audit-1"))
    monkeypatch.setattr(action_module, "get_run_store", lambda: _Audit())
    monkeypatch.setattr(action_module, "generate_text", lambda *_args, **_kwargs: SimpleNamespace(
        text='{"events": ['
             '{"title":"Access restriction","date_start":"2026-05-05",'
             '"source_doc":"notice.pdf","source_snippet":"Access was unavailable from 5 May 2026.",'
             '"confidence":"high"},'
             '{"title":"Invented","source_doc":"notice.pdf",'
             '"source_snippet":"This sentence does not exist."}]}'
    ))
    result = ForensicActionService(store).extract_tia_events(
        project_id="p1", workspace_id=workspace["workspace_id"], username="owner",
        expected_version=1, source_ids=["doc-1"],
    )
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["verified"] is True
    assert result["dropped_unverified"] == 1
    assert store.get_workspace_state("p1", workspace["workspace_id"])["version"] == 2


def test_fragnet_and_logic_ai_outputs_pass_upstream_validators(tmp_path: Path, monkeypatch):
    import backend.services.forensic_toolkit.actions as action_module

    source = sorted((VENDOR_ROOT / "sample" / "revisions").glob("*.xer"))[-1]
    store = ForensicStore(tmp_path / "forensic.db")
    programme, _ = store.add_programme(
        project_id="p1", username="owner", file_name=source.name,
        file_path=str(source), size_bytes=source.stat().st_size, sha256="c" * 64,
    )
    workspace = store.create_workspace(
        project_id="p1", username="owner", name="Analysis",
        programme_ids=[programme["file_id"]], settings={},
    )
    monkeypatch.setattr(action_module.ForensicActionService, "_start_audit",
                        staticmethod(lambda *_args, **_kwargs: "audit-1"))
    monkeypatch.setattr(action_module, "get_run_store", lambda: _Audit())
    event = {
        "event_id": "EV-001", "title": "Utility diversion", "description": "Divert utility",
        "date_raised": "2026-01-02", "responsibility_asserted": "", "evidence_note": "",
        "area": "", "discipline": "", "project_context": "", "work_package": "",
    }
    monkeypatch.setattr(action_module, "generate_text", lambda *_args, **_kwargs: SimpleNamespace(
        text='{"activities":[{"id":"TIA-010","name":"Utility diversion",'
             '"duration_days":5,"calendar_id":"",'
             '"predecessors":[{"id":"A2000","type":"FS","lag_days":0}],'
             '"successors":[{"id":"MS1000","type":"FS","lag_days":0}],'
             '"rationale":"planner estimate","assumptions":"review"}]}'
    ))
    fragnet = ForensicActionService(store).recommend_fragnet(
        project_id="p1", workspace_id=workspace["workspace_id"], username="owner",
        expected_version=1, programme_id=programme["file_id"], event_record=event,
    )
    assert fragnet["fragnet"][0]["id"] == "TIA-010"
    assert not any("unknown" in issue for issue in fragnet["validation_issues"])

    monkeypatch.setattr(action_module, "generate_text", lambda *_args, **_kwargs: SimpleNamespace(
        text='{"predecessors":[{"id":"A2000","type":"FS","lag_days":0,'
             '"rationale":"existing logic","confidence":"high"}],'
             '"successors":[{"id":"MS1000","type":"FS","lag_days":0,'
             '"rationale":"completion tie","confidence":"high"}],'
             '"impacted_sections":[],"warnings":[]}'
    ))
    logic = ForensicActionService(store).recommend_logic(
        project_id="p1", workspace_id=workspace["workspace_id"], username="owner",
        expected_version=2, programme_id=programme["file_id"], event_record=event,
        fragnet_rows=fragnet["fragnet"],
    )
    assert logic["recommendation"]["predecessors"][0]["id"] == "A2000"
    assert logic["recommendation"]["successors"][0]["id"] == "MS1000"
