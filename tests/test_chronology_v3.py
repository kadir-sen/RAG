from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from src.chronology_v2 import PreparedChronologyQuery
from src.chronology_v3 import (
    _events_valid, _style_valid, evidence_from_documents, evidence_markdown, extract_events,
    prepare_chronology_query, research_documents,
)
from src.document_index import CandidateDocument, DocumentIndex, DocumentIndexRecord
from src.evidence_model import EvidenceItem


class MemoryChunkStore:
    def __init__(self):
        self._con = duckdb.connect(":memory:")
        self._con.execute(
            "CREATE TABLE chunks (chunk_id VARCHAR, doc_id VARCHAR, file_name VARCHAR, "
            "page_number INTEGER, text VARCHAR, project_id VARCHAR)"
        )
        self._con.execute(
            "CREATE TABLE document_index (search_id VARCHAR PRIMARY KEY, project_id VARCHAR, "
            "doc_id VARCHAR, file_name VARCHAR, reference VARCHAR, title VARCHAR, "
            "description VARCHAR, document_family VARCHAR, parties_json VARCHAR, "
            "topics_json VARCHAR, sheet_names_json VARCHAR, metadata_date VARCHAR, "
            "metadata_date_source VARCHAR, ocr_quality VARCHAR, content_hash VARCHAR, "
            "search_text VARCHAR, updated_at VARCHAR)"
        )
        self._dirty = False

    def connection(self):
        return self._con

    def _persist(self):
        return None


@pytest.fixture
def document_index(monkeypatch):
    store = MemoryChunkStore()
    monkeypatch.setattr("src.document_index.get_chunk_store", lambda: store)
    monkeypatch.setattr("src.chronology_v3.get_document_index", lambda: DocumentIndex())
    yield DocumentIndex(), store
    store._con.close()


def _record(project: str, doc_id: str, reference: str, title: str, family: str = "other",
            quality: str = "good") -> DocumentIndexRecord:
    return DocumentIndexRecord(
        project_id=project, doc_id=doc_id, file_name=f"{reference}.pdf",
        reference=reference, title=title, description=title,
        document_family=family, ocr_quality=quality, content_hash=f"hash-{doc_id}",
    )


def test_document_index_is_project_scoped_and_exact_map_documents_rank_first(document_index):
    index, _ = document_index
    index.upsert(_record("demo-a", "sds", "CEC00307573", "SDS historical review", "overview"))
    index.upsert(_record("demo-a", "tie", "CEC02086351", "TIE audit report", "audit"))
    index.upsert(_record("demo-a", "mudfa", "CEC01891483", "MUDFA close-out review", "review"))
    index.upsert(_record("demo-b", "secret", "CEC00307573", "Other project's SDS review", "overview"))

    ranked = index.search(
        project_id="demo-a", topic="SDS design chronology",
        queries=["CEC00307573", "CEC02086351", "CEC01891483"], limit=10,
    )

    assert {item.doc_id for item in ranked[:3]} == {"sds", "tie", "mudfa"}
    assert all(item.doc_id != "secret" for item in ranked)
    assert ranked[0].doc_id == "sds"


def test_metadata_dates_are_rejected_but_content_and_table_dates_are_accepted():
    evidence = [EvidenceItem(
        source_id="src-1", doc_id="doc-1", file_name="notice.pdf",
        excerpt="Date: 14 March 2025. The Engineer issued Notice 17.",
    )]
    base = {
        "event_date": "2025-03-14", "date_precision": "exact",
        "date_evidence": "14 March 2025", "actor": "Engineer", "action": "issued",
        "established_fact": "The Engineer issued Notice 17.", "party_position": "",
        "analytical_inference": "", "immediate_consequence": "",
        "supporting_source_ids": ["src-1"], "counter_source_ids": [], "missing_records": [],
    }
    for prohibited in ("metadata", "publication_date", "index_date", "manifest"):
        assert not _events_valid({"entries": [{**base, "date_source": prohibited}]}, evidence)
    assert _events_valid({"entries": [{**base, "date_source": "content_header"}]}, evidence)
    assert _events_valid({"entries": [{**base, "date_source": "content_body"}]}, evidence)
    assert _events_valid({"entries": [{**base, "date_source": "table_period"}]}, evidence)
    assert not _events_valid({"entries": [{
        **base, "event_date": "14 March 2025", "date_source": "content_header",
    }]}, evidence)


def test_solicitor_style_gate_checks_overview_event_length_and_date_order():
    overview = " ".join(["contract"] * 100)
    event = " ".join(["record"] * 40)
    value = {
        "overview_claims": [{"text": overview}],
        "entries": [
            {"event_date": "2025-01-01", "claims": [{"text": event}]},
            {"event_date": "2025-02-01", "claims": [{"text": event}]},
        ],
    }
    assert _style_valid(value)
    assert not _style_valid({**value, "overview_claims": [{"text": "too short"}]})
    assert not _style_valid({**value, "entries": list(reversed(value["entries"]))})


def test_map_identifier_harvest_forces_a_second_document_search(monkeypatch):
    map_doc = CandidateDocument(
        doc_id="map", file_name="review.pdf", reference="MAP-1", title="Historical review",
        description="", document_family="overview", metadata_date="",
        metadata_date_source="unknown", ocr_quality="good", score=5, role="map", reasons=[],
    )
    notice = CandidateDocument(
        doc_id="notice", file_name="N-417.pdf", reference="NOTICE-417", title="Notice 417",
        description="", document_family="notice", metadata_date="",
        metadata_date_source="unknown", ocr_quality="good", score=7, role="primary", reasons=[],
    )

    class Index:
        calls = []

        def search(self, **kwargs):
            self.calls.append(list(kwargs["queries"]))
            return [map_doc] if len(self.calls) == 1 else [notice, map_doc]

        def list_project(self, _project_id):
            return [
                _record("p1", "map", "MAP-1", "Historical review", "overview"),
                _record("p1", "notice", "NOTICE-417", "Notice 417", "notice"),
            ]

    index = Index()
    monkeypatch.setattr("src.chronology_v3.get_document_index", lambda: index)
    monkeypatch.setattr("src.chronology_v3.evidence_from_documents", lambda _p, ids: [
        EvidenceItem(source_id=f"src-{doc_id}", doc_id=doc_id, file_name=f"{doc_id}.pdf",
                     excerpt="14 March 2025 Notice 417") for doc_id in ids
    ])
    monkeypatch.setattr("src.chronology_v3._map_extract", lambda *_args, **_kwargs: {
        "skeleton": ["notice"],
        "leads": [{"kind": "notice", "value": "NOTICE-417",
                   "suggested_query": "NOTICE-417", "source_id": "src-map"}],
    })
    monkeypatch.setattr("src.chronology_v3.coverage_matrix", lambda _e: {"framework": 1})
    prepared = PreparedChronologyQuery(
        original_query="delay", english_query="delay", jargon_matches=(), parties=(),
        contracts=(), work_packages=(), exclusions=(), research_queries=("delay overview",),
    )

    selected, _, audit = research_documents("p1", prepared)

    assert any("NOTICE-417" in query for query in index.calls[1])
    assert {item.doc_id for item in selected} == {"map", "notice"}
    assert audit["research_leads"][0]["value"] == "NOTICE-417"


def test_unreadable_title_only_document_is_never_loaded_as_evidence(document_index):
    index, _ = document_index
    index.upsert(_record(
        "demo-a", "empty", "NOTICE-9", "Notice concerning delay", "notice", "unreadable",
    ))
    ranked = index.search(
        project_id="demo-a", topic="delay", queries=["NOTICE-9"], limit=10,
    )
    assert ranked and ranked[0].ocr_quality == "unreadable"
    from src.chronology_v3 import _select
    assert _select(ranked) == []


def test_excel_parquet_becomes_sheet_and_row_addressable_evidence(
    document_index, monkeypatch, tmp_path: Path,
):
    pd = pytest.importorskip("pandas")
    index, store = document_index
    index.upsert(DocumentIndexRecord(
        project_id="demo-a", doc_id="sheet-1", file_name="progress.xlsx",
        title="Progress register", description="weekly progress", document_family="schedule",
        sheet_names=["Period 01"], ocr_quality="table", content_hash="table-hash",
    ))
    parquet = tmp_path / "progress.parquet"
    pd.DataFrame({"Date": ["14 March 2025", "21 March 2025"], "Progress": [40, 55]}).to_parquet(parquet)
    table = SimpleNamespace(
        parquet_path=str(parquet), page_number=None, sheet_name="Period 01",
        table_name="t_progress", table_id="progress-1",
    )
    catalog = SimpleNamespace(entries={"entry": SimpleNamespace(
        project_id="demo-a", source_file="/old/host/progress.xlsx",
        source_type="excel", tables=[table],
    )})
    monkeypatch.setattr("src.catalog.get_catalog", lambda: catalog)
    monkeypatch.setattr("src.chronology_v3.get_chunk_store", lambda: store, raising=False)
    # evidence_from_documents imports the symbol directly from src.chunk_store.
    monkeypatch.setattr("src.chunk_store.get_chunk_store", lambda: store)

    evidence = evidence_from_documents("demo-a", ["sheet-1"])

    assert len(evidence) == 1
    assert evidence[0].kind == "excel"
    assert evidence[0].sheet == "Period 01"
    assert (evidence[0].row_from, evidence[0].row_to) == (2, 3)
    assert "| Date | Progress |" in evidence[0].excerpt
    assert "TABLE sheet=Period 01 rows=2-3" in evidence_markdown(evidence)


def test_validated_extraction_checkpoint_skips_provider_call(monkeypatch):
    evidence = [EvidenceItem(
        source_id="src-1", doc_id="doc-1", file_name="notice.pdf",
        excerpt="Date: 14 March 2025. The Engineer issued Notice 17.",
    )]
    prepared = PreparedChronologyQuery(
        original_query="delay", english_query="delay", jargon_matches=(), parties=(),
        contracts=(), work_packages=(), exclusions=(), research_queries=("delay",),
    )
    saved = {"entries": [{
        "event_date": "2025-03-14", "date_precision": "exact",
        "date_source": "content_header", "date_evidence": "14 March 2025",
        "actor": "Engineer", "action": "issued", "established_fact": "Notice 17",
        "party_position": "", "analytical_inference": "", "immediate_consequence": "",
        "supporting_source_ids": ["src-1"], "counter_source_ids": [], "missing_records": [],
    }]}
    monkeypatch.setattr(
        "src.llm_client.generate_response_json",
        lambda *_args, **_kwargs: pytest.fail("provider must not run for a ready checkpoint"),
    )

    result = extract_events(
        evidence, prepared,
        load_step=lambda _key, _hash: {"status": "ready", "output": saved},
    )

    assert result == saved["entries"]


def test_credit_exhaustion_is_not_swallowed_by_planner_fallback(monkeypatch):
    from src.billing_store import CreditBalanceExceededError
    monkeypatch.setattr(
        "src.llm_client.generate_response_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(CreditBalanceExceededError("demo_user")),
    )
    with pytest.raises(CreditBalanceExceededError):
        prepare_chronology_query("contract delay", project_id="demo-a")


def test_provider_timeout_does_not_trigger_recursive_batch_split(monkeypatch):
    evidence = [
        EvidenceItem(source_id=f"src-{index}", doc_id=f"doc-{index}",
                     file_name=f"notice-{index}.pdf", excerpt="14 March 2025 Notice")
        for index in range(2)
    ]
    prepared = PreparedChronologyQuery(
        original_query="delay", english_query="delay", jargon_matches=(), parties=(),
        contracts=(), work_packages=(), exclusions=(), research_queries=("delay",),
    )
    calls = []
    monkeypatch.setattr(
        "src.llm_client.generate_response_json",
        lambda *_args, **_kwargs: (calls.append(1), (_ for _ in ()).throw(
            RuntimeError("provider timeout")
        ))[1],
    )
    with pytest.raises(RuntimeError, match="provider timeout"):
        extract_events(evidence, prepared)
    assert len(calls) == 1


def test_demo_plan_routes_to_v3_while_legacy_stays_v2(monkeypatch):
    from backend.api import reports

    class Billing:
        plan = "demo"

        def summary(self, _username):
            return {"plan_type": self.plan}

    billing = Billing()
    monkeypatch.setattr(
        "src.user_store.get_user_store", lambda: SimpleNamespace(billing=billing),
    )
    assert reports._chronology_pipeline("demo_user") == "chronology-v3"
    billing.plan = "legacy"
    assert reports._chronology_pipeline("admin2") == "chronology-v2"


def test_normal_report_contract_redacts_research_and_cost_diagnostics():
    from backend.api.reports import _public

    public = _public({
        "job_id": "job-1", "status": "ready", "coverage_status": "partial",
        "result": {
            "entries": [{"event_date": "2025-03-14"}],
            "evidence": [{"source_id": "src-1", "doc_id": "doc-1"}],
            "research_audit": {"queries": ["secret"]},
            "verification_audit": {"decisions": []},
            "render_audit": {"paragraphs": 2}, "model": "gemini-3.6-flash",
            "prompt_version": "chronology-v3", "provider_cost_usd": 1.2,
        },
    })

    assert set(public["result"]) == {"entries", "evidence"}
    # Unknown monetary fields must not leak even if a future pipeline adds one.
    assert "coverage_status" not in public
