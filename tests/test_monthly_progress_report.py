"""monthly_progress_report workflow + the metric catalogue behind it.

Uses a real in-memory DuckDB so execute_raw_sql (and the SQL guards it runs)
are exercised for real; only the analyzer singleton and the corpus lookup are
substituted.
"""

import duckdb
import pandas as pd
import pytest

from backend.models.blocks import validate_blocks
from src.workflows import metrics
from src.workflows.adapters import monthly_progress_report as mpr
from src.workflows.types import (RESULT_PARTIAL, RESULT_SUCCESS,
                                 RESULT_UNAVAILABLE)

MANPOWER = pd.DataFrame({
    "Date": ["2025-01-05", "2025-01-06", "2025-02-05", "2025-02-06"],
    "Block": ["A", "B", "A", "B"],
    "Job Description": ["Mason", "Carpenter", "Mason", "Carpenter"],
    "Number of Workers": [10, 5, 20, 4],
    "Quantification": [100.0, 50.0, 200.0, 40.0],
})
EQUIPMENT = pd.DataFrame({
    "Date": ["2025-01-05", "2025-02-05"],
    "Block": ["A", "B"],
    "Machinery Name": ["Crane", "Excavator"],
    "Estimated Machinery Hours": [8.0, 6.0],
})
IPC_JAN = pd.DataFrame({
    "Activity Name": ["Blockwork", "Tiling"],
    "Cumulative Amount": [1000.0, 500.0],
})
IPC_FEB = pd.DataFrame({
    "Activity Name": ["Blockwork", "Tiling"],
    "Cumulative Amount": [3000.0, 1500.0],   # cumulative: includes January
})


class FakeAnalyzer:
    """Real DuckDB, hand-built catalogue. _clean views carry the normalizer's
    derived columns (date_key/is_total_row), as the real ones do."""

    def __init__(self):
        self.conn = duckdb.connect(":memory:")
        self.tables = {}

    def add(self, name, df, schema, date_key=None, clean=True):
        self.conn.register("_t", df)
        self.conn.execute(f'CREATE TABLE "{name}" AS SELECT * FROM _t')
        self.conn.unregister("_t")
        self.tables[name] = {
            "columns": list(df.columns), "row_count": len(df),
            "corpus": "demo", "source_file": f"/data/{name}.xlsx",
            "header_metadata": {"target_schema": schema},
        }
        if not clean:
            return
        cdf = df.copy()
        cdf["is_total_row"] = False
        if date_key is not None:
            cdf["date_key"] = date_key
        else:
            cdf["date_key"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m")
        self.conn.register("_c", cdf)
        self.conn.execute(f'CREATE TABLE "{name}_clean" AS SELECT * FROM _c')
        self.conn.unregister("_c")
        self.tables[f"{name}_clean"] = {
            "columns": list(cdf.columns), "row_count": len(cdf),
            "corpus": "demo", "source_type": "normalized_clean",
        }

    def get_tables_for_corpus(self, corpus):
        return None

    def execute_raw_sql(self, sql):
        from src.data_analyzer_sql import validate_sql
        ok, err = validate_sql(sql)
        if not ok:
            return None, err
        try:
            return self.conn.execute(sql).fetchdf(), ""
        except Exception as e:
            return None, str(e)


def _install(monkeypatch, analyzer):
    monkeypatch.setattr("src.data_analyzer_sql.get_data_analyzer",
                        lambda: analyzer)
    monkeypatch.setattr("src.workflows.adapters.monthly_progress_report."
                        "corpus_id", lambda: "demo")
    monkeypatch.setattr("src.learning.schema_memory.pending_confirmations",
                        lambda c=None: [])


@pytest.fixture
def full(monkeypatch):
    a = FakeAnalyzer()
    a.add("manpower_1", MANPOWER, "manpower_production")
    a.add("equipment_1", EQUIPMENT, "equipment_log")
    a.add("ipc_jan", IPC_JAN, "ipc_sample", date_key="2025-01")
    a.add("ipc_feb", IPC_FEB, "ipc_sample", date_key="2025-02")
    _install(monkeypatch, a)
    return a


def _tables(wr):
    return {b.get("title", ""): b for b in wr.blocks if b["type"] == "data_table"}


def _guards(wr):
    for b in wr.blocks:
        if b["type"] == "validation_status":
            return b
    return {}


def _caveats(wr):
    for b in wr.blocks:
        if b["type"] == "caveats":
            return b.get("caveats", [])
    return []


class TestMetricWhitelist:
    """The LLM cannot name a metric; only ids in _METRICS produce SQL."""

    def test_unknown_metric_returns_reason_not_sql(self, full):
        table, reason = metrics.run_metric("'; DROP TABLE x; --", "demo")
        assert table is None
        assert "unknown metric" in reason

    def test_every_registered_metric_is_runnable_or_explains_itself(self, full):
        for mid in metrics.metric_ids():
            table, reason = metrics.run_metric(mid, "demo")
            assert table is not None or reason, f"{mid} failed silently"


class TestMetrics:
    def test_manpower_by_trade_sums_across_months(self, full):
        table, _ = metrics.run_metric("manpower_by_trade", "demo")
        rows = dict((r[0], r[1]) for r in table["rows"])
        assert rows == {"Mason": 30.0, "Carpenter": 9.0}

    def test_period_filter_narrows_to_that_month(self, full):
        table, _ = metrics.run_metric("manpower_by_trade", "demo",
                                      period={"date_key": "2025-02"})
        rows = dict((r[0], r[1]) for r in table["rows"])
        assert rows == {"Mason": 20.0, "Carpenter": 4.0}
        assert "2025-02" in table["title"]

    def test_monthly_metric_is_ordered_by_period(self, full):
        table, _ = metrics.run_metric("manpower_by_month", "demo")
        assert [r[0] for r in table["rows"]] == ["2025-01", "2025-02"]

    def test_ipc_reads_only_the_latest_certificate(self, full):
        """Cumulative-to-date figures must not be added across certificates —
        February already contains January."""
        table, _ = metrics.run_metric("ipc_cumulative_by_activity", "demo")
        rows = dict((r[0], r[1]) for r in table["rows"])
        assert rows == {"Blockwork": 3000.0, "Tiling": 1500.0}
        assert sum(rows.values()) == 4500.0      # not 1500+4500 = 6000
        assert "2025-02" in table["title"]

    def test_ipc_refuses_when_two_certificates_share_the_latest_period(
            self, monkeypatch):
        a = FakeAnalyzer()
        a.add("ipc_feb_a", IPC_FEB, "ipc_sample", date_key="2025-02")
        a.add("ipc_feb_b", IPC_FEB, "ipc_sample", date_key="2025-02")
        _install(monkeypatch, a)
        table, reason = metrics.run_metric("ipc_cumulative_by_activity", "demo")
        assert table is None
        assert "supersedes" in reason

    def test_missing_schema_reports_a_reason(self, monkeypatch):
        a = FakeAnalyzer()
        a.add("manpower_1", MANPOWER, "manpower_production")
        _install(monkeypatch, a)
        table, reason = metrics.run_metric("equipment_hours_by_block", "demo")
        assert table is None
        assert "equipment log" in reason

    def test_monthly_metric_needs_the_clean_view(self, monkeypatch):
        a = FakeAnalyzer()
        a.add("manpower_1", MANPOWER, "manpower_production", clean=False)
        _install(monkeypatch, a)
        table, reason = metrics.run_metric("manpower_by_month", "demo")
        assert table is None
        assert "date column" in reason
        # ...but a non-dated metric still works off the base table.
        assert metrics.run_metric("manpower_by_trade", "demo")[0] is not None


class TestDataInventory:
    def test_summarises_one_row_per_schema(self, full):
        table, _ = metrics.data_inventory("demo")
        assert [r[0] for r in table["rows"]] == [
            "equipment log", "ipc sample", "manpower production"]
        ipc = [r for r in table["rows"] if r[0] == "ipc sample"][0]
        assert ipc[2] == 2                       # two IPC tables
        assert ipc[4] == "2025-01 → 2025-02"

    def test_flags_tables_awaiting_schema_confirmation(self, full, monkeypatch):
        monkeypatch.setattr("src.learning.schema_memory.pending_confirmations",
                            lambda c=None: ["a", "b"])
        _, caveats = metrics.data_inventory("demo")
        assert any("awaiting schema confirmation" in c for c in caveats)


class TestReport:
    def test_full_data_produces_charts_tables_and_passes_guards(self, full):
        wr = mpr.run("Generate the monthly progress report.")
        assert wr.status == RESULT_SUCCESS
        charts = [b for b in wr.blocks if b["type"] == "chart"]
        assert any(c["chart_type"] == "bar" for c in charts)
        assert any(c["chart_type"] == "line" for c in charts)
        assert _guards(wr)["guards"]["chart_guard"] == "passed"
        assert _guards(wr)["fallbacks_used"] == []
        assert "Project data inventory" in _tables(wr)

    def test_partial_when_a_schema_is_missing(self, monkeypatch):
        a = FakeAnalyzer()
        a.add("manpower_1", MANPOWER, "manpower_production")
        _install(monkeypatch, a)
        wr = mpr.run("Generate the monthly progress report.")
        assert wr.status == RESULT_PARTIAL
        assert any("equipment log" in c for c in _caveats(wr))
        # The sections that do have data still render.
        assert "Manpower by trade" in _tables(wr)

    def test_unavailable_when_no_reportable_data(self, monkeypatch):
        _install(monkeypatch, FakeAnalyzer())
        wr = mpr.run("Generate the monthly progress report.")
        assert wr.status == RESULT_UNAVAILABLE
        assert wr.substitute == "preliminary_programme_pack"

    def test_chart_guard_failure_keeps_the_table(self, full, monkeypatch):
        monkeypatch.setattr(
            "src.workflows.adapters.monthly_progress_report.chart_guard",
            lambda *a, **k: ["values diverge from source data"])
        wr = mpr.run("Generate the monthly progress report.")
        assert _guards(wr)["guards"]["chart_guard"] == "failed"
        assert _guards(wr)["fallbacks_used"]
        assert not [b for b in wr.blocks if b["type"] == "chart"]
        assert "Manpower by trade" in _tables(wr)      # data survives

    def test_progress_is_never_presented_as_entitlement(self, full):
        wr = mpr.run("Generate the monthly progress report.")
        assert any("not an assessment of delay" in c for c in _caveats(wr))

    def test_ipc_caveat_states_the_real_limitation(self, full):
        wr = mpr.run("Generate the monthly progress report.")
        assert any("latest certificate only" in c for c in _caveats(wr))

    def test_period_in_query_is_applied(self, full):
        wr = mpr.run("monthly progress report for February 2025")
        assert "2025-02" in wr.answer
        assert any("2025-02" in t for t in _tables(wr))


class TestBlockContract:
    def test_every_block_survives_the_response_guard(self, full):
        wr = mpr.run("Generate the monthly progress report.")
        valid, dropped = validate_blocks(wr.blocks)
        assert dropped == []
        assert len(valid) == len(wr.blocks)

    def test_no_clarification_block_can_reach_a_multi_section_report(self, full):
        """clarification is exclusive — one would delete the whole report."""
        wr = mpr.run("Generate the monthly progress report.")
        assert not [b for b in wr.blocks if b["type"] == "clarification"]

    def test_unavailable_result_also_honours_the_contract(self, monkeypatch):
        _install(monkeypatch, FakeAnalyzer())
        wr = mpr.run("Generate the monthly progress report.")
        assert validate_blocks(wr.blocks)[1] == []
