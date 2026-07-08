"""Vendored programme-engine tests — port of the upstream executable spec.

Doubles as the import-rewrite smoke test: importing every vendored module
proves the absolute→relative rewrite left no dangling `from dcma...` import.
No network, no LLM, no Streamlit.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "xer"


def load_revisions():
    from src.programme_tools.vendor.dcma import parse_xer
    files = []
    for path in sorted(FIXTURES.glob("*.xer")):
        files.append((path.name, parse_xer(path.read_bytes())))
    return files


class TestVendorImports:
    def test_every_vendored_module_imports(self):
        import importlib
        for mod in [
            "src.programme_tools.vendor.dcma.models",
            "src.programme_tools.vendor.dcma.config",
            "src.programme_tools.vendor.dcma.xer_parser",
            "src.programme_tools.vendor.dcma.checks",
            "src.programme_tools.vendor.dcma.rationale",
            "src.programme_tools.vendor.dcma.narrative",
            "src.programme_tools.vendor.dcma.report_xlsx",
            "src.programme_tools.vendor.programme.inventory",
            "src.programme_tools.vendor.programme.milestones",
            "src.programme_tools.vendor.programme.variance",
            "src.programme_tools.vendor.programme.critical_path",
            "src.programme_tools.vendor.programme.activity_codes",
            "src.programme_tools.vendor.programme.wbs",
            "src.programme_tools.vendor.programme.narrative",
            "src.programme_tools.vendor.programme.report_xlsx",
        ]:
            importlib.import_module(mod)

    def test_llm_backends_removed(self):
        from src.programme_tools.vendor.dcma import narrative
        assert hasattr(narrative, "build_report_prompt")
        assert not hasattr(narrative, "stream_narrative")
        assert not hasattr(narrative, "generate_narrative")


class TestEngines:
    @pytest.fixture(scope="class")
    def files(self):
        return load_revisions()

    def test_fixtures_present(self, files):
        assert len(files) == 3

    def test_inventory_auto_baseline_current(self, files):
        from src.programme_tools.vendor.programme import build_inventory
        inv = build_inventory(files, has_contract=True)
        assert inv.baseline is not None
        assert inv.current is not None
        assert inv.baseline.data_date < inv.current.data_date
        assert len(inv.revisions) == 3

    def test_milestone_shift(self, files):
        from src.programme_tools.vendor.programme import (
            build_inventory, track_milestone_shifts,
        )
        inv = build_inventory(files)
        data_by_name = dict(files)
        revs = [(r.label, r.data_date, data_by_name[r.file_name])
                for r in inv.revisions if r.data_date is not None]
        shifts = track_milestone_shifts(revs)
        pc = next(s for s in shifts.series if s.key == "MS1000")
        assert pc.total_shift_days and pc.total_shift_days > 0  # PC slips later
        sect = next(s for s in shifts.series if s.key == "MS0500")
        assert sect.is_achieved  # sectional completion achieved in rev C

    def test_dcma_runs_14_checks(self, files):
        from src.programme_tools.vendor.dcma import run_all_checks
        _, data = files[0]
        results = run_all_checks(data)
        assert len(results) == 14
        assert all(r.status.value in ("PASS", "FAIL", "N/A") for r in results)

    def test_variance_standing_caveats(self, files):
        from src.programme_tools.vendor.programme import (
            activity_code_types, build_inventory, compute_variance,
        )
        inv = build_inventory(files)
        data_by_name = dict(files)
        base = data_by_name[inv.baseline.file_name]
        cur = data_by_name[inv.current.file_name]
        ctypes = activity_code_types(base)
        assert ctypes
        var = compute_variance(base, cur, ctypes[0].type_id, ctypes[0].name)
        zone_b = next(g for g in var.groups if g.code_value == "Zone B")
        assert zone_b.finish_delta_days and zone_b.finish_delta_days > 0
        assert var.caveats  # variance must always emit standing caveats

    def test_xlsx_builders_return_bytes(self, files):
        from src.programme_tools.vendor.dcma import run_all_checks
        from src.programme_tools.vendor.dcma.report_xlsx import build_xlsx_report
        from src.programme_tools.vendor.programme import build_inventory
        from src.programme_tools.vendor.programme.report_xlsx import build_inventory_xlsx
        _, data = files[0]
        assert build_xlsx_report(data, run_all_checks(data))[:2] == b"PK"
        assert build_inventory_xlsx(build_inventory(files))[:2] == b"PK"
