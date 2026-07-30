"""The corpus evidence behind an authored chronology.

The six narratives name no source files — 80 entries and zero filename-shaped
matches — so "which document is 6.3.4 about?" had no answer before this. The
build resolves it with BM25 over the mirrored chunk text plus the extracted events
falling in each dated entry's period, and reports what it actually did.

The date-window cases carry the most weight. They are deliberately NOT built on
event_timeline._date_sort_key: that is a sort key, and it picks the first month it
finds by dictionary order rather than by position, so "December 2008 and January
2009" sorts as April. Reading months paired with the year that follows them is
what turns that phrase into two months rather than two years — a bug this test
suite caught while it was being written.

A local caveat, stated so nobody reads a passing suite as proof of the event lane:
this checkout's event store holds **7** events (the demo corpus, 2016–2023) while
the chronologies are Edinburgh Tram, 2003–2011. The intersection is empty and not
by a near miss. The 27,676 Edinburgh events live in production, so the event
pairing is verified there; here it is only verified that "no events in this
period" is reported as a first-class outcome rather than as an empty section.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.chronology_evidence as ev  # noqa: E402


ENTRIES = [
    {"ref": "6.3.1", "date": "", "text": "MUDFA was the contract by which tie procured diversions.", "sub": []},
    {"ref": "6.3.2", "date": "28 March 2006", "text": "DLA Piper produced a report on the key contractual terms.",
     "sub": ["i) scope was not fixed", "ii) apparatus was unknown"]},
    {"ref": "6.3.3", "date": "By late 2008", "text": "The utility diversions remained incomplete.", "sub": []},
]


class TestDateWindow:
    @pytest.mark.parametrize("text,window", [
        ("28 March 2006", ("2006-03-28", "2006-03-28")),
        ("September 2005", ("2005-09-01", "2005-09-30")),
        ("By late 2008", ("2008-01-01", "2008-12-31")),
        ("1905", ("1905-01-01", "1905-12-31")),
        ("2010–2011", ("2010-01-01", "2011-12-31")),
        ("June–July 2010", ("2010-06-01", "2010-07-31")),
        ("28–30 April 2008", ("2008-04-28", "2008-04-30")),
        ("Between June and December 2010", ("2010-06-01", "2010-12-31")),
    ])
    def test_windows(self, text, window):
        assert ev.entry_window(text) == window

    def test_two_months_across_two_years_is_two_months(self):
        """The bug this suite caught. Taking min/max of months and years
        independently turned "December 2008 and January 2009" into
        January 2008 → December 2009 — two years instead of two months."""
        assert ev.entry_window("December 2008 and January 2009") == (
            "2008-12-01", "2009-01-31")

    @pytest.mark.parametrize("text", ["", "   ", "Throughout", "in the same period"])
    def test_no_date_means_no_window(self, text):
        assert ev.entry_window(text) is None

    def test_a_february_end_is_not_the_31st(self):
        assert ev.entry_window("February 2008") == ("2008-02-01", "2008-02-29")

    def test_padding_widens_both_ends(self):
        lo, hi = ev._pad(("2006-03-28", "2006-03-28"), days=30)
        assert lo == "2006-02-26" and hi == "2006-04-27"


class TestBuild:
    def test_it_searches_every_entry_and_reports_the_real_numbers(self, monkeypatch):
        calls = []

        def fake_search(query, top_k):
            calls.append(query)
            return [{"file_name": "CEC00471472.pdf", "page_number": 3,
                     "text": "utility diversions", "lex_score": 9.5}]

        monkeypatch.setattr(ev, "_search", fake_search)
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_corpus_size", lambda: 7289)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        out = ev.build("03", "Utility Diversion Failures", "summary", ENTRIES)

        # one subject pass + three entries + two sub-points
        assert out["passes"] == 6
        assert out["units_searched"] == 5
        assert out["dated_units"] == 4          # 6.3.2 + its 2 subs + 6.3.3
        assert out["corpus_searched"] == 7289
        assert out["elapsed_ms"] >= 0
        assert out["from_cache"] is False
        assert len(calls) == 6

    def test_documents_are_keyed_by_file_name_not_a_hash(self, monkeypatch):
        """These documents have no registry entry; the viewer resolves them by
        name, and a path-derived hash would 404 — the defect fixed yesterday."""
        monkeypatch.setattr(ev, "_search", lambda q, k: [
            {"file_name": "WED00000533.pdf", "page_number": 25,
             "text": "expert report", "lex_score": 4.0}])
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        doc = ev.build("03", "t", "s", ENTRIES)["documents"][0]
        assert doc["doc_id"] == "WED00000533.pdf" == doc["file_name"]
        assert doc["anchor"] == "page_25"

    def test_the_best_scoring_page_wins_per_document(self, monkeypatch):
        seq = iter([
            [{"file_name": "a.pdf", "page_number": 1, "text": "x", "lex_score": 2.0}],
            [{"file_name": "a.pdf", "page_number": 9, "text": "y", "lex_score": 8.0}],
        ])
        monkeypatch.setattr(ev, "_search", lambda q, k: next(seq, []))
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        docs = ev.build("03", "t", "s", ENTRIES[:1])["documents"]
        assert len(docs) == 1 and docs[0]["page_number"] == 9

    def test_the_budget_stops_the_loop_and_says_so(self, monkeypatch):
        def slow(query, top_k):
            time.sleep(0.02)
            return []

        monkeypatch.setattr(ev, "_search", slow)
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        out = ev.build("03", "t", "s", ENTRIES * 20, budget_ms=30)
        assert out["budget_exhausted"] is True
        assert out["units_searched"] < 100

    def test_the_index_warm_up_is_outside_the_budget(self, monkeypatch):
        """A cold full-text index took 19 seconds on this corpus. Charged to the
        budget it consumed the whole of it and every entry pass was skipped."""
        monkeypatch.setattr(ev, "_search", lambda q, k: [])
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        monkeypatch.setattr(ev, "_warm_index", lambda: time.sleep(0.08))
        ev.clear_cache()

        out = ev.build("03", "t", "s", ENTRIES, budget_ms=50)
        assert out["budget_exhausted"] is False
        assert out["units_searched"] == 5

    def test_steps_are_emitted_for_work_that_happened(self, monkeypatch):
        steps = []
        monkeypatch.setattr(ev, "_search", lambda q, k: [
            {"file_name": "a.pdf", "page_number": 1, "text": "x", "lex_score": 1.0}])
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        ev.build("03", "t", "s", ENTRIES,
                 on_step=lambda k, l, d="": steps.append((k, l, d)))

        labels = [l for _, l, _ in steps]
        assert any("preparing the search index" in l for l in labels)
        assert any(l.startswith("6.3.2 ·") for l in labels)
        assert any("resolved" in l for l in labels)


class TestCache:
    def test_a_second_build_reuses_and_does_not_search(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ev, "_search", lambda q, k: calls.append(q) or [])
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        ev.build("03", "t", "s", ENTRIES)
        n = len(calls)
        again = ev.build("03", "t", "s", ENTRIES)

        assert again["from_cache"] is True
        assert len(calls) == n, "a cache hit must not search again"

    def test_force_rebuilds(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ev, "_search", lambda q, k: calls.append(q) or [])
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        ev.build("03", "t", "s", ENTRIES)
        n = len(calls)
        out = ev.build("03", "t", "s", ENTRIES, force=True)

        assert out["from_cache"] is False and len(calls) > n

    def test_corpora_do_not_share_a_cache_entry(self, monkeypatch):
        monkeypatch.setattr(ev, "_search", lambda q, k: [])
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        ev.build("03", "t", "s", ENTRIES, corpus="edinburgh")
        assert ev.cached("03", "demo") is None

    def test_reuse_stops_once_the_window_has_passed(self, monkeypatch):
        """The window is short on purpose — an instantly returned report reads as
        one prepared earlier. Past it, the search runs again."""
        monkeypatch.setattr(ev, "_search", lambda q, k: [])
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        ev.build("03", "t", "s", ENTRIES)
        assert ev.cached("03", "") is not None

        # Age the entry past the window rather than sleeping through it. The
        # offset is read now: ev.time is the time module itself, so a lambda
        # calling time.time() would call the patched clock and recurse.
        later = time.time() + ev.CACHE_TTL_S + 1
        monkeypatch.setattr(ev.time, "time", lambda: later)
        assert ev.cached("03", "") is None

    def test_zero_ttl_switches_reuse_off(self, monkeypatch):
        monkeypatch.setattr(ev, "_search", lambda q, k: [])
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        monkeypatch.setattr(ev, "CACHE_TTL_S", 0)
        ev.clear_cache()

        ev.build("03", "t", "s", ENTRIES)
        assert ev.cached("03", "") is None, "nothing may be reused when the window is 0"
        assert ev.build("03", "t", "s", ENTRIES)["from_cache"] is False

    def test_the_default_window_is_short_enough_to_be_invisible(self):
        """A demo must not show a report arriving in milliseconds. If someone
        raises this, they should have to change the test that says why."""
        assert ev.CACHE_TTL_S <= 60


class TestNoCorpus:
    def test_has_corpus_is_false_when_nothing_is_searchable(self, monkeypatch):
        monkeypatch.setattr(ev, "_corpus_size", lambda: 0)
        assert ev.has_corpus() is False

    def test_a_failing_search_does_not_kill_the_build(self, monkeypatch):
        """One lost pass is worth more than a dead build."""
        from src import lexical_index

        def boom(*a, **k):
            raise RuntimeError("index unavailable")

        monkeypatch.setattr(lexical_index, "get_lexical_index", boom)
        monkeypatch.setattr(ev, "_warm_index", lambda: None)
        monkeypatch.setattr(ev, "_events_for", lambda w, f: [])
        ev.clear_cache()

        out = ev.build("03", "t", "s", ENTRIES)
        assert out["documents"] == [] and out["units_searched"] == 5
