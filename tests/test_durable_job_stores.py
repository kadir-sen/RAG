import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tasks.ingestion_jobs import IngestionJobStore
from backend.tasks.report_jobs import ReportJobStore
from src.toolkit_evidence_store import ToolkitEvidenceStore


def test_ingestion_queue_is_project_scoped_and_recovers_after_restart(tmp_path):
    store = IngestionJobStore(tmp_path / "ingestion.db")
    first = store.enqueue("project-a", "file-1", "/tmp/one.pdf", "one.pdf")
    store.enqueue("project-b", "file-2", "/tmp/two.pdf", "two.pdf")

    claimed = store.claim_next()
    assert claimed["job_id"] == first["job_id"]
    assert claimed["status"] == "processing"
    assert store.recover_interrupted() == 1
    assert store.get(first["job_id"], "project-b") is None
    assert store.get(first["job_id"], "project-a")["status"] == "queued"

    claimed_again = store.claim_next()
    store.complete(claimed_again["job_id"], {"pages": 3})
    assert store.project_summary("project-a")["ready"] == 1
    assert store.project_summary("project-b")["queued"] == 1


def test_report_queue_recovers_and_never_reads_another_project(tmp_path):
    store = ReportJobStore(tmp_path / "reports.db")
    job = store.enqueue(
        project_id="project-a", username="alice", module="chronology",
        title="Access", request={"title": "Access"},
    )
    assert store.claim_next()["status"] == "processing"
    assert store.recover() == 1
    assert store.get(job["job_id"], "project-b") is None
    assert store.get(job["job_id"], "project-a")["status"] == "queued"
    assert job["sequence_number"] == 1
    assert job["report_url"].endswith(job["job_id"])


def test_chronology_sequence_is_atomic_per_project(tmp_path):
    store = ReportJobStore(tmp_path / "sequence.db")
    def create(index: int):
        return store.enqueue(
            project_id="project-a", username="alice", module="chronology",
            title=f"Topic {index}", request={"topic": f"Topic {index}"},
        )
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = list(pool.map(create, range(12)))
    assert sorted(job["sequence_number"] for job in jobs) == list(range(1, 13))

    other = store.enqueue(
        project_id="project-b", username="alice", module="chronology",
        title="Other", request={"topic": "Other"},
    )
    assert other["sequence_number"] == 1


def test_large_ingestion_waits_for_twenty_document_calibration(tmp_path):
    store = IngestionJobStore(tmp_path / "calibration.db")
    for number in range(21):
        store.enqueue("project-a", f"file-{number:02}", f"/tmp/{number}.pdf", f"{number}.pdf")

    claimed = []
    for _ in range(20):
        job = store.claim_next()
        assert job is not None
        claimed.append(job)
        if len(claimed) < 20:
            store.complete(job["job_id"])
    # The twentieth calibration document is still running, so document 21
    # remains queued instead of invalidating the measured ETA baseline.
    assert store.claim_next() is None
    store.complete(claimed[-1]["job_id"])
    assert store.project_summary("project-a")["calibration_complete"] is True
    assert store.claim_next()["file_id"] == "file-20"


def test_toolkit_evidence_is_immutable_and_project_scoped(tmp_path):
    store = ToolkitEvidenceStore(tmp_path / "toolkit.db")
    artifact = store.create(
        project_id="project-a", title="Time Slice Analysis",
        methodology="Windows analysis", findings=["Window 3 recorded 14 days."],
        source_doc_ids=["programme-1"], created_by="alice",
    )
    assert store.get(artifact["artifact_id"], "project-b") is None
    evidence = store.as_evidence([artifact["artifact_id"]], "project-a")
    assert evidence[0].kind == "toolkit"
    assert evidence[0].excerpt == "Window 3 recorded 14 days."
