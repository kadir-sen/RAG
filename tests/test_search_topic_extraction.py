"""The document-search topic extractor must not eat the question.

Regression for a missing word boundary: the `on` alternative in the topic
pattern matched the "on" INSIDE any -ion word and discarded everything before
it. In a construction/inquiry corpus — completion, construction, variation,
information, decision, inspection, provision, notification — that is most
questions, so retrieval searched a fragment and the answer denied a corpus it
had never really looked in.

Measured in production: "Who signed the certificate of practical completion for
Phase 1b?" searched for "for Phase 1b" and came back "not in the documents",
while five documents named "Phase 1b — Roseburn to Granton".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.router import QueryRouter

extract = QueryRouter._extract_document_search_topic


# Every one of these was mangled. The whole question must survive: none of them
# carries a topic marker, so there is nothing to narrow to.
@pytest.mark.parametrize("query", [
    "Who signed the certificate of practical completion for Phase 1b?",
    "What caused the delay to construction of the depot?",
    "Which variation orders affected the utility diversions?",
    "What information was provided to the board?",
    "Explain the inspection findings",
    "Summarise the provisions for liquidated damages",
    "Was there any notification of the completion date change?",
])
def test_an_ion_word_does_not_truncate_the_question(query):
    assert extract(query) == query


# The narrowing this function exists for still works — a real topic marker,
# standing as its own word.
@pytest.mark.parametrize("query,topic", [
    ("Which documents are related to the MUDFA contract?", "the MUDFA contract"),
    ("Show me letters about the funding gap", "the funding gap"),
    ("documents regarding the depot", "the depot"),
    ("What was the decision on the tram programme?", "the tram programme"),
    ("emails mentioning the Roseburn junction", "the Roseburn junction"),
])
def test_a_real_topic_marker_still_narrows(query, topic):
    assert extract(query) == topic


def test_the_production_case():
    """The exact question that produced the measured false negative."""
    q = "Who signed the certificate of practical completion for Phase 1b?"
    assert "Phase 1b" in extract(q)
    assert extract(q) != "for Phase 1b"
    # the words that make the question answerable are still there
    assert "certificate" in extract(q) and "completion" in extract(q)
