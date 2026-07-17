"""SQL-path safety guards. This file gates the deploy (see deploy.yml).

Threat model: the LLM writes the SQL, and the prompt it writes from contains
untrusted material — uploaded file names and sample cell values reach the model
via _build_table_context. So a crafted spreadsheet is an indirect
prompt-injection channel into SQL generation.

DuckDB serves file and network reads as *table functions*
(read_csv_auto/read_parquet/glob/...), which means they are reachable from a
plain SELECT and would sail past a mutation-only denylist. Two independent
layers stop that here:

  1. validate_sql       — keyword denylist, scanned on literal-stripped SQL
  2. find_table_violation — every FROM/JOIN target must be a known table

Either layer alone blocks the exploit; both are tested alone.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_analyzer_sql import validate_sql
from src.prompt_security import (TABLE_FUNCTION, UNKNOWN_TABLE,
                                 find_table_violation, strip_sql_literals,
                                 validate_sql_tables)

# The exploit: each of these reads a file or calls out to the network, and each
# one is a syntactically valid SELECT.
EXPLOITS = [
    "SELECT * FROM read_csv_auto('/etc/passwd')",
    "SELECT * FROM read_csv('/app/.env')",
    "SELECT * FROM read_parquet('https://attacker.example/x.parquet')",
    "SELECT * FROM read_json_auto('/app/.env.production')",
    "SELECT * FROM read_text('/etc/passwd')",
    "SELECT * FROM read_blob('/etc/passwd')",
    "SELECT * FROM glob('/etc/*')",
]

ALLOWED = ['manpower_production', 'equipment_log']


class TestDenylistLayer:
    """Layer 1: validate_sql keyword denylist."""

    @pytest.mark.parametrize('sql', EXPLOITS)
    def test_file_read_rejected(self, sql):
        valid, err = validate_sql(sql)
        assert valid is False, f'exploit passed validate_sql: {sql}'
        assert err

    @pytest.mark.parametrize('sql', [
        'DROP TABLE t', 'DELETE FROM t', 'INSERT INTO t VALUES (1)',
        'UPDATE t SET x=1', 'ATTACH \'x.db\'', 'COPY t TO \'/tmp/x.csv\'',
        'INSTALL httpfs', 'SELECT 1; DROP TABLE t',
    ])
    def test_mutation_and_extension_rejected(self, sql):
        assert validate_sql(sql)[0] is False


class TestNoFalsePositives:
    """Construction data is full of words the denylist scans for. Scanning raw
    SQL would reject valid reporting queries — the scan runs on structure only.
    """

    @pytest.mark.parametrize('sql', [
        'SELECT "Progress Update" FROM manpower_production',
        'SELECT "Update Date", "Load Date" FROM equipment_log',
        'SELECT "Drop Zone" FROM equipment_log',
        "SELECT * FROM manpower_production WHERE note = 'please update it'",
        "SELECT * FROM manpower_production WHERE x = 'a;b'",
        'SELECT * FROM manpower_production -- copy of the old query',
        'WITH m AS (SELECT 1) SELECT * FROM m',
        'SELECT * FROM manpower_production; ',
    ])
    def test_valid_query_accepted(self, sql):
        valid, err = validate_sql(sql)
        assert valid is True, f'false positive: {sql} -> {err}'


class TestTableGuardLayer:
    """Layer 2: table-reference guard. Blocks the exploit on its own."""

    @pytest.mark.parametrize('sql', EXPLOITS)
    def test_exploit_flagged_as_table_function(self, sql):
        violation = find_table_violation(sql, ALLOWED)
        assert violation is not None, f'exploit passed table guard: {sql}'
        assert violation[0] == TABLE_FUNCTION

    @pytest.mark.parametrize('sql', [
        'SELECT * FROM manpower_production',
        'SELECT * FROM manpower_production m JOIN equipment_log e ON 1=1',
        'SELECT * FROM "manpower_production"',
        'SELECT * FROM (SELECT * FROM manpower_production) t',
        # CTE names are locally defined, not tables. Enforcing without this
        # would reject every WITH query the model writes.
        'WITH m AS (SELECT 1) SELECT * FROM m',
        'WITH RECURSIVE r AS (SELECT 1) SELECT * FROM r',
        'WITH a AS (SELECT 1), b AS (SELECT 2) SELECT * FROM a JOIN b ON 1=1',
        # Table refs come from SQL structure, never from data.
        "SELECT 'FROM secrets' AS note FROM manpower_production",
        'SELECT * FROM manpower_production -- FROM secrets',
    ])
    def test_legitimate_query_allowed(self, sql):
        assert find_table_violation(sql, ALLOWED) is None, f'blocked: {sql}'

    def test_unknown_table_is_retryable_not_hostile(self):
        """A hallucinated name is a syntax slip the self-correction retry
        fixes; conflating it with an attack would regress that path."""
        violation = find_table_violation('SELECT * FROM manpwoer', ALLOWED)
        assert violation is not None
        assert violation[0] == UNKNOWN_TABLE

    def test_validate_sql_tables_wrapper(self):
        assert validate_sql_tables('SELECT * FROM manpower_production', ALLOWED)[0] is True
        ok, reason = validate_sql_tables(EXPLOITS[0], ALLOWED)
        assert ok is False and 'read_csv_auto' in reason


class TestStripSqlLiterals:
    def test_masks_string_literals(self):
        assert 'secrets' not in strip_sql_literals("SELECT 'secrets' FROM t")

    def test_keeps_identifiers_by_default(self):
        assert 'Progress Update' in strip_sql_literals('SELECT "Progress Update" FROM t')

    def test_masks_identifiers_on_request(self):
        out = strip_sql_literals('SELECT "Progress Update" FROM t',
                                 mask_identifiers=True)
        assert 'Progress Update' not in out

    def test_masks_comments(self):
        assert 'secrets' not in strip_sql_literals('SELECT 1 -- secrets')
        assert 'secrets' not in strip_sql_literals('SELECT 1 /* secrets */')

    def test_handles_escaped_quotes(self):
        # '' is an escaped quote inside a literal, not a literal boundary.
        assert 'DROP' not in strip_sql_literals("SELECT 'it''s a DROP' FROM t")


class TestExecuteCheckedIsTheOnlyDoor:
    """The guard sits at execution, not just after generation, because the
    column auto-correction rewrites `sql` after validate_sql has run."""

    @pytest.fixture
    def analyzer(self):
        import duckdb
        import pandas as pd

        from src.data_analyzer_sql import DataAnalyzerSQL

        a = DataAnalyzerSQL.__new__(DataAnalyzerSQL)  # skip real __init__
        a.conn = duckdb.connect(':memory:')
        a.tables = {}
        a.file_paths = {}
        a._jargon = None
        df = pd.DataFrame({'Job Description': ['Mason', 'Carpenter'],
                           'Number of Workers': [10, 5],
                           'Progress Update': ['ok', 'late']})
        a.conn.register('tmp', df)
        a.conn.execute('CREATE TABLE manpower AS SELECT * FROM tmp')
        a.tables['manpower'] = {'columns': list(df.columns)}
        return a

    @pytest.mark.parametrize('sql', EXPLOITS)
    def test_exploit_refused(self, analyzer, sql):
        from src.data_analyzer_sql import UnsafeSqlError
        with pytest.raises(UnsafeSqlError):
            analyzer._execute_checked(sql)

    @pytest.mark.parametrize('sql', [
        'SELECT * FROM manpower',
        'WITH t AS (SELECT * FROM manpower) SELECT COUNT(*) FROM t',
        'SELECT "Progress Update" FROM manpower',
        'SELECT "Job Description", SUM("Number of Workers") FROM manpower GROUP BY 1',
    ])
    def test_legitimate_query_runs(self, analyzer, sql):
        assert analyzer._execute_checked(sql) is not None

    def test_unknown_table_raises_retryable_error(self, analyzer):
        from src.data_analyzer_sql import UnsafeSqlError
        with pytest.raises(Exception) as exc:
            analyzer._execute_checked('SELECT * FROM manpwoer')
        assert not isinstance(exc.value, UnsafeSqlError)

    def test_allowed_tables_can_be_narrowed(self, analyzer):
        """Callers holding a corpus-scoped list can pass it in."""
        from src.data_analyzer_sql import UnsafeSqlError
        with pytest.raises(Exception) as exc:
            analyzer._execute_checked('SELECT * FROM manpower',
                                      allowed_tables=['other_table'])
        assert not isinstance(exc.value, UnsafeSqlError)
