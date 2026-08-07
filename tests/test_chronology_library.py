"""What each typed subject must resolve to.

The chronology matcher is deliberately not a model, which means its behaviour
is a design rather than a tendency — and a design can be pinned down. These
cases are the design: for every chronology, the exact title, a natural phrasing
someone would actually type, a party or place named only in that document, and
an abbreviation.

The negative cases matter as much. Handing over the chronology for the wrong
issue is a real problem, so "no match" is a correct and useful answer, and
nothing should ever resolve to a document it is not about.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.chronology_library import (doc_path, download_filename, list_docs,  # noqa: E402
                                    match)


# (typed subject, chronology it must resolve to)
CASES = [
    # 01 — the SDS design contract
    ("incomplete and misaligned design", "01"),
    ("the design was late", "01"),
    ("what happened with the design", "01"),
    ("parsons brinckerhoff", "01"),
    ("sds contract", "01"),
    ("design deliverables", "01"),
    # 02 — tie as delivery vehicle
    ("tie mismanagement", "02"),
    ("how was the project governed", "02"),
    ("audit scotland review", "02"),
    ("deloitte", "02"),
    ("the board", "02"),
    ("cost estimating", "02"),
    # 03 — utility diversions
    ("utility diversions", "03"),
    ("the utilities were diverted", "03"),
    ("mudfa", "03"),
    ("carillion", "03"),
    ("underground apparatus", "03"),
    ("trial holes", "03"),
    # 04 — the contract strategy
    ("irreparably flawed contract strategy", "04"),
    ("contract strategy", "04"),
    ("the procurement risk transfer", "04"),
    ("wiesbaden", "04"),
    ("notified departures", "04"),
    ("dla piper advice", "04"),
    # 05 — disputes and stoppages
    ("contractor disputes", "05"),
    ("contractor", "05"),
    ("work stoppages", "05"),
    ("princes street", "05"),
    ("adjudications", "05"),
    ("downing tools", "05"),
    # 06 — national oversight
    ("withdrawal of national oversight", "06"),
    ("transport scotland", "06"),
    ("scottish ministers", "06"),
    ("grant offer", "06"),
    ("who funded it", "06"),
    ("scrutiny by government", "06"),
]

# Nothing in the collection is about these, so a confident answer would be a
# wrong one. This list is the guarantee someone demonstrating the product needs:
# type something off-subject and you get the list of chronologies, never a
# document. It holds because of the keyword lists as they stand today, which is
# exactly why it is pinned — one over-general word added to _DOCS later would
# take it away silently.
NON_SUBJECTS = [
    # nothing at all
    "banana bread", "the weather in paris", "hava durumu", "xyzzy", "",
    # keyboard noise
    "asdasd", "qwerty zxcvb", "123456", "hello", "test test test",
    # real sentences about something else entirely
    "what is the weather in dubai", "football match results",
    "who is the ceo of the company", "how much does a coffee cost",
    # construction, and even this project — but not one of the six subjects
    "concrete pour quality", "steel reinforcement schedule",
    "health and safety incidents", "passenger numbers and ticketing",
    "tram testing and commissioning", "labour productivity",
]

# A single distinctive word is a legitimate way to ask: these name one document
# and nothing else. Guarding the list above must never cost this.
ONE_WORD_CASES = [
    ("mudfa", "03"), ("sds", "01"), ("wiesbaden", "04"),
    ("carillion", "03"), ("bilfinger", "05"), ("novation", "01"),
    ("adjudication", "05"), ("oversight", "06"),
]


@pytest.mark.parametrize("subject,expected", CASES)
def test_subject_resolves_to_its_chronology(subject, expected):
    result = match(subject)
    if result["status"] == "ambiguous":
        # Asking is acceptable, answering wrongly is not — the right document
        # must at least be among the candidates offered.
        refs = [r["doc"].ref for r in result["ranked"]]
        assert expected in refs, f"{subject!r} → {refs}, missing {expected}"
        return
    assert result["status"] == "match", f"{subject!r} → {result['status']}"
    assert result["doc"].ref == expected


@pytest.mark.parametrize("subject", NON_SUBJECTS)
def test_unrelated_subjects_match_nothing(subject):
    result = match(subject)
    assert result["status"] == "none", (
        f"{subject!r} produced {result['status']} — an off-subject query must "
        f"never resolve to a chronology"
    )


@pytest.mark.parametrize("subject,expected", ONE_WORD_CASES)
def test_one_distinctive_word_is_enough(subject, expected):
    result = match(subject)
    assert result["status"] == "match", f"{subject!r} → {result['status']}"
    assert result["doc"].ref == expected


def test_every_chronology_is_reachable():
    """A document nothing can resolve to may as well not be in the library."""
    reached = set()
    for subject, _ in CASES:
        r = match(subject)
        if r["status"] == "match":
            reached.add(r["doc"].ref)
    assert reached == {d.ref for d in list_docs()}


def test_every_chronology_is_on_disk_and_has_a_download_name():
    """The registry is only a promise; these are the two things that have to be
    true for a subject to produce a document. A file that stopped shipping, or
    an entry added without the author's own name for it, both fail here rather
    than at the moment someone tries to download it."""
    for doc in list_docs():
        assert doc_path(doc).is_file(), f"{doc.file} is missing from content/chronologies/"
        assert doc.download_name.strip(), f"{doc.ref} has no download_name"
        assert download_filename(doc).endswith(".docx")


def test_scores_are_stable():
    """Asked twice, answered the same. The matcher has no state and no model,
    so this should hold by construction — the test is here because that is the
    property the whole design rests on."""
    for subject, _ in CASES[:8]:
        first, second = match(subject), match(subject)
        assert first["status"] == second["status"]
        if first["status"] == "match":
            assert first["doc"].ref == second["doc"].ref
            assert first["score"] == second["score"]
