"""A cited document must open even when its stored doc_id has died.

`generate_doc_id` is an md5 of the file *path* at ingest time, so it is a
fingerprint of a moment: re-ingest the corpus, move the data directory or change
the host layout, and every id minted before that stops resolving — while the
documents themselves sit untouched on disk.

Measured on production: of 932 stored citations, **398 (43%) carry such an id**.
A sample of 20 was tested both ways — 20 of 20 failed to open by doc_id, and 20
of 20 of the same documents opened by file name. Example: citation
`0b562d7b9e56aaaa` → "Document not found", while
`/api/docs/CEC00381196_PART1.pdf/content` served page 5 of 32.

Every citation already carries `doc_name`, so a viewer that gives up on the id
is discarding the answer it was handed. These tests pin the fallback, and pin
that it stays *last* — the id chain can serve an extracted table rather than a
raw sheet, so it must keep winning when it works.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.document_service import DocumentService  # noqa: E402


@pytest.fixture
def service(tmp_path, monkeypatch):
    """A DocumentService whose disk search is confined to tmp_path."""
    import backend.services.document_service as ds
    monkeypatch.setattr(ds, "_DATA_FALLBACK_ROOTS", [tmp_path], raising=False)
    return DocumentService()


def _pdf(path: Path) -> None:
    """A one-page PDF, small but real enough for the renderer to open."""
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )


class TestDeadDocIdStillOpens:
    def test_a_hash_id_that_resolves_to_nothing_falls_back_to_the_name(
            self, service, tmp_path, monkeypatch):
        """The production failure: a real 16-hex id from a stored citation."""
        _pdf(tmp_path / "CEC00381196_PART1.pdf")
        served = {}
        monkeypatch.setattr(
            service, "_serve_by_extension",
            lambda p, a="": served.update(path=p, anchor=a) or "SERVED")

        out = service._get_content_sync(
            "0b562d7b9e56aaaa", "page_5", "CEC00381196_PART1.pdf")

        assert out == "SERVED"
        assert Path(served["path"]).name == "CEC00381196_PART1.pdf"
        assert served["anchor"] == "page_5"       # the cited page is not lost

    def test_no_file_name_still_reports_not_found(self, service):
        out = service._get_content_sync("0b562d7b9e56aaaa", "", "")
        assert out.error == "Document not found"

    def test_a_file_name_alone_is_enough(self, service, tmp_path, monkeypatch):
        """Callers that never had an id — an empty doc_id must not short-circuit."""
        _pdf(tmp_path / "WED00000533.pdf")
        monkeypatch.setattr(service, "_serve_by_extension",
                            lambda p, a="": f"SERVED:{Path(p).name}")

        assert service._get_content_sync("", "", "WED00000533.pdf") == "SERVED:WED00000533.pdf"

    def test_nothing_at_all_is_rejected(self, service):
        out = service._get_content_sync("", "", "")
        assert out.error == "No document ID provided"
        assert service._get_content_sync("   ", "", "  ").error == "No document ID provided"

    def test_a_name_that_is_not_on_disk_reports_not_found(self, service):
        out = service._get_content_sync("deadbeefdeadbeef", "", "NOT-THERE.pdf")
        assert out.error == "Document not found"


class TestTheFallbackStaysLast:
    def test_a_working_doc_id_still_wins(self, service, tmp_path, monkeypatch):
        """The id chain is more specific — it can serve an extracted table rather
        than the raw sheet — so the name must not pre-empt it."""
        import backend.services.document_service as ds

        class _Reg:
            def get(self, doc_id):
                return type("R", (), {"file_path": str(tmp_path / "by_id.pdf")})()

            def get_all(self):
                return []

        _pdf(tmp_path / "by_id.pdf")
        _pdf(tmp_path / "by_name.pdf")
        monkeypatch.setattr(ds, "_DATA_FALLBACK_ROOTS", [tmp_path], raising=False)
        monkeypatch.setattr("src.document_registry.get_document_registry",
                            lambda: _Reg())
        monkeypatch.setattr(service, "_serve_by_extension",
                            lambda p, a="": f"SERVED:{Path(p).name}")

        out = service._get_content_sync("whatever", "", "by_name.pdf")

        assert out == "SERVED:by_id.pdf"
