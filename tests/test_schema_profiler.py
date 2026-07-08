"""Excel Schema Profiler + Column Mapper.

Covers the documented mismatched-header cases (item 10), English fuzzy/synonym
mapping, low-confidence clarification, persistence, and the FormatConverter
integration (fuzzy schema assignment + rename-to-canonical at ingest).
"""

import pandas as pd
import pytest

from src.schema_profiler import (SchemaProfiler, get_profiler, normalize,
                                  COLUMN_MATCH_THRESHOLD)


@pytest.fixture(scope="module")
def profiler():
    return get_profiler()


# ── normalization ────────────────────────────────────────────
class TestNormalize:
    @pytest.mark.parametrize("raw,expected", [
        ("Machinery Name", "machinery name"),
        ("  Cumulative %  ", "cumulative"),
        ("No. of Workers", "no of workers"),
        ("Makine Adı", "makine adi"),      # Turkish dotless-ı folds to i
        ("Çalışma Saati", "calisma saati"),
        ("Blok", "blok"),
        ("BOQ_Qty", "boq qty"),
    ])
    def test_normalize(self, raw, expected):
        assert normalize(raw) == expected


# ── item 10: the three documented mismatched-header cases ─────
class TestDocumentedMismatchCases:
    def test_turkish_equipment_headers_map_to_equipment_log(self, profiler):
        # "Makine Adı", "Çalışma Saati", "Blok", "Tarih"
        r = profiler.profile(["Makine Adı", "Çalışma Saati", "Blok", "Tarih"])
        assert r.schema_id == "equipment_log"
        assert not r.needs_clarification
        assert r.column_map == {
            "Makine Adı": "Machinery Name",
            "Çalışma Saati": "Estimated Machinery Hours",
            "Blok": "Block",
            "Tarih": "Date",
        }
        assert r.missing_required == ["Floor"]

    def test_trade_manpower_month_maps_columns_but_clarifies(self, profiler):
        # "Trade", "Manpower Count", "Month" — only 2 of 8 required fields,
        # so the column mapper resolves the two but the schema stays ambiguous.
        r = profiler.profile(["Trade", "Manpower Count", "Month"])
        assert r.column_map.get("Trade") == "Job Description"
        assert r.column_map.get("Manpower Count") == "Number of Workers"
        assert r.schema_id is None          # too little coverage to auto-assign
        assert r.needs_clarification
        assert r.candidates and r.candidates[0][0] == "manpower_production"

    def test_ipc_amount_cumulative_maps_columns_but_clarifies(self, profiler):
        # "IPC Amount", "Cumulative %"
        r = profiler.profile(["IPC Amount", "Cumulative %"])
        assert r.column_map.get("IPC Amount") == "Total BOQ Amount"
        assert r.column_map.get("Cumulative %") == "Cumulative %"
        assert r.schema_id is None
        assert r.needs_clarification


# ── English fuzzy / synonym mapping (the prod case) ──────────
class TestEnglishVariants:
    def test_equipment_synonyms_confident(self, profiler):
        r = profiler.profile(["Machine", "Operating Hours", "Building",
                              "Work Date", "Level"])
        assert r.schema_id == "equipment_log"
        assert r.confidence == 1.0
        assert r.column_map["Machine"] == "Machinery Name"
        assert r.column_map["Operating Hours"] == "Estimated Machinery Hours"
        assert r.column_map["Building"] == "Block"

    def test_full_manpower_variant_confident(self, profiler):
        r = profiler.profile(["Work Date", "Building", "Level", "Task",
                              "Trade", "Headcount", "Output", "UOM"])
        assert r.schema_id == "manpower_production"
        assert r.confidence == 1.0
        assert r.column_map["Headcount"] == "Number of Workers"
        assert r.column_map["Task"] == "Activity Description"

    def test_typo_tolerance(self, profiler):
        # single-character typo still clears the fuzzy threshold
        assert profiler._score_raw_to_field(
            normalize("Machnery Name"),
            profiler._field_candidates(
                profiler.schemas.get_schema("equipment_log").columns[3]),
        ) >= COLUMN_MATCH_THRESHOLD


# ── exact canonical must still be perfect (regression guard) ──
class TestExactCanonicalRegression:
    def test_exact_headers_full_coverage(self, profiler):
        r = profiler.profile(["Date", "Block", "Floor", "Machinery Name",
                              "Estimated Machinery Hours"])
        assert r.schema_id == "equipment_log"
        assert r.confidence == 1.0
        # every header maps to its own canonical name (no cross-field theft)
        assert all(k == v for k, v in r.column_map.items())
        assert "Estimated Machinery Hours" in r.column_map


# ── negative / robustness ────────────────────────────────────
class TestNoMatch:
    def test_junk_headers_no_schema(self, profiler):
        r = profiler.profile(["col_0", "foo", "bar", "xyz"])
        assert r.schema_id is None
        assert r.column_map == {}

    def test_empty(self, profiler):
        assert profiler.profile([]).schema_id is None
        assert profiler.profile(["", "   "]).schema_id is None

    def test_conflict_resolution_highest_score_wins(self, profiler):
        # Two headers that both lean toward "Machinery Name"; the exact one wins,
        # the weaker one must not also claim the same field.
        r = profiler.profile(["Machinery Name", "Machine Type", "Date", "Block",
                              "Floor", "Estimated Machinery Hours"])
        # exactly one raw header maps to Machinery Name
        assert list(r.column_map.values()).count("Machinery Name") == 1
        assert r.column_map["Machinery Name"] == "Machinery Name"


# ── persistence round-trip ───────────────────────────────────
class TestPersistence:
    def test_persist_and_reload(self, tmp_path, monkeypatch):
        import src.schema_profiler as sp
        monkeypatch.setattr(sp, "_MAPPINGS_FILE", tmp_path / "schema_mappings.json")
        prof = SchemaProfiler()
        cols = ["Makine Adı", "Çalışma Saati", "Blok", "Tarih", "Kat"]
        r = prof.profile(cols)
        prof.persist_mapping(cols, r)
        assert (tmp_path / "schema_mappings.json").exists()

        # a fresh instance (same file) resolves via the persisted record
        prof2 = SchemaProfiler()
        r2 = prof2.profile(cols)
        assert r2.source == "persisted"
        assert r2.schema_id == r.schema_id
        assert r2.column_map == r.column_map


# ── FormatConverter integration ──────────────────────────────
class TestConverterIntegration:
    def test_match_schema_accepts_english_variants(self):
        from src.schema_converter import get_format_converter
        conv = get_format_converter()
        df = pd.DataFrame(columns=["Machine", "Operating Hours", "Building",
                                   "Work Date", "Level"])
        assert conv._match_schema(df) == "equipment_log"

    def test_match_schema_declines_ambiguous(self):
        from src.schema_converter import get_format_converter
        conv = get_format_converter()
        df = pd.DataFrame(columns=["Trade", "Manpower Count", "Month"])
        assert conv._match_schema(df) is None   # ambiguous → clarify, not assign

    def test_cast_types_renames_variants_to_canonical(self):
        from src.schema_converter import get_format_converter
        conv = get_format_converter()
        df = pd.DataFrame({
            "Machine": ["Excavator"],
            "Operating Hours": [8],
            "Building": ["A"],
            "Work Date": ["2027-03-01"],
            "Level": ["L1"],
        })
        out = conv._cast_types(df, "equipment_log")
        assert "Machinery Name" in out.columns
        assert "Estimated Machinery Hours" in out.columns
        assert "Block" in out.columns
        assert "Date" in out.columns
        assert "Machine" not in out.columns    # raw header renamed away
