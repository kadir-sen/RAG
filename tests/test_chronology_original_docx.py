"""The authored chronology comes down as itself.

What this endpoint returns is pasted straight into a client's report. For a
while it returned a re-typeset copy — the same entries, our layout, our
provenance stamp — which is a different document from the one the author wrote
and handed over. These tests pin the two things that make it the same document
again: the bytes, and the name.

Offline and deterministic: no network, no LLM, no user store — the six .docx
files ship in the image, and the auth dependency is overridden.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Must be set before backend.core.security is imported.
os.environ.setdefault("JWT_SECRET", "test-secret-please-replace-in-prod")

from src.chronology_library import (  # noqa: E402
    doc_path,
    download_filename,
    get_doc,
    list_docs,
)

REFS = [d.ref for d in list_docs()]


@pytest.fixture()
def client():
    from backend.api import chronology as chronology_api
    from backend.core.security import UserContext, get_current_user

    app = FastAPI()
    app.include_router(chronology_api.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: UserContext(
        username="tester", role="admin", display_name="Tester",
        features={"corpus": "edinburgh"}, token_limit=0,
    )
    return TestClient(app)


def _disposition(res) -> str:
    return res.headers["content-disposition"]


def _name_as_the_browser_sees_it(disposition: str) -> str:
    """The extraction frontend/src/api/download.ts performs, in Python.

    The download is an XHR blob, so the browser's own RFC 6266 parsing never
    runs — that regex is the whole filename logic. There is no JS unit runner
    in frontend/, so this is where the two halves are held to the same contract.
    """
    star = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
    if star:
        return unquote(star.group(1))
    plain = re.search(r'filename="([^"]*)"', disposition)
    return plain.group(1) if plain else ""


# ── the bytes ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("ref", REFS)
def test_body_is_the_authored_file_byte_for_byte(client, ref):
    res = client.get(f"/api/chronology/subjects/{ref}/document")
    assert res.status_code == 200

    original = doc_path(get_doc(ref)).read_bytes()
    assert res.content == original
    assert res.headers["content-length"] == str(len(original))
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )


# ── the name ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ref", REFS)
def test_download_carries_the_authors_own_name(client, ref):
    res = client.get(f"/api/chronology/subjects/{ref}/document")
    wanted = download_filename(get_doc(ref))

    assert f"filename*=UTF-8''{quote(wanted, safe='')}" in _disposition(res)
    assert _name_as_the_browser_sees_it(_disposition(res)) == wanted
    # Never the numbered name we store it under.
    assert get_doc(ref).file not in _disposition(res)


def test_curly_quotes_survive_the_header(client):
    """04's name carries quotes. The ASCII form flattens them; filename* must
    not, or the file arrives under a mangled name."""
    res = client.get("/api/chronology/subjects/04/document")
    assert (_name_as_the_browser_sees_it(_disposition(res))
            == "An “Irreparably Flawed” Contract Strategy.docx")
    # A quote must never reach the quoted-string form: it would close it early
    # and truncate the name at "An ".
    ascii_part = _disposition(res).split("filename*=")[0]
    assert ascii_part.count('"') == 2


def test_filename_header_is_readable_from_script(client):
    """Without this the browser names every download "download"."""
    res = client.get("/api/chronology/subjects/01/document")
    assert res.headers["access-control-expose-headers"] == "Content-Disposition"


# ── the escape hatch ────────────────────────────────────────────────────
def test_rendered_still_builds_the_typeset_copy(client):
    res = client.get("/api/chronology/subjects/03/document?rendered=1")
    assert res.status_code == 200
    assert res.content.startswith(b"PK")  # a real .docx
    assert res.content != doc_path(get_doc("03")).read_bytes()
    assert "Chronology-03" in _disposition(res)


# ── failure modes ───────────────────────────────────────────────────────
@pytest.mark.parametrize("suffix", ["", "?rendered=1"])
def test_unknown_ref_is_404(client, suffix):
    res = client.get(f"/api/chronology/subjects/99/document{suffix}")
    assert res.status_code == 404
    assert res.json()["detail"] == "No such chronology"


def test_missing_file_says_so_instead_of_serving_an_empty_chronology(
    client, tmp_path, monkeypatch
):
    """A deployment that lost content/ must fail loudly. Falling through to the
    rendered build would parse the same absent file into zero entries and hand
    over a chronology that looks legitimate and says nothing."""
    from src import chronology_library

    monkeypatch.setattr(chronology_library, "CHRONOLOGY_DIR", tmp_path)
    res = client.get("/api/chronology/subjects/01/document")

    assert res.status_code == 500
    assert res.json()["detail"] == "Chronology file missing on this deployment"
