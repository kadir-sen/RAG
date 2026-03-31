import pandas as pd

from src.data_analyzer_sql import DataAnalyzerSQL
from src.table_normalizer import parse_mixed_datetime


def _register_table(
    analyzer: DataAnalyzerSQL,
    table_name: str,
    source_file: str,
    df: pd.DataFrame,
    date_range: str,
    months: list[str],
) -> None:
    tmp_name = f"tmp_{table_name}"
    analyzer.conn.register(tmp_name, df)
    analyzer.conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    analyzer.conn.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM {tmp_name}')
    analyzer.conn.unregister(tmp_name)

    info = analyzer._get_table_info(table_name)
    analyzer.tables[table_name] = {
        "file_name": source_file.split("\\")[-1],
        "file_path": source_file,
        "source_file": source_file,
        "source_type": "excel",
        "description": f"Manpower Production Log - {date_range}",
        "semantic_tags": ["manpower", "workforce", "workers", "production", "labor"],
        "header_metadata": {"target_schema": "manpower_production"},
        "insight": {"date_range": date_range, "months": months},
        **info,
    }
    analyzer.file_paths[table_name] = source_file


def _build_manpower_grouped_fixture() -> tuple[DataAnalyzerSQL, str]:
    analyzer = DataAnalyzerSQL()

    df_base = pd.DataFrame({
        "Date": ["01/02/2025", "04/25/2025"],
        "Block": ["A", "A"],
        "Floor": ["1", "1"],
        "Activity Description": ["Concrete", "Concrete"],
        "Job Description": ["Mason", "Mason"],
        "Number of Workers": [50, 45],
        "Quantification": [10.0, 9.0],
        "Unit of Measure": ["m3", "m3"],
    })
    _register_table(
        analyzer=analyzer,
        table_name="t_manpower_production_sheet1_base",
        source_file=r"C:\projects\ML_project\data\tables\Manpower Production Log.xlsx",
        df=df_base,
        date_range="January 2025 - April 2025",
        months=["2025-01", "2025-04"],
    )

    df_late = pd.DataFrame({
        "Date": ["2027-06-21 0:00:00", "2027-09-18"],
        "Block": ["B", "B"],
        "Floor": ["2", "2"],
        "Activity Description": ["Rebar", "Rebar"],
        "Job Description": ["Bar Bender", "Bar Bender"],
        "Number of Workers": [60, 58],
        "Quantification": [12.0, 11.5],
        "Unit of Measure": ["ton", "ton"],
    })
    _register_table(
        analyzer=analyzer,
        table_name="t_manpower_production_sheet1_11",
        source_file=r"C:\projects\ML_project\data\tables\Manpower Production Log 11.xlsx",
        df=df_late,
        date_range="June 2027 - September 2027",
        months=["2027-06", "2027-09"],
    )

    analyzer._create_grouped_dataset_views()
    grouped = [
        name for name, info in analyzer.tables.items()
        if info.get("is_grouped")
        and info.get("header_metadata", {}).get("target_schema") == "manpower_production"
    ]
    assert len(grouped) == 1
    return analyzer, grouped[0]


def test_parse_mixed_datetime_formats():
    series = pd.Series(["2.01.2025", "2027-06-21 0:00:00", "09/18/2027"])
    parsed = parse_mixed_datetime(series)

    assert parsed.notna().all()
    assert parsed.iloc[0].strftime("%Y-%m-%d") == "2025-01-02"
    assert parsed.iloc[1].strftime("%Y-%m-%d") == "2027-06-21"
    assert parsed.iloc[2].strftime("%Y-%m-%d") == "2027-09-18"


def test_manpower_grouped_view_selected_for_broad_query():
    analyzer, grouped_name = _build_manpower_grouped_fixture()

    selected = analyzer.select_table("show overall manpower trend across all months")
    assert selected == grouped_name


def test_grouped_view_reaches_beyond_april_2025():
    analyzer, grouped_name = _build_manpower_grouped_fixture()

    max_df = analyzer.conn.execute(
        f'SELECT MAX(TRY_CAST("Date" AS DATE)) AS max_date FROM "{grouped_name}"'
    ).fetchdf()
    assert str(max_df.iloc[0]["max_date"])[:10] == "2027-09-18"

    count_df = analyzer.conn.execute(
        f'SELECT COUNT(*) AS c FROM "{grouped_name}" '
        f'WHERE TRY_CAST("Date" AS DATE) > DATE \'2025-04-30\''
    ).fetchdf()
    assert int(count_df.iloc[0]["c"]) > 0
