"""Register validation core — the containment guard. No LLM."""

import pytest

from src.delay_reports.register import (
    actor_in_snippet, date_in_snippet, dates_in_text, normalize_date_multi,
    quote_in_snippet, validate_entry,
)

SNIPPET = (
    "Letter ref JMD/1234. On 19 July 2023, JAMED raised concerns about "
    "delayed access to several buildings, including CC2 and CM1. JAMED "
    "requested clarification of access dates."
)


class TestDateNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("19 July 2023", "2023-07-19"),
        ("19th July 2023", "2023-07-19"),
        ("19 Jul 23", "2023-07-19"),
        ("July 19, 2023", "2023-07-19"),
        ("2023-07-19", "2023-07-19"),
        ("19/07/2023", "2023-07-19"),
        ("19.07.23", "2023-07-19"),
        ("30 June 2024", "2024-06-30"),
    ])
    def test_surface_forms(self, raw, expected):
        assert normalize_date_multi(raw) == expected

    def test_garbage_returns_none(self):
        assert normalize_date_multi("next Tuesday") is None
        assert normalize_date_multi("") is None
        assert normalize_date_multi("99/99/2023") is None

    def test_dates_in_text_finds_all_forms(self):
        text = "On 19 July 2023 and again on 20/07/2023 and 2023-08-01."
        assert dates_in_text(text) == {"2023-07-19", "2023-07-20", "2023-08-01"}


class TestContainment:
    def test_date_in_snippet(self):
        assert date_in_snippet("2023-07-19", SNIPPET) is True
        assert date_in_snippet("2023-07-20", SNIPPET) is False

    def test_actor_in_snippet(self):
        assert actor_in_snippet("JAMED", SNIPPET) is True
        assert actor_in_snippet("Bilfinger Berger", SNIPPET) is False

    def test_quote_verbatim(self):
        assert quote_in_snippet("raised concerns about delayed access", SNIPPET)
        assert not quote_in_snippet("expressed frustration about access", SNIPPET)

    def test_quote_whitespace_tolerant(self):
        assert quote_in_snippet("JAMED  raised\nconcerns", SNIPPET)


class TestValidateEntry:
    def _raw(self, **kw):
        base = {"event_date": "19 July 2023", "actor": "JAMED",
                "quote": "JAMED raised concerns about delayed access"}
        base.update(kw)
        return base

    def test_all_pass_verified(self):
        level, _ = validate_entry(self._raw(), SNIPPET)
        assert level == "verified"

    def test_invented_date_dropped(self):
        level, reason = validate_entry(self._raw(event_date="25 December 2023"), SNIPPET)
        assert level is None and "not found in evidence" in reason

    def test_unparseable_date_dropped(self):
        level, reason = validate_entry(self._raw(event_date="mid-summer"), SNIPPET)
        assert level is None and "not parseable" in reason

    def test_wrong_actor_date_only(self):
        level, reason = validate_entry(self._raw(actor="Siemens"), SNIPPET)
        assert level == "date_only" and "actor" in reason

    def test_paraphrased_quote_date_only_when_actor_ok(self):
        # Date + actor verified; paraphrased quote must not lose the event —
        # it downgrades to date_only (and the caller swaps in a verbatim
        # snippet excerpt).
        level, reason = validate_entry(
            self._raw(quote="JAMED complained about slow access"), SNIPPET)
        assert level == "date_only" and "quote" in reason

    def test_neither_actor_nor_quote_dropped(self):
        level, reason = validate_entry(
            self._raw(actor="Siemens",
                      quote="JAMED complained about slow access"), SNIPPET)
        assert level is None and "neither" in reason

    def test_publication_date_leak_guard(self):
        # An edinburgh payload/publication date NOT present in the letter text
        # must never validate as an event date.
        level, _ = validate_entry(self._raw(event_date="20 June 2018"), SNIPPET)
        assert level is None
