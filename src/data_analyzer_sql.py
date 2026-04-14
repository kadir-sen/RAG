"""
Safe SQL-based Data Analyzer using DuckDB.
NO arbitrary Python execution from LLM - only validated SELECT queries.
Supports Parquet views for extracted tables.

Hardening features:
  - SQL generation via llm_client with caching & cost tracking
  - Pydantic schema validation on LLM SQL output
  - Lazy summary: skip LLM if result is small (<=5 rows / <=30 cells)
  - Self-correction: retry once with error feedback on SQL failure
  - Prompt injection hardening via prompt_security
  - Per-query telemetry
"""
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import duckdb
import pandas as pd

from .config import (
    GOOGLE_API_KEY, GEMINI_MODEL, MAX_UI_DISPLAY_ROWS,
    SQL_LAZY_SUMMARY_MAX_ROWS, SQL_LAZY_SUMMARY_MAX_CELLS,
)
from .logger import logger, log_separator, log_document_processing


# SQL validation patterns
DANGEROUS_PATTERNS = [
    r'\bDROP\b', r'\bDELETE\b', r'\bINSERT\b', r'\bUPDATE\b',
    r'\bCREATE\b', r'\bALTER\b', r'\bTRUNCATE\b', r'\bGRANT\b',
    r'\bREVOKE\b', r'\bEXEC\b', r'\bEXECUTE\b', r'\bCALL\b',
    r'\bATTACH\b', r'\bDETACH\b', r'\bCOPY\b', r'\bEXPORT\b',
]

MAX_UI_ROWS = MAX_UI_DISPLAY_ROWS  # For UI payload only, never injected into SQL


def sanitize_table_name(name: str) -> str:
    """Create a safe SQL table name from file name."""
    clean = Path(name).stem
    clean = re.sub(r'[^a-zA-Z0-9]', '_', clean)
    clean = re.sub(r'_+', '_', clean).strip('_')
    if clean and not clean[0].isalpha():
        clean = 't_' + clean
    return clean.lower()[:50] or 'table_data'


def canonical_dataset_key(source_file: str) -> str:
    """
    Build a stable dataset key from source filename.
    Example:
      "Manpower Production Log 11.xlsx" -> "manpower production log"
    """
    stem = Path(source_file).stem.lower()
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = re.sub(r"\s+\d+$", "", stem)  # trailing sequence suffix
    return stem


def validate_sql(sql: str) -> Tuple[bool, str]:
    """
    Validate SQL query for safety.
    Only SELECT queries (including WITH/CTE) are allowed.
    Returns (is_valid, error_message).
    """
    sql_upper = sql.upper().strip()

    # Allow SELECT and WITH...SELECT (CTEs)
    if not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')):
        return False, "Only SELECT queries are allowed"

    # WITH must contain a SELECT
    if sql_upper.startswith('WITH') and 'SELECT' not in sql_upper:
        return False, "Only SELECT queries are allowed"

    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, sql_upper):
            return False, f"Dangerous SQL pattern detected: {pattern}"

    if ';' in sql[:-1]:  # Allow trailing semicolon
        return False, "Multiple SQL statements not allowed"

    return True, ""


def _fix_unterminated_quotes(sql: str) -> str:
    """Fix unterminated double-quoted identifiers in SQL.
    Counts double quotes and adds a closing one if odd."""
    if sql.count('"') % 2 != 0:
        # Find the last double quote and close it
        last_quote = sql.rfind('"')
        # Check if the text after last quote looks like it needs closing
        after = sql[last_quote + 1:]
        # Add closing quote before the next SQL keyword or end
        for i, ch in enumerate(after):
            if ch in (' ', ',', ')', '\n', ';'):
                sql = sql[:last_quote + 1 + i] + '"' + sql[last_quote + 1 + i:]
                break
        else:
            sql = sql + '"'
    return sql


def _simple_stem(word: str) -> str:
    """Minimal stemmer for table/column matching (plural → singular)."""
    w = word.lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"  # activities → activity
    if w.endswith(("sses", "shes", "ches", "xes", "zes")):
        return w[:-2]  # processes → process, boxes → box
    if w.endswith("s") and len(w) > 3 and not w.endswith("ss"):
        return w[:-1]  # workers → worker, names → name
    return w


class DataAnalyzerSQL:
    """
    Safe data analysis using DuckDB SQL.
    Generates and validates SQL queries - never executes arbitrary code.
    Uses llm_client for all LLM calls with caching and cost tracking.
    """

    SCHEMA_SQL_HINTS = {
        "equipment_log": (
            "SCHEMA CONTEXT: Equipment Log — daily machinery deployment on a construction site.\n"
            "COLUMNS:\n"
            "- 'Date' = work date, 'Block' = building/tower identifier, 'Floor' = floor/level\n"
            "- 'Machinery Name' = equipment type (e.g. Tower Crane, Mobile Crane, Excavator, Concrete Pump, Loader, Forklift)\n"
            "- 'Estimated Machinery Hours' = operating hours (numeric float, THIS is the main metric)\n\n"
            "CONSTRUCTION ANALYTICS FORMULAS:\n"
            "- Total utilization: SUM(\"Estimated Machinery Hours\")\n"
            "- Average daily utilization: AVG(\"Estimated Machinery Hours\")\n"
            "- Utilization by equipment: GROUP BY \"Machinery Name\", SUM hours\n"
            "- Utilization by location: GROUP BY \"Block\", \"Floor\", SUM hours\n"
            "- Daily utilization rate: SUM(hours) per day — if >8 hrs/machine, indicates overtime or multiple shifts\n"
            "- Monthly trend: GROUP BY STRFTIME('%Y-%m', \"Date\"), SUM hours\n"
            "- Peak usage days: ORDER BY daily SUM DESC — identifies high-activity periods\n"
            "- Equipment idle detection: dates where a machine has 0 hours\n"
            "- Cross-block comparison: GROUP BY \"Block\" to compare equipment deployment across buildings\n\n"
            "DOMAIN KNOWLEDGE:\n"
            "- Tower cranes typically operate 8-12 hrs/day on active sites\n"
            "- Concrete pumps are used during pour days — sporadic but high hours\n"
            "- High excavator hours suggest earthwork/foundation phase\n"
            "- Multiple cranes on one block = heavy structural or MEP lifting activity\n"
        ),
        "manpower_production": (
            "SCHEMA CONTEXT: Manpower Production Log — daily workforce deployment and output.\n"
            "COLUMNS:\n"
            "- 'Date' = work date, 'Block' = building/tower, 'Floor' = floor/level\n"
            "- 'Activity Description' = construction activity (e.g. Concrete Pouring, Rebar Fixing, Formwork, Plastering)\n"
            "- 'Job Description' = worker trade/craft (e.g. Mason, Carpenter, Steel Fixer, Electrician, Plumber)\n"
            "- 'Number of Workers' = headcount deployed (integer, THIS is the workforce metric)\n"
            "- 'Quantification' = measured work output (float), 'Unit of Measure' = sqm, m3, LM, kg, nos, etc.\n\n"
            "CONSTRUCTION ANALYTICS FORMULAS:\n"
            "- Total manpower: SUM(\"Number of Workers\")\n"
            "- Manpower by trade: GROUP BY \"Job Description\", SUM(\"Number of Workers\")\n"
            "- Manpower by activity: GROUP BY \"Activity Description\", SUM(\"Number of Workers\")\n"
            "- Labor productivity: SUM(\"Quantification\") / NULLIF(SUM(\"Number of Workers\"), 0) = output per worker\n"
            "- Daily average headcount: SUM(\"Number of Workers\") / COUNT(DISTINCT \"Date\")\n"
            "- Activity distribution: what % of total workers each activity consumes\n"
            "- Trade distribution: what % of total workers each trade represents\n"
            "- Peak manpower day: GROUP BY \"Date\", ORDER BY SUM workers DESC\n"
            "- Floor-wise deployment: GROUP BY \"Floor\" to see vertical progress\n"
            "- Block comparison: GROUP BY \"Block\" to compare workforce across buildings\n\n"
            "DOMAIN KNOWLEDGE:\n"
            "- 'Steel Fixer' works on rebar/reinforcement before concrete pours\n"
            "- 'Carpenter' in construction = formwork carpenter (not furniture)\n"
            "- 'Mason' does blockwork, plastering, tiling\n"
            "- High manpower + low output = possible productivity issue\n"
            "- Typical productivity benchmarks: Concrete ~0.5-1.0 m3/worker/day, Blockwork ~3-5 sqm/worker/day\n"
            "- Rising headcount on upper floors = vertical construction progress\n"
        ),
        "ipc_sample": (
            "SCHEMA CONTEXT: IPC (Interim Progress Certificate) — contract cost and progress tracking.\n"
            "COLUMNS:\n"
            "- 'Activity Code' = BOQ/WBS line item code, 'Activity Name' = description of work item\n"
            "- 'Unit' = unit of measure (sqm, m3, LM, LS, nos)\n"
            "- 'BOQ Qty' = contract quantity, 'Unit Rate' = price per unit\n"
            "- 'Total BOQ Amount' = contract value (BOQ Qty x Unit Rate)\n"
            "- Progress: 'Previous %', 'Previous Amount' (last period), 'Current %', 'Current Amount' (this period),\n"
            "  'Cumulative %', 'Cumulative Amount' (total to date)\n"
            "- Quantities: 'Previous Qty', 'Current Qty', 'Cumulative Qty'\n\n"
            "CONSTRUCTION ANALYTICS FORMULAS:\n"
            "- Overall project progress: ROUND(SUM(\"Cumulative Amount\") / NULLIF(SUM(\"Total BOQ Amount\"), 0) * 100, 2)\n"
            "- Current period progress: ROUND(SUM(\"Current Amount\") / NULLIF(SUM(\"Total BOQ Amount\"), 0) * 100, 2)\n"
            "- Remaining value: SUM(\"Total BOQ Amount\") - SUM(\"Cumulative Amount\")\n"
            "- Remaining quantity: \"BOQ Qty\" - \"Cumulative Qty\" per activity\n"
            "- Top activities by value: ORDER BY \"Total BOQ Amount\" DESC\n"
            "- Activities with zero progress: WHERE \"Cumulative %\" = 0 OR \"Cumulative Amount\" = 0\n"
            "- Completed activities: WHERE \"Cumulative %\" >= 100\n"
            "- Near-completion (>90%): WHERE \"Cumulative %\" BETWEEN 90 AND 99.99\n"
            "- Current period top movers: ORDER BY \"Current Amount\" DESC — what progressed most this period\n"
            "- Weighted progress: each activity's contribution = (\"Cumulative Amount\" / Total BOQ) * 100\n\n"
            "DOMAIN KNOWLEDGE:\n"
            "- IPC is submitted monthly to the client/engineer for payment certification\n"
            "- 'LS' (Lump Sum) items have quantity = 1, progress measured by %\n"
            "- Activities at 0% progress may indicate not-yet-started work or blocked activities\n"
            "- Current Amount >> Previous Amount suggests acceleration\n"
            "- High BOQ Amount items are critical path drivers — delays here impact the project most\n"
        ),
    }

    SQL_GENERATION_PROMPT = (
        "You are a DuckDB SQL expert for construction project analytics.\n\n"
        "{schema_hints}\n"
        "TABLE: {table_name} ({row_count} rows)\n"
        "COLUMNS AND TYPES:\n{column_info}\n\n"
        "SAMPLE DATA (first 5 rows):\n{sample_data}\n\n"
        "{table_context}\n\n"
        "{jargon_context}\n\n"
        "{normalization_hint}\n\n"
        "DUCKDB SYNTAX RULES:\n"
        "- Date formatting: STRFTIME('%Y-%m', date_column) — format string FIRST, then column\n"
        "- Safe date cast: TRY_CAST(column AS DATE) — returns NULL on invalid values\n"
        "- Date truncation: DATE_TRUNC('month', date_column) for monthly grouping\n"
        "- Date extraction: EXTRACT(YEAR FROM date_column), EXTRACT(MONTH FROM date_column)\n"
        "- Relative dates: CURRENT_DATE - INTERVAL '1 month', DATE_TRUNC('month', CURRENT_DATE)\n"
        "- String matching: column ILIKE '%pattern%' (case-insensitive). ALWAYS use single quotes around the pattern.\n"
        "- Numeric cast: TRY_CAST(column AS DOUBLE) for strings that may be numbers\n"
        "- Safe division: use NULLIF(divisor, 0) to avoid division by zero\n"
        "- Use aggregate functions: SUM, AVG, MAX, MIN, COUNT for calculations\n"
        "- ROUND() numeric results to 2 decimal places for readability\n"
        "- Do NOT add LIMIT unless the user explicitly asks for a subset (e.g. 'top 10'). "
        "For GROUP BY / aggregation queries, always return ALL results.\n"
        "- Column names with spaces MUST be double-quoted: \"Machinery Name\"\n"
        "- If table has '_sheet_name' column, use it for period filtering:\n"
        "  WHERE \"_sheet_name\" ILIKE '%jan%' for January queries\n"
        "- If table has 'date_key' column (format: YYYY-MM), use it:\n"
        "  WHERE \"date_key\" = '2025-01' for January 2025\n"
        "- If table has 'month_num' column, use it:\n"
        "  WHERE \"month_num\" = 1 AND \"year\" = 2025\n\n"
        "ADVANCED QUERY PATTERNS:\n"
        "- DISTINCT/unique: SELECT DISTINCT col FROM table ORDER BY col\n"
        "- Period comparison: WITH jan AS (...), feb AS (...) SELECT ... FROM jan JOIN feb ...\n"
        "- Conditional aggregation: SUM(CASE WHEN cond THEN value ELSE 0 END)\n"
        "- Percentage of total: ROUND(value * 100.0 / SUM(value) OVER(), 2) AS pct\n"
        "- Running totals: SUM(value) OVER(ORDER BY date_col) AS cumulative\n"
        "- Ranking: ROW_NUMBER() OVER(ORDER BY metric DESC) or RANK()\n"
        "- Above/below average: WITH cte AS (SELECT AVG(col) AS avg_val FROM t) "
        "SELECT * FROM t, cte WHERE col > avg_val\n"
        "- CTEs (WITH clause) and subqueries are allowed and encouraged for complex queries\n\n"
        "CONSTRUCTION-SPECIFIC QUERY INTELLIGENCE:\n"
        "- 'productivity' or 'output per worker' = Quantification / NULLIF(Number of Workers, 0)\n"
        "- 'utilization' or 'utilization rate' = SUM(hours) — higher means more active\n"
        "- 'progress' = Cumulative Amount / NULLIF(Total BOQ Amount, 0) * 100\n"
        "- 'remaining' or 'balance' = Total - Cumulative (for qty or amount)\n"
        "- 'trend' = GROUP BY month/week, ORDER BY date — show how metric changes over time\n"
        "- 'comparison' or 'vs' = side-by-side values using CASE WHEN or JOIN\n"
        "- 'distribution' or 'breakdown' = GROUP BY category, show count/sum and percentage\n"
        "- 'peak' or 'busiest' = ORDER BY metric DESC LIMIT 1 (or GROUP BY date, ORDER BY SUM DESC)\n"
        "- 'idle' or 'no activity' = WHERE metric = 0 OR metric IS NULL\n"
        "- When user asks about 'Block A' or 'Block B' etc., filter with WHERE \"Block\" ILIKE '%A%'\n"
        "- When user asks about specific trades (mason, carpenter, etc.), use ILIKE for fuzzy matching\n\n"
        "{date_format_hint}\n\n"
        "QUERY RULES:\n"
        "1. ONLY generate SELECT queries\n"
        "2. Use exact table name: {table_name}\n"
        "3. Match column names EXACTLY as listed above — quote names with spaces\n"
        "4. When user mentions a concept, map it to the closest column name\n"
        "5. Return ONLY the SQL query — no explanations, no markdown\n"
        "6. PROACTIVE: Generate SQL that provides comprehensive context:\n"
        "   - For count queries: include GROUP BY breakdown\n"
        "   - For sum/total queries: include category breakdown and percentages\n"
        "   - For 'which' or 'what' queries: include relevant metrics, not just names\n"
        "   - Always ORDER BY the main metric DESC for ranking visibility\n"
        "   - Include ROUND() on all calculated columns for clean output\n\n"
        "FEW-SHOT SQL EXAMPLES:\n"
        "Q: \"How many workers by trade?\"\n"
        "SQL: SELECT \"Job Description\", SUM(\"Number of Workers\") AS total_workers "
        "FROM manpower_production_clean GROUP BY \"Job Description\" ORDER BY total_workers DESC\n\n"
        "Q: \"Equipment utilization by block in January\"\n"
        "SQL: SELECT \"Block\", \"Machinery Name\", ROUND(SUM(\"Estimated Machinery Hours\"), 2) AS total_hours "
        "FROM equipment_log_clean WHERE \"_sheet_name\" ILIKE '%jan%' "
        "GROUP BY \"Block\", \"Machinery Name\" ORDER BY total_hours DESC\n\n"
        "Q: \"Overall project progress percentage\"\n"
        "SQL: SELECT ROUND(SUM(\"Cumulative Amount\") * 100.0 / NULLIF(SUM(\"Total BOQ Amount\"), 0), 2) AS overall_progress_pct "
        "FROM ipc_sample_clean\n\n"
        "Q: \"Which activities have zero progress?\"\n"
        "SQL: SELECT \"Activity Code\", \"Activity Name\", \"Total BOQ Amount\" "
        "FROM ipc_sample_clean WHERE \"Cumulative %\" = 0 OR \"Cumulative Amount\" = 0 "
        "ORDER BY \"Total BOQ Amount\" DESC\n\n"
        "Q: \"Average daily headcount by block\"\n"
        "SQL: SELECT \"Block\", ROUND(SUM(\"Number of Workers\") * 1.0 / NULLIF(COUNT(DISTINCT \"Date\"), 0), 1) AS avg_daily_workers "
        "FROM manpower_production_clean GROUP BY \"Block\" ORDER BY avg_daily_workers DESC\n\n"
        "Q: \"Peak crane usage day\"\n"
        "SQL: SELECT \"Date\", ROUND(SUM(\"Estimated Machinery Hours\"), 2) AS total_hours "
        "FROM equipment_log_clean WHERE \"Machinery Name\" ILIKE '%crane%' "
        "GROUP BY \"Date\" ORDER BY total_hours DESC LIMIT 5\n\n"
        "NOW GENERATE SQL FOR:\n"
        "{user_query}\n\n"
        "SQL:"
    )

    SQL_RETRY_PROMPT = (
        "The previous DuckDB SQL query failed. Fix it.\n\n"
        "Previous query:\n{previous_sql}\n\n"
        "Error:\n{error}\n\n"
        "Table: {table_name}\n"
        "Columns: {columns}\n\n"
        "DUCKDB SYNTAX REMINDERS:\n"
        "- STRFTIME(format, value) — format string FIRST: STRFTIME('%Y-%m', date_col)\n"
        "- Use TRY_CAST instead of CAST for safe type conversion\n"
        "- Use WHERE TRY_CAST(col AS DATE) IS NOT NULL to filter invalid dates\n\n"
        "Return ONLY the corrected SQL query."
    )

    SUMMARY_PROMPT = (
        "You are a senior construction project data analyst presenting findings to a project manager.\n\n"
        "Question: {user_query}\n"
        "SQL Query: {sql}\n"
        "Result ({row_count} rows):\n{result_preview}\n\n"
        "Table Context:\n{table_context}\n\n"
        "{jargon_hints}\n\n"
        "ANSWER RULES:\n"
        "1. Answer in complete, professional sentences — never raw numbers or tables alone\n"
        "2. Include ALL specific values from the data — enumerate, don't just say 'there are N types'\n"
        "3. Always answer in English\n\n"
        "CONSTRUCTION CONTEXT RULES:\n"
        "4. Interpret numbers in construction context:\n"
        "   - Equipment hours: >8 hrs/day per machine = overtime/double shift. >12 hrs = unusual.\n"
        "   - Manpower: compare trades — if steel fixers outnumber carpenters, structural phase is dominant.\n"
        "   - Productivity: output/worker. Low values may indicate rework, material shortages, or access issues.\n"
        "   - IPC progress: <30% halfway through = likely behind schedule. >90% = nearing completion.\n"
        "5. For comparisons: explicitly state which is higher/lower, by how much, and what it implies.\n"
        "   Example: 'Block A deployed 245 workers vs Block B with 180 — Block A has 36% more workforce, "
        "suggesting it is in a more labor-intensive phase (likely structural or finishing).'\n"
        "6. For trends: describe the direction (increasing/decreasing/stable) and what phase it suggests.\n"
        "   Example: 'Crane hours increased from 120 in Jan to 380 in Mar — consistent with structural phase ramp-up.'\n"
        "7. Flag anomalies: sudden spikes/drops, zero values where activity is expected, "
        "unusually high/low figures compared to other blocks or periods.\n"
        "8. For distribution/breakdown: highlight the dominant item AND the least active.\n\n"
        "FORMAT RULES:\n"
        "9. When supplementary detail data is provided, incorporate it naturally\n"
        "10. Reference the source Excel file name at the end\n"
        "11. If the result has many rows (>5), summarize the top items and overall pattern "
        "rather than listing every single row\n"
        "12. Use bullet points or numbered lists for multi-item answers\n\n"
        "GOOD EXAMPLE:\n"
        "'Based on the Equipment Log, Block A recorded a total of **450 crane hours** in February 2025, "
        "the highest among all blocks. Block B followed with 320 hours (+40% less). "
        "The high crane utilization on Block A is consistent with active structural work on upper floors. "
        "Block C had only 45 hours, suggesting minimal lifting activity — likely in finishing phase. "
        "(Source: DPR_Equipment_Log_2025.xlsx)'\n\n"
        "BAD EXAMPLE: '450'\n\n"
        "MORE EXAMPLES BY SCHEMA:\n"
        "MANPOWER EXAMPLE:\n"
        "'The total workforce deployed across all blocks was **1,245 workers** in February 2025. "
        "Steel Fixers formed the largest trade group with 320 workers (25.7%), followed by Carpenters "
        "with 210 (16.9%) and Masons with 185 (14.9%). Block A had the highest deployment with 480 workers, "
        "suggesting active structural work. The average daily headcount was 62 workers, with a peak of 95 on Feb 15. "
        "(Source: Manpower_Feb_2025.xlsx)'\n\n"
        "IPC PROGRESS EXAMPLE:\n"
        "'The overall project progress stands at **43.2%** based on cumulative certified amounts. "
        "This period saw 3.8% progress (AED 2.1M certified). The top-progressing activity was "
        "\"Concrete Works\" at 67% cumulative (+5.2% this period). There are 12 activities still at 0% progress, "
        "collectively worth AED 8.5M — these should be flagged for attention. "
        "The remaining contract value is AED 31.4M. (Source: IPC_March_2025.xlsx)'\n\n"
        "Provide your answer:"
    )

    def __init__(self):
        """Initialize SQL-based data analyzer."""
        log_separator("Initializing SQL Data Analyzer")
        self.conn = duckdb.connect(':memory:')
        self.tables: Dict[str, Dict[str, Any]] = {}
        self.file_paths: Dict[str, str] = {}
        self._jargon = None
        logger.info("SQL Data Analyzer initialized (DuckDB)")

    @property
    def jargon(self):
        """Lazy-load jargon manager."""
        if self._jargon is None:
            from .jargon_manager import get_jargon_manager
            self._jargon = get_jargon_manager()
        return self._jargon

    def _get_table_info(self, table_name: str) -> Dict[str, Any]:
        """Get schema and sample data for a table."""
        try:
            cols_df = self.conn.execute(f"DESCRIBE {table_name}").fetchdf()
            columns = cols_df['column_name'].tolist()
            dtypes = dict(zip(cols_df['column_name'], cols_df['column_type']))
            sample_df = self.conn.execute(f"SELECT * FROM {table_name} LIMIT 5").fetchdf()
            row_count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

            return {
                "columns": columns,
                "dtypes": dtypes,
                "sample": sample_df,
                "row_count": row_count,
            }
        except Exception as e:
            logger.error(f"Error getting table info: {e}")
            return {}

    def _find_header_row(self, file_path: str, sheet_name: Optional[str] = None) -> int:
        """Find the actual header row in Excel (skip title/merged rows)."""
        try:
            df_preview = pd.read_excel(file_path, sheet_name=sheet_name, header=None, nrows=20)
            best_row = 0
            best_score = 0

            for idx in range(min(10, len(df_preview))):
                row = df_preview.iloc[idx]
                non_null = row.notna().sum()
                string_count = sum(1 for v in row if isinstance(v, str) and len(str(v)) > 1)
                score = non_null + string_count
                if score > best_score:
                    best_score = score
                    best_row = idx

            logger.info(f"   Detected header row: {best_row}")
            return best_row
        except Exception:
            return 0

    def _process_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process DataFrame: clean columns and handle data types."""
        df = df.dropna(how='all')

        new_columns = []
        for i, col in enumerate(df.columns):
            clean = re.sub(r'[^a-zA-Z0-9]', '_', str(col)).strip('_').lower()
            clean = re.sub(r'_+', '_', clean)
            if not clean or clean == 'nan' or clean == 'unnamed':
                clean = f"col_{i}"
            new_columns.append(clean)

        seen = {}
        final_columns = []
        for col in new_columns:
            if col in seen:
                seen[col] += 1
                final_columns.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                final_columns.append(col)

        df.columns = final_columns
        logger.info(f"   Cleaned columns: {list(df.columns)[:10]}...")

        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str).str.strip()
                df[col] = df[col].replace(['nan', 'None', 'NaN', 'NaT', ''], None)

        return df

    # ── Table normalization ─────────────────────────────────────

    def _register_normalized_views(self, table_name: str, df: pd.DataFrame):
        """
        Run table normalizer and register <table>_raw and <table>_clean views.
        Stores normalization report in self.tables[table_name].
        """
        from .table_normalizer import normalize_table, get_clean_df

        norm_df, report = normalize_table(df, table_name)

        # Register _raw (includes is_total_row, month_num, year, date_key)
        raw_name = f"{table_name}_raw"
        self.conn.execute(f"DROP TABLE IF EXISTS {raw_name}")
        self.conn.register("_tmp_raw", norm_df)
        self.conn.execute(f"CREATE TABLE {raw_name} AS SELECT * FROM _tmp_raw")
        self.conn.unregister("_tmp_raw")

        raw_info = self._get_table_info(raw_name)
        self.tables[raw_name] = {
            "file_name": self.tables.get(table_name, {}).get("file_name", ""),
            "file_path": self.file_paths.get(table_name, ""),
            "source_type": "normalized_raw",
            "is_normalized": True,
            **raw_info,
        }

        # Register _clean (totals removed)
        clean_df = get_clean_df(norm_df)
        clean_name = f"{table_name}_clean"
        self.conn.execute(f"DROP TABLE IF EXISTS {clean_name}")
        self.conn.register("_tmp_clean", clean_df)
        self.conn.execute(f"CREATE TABLE {clean_name} AS SELECT * FROM _tmp_clean")
        self.conn.unregister("_tmp_clean")

        clean_info = self._get_table_info(clean_name)
        self.tables[clean_name] = {
            "file_name": self.tables.get(table_name, {}).get("file_name", ""),
            "file_path": self.file_paths.get(table_name, ""),
            "source_type": "normalized_clean",
            "is_normalized": True,
            **clean_info,
        }

        # Store report on the base table entry
        if table_name in self.tables:
            self.tables[table_name]["normalization"] = {
                "total_rows": report.total_rows_detected,
                "months_detected": report.months_detected,
                "month_source": report.month_source,
                "clean_rows": report.clean_row_count,
                "raw_rows": report.raw_row_count,
            }

        logger.info(
            f"[Normalizer] {table_name}: "
            f"_raw({raw_info.get('row_count', 0)} rows), "
            f"_clean({clean_info.get('row_count', 0)} rows)"
        )

        # Propagate enrichment metadata to normalized views
        base_info = self.tables.get(table_name, {})
        for view_name in [raw_name, clean_name]:
            if view_name in self.tables:
                self.tables[view_name]["semantic_tags"] = base_info.get("semantic_tags", [])
                self.tables[view_name]["description"] = base_info.get("description", "")
                self.tables[view_name]["header_metadata"] = base_info.get("header_metadata", {})
                self.tables[view_name]["insight"] = base_info.get("insight", {})

    # ── Deterministic shortcut ───────────────────────────────────

    _SHORTCUT_PATTERNS = [
        # "highest/max ... month"
        (
            r'(?:highest|max|maximum|most)',
            r'(?:month)',
            "MAX",
        ),
        # "lowest/min ... month"
        (
            r'(?:lowest|min|minimum|least)',
            r'(?:month)',
            "MIN",
        ),
    ]

    # ── Proactive detail map: aggregate → supplementary detail query ──
    PROACTIVE_DETAIL_MAP = {
        "equipment_log": {
            "Machinery Name": 'SELECT DISTINCT "Machinery Name" FROM {table} ORDER BY "Machinery Name"',
            "Block": 'SELECT DISTINCT "Block" FROM {table} ORDER BY "Block"',
            "Floor": 'SELECT DISTINCT "Floor" FROM {table} ORDER BY "Floor"',
        },
        "manpower_production": {
            "Activity Description": 'SELECT DISTINCT "Activity Description" FROM {table} ORDER BY "Activity Description"',
            "Job Description": 'SELECT DISTINCT "Job Description" FROM {table} ORDER BY "Job Description"',
            "Block": 'SELECT DISTINCT "Block" FROM {table} ORDER BY "Block"',
        },
        "ipc_sample": {
            "Activity Code": 'SELECT "Activity Code", "Activity Name" FROM {table} ORDER BY "Activity Code"',
            "Activity Name": 'SELECT "Activity Code", "Activity Name" FROM {table} ORDER BY "Activity Name"',
        },
    }

    _SCHEMA_SHORTCUTS = {
        "equipment_log": [
            (r'(?:total|overall|all)\s+(?:hours|machinery\s+hours)',
             'SELECT SUM(TRY_CAST("Estimated Machinery Hours" AS DOUBLE)) AS total_hours FROM {table}'),
            (r'(?:hours|utilization)\s+(?:by|per|for\s+each)\s+block',
             'SELECT "Block", ROUND(SUM(TRY_CAST("Estimated Machinery Hours" AS DOUBLE)), 2) AS total_hours FROM {table} GROUP BY "Block" ORDER BY total_hours DESC'),
            (r'(?:hours|usage)\s+(?:by|per|for\s+each)\s+(?:machinery|equipment)|which\s+(?:machinery|equipment)',
             'SELECT "Machinery Name", ROUND(SUM(TRY_CAST("Estimated Machinery Hours" AS DOUBLE)), 2) AS total_hours FROM {table} GROUP BY "Machinery Name" ORDER BY total_hours DESC'),
            (r'how\s+many\s+blocks',
             'SELECT COUNT(DISTINCT "Block") AS block_count FROM {table}'),
            (r'how\s+many\s+(?:floors|levels)',
             'SELECT COUNT(DISTINCT "Floor") AS floor_count FROM {table}'),
            (r'how\s+many\s+(?:types?\s+of\s+)?(?:machinery|equipment)',
             'SELECT COUNT(DISTINCT "Machinery Name") AS equipment_types, LIST(DISTINCT "Machinery Name") AS equipment_list FROM {table}'),
            # Average daily utilization
            (r'(?:average|avg)\s+(?:daily)?\s*(?:hours|utilization)',
             'SELECT "Machinery Name", ROUND(AVG(TRY_CAST("Estimated Machinery Hours" AS DOUBLE)), 2) AS avg_daily_hours, COUNT(DISTINCT "Date") AS active_days FROM {table} GROUP BY "Machinery Name" ORDER BY avg_daily_hours DESC'),
            # Equipment by floor
            (r'(?:equipment|machinery)\s+(?:by|per|on)\s+(?:floor|level)',
             'SELECT "Floor", "Machinery Name", ROUND(SUM(TRY_CAST("Estimated Machinery Hours" AS DOUBLE)), 2) AS total_hours FROM {table} GROUP BY "Floor", "Machinery Name" ORDER BY "Floor", total_hours DESC'),
        ],
        "manpower_production": [
            (r'(?:total|overall|all)\s+(?:workers|manpower|headcount)',
             'SELECT SUM("Number of Workers") AS total_workers FROM {table}'),
            (r'(?:workers|manpower)\s+(?:by|per|for\s+each)\s+activity',
             'SELECT "Activity Description", SUM("Number of Workers") AS total_workers FROM {table} GROUP BY "Activity Description" ORDER BY total_workers DESC'),
            (r'(?:workers|manpower|headcount)\s+(?:by|per|for\s+each)\s+(?:trade|job|craft)',
             'SELECT "Job Description", SUM("Number of Workers") AS total_workers FROM {table} GROUP BY "Job Description" ORDER BY total_workers DESC'),
            (r'(?:production|output|quantity)\s+(?:by|per|for\s+each)\s+(?:job|trade|craft)',
             'SELECT "Job Description", ROUND(SUM(TRY_CAST("Quantification" AS DOUBLE)), 2) AS total_output, MIN("Unit of Measure") AS unit FROM {table} GROUP BY "Job Description" ORDER BY total_output DESC'),
            (r'how\s+many\s+(?:activities|types\s+of\s+(?:work|activity))',
             'SELECT COUNT(DISTINCT "Activity Description") AS activity_count FROM {table}'),
            (r'how\s+many\s+(?:types?\s+of\s+)?(?:trades?|jobs?|crafts?)',
             'SELECT COUNT(DISTINCT "Job Description") AS trade_count, LIST(DISTINCT "Job Description") AS trade_list FROM {table}'),
            # Productivity
            (r'(?:productivity|output\s+per\s+worker)',
             'SELECT "Activity Description", ROUND(SUM(TRY_CAST("Quantification" AS DOUBLE)) / NULLIF(SUM("Number of Workers"), 0), 2) AS output_per_worker, MIN("Unit of Measure") AS unit, SUM("Number of Workers") AS total_workers FROM {table} GROUP BY "Activity Description" ORDER BY output_per_worker DESC'),
            # Daily headcount
            (r'(?:daily|per\s+day)\s+(?:headcount|workers|manpower)',
             'SELECT TRY_CAST("Date" AS DATE) AS work_date, SUM("Number of Workers") AS daily_headcount FROM {table} GROUP BY work_date ORDER BY work_date'),
            # Manpower by block
            (r'(?:workers|manpower|headcount)\s+(?:by|per|for\s+each)\s+block',
             'SELECT "Block", SUM("Number of Workers") AS total_workers, COUNT(DISTINCT "Activity Description") AS activity_count FROM {table} GROUP BY "Block" ORDER BY total_workers DESC'),
            # Average daily headcount
            (r'(?:average|avg)\s+(?:daily)?\s*(?:headcount|workers)',
             'SELECT ROUND(SUM("Number of Workers") * 1.0 / NULLIF(COUNT(DISTINCT "Date"), 0), 1) AS avg_daily_headcount FROM {table}'),
        ],
        "ipc_sample": [
            (r'(?:total|overall)\s+(?:boq|contract)\s+(?:amount|value)',
             'SELECT ROUND(SUM(TRY_CAST("Total BOQ Amount" AS DOUBLE)), 2) AS total_boq_amount FROM {table}'),
            (r'(?:overall|total|project)\s+progress',
             'SELECT ROUND(SUM(TRY_CAST("Cumulative Amount" AS DOUBLE)) / NULLIF(SUM(TRY_CAST("Total BOQ Amount" AS DOUBLE)), 0) * 100, 2) AS progress_pct, ROUND(SUM(TRY_CAST("Cumulative Amount" AS DOUBLE)), 2) AS earned, ROUND(SUM(TRY_CAST("Total BOQ Amount" AS DOUBLE)), 2) AS total_contract FROM {table}'),
            (r'(?:top|biggest|largest|highest\s+value)\s+(?:activities|items)',
             'SELECT "Activity Code", "Activity Name", ROUND(TRY_CAST("Total BOQ Amount" AS DOUBLE), 2) AS amount FROM {table} ORDER BY amount DESC'),
            (r'how\s+many\s+(?:activities|items|line\s+items)',
             'SELECT COUNT(*) AS activity_count FROM {table}'),
            # Remaining work
            (r'(?:remaining|balance|left|outstanding)',
             'SELECT "Activity Code", "Activity Name", ROUND(TRY_CAST("Total BOQ Amount" AS DOUBLE) - TRY_CAST("Cumulative Amount" AS DOUBLE), 2) AS remaining_amount, ROUND(100 - TRY_CAST("Cumulative %" AS DOUBLE), 2) AS remaining_pct FROM {table} WHERE TRY_CAST("Cumulative %" AS DOUBLE) < 100 ORDER BY remaining_amount DESC'),
            # Not started activities
            (r'(?:not\s+started|zero\s+progress|pending|unstarted)',
             'SELECT "Activity Code", "Activity Name", ROUND(TRY_CAST("Total BOQ Amount" AS DOUBLE), 2) AS contract_amount FROM {table} WHERE (TRY_CAST("Cumulative %" AS DOUBLE) = 0 OR TRY_CAST("Cumulative %" AS DOUBLE) IS NULL) ORDER BY contract_amount DESC'),
            # Completed activities
            (r'(?:completed|finished|done|100\s*%)',
             'SELECT "Activity Code", "Activity Name", ROUND(TRY_CAST("Total BOQ Amount" AS DOUBLE), 2) AS contract_amount FROM {table} WHERE TRY_CAST("Cumulative %" AS DOUBLE) >= 100'),
            # Current period progress
            (r'(?:current|this)\s+(?:period|month)\s+(?:progress|work)',
             'SELECT ROUND(SUM(TRY_CAST("Current Amount" AS DOUBLE)) / NULLIF(SUM(TRY_CAST("Total BOQ Amount" AS DOUBLE)), 0) * 100, 2) AS current_period_pct, ROUND(SUM(TRY_CAST("Current Amount" AS DOUBLE)), 2) AS current_period_value FROM {table}'),
        ],
    }

    def _try_deterministic_shortcut(
        self, question: str, table_name: str, provider: str = "gemini"
    ) -> Optional[Dict[str, Any]]:
        """
        Try to answer common questions with deterministic SQL (no LLM for SQL gen).
        Summary is still generated by the specified provider's LLM.
        """
        q = question.lower()

        # 1) Month-aggregation shortcuts (require _clean table with month_num)
        clean_name = f"{table_name}_clean"
        if clean_name in self.tables:
            clean_info = self.tables[clean_name]
            if "month_num" in clean_info.get("columns", []):
                for agg_pat, dim_pat, agg_fn in self._SHORTCUT_PATTERNS:
                    if re.search(agg_pat, q) and re.search(dim_pat, q):
                        return self._run_month_shortcut(question, clean_name, agg_fn, provider=provider)

        # 2) Schema-specific shortcuts
        info = self.tables.get(table_name, {})
        target_schema = info.get("header_metadata", {}).get("target_schema", "")
        shortcuts = self._SCHEMA_SHORTCUTS.get(target_schema, [])
        for pattern, sql_template in shortcuts:
            if re.search(pattern, q):
                return self._run_schema_shortcut(
                    question, table_name, sql_template, target_schema, provider=provider
                )

        return None

    def _run_schema_shortcut(
        self, question: str, table_name: str, sql_template: str, target_schema: str,
        provider: str = "gemini"
    ) -> Optional[Dict[str, Any]]:
        """Execute a schema-specific deterministic query with provider-specific summary."""
        sql = sql_template.format(table=f'"{table_name}"')
        try:
            result_df = self.conn.execute(sql).fetchdf()
            if result_df.empty:
                return None

            # Proactive detail enrichment
            detail_df = self._generate_proactive_detail(
                question, sql, result_df, table_name
            )

            summary = self._generate_summary(question, sql, result_df,
                                             provider=provider,
                                             table_name=table_name,
                                             detail_df=detail_df)

            file_path = self.file_paths.get(table_name, '')
            from .document_rag import generate_doc_id
            sources = [{
                "type": "structured_data",
                "doc_id": generate_doc_id(file_path) if file_path else "",
                "file_name": self.tables.get(table_name, {}).get('file_name', table_name),
                "file_path": file_path,
                "table_name": table_name,
                "target_schema": target_schema,
                "sql_query": sql,
            }]

            return {
                "answer": summary,
                "sources": sources,
                "sql": sql,
                "result_data": result_df.to_dict('records'),
            }
        except Exception as e:
            logger.warning(f"   Schema shortcut failed: {e}")
            return None

    def _run_month_shortcut(
        self, question: str, clean_table: str, agg_fn: str,
        provider: str = "gemini"
    ) -> Dict[str, Any]:
        """Execute a deterministic month-aggregation query."""
        from .table_normalizer import ALL_MONTHS

        info = self.tables[clean_table]
        columns = info.get("columns", [])

        # Find the best numeric column to aggregate
        numeric_col = self._find_best_numeric_column(clean_table, question)
        if not numeric_col:
            return None  # Fall back to LLM

        month_names = {v: k.capitalize() for k, v in ALL_MONTHS.items() if len(k) > 3}
        # Deduplicate: keep English names for display
        en_month_names = {
            1: "January", 2: "February", 3: "March", 4: "April",
            5: "May", 6: "June", 7: "July", 8: "August",
            9: "September", 10: "October", 11: "November", 12: "December",
        }

        order = "DESC" if agg_fn == "MAX" else "ASC"
        sql = (
            f"SELECT month_num, SUM(TRY_CAST({numeric_col} AS DOUBLE)) AS total_value "
            f"FROM {clean_table} "
            f"WHERE month_num IS NOT NULL AND is_total_row = false "
            f"GROUP BY month_num "
            f"ORDER BY total_value {order} "
            f"LIMIT 1"
        )

        try:
            result_df = self.conn.execute(sql).fetchdf()
            if result_df.empty:
                return None

            month_num = int(result_df.iloc[0]["month_num"])
            total_val = result_df.iloc[0]["total_value"]
            month_name = en_month_names.get(month_num, str(month_num))

            label = "highest" if agg_fn == "MAX" else "lowest"
            summary = (
                f"The month with the {label} value is **{month_name}** "
                f"(month {month_num}) with a total of **{total_val:,.2f}** "
                f"for column '{numeric_col}'."
            )

            # Also get full breakdown for display
            sql_all = (
                f"SELECT month_num, SUM(TRY_CAST({numeric_col} AS DOUBLE)) AS total_value "
                f"FROM {clean_table} "
                f"WHERE month_num IS NOT NULL AND is_total_row = false "
                f"GROUP BY month_num "
                f"ORDER BY month_num"
            )
            full_df = self.conn.execute(sql_all).fetchdf()

            from .document_rag import generate_doc_id
            shortcut_fp = self.file_paths.get(clean_table, '')
            sources = [{
                "type": "structured_data",
                "doc_id": generate_doc_id(shortcut_fp) if shortcut_fp else "",
                "file_name": info.get("file_name", clean_table),
                "file_path": shortcut_fp,
                "table_name": clean_table,
                "columns_used": ["month_num", numeric_col],
                "row_count_returned": len(full_df),
                "total_rows": info.get("row_count", 0),
                "sql_query": sql_all,
            }]

            logger.info(f"[Shortcut] Deterministic answer: {month_name} = {total_val}")

            return {
                "answer": summary,
                "sources": sources,
                "sql": sql_all,
                "result_data": full_df.to_dict("records"),
                "result_columns": list(full_df.columns),
            }

        except Exception as e:
            logger.warning(f"[Shortcut] Failed: {e}")
            return None

    def _find_best_numeric_column(self, table_name: str, question: str) -> Optional[str]:
        """Find the best numeric column for aggregation based on question context."""
        info = self.tables.get(table_name, {})
        columns = info.get("columns", [])
        dtypes = info.get("dtypes", {})

        # Columns to skip
        skip = {"is_total_row", "month_num", "year", "date_key", "row_number"}

        # Prefer columns matching question words
        q_lower = question.lower()
        candidates = []
        for col in columns:
            if col in skip:
                continue
            dtype = str(dtypes.get(col, "")).upper()
            # Check if numeric type
            is_numeric = any(t in dtype for t in ["INT", "FLOAT", "DOUBLE", "DECIMAL", "BIGINT", "NUMBER"])
            if not is_numeric:
                # Try checking actual data
                try:
                    sample = self.conn.execute(
                        f"SELECT TRY_CAST({col} AS DOUBLE) FROM {table_name} LIMIT 10"
                    ).fetchdf()
                    non_null = sample.iloc[:, 0].notna().sum()
                    is_numeric = non_null >= 5
                except Exception:
                    continue

            if is_numeric:
                # Score: higher if column name words appear in question
                col_words = set(col.lower().split("_"))
                score = sum(1 for w in col_words if w in q_lower)
                candidates.append((col, score))

        if not candidates:
            return None

        # Return highest scoring, break ties with first found
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    # ── Proactive detail enrichment ──────────────────────────

    def _generate_proactive_detail(
        self, question: str, primary_sql: str, primary_df: pd.DataFrame, table_name: str
    ) -> Optional[pd.DataFrame]:
        """
        After a primary aggregate query, automatically run a supplementary detail query.
        E.g., if primary returned COUNT=10, this returns the 10 distinct values.
        Returns detail DataFrame or None.
        """
        if primary_df.empty or len(primary_df) > 3:
            return None

        # Check if result looks like an aggregate (column names contain count/total/sum/etc.)
        cols_lower = [c.lower() for c in primary_df.columns]
        agg_keywords = ('count', 'total', 'sum', 'avg', 'average', 'min_', 'max_')
        is_aggregate = any(
            any(kw in col for kw in agg_keywords) for col in cols_lower
        )
        if not is_aggregate:
            return None

        info = self.tables.get(table_name, {})
        target_schema = info.get("header_metadata", {}).get("target_schema", "")
        detail_sql = self._infer_detail_sql(primary_sql, table_name, target_schema)
        if not detail_sql:
            return None

        try:
            detail_df = self.conn.execute(detail_sql).fetchdf()
            if detail_df.empty or len(detail_df) > 50:
                return None
            logger.info(f"   [Proactive] Detail query returned {len(detail_df)} rows")
            return detail_df
        except Exception as e:
            logger.warning(f"   [Proactive] Detail query failed: {e}")
            return None

    def _infer_detail_sql(
        self, primary_sql: str, table_name: str, target_schema: str
    ) -> Optional[str]:
        """Infer a supplementary detail SQL based on the primary query and schema."""
        sql_upper = primary_sql.upper()
        detail_map = self.PROACTIVE_DETAIL_MAP.get(target_schema, {})

        for col_name, detail_template in detail_map.items():
            # Check if the column appears in the primary SQL
            col_upper = col_name.upper()
            col_quoted = f'"{col_name}"'
            if col_upper in sql_upper or col_quoted in primary_sql:
                return detail_template.format(table=f'"{table_name}"')

        return None

    def load_excel(self, file_path: str, sheet_name: Optional[str] = None) -> bool:
        """Load Excel file into DuckDB table with smart header detection."""
        path = Path(file_path)
        table_name = sanitize_table_name(path.name)

        log_document_processing(path.name, "Loading Excel to SQL...")

        try:
            header_row = self._find_header_row(file_path, sheet_name)

            if sheet_name:
                table_name = f"{table_name}_{sanitize_table_name(sheet_name)}"

            df = None
            try:
                df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)
            except Exception as e1:
                logger.warning(f"   Normal read failed: {e1}, trying with dtype=str")
                df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row, dtype=str)

            if df is None or df.empty:
                logger.error("   Empty DataFrame after reading")
                return False

            df = self._process_dataframe(df)

            self.conn.execute(f"DROP TABLE IF EXISTS {table_name}")

            try:
                self.conn.register('temp_df', df)
                self.conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM temp_df")
                self.conn.unregister('temp_df')
            except Exception as e2:
                logger.warning(f"   DuckDB create failed: {e2}, converting all to string")
                df = df.astype(str)
                df = df.replace(['nan', 'None'], None)
                self.conn.register('temp_df', df)
                self.conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM temp_df")
                self.conn.unregister('temp_df')

            info = self._get_table_info(table_name)
            self.tables[table_name] = {
                "file_name": path.name,
                "file_path": str(file_path),
                **info,
            }
            self.file_paths[table_name] = str(file_path)

            logger.info(f"   Table: {table_name}")
            logger.info(f"   Rows: {info.get('row_count', 0)}, Columns: {len(info.get('columns', []))}")

            # Register normalized _raw and _clean views
            try:
                self._register_normalized_views(table_name, df)
            except Exception as norm_err:
                logger.warning(f"   Normalization skipped: {norm_err}")

            log_document_processing(path.name, "Loaded to SQL")
            return True

        except Exception as e:
            logger.error(f"Error loading Excel: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def load_csv(self, file_path: str) -> bool:
        """Load CSV file into DuckDB table."""
        path = Path(file_path)
        table_name = sanitize_table_name(path.name)

        log_document_processing(path.name, "Loading CSV to SQL...")

        try:
            self.conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            self.conn.execute(f"""
                CREATE TABLE {table_name} AS
                SELECT * FROM read_csv_auto('{file_path.replace("'", "''")}')
            """)

            info = self._get_table_info(table_name)
            self.tables[table_name] = {
                "file_name": path.name,
                "file_path": str(file_path),
                **info,
            }
            self.file_paths[table_name] = str(file_path)

            logger.info(f"   Table: {table_name}")
            logger.info(f"   Rows: {info.get('row_count', 0)}, Columns: {len(info.get('columns', []))}")
            log_document_processing(path.name, "Loaded to SQL")
            return True

        except Exception as e:
            logger.error(f"Error loading CSV: {e}")
            return False

    def load_file(self, file_path: str) -> bool:
        """Load file based on extension."""
        ext = Path(file_path).suffix.lower()
        if ext in ['.xlsx', '.xls']:
            return self.load_excel(file_path)
        elif ext == '.csv':
            return self.load_csv(file_path)
        elif ext == '.parquet':
            return self.register_parquet_view(file_path)
        else:
            logger.warning(f"Unsupported file type: {ext}")
            return False

    def register_parquet_view(self, parquet_path: str, view_name: Optional[str] = None) -> bool:
        """Register a parquet file as a DuckDB view."""
        path = Path(parquet_path)

        if not path.exists():
            logger.error(f"[Parquet] File not found: {parquet_path}")
            return False

        if view_name is None:
            view_name = sanitize_table_name(path.name)

        log_document_processing(path.name, "Registering parquet view...")

        try:
            self.conn.execute(f"DROP VIEW IF EXISTS {view_name}")
            escaped_path = str(path).replace("'", "''").replace("\\", "/")
            self.conn.execute(f"""
                CREATE VIEW {view_name} AS
                SELECT * FROM read_parquet('{escaped_path}')
            """)

            info = self._get_table_info(view_name)
            self.tables[view_name] = {
                "file_name": path.name,
                "file_path": str(parquet_path),
                "source_type": "parquet",
                **info,
            }
            self.file_paths[view_name] = str(parquet_path)

            logger.info(f"   View: {view_name}")
            logger.info(f"   Rows: {info.get('row_count', 0)}, Columns: {len(info.get('columns', []))}")

            # Normalize parquet data for clean/raw views
            try:
                df = self.conn.execute(f"SELECT * FROM {view_name}").fetchdf()
                self._register_normalized_views(view_name, df)
            except Exception as norm_err:
                logger.warning(f"   Parquet normalization skipped: {norm_err}")

            log_document_processing(path.name, "Parquet view registered")
            return True

        except Exception as e:
            logger.error(f"[Parquet] Error registering view: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def drop_tables(self, table_names: List[str]) -> int:
        """Drop specified tables and their _raw/_clean variants from DuckDB."""
        dropped = 0
        for name in table_names:
            for variant in (name, f"{name}_raw", f"{name}_clean"):
                try:
                    self.conn.execute(f'DROP TABLE IF EXISTS "{variant}"')
                    self.tables.pop(variant, None)
                    dropped += 1
                except Exception:
                    pass
        logger.info(f"[SQL] Dropped {dropped} tables for {len(table_names)} entries")
        return dropped

    def load_from_catalog(self) -> int:
        """Load tables from the catalog as parquet views. Skips already-loaded tables."""
        try:
            from .catalog import get_catalog
            catalog = get_catalog()
            all_tables = catalog.get_all_tables()

            # Track loaded parquet paths to prevent same file under different names
            loaded_parquets = {
                info.get("parquet_path")
                for info in self.tables.values()
                if info.get("parquet_path")
            }

            count = 0
            for table_meta in all_tables:
                # Skip already loaded tables
                if table_meta.table_name in self.tables:
                    continue
                parquet_path = table_meta.parquet_path
                # Skip if same parquet already loaded under different name
                if parquet_path in loaded_parquets:
                    continue
                if not Path(parquet_path).exists():
                    logger.warning(f"[Catalog] Parquet not found: {parquet_path}")
                    continue
                if self.register_parquet_view(parquet_path, table_meta.table_name):
                    self.tables[table_meta.table_name]["source_file"] = table_meta.source_file
                    self.tables[table_meta.table_name]["source_type"] = table_meta.source_type
                    self.tables[table_meta.table_name]["extraction_method"] = table_meta.extraction_method
                    self.tables[table_meta.table_name]["parquet_path"] = parquet_path
                    self.tables[table_meta.table_name]["sheet_name"] = getattr(table_meta, 'sheet_name', '')
                    # Store enriched metadata for query routing
                    self.tables[table_meta.table_name]["description"] = getattr(table_meta, 'description', '')
                    self.tables[table_meta.table_name]["semantic_tags"] = getattr(table_meta, 'semantic_tags', [])
                    self.tables[table_meta.table_name]["header_metadata"] = getattr(table_meta, 'header_metadata', {})
                    self.tables[table_meta.table_name]["insight"] = getattr(table_meta, 'insight', {})
                    loaded_parquets.add(parquet_path)
                    count += 1

            # Only rebuild combined views if new tables were added
            if count > 0:
                self._create_combined_views()
                self._create_grouped_dataset_views()

            logger.info(f"[Catalog] Loaded {count} new tables from catalog")
            return count
        except Exception as e:
            logger.error(f"[Catalog] Error loading from catalog: {e}")
            return 0

    def _create_combined_views(self):
        """Create combined UNION ALL views for multi-sheet source files."""
        # Group tables by source file
        by_source = {}
        for table_name, info in self.tables.items():
            source = info.get('source_file', info.get('file_name', ''))
            if source and not info.get('is_combined') and not info.get('is_normalized'):
                if source not in by_source:
                    by_source[source] = []
                by_source[source].append(table_name)

        for source, table_names in by_source.items():
            if len(table_names) < 2:
                continue

            # Group tables by column signature (only combine identical schemas)
            # Use frozenset for comparison but preserve original column order
            col_groups = {}
            for tn in table_names:
                cols = frozenset(self.tables[tn].get('columns', []))
                if cols not in col_groups:
                    col_groups[cols] = []
                col_groups[cols].append(tn)

            # Create combined view for the largest compatible group
            largest_group = max(col_groups.values(), key=len)
            if len(largest_group) < 2:
                continue

            # Deduplicate: skip tables with same parquet_path
            seen_paths = set()
            unique_group = []
            for tn in largest_group:
                pp = self.tables.get(tn, {}).get("parquet_path", "")
                if pp and pp in seen_paths:
                    logger.info(f"[Combined] Skipping duplicate parquet in combined view: {tn}")
                    continue
                if pp:
                    seen_paths.add(pp)
                unique_group.append(tn)
            largest_group = unique_group
            if len(largest_group) < 2:
                continue

            view_name = sanitize_table_name(Path(source).stem) + "_combined"
            raw_cols = self.tables[largest_group[0]].get('columns', [])
            col_list = ', '.join(f'"{c}"' for c in raw_cols)

            # Preserve _sheet_name for period filtering in combined views
            union_parts = []
            for tn in largest_group:
                if '_sheet_name' in raw_cols:
                    union_parts.append(f"SELECT {col_list} FROM {tn}")
                else:
                    sheet = self.tables.get(tn, {}).get('sheet_name', tn)
                    safe_sheet = str(sheet).replace("'", "''")
                    union_parts.append(
                        f"SELECT {col_list}, '{safe_sheet}' AS \"_sheet_name\" FROM {tn}"
                    )
            unions = " UNION ALL ".join(union_parts)

            try:
                self.conn.execute(f"DROP VIEW IF EXISTS {view_name}")
                self.conn.execute(f"CREATE VIEW {view_name} AS {unions}")

                info = self._get_table_info(view_name)

                # Inherit description, tags, header_metadata from source tables
                first_info = self.tables.get(largest_group[0], {})
                base_desc = first_info.get('description', '')
                combined_tags = list(first_info.get('semantic_tags', []))
                combined_hdr = dict(first_info.get('header_metadata', {}))

                # Build combined description with date range from sheet names
                sheet_names = []
                for tn in largest_group:
                    sn = self.tables.get(tn, {}).get('sheet_name', tn)
                    if sn:
                        sheet_names.append(str(sn))
                if sheet_names:
                    combined_desc = f"{base_desc} - Sheets: {', '.join(sheet_names)}"
                else:
                    combined_desc = base_desc

                self.tables[view_name] = {
                    "file_name": f"Combined: {Path(source).name}",
                    "file_path": source,
                    "source_type": "combined",
                    "is_combined": True,
                    "source_tables": largest_group,
                    "description": combined_desc,
                    "semantic_tags": combined_tags,
                    "header_metadata": combined_hdr,
                    **info,
                }

                logger.info(
                    f"[Combined] Created view {view_name}: "
                    f"{len(largest_group)} tables, {info.get('row_count', 0)} rows"
                )
            except Exception as e:
                logger.error(f"[Combined] Error creating view: {e}")

    def _build_month_coverage(self, table_names: List[str]) -> str:
        """Build consolidated month coverage (e.g., January 2025 - September 2027)."""
        month_keys = set()
        for tn in table_names:
            insight = self.tables.get(tn, {}).get("insight", {}) or {}
            months = insight.get("months", []) or []
            for m in months:
                m_str = str(m)
                if re.match(r"^\d{4}-\d{2}$", m_str):
                    month_keys.add(m_str)

        if not month_keys:
            return ""

        first = min(month_keys)
        last = max(month_keys)

        def _fmt(month_key: str) -> str:
            dt = pd.to_datetime(f"{month_key}-01", errors="coerce")
            if pd.isna(dt):
                return month_key
            return dt.strftime("%B %Y")

        return _fmt(first) if first == last else f"{_fmt(first)} - {_fmt(last)}"

    def _create_grouped_dataset_views(self):
        """
        Create grouped UNION ALL views across multi-file datasets.
        This complements _create_combined_views() which only combines multi-sheet files.

        Grouping strategy:
        1. Primary: by target_schema (e.g. all "equipment_log" tables together)
        2. Fallback: by dataset_key + columns (for files without schema)
        """
        # First pass: group by target_schema (strongest grouping)
        schema_groups = {}
        no_schema = []
        for table_name, info in self.tables.items():
            if info.get("is_combined") or info.get("is_grouped") or info.get("is_normalized"):
                continue
            source = info.get("source_file", info.get("file_name", ""))
            if not source:
                continue
            columns = info.get("columns", [])
            if not columns:
                continue

            target_schema = (
                info.get("header_metadata", {}).get("target_schema", "") or ""
            )
            if target_schema:
                schema_groups.setdefault(target_schema, []).append(table_name)
            else:
                no_schema.append(table_name)

        # For tables with target_schema: group by schema only (ignore filename differences)
        grouped = {}
        for target_schema, table_names in schema_groups.items():
            # Find the common column set (intersection of all tables in schema)
            col_sets = {}
            for tn in table_names:
                cols = tuple(self.tables[tn].get('columns', []))
                col_sets.setdefault(cols, []).append(tn)
            # Use the largest column group
            largest_cols = max(col_sets.keys(), key=lambda c: len(col_sets[c]))
            group_key = (target_schema, target_schema, largest_cols)
            grouped[group_key] = col_sets[largest_cols]

        # For tables without schema: fall back to dataset_key + columns
        for table_name in no_schema:
            info = self.tables[table_name]
            source = info.get("source_file", info.get("file_name", ""))
            columns = info.get("columns", [])
            dataset_key = canonical_dataset_key(source)
            group_key = ("", dataset_key, tuple(columns))
            grouped.setdefault(group_key, []).append(table_name)

        for (target_schema, dataset_key, _col_sig), table_names in grouped.items():
            if len(table_names) < 2:
                continue

            # Deduplicate by parquet path to avoid accidental double registration.
            seen_paths = set()
            unique_group = []
            for tn in table_names:
                pp = self.tables.get(tn, {}).get("parquet_path", "")
                if pp and pp in seen_paths:
                    continue
                if pp:
                    seen_paths.add(pp)
                unique_group.append(tn)
            if len(unique_group) < 2:
                continue

            raw_cols = self.tables[unique_group[0]].get("columns", [])
            col_list = ", ".join(f'"{c}"' for c in raw_cols)
            has_sheet = "_sheet_name" in raw_cols
            has_source = "_source_file" in raw_cols

            union_parts = []
            for tn in unique_group:
                source_file = self.tables.get(tn, {}).get("source_file", tn)
                source_stem = Path(source_file).stem
                source_name = Path(source_file).name
                safe_stem = source_stem.replace("'", "''")
                safe_name = source_name.replace("'", "''")
                select_sql = f"SELECT {col_list}"
                if not has_sheet:
                    select_sql += f", '{safe_stem}' AS \"_sheet_name\""
                if not has_source:
                    select_sql += f", '{safe_name}' AS \"_source_file\""
                select_sql += f" FROM {tn}"
                union_parts.append(select_sql)

            view_name = sanitize_table_name(f"{dataset_key}_{target_schema}_all") + "_grouped"
            unions = " UNION ALL ".join(union_parts)

            try:
                self.conn.execute(f"DROP VIEW IF EXISTS {view_name}")
                self.conn.execute(f"CREATE VIEW {view_name} AS {unions}")
                info = self._get_table_info(view_name)

                tags = []
                for tn in unique_group:
                    tags.extend(self.tables.get(tn, {}).get("semantic_tags", []))
                tags = list(dict.fromkeys(tags))

                coverage = self._build_month_coverage(unique_group)
                display_key = dataset_key.title()
                desc = f"{display_key} - all files ({len(unique_group)} tables)"
                if coverage:
                    desc += f" - {coverage}"

                header_metadata = {
                    "target_schema": target_schema,
                    "dataset_key": dataset_key,
                    "coverage": coverage,
                    "source_file_count": str(len(unique_group)),
                }

                first_source = self.tables.get(unique_group[0], {}).get("source_file", "")
                self.tables[view_name] = {
                    "file_name": f"Grouped: {display_key}",
                    "file_path": first_source,
                    "source_file": first_source,
                    "source_type": "grouped_dataset",
                    "is_grouped": True,
                    "source_tables": unique_group,
                    "description": desc,
                    "semantic_tags": tags,
                    "header_metadata": header_metadata,
                    **info,
                }
                if first_source:
                    self.file_paths[view_name] = first_source

                logger.info(
                    f"[Grouped] Created view {view_name}: "
                    f"{len(unique_group)} tables, {info.get('row_count', 0)} rows"
                )
            except Exception as e:
                logger.error(f"[Grouped] Error creating view {view_name}: {e}")

    def refresh_from_catalog(self) -> int:
        """Refresh views from catalog."""
        return self.load_from_catalog()

    def load_files_from_folder(self, folder_path: str) -> int:
        """Load all data files from a folder."""
        count = 0
        supported = {'.xlsx', '.xls', '.csv'}
        folder = Path(folder_path)

        if not folder.exists():
            return 0

        log_separator(f"Scanning Data: {folder.name}")

        for file_path in folder.rglob("*"):
            if file_path.suffix.lower() in supported:
                if file_path.name.startswith('~$'):
                    continue
                if self.load_file(str(file_path)):
                    count += 1

        logger.info(f"Loaded {count} data files")
        return count

    def list_tables(self) -> List[str]:
        """List all loaded tables."""
        return list(self.tables.keys())

    def create_ipc_unified_view(self, table_names: List[str]) -> Optional[str]:
        """Create a unified IPC view combining all monthly sheets with a period column."""
        if len(table_names) < 2:
            return None

        union_parts = []
        for tname in table_names:
            info = self.tables.get(tname, {})
            sheet_name = info.get("sheet_name", tname)
            # Extract period label (e.g., "IPC_Jan_2025" → "Jan 2025")
            period_label = str(sheet_name).replace("IPC_", "").replace("_", " ")
            union_parts.append(
                f"SELECT *, '{period_label}' AS period FROM \"{tname}\""
            )

        unified_name = f"{table_names[0]}_unified"
        sql = f'CREATE OR REPLACE VIEW "{unified_name}" AS\n' + \
              "\nUNION ALL\n".join(union_parts)

        try:
            self.conn.execute(sql)
            info = self._get_table_info(unified_name)
            source_file = self.file_paths.get(table_names[0], "")
            self.tables[unified_name] = {
                "file_name": f"IPC Unified ({len(table_names)} periods)",
                "file_path": source_file,
                "description": "Combined IPC data across all periods with 'period' column",
                "is_combined": True,
                "source_tables": table_names,
                "header_metadata": {"target_schema": "ipc_sample"},
                **info,
            }
            self.file_paths[unified_name] = source_file
            logger.info(f"[IPC] Unified view created: {unified_name} "
                        f"({len(table_names)} sheets, {info.get('row_count', 0)} rows)")
            return unified_name
        except Exception as e:
            logger.error(f"[IPC] Unified view error: {e}")
            return None

    def get_table_summary(self, table_name: str) -> Optional[Dict[str, Any]]:
        """Get summary info for a table."""
        return self.tables.get(table_name)

    def get_all_tables_summary(self) -> str:
        """Get summary of all tables for routing, including metadata."""
        if not self.tables:
            return "No data tables loaded."

        summaries = []
        for name, info in self.tables.items():
            cols = ', '.join(info.get('columns', [])[:5])
            if len(info.get('columns', [])) > 5:
                cols += '...'
            line = f"- {name}: {info.get('row_count', 0)} rows | Columns: {cols}"

            # Add description if available
            desc = info.get('description', '')
            if desc:
                line += f"\n  Description: {desc}"

            # Add semantic tags if available
            tags = info.get('semantic_tags', [])
            if tags:
                line += f"\n  Tags: {', '.join(tags[:8])}"

            summaries.append(line)

        return '\n'.join(summaries)

    # ── Table context & column detection ──────────────────────

    def _build_table_context(self, table_name: str) -> str:
        """Build table context string from insight for LLM prompts."""
        if not table_name:
            return ""
        info = self.tables.get(table_name, {})
        parts = []

        # Source file reference
        source_file = info.get("file_name", "")
        if source_file:
            parts.append(f"SOURCE FILE: {source_file}")

        narrative = info.get("insight", {}).get("narrative", "")
        if not narrative:
            narrative = info.get("description", "")
        if narrative:
            parts.append(f"TABLE DESCRIPTION: {narrative}")

        stats = info.get("insight", {}).get("stats", {})
        if stats:
            import json
            parts.append(f"KEY STATS: {json.dumps(stats, default=str, ensure_ascii=False)}")

        return "\n".join(parts) if parts else ""

    @staticmethod
    def _fix_sql_syntax(sql: str) -> str:
        """Fix common LLM-generated SQL syntax issues before execution."""
        # Fix unterminated ILIKE/LIKE strings: '%pattern% without closing quote
        # Pattern: ILIKE '%...% at end of line or before keyword without closing '
        sql = re.sub(
            r"(I?LIKE\s+'%[^']*%)(\s*$|\s+(?:AND|OR|GROUP|ORDER|LIMIT|HAVING|\)))",
            r"\1'\2",
            sql,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        # Fix unterminated regular string literals at end of WHERE clause
        # Count single quotes - if odd, add one at the end of the last string
        lines = sql.split('\n')
        fixed_lines = []
        for line in lines:
            single_quotes = line.count("'") - line.count("\\'")
            if single_quotes % 2 != 0:
                # Find the last unclosed quote and close it
                last_q = line.rfind("'")
                if last_q >= 0:
                    line = line[:last_q + 1] + "'" + line[last_q + 1:]
            fixed_lines.append(line)
        sql = '\n'.join(fixed_lines)

        # Remove markdown code fences if LLM wrapped SQL in them
        sql = re.sub(r'^```(?:sql)?\s*', '', sql, flags=re.MULTILINE)
        sql = re.sub(r'\s*```\s*$', '', sql, flags=re.MULTILINE)

        # Fix unterminated double-quoted identifiers (column names)
        sql = _fix_unterminated_quotes(sql)

        return sql.strip()

    @staticmethod
    def _detect_key_columns(sql: str) -> list:
        """Extract key columns from SQL for highlighting (GROUP BY, WHERE, aggregates)."""
        key_cols = []
        # GROUP BY columns
        group_match = re.search(r'GROUP\s+BY\s+(.+?)(?:ORDER|LIMIT|HAVING|$)', sql, re.I)
        if group_match:
            key_cols.extend(re.findall(r'"?(\w[\w\s]*?)"?\s*(?:,|$)', group_match.group(1)))
        # WHERE columns
        where_match = re.search(r'WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|$)', sql, re.I)
        if where_match:
            key_cols.extend(re.findall(r'"?(\w+)"?\s*(?:=|LIKE|>|<|IN|BETWEEN)',
                                       where_match.group(1), re.I))
        # Aggregate columns
        agg_cols = re.findall(r'(?:SUM|AVG|MAX|MIN|COUNT)\s*\(\s*"?(\w+)"?', sql, re.I)
        key_cols.extend(agg_cols)
        return list(set(c.strip() for c in key_cols if c.strip()))

    # ── SQL generation via llm_client ─────────────────────────

    def _generate_sql(self, question: str, table_name: str, provider: str = "gemini") -> str:
        """Use llm_client to generate SQL query with jargon context."""
        from . import llm_client
        from .prompt_security import safe_render_prompt, build_system_prompt

        info = self.tables.get(table_name, {})
        columns = info.get('columns', [])
        dtypes = info.get('dtypes', {})
        row_count = info.get('row_count', 0)

        try:
            sample = self.conn.execute(f"SELECT * FROM {table_name} LIMIT 5").fetchdf()
        except Exception:
            sample = info.get('sample', pd.DataFrame())

        sample_str = sample.to_string(index=False) if not sample.empty else "No sample data"

        # Build column info with types and human-readable names
        # Quote column names with spaces for DuckDB compatibility
        column_info_parts = []
        for col in columns:
            dtype = dtypes.get(col, 'VARCHAR')
            human_name = col.replace('_', ' ').title()
            quoted = f'"{col}"' if ' ' in col else col
            column_info_parts.append(f"  - {quoted} ({dtype}) = {human_name}")
        column_info = '\n'.join(column_info_parts)

        jargon_context = self.jargon.build_column_context(columns)

        expanded_question = self.jargon.expand_query(question)
        if expanded_question != question:
            logger.info(f"   Expanded query: {expanded_question[:100]}...")

        # Build normalization hint
        normalization_hint = ""
        norm_info = info.get("normalization")
        clean_name = f"{table_name}_clean"
        if norm_info and norm_info.get("total_rows", 0) > 0:
            normalization_hint = (
                f"IMPORTANT: This table has {norm_info['total_rows']} total/subtotal rows.\n"
                f"A clean version without totals is available as: {clean_name}\n"
                f"The clean table has columns: is_total_row (bool), month_num (1-12), year (int), date_key (YYYY-MM).\n"
                f"ALWAYS prefer using {clean_name} for aggregation queries to avoid double-counting total rows.\n"
                f"Only use {table_name} if the user explicitly asks for 'total' or 'grand total' rows."
            )
        elif clean_name in self.tables:
            normalization_hint = (
                f"A normalized version is available as: {clean_name}\n"
                f"It includes columns: is_total_row (bool), month_num (1-12), year (int), date_key (YYYY-MM).\n"
                f"Prefer {clean_name} for monthly/yearly aggregation queries."
            )

        # Build table context from insight
        table_context = self._build_table_context(table_name)

        # Schema-specific hints for known formats
        target_schema = info.get("header_metadata", {}).get("target_schema", "")
        schema_hints = self.SCHEMA_SQL_HINTS.get(target_schema, "")

        # Enrich with header metadata (project name, contract value, etc.)
        header_meta = info.get("header_metadata", {})
        if header_meta:
            header_parts = []
            for k, v in header_meta.items():
                if k != "target_schema" and v:
                    header_parts.append(f"  - {k}: {v}")
            if header_parts:
                table_context += "\n\nHEADER METADATA (from Excel file headers):\n" + "\n".join(header_parts)

        # Enrich with schema column aliases and descriptions
        if target_schema:
            import json as _json
            schema_file = Path(info.get("file_path", "")).parent.parent / "storage" / "schemas" / f"{target_schema}.json"
            if not schema_file.exists():
                from .config import BASE_DIR
                schema_file = BASE_DIR / "storage" / "schemas" / f"{target_schema}.json"
            if schema_file.exists():
                try:
                    with open(schema_file, "r", encoding="utf-8") as sf:
                        schema_def = _json.load(sf)
                    alias_parts = []
                    for col_def in schema_def.get("columns", []):
                        hint = f"  - {col_def['name']}: {col_def.get('description', '')}"
                        aliases = col_def.get("aliases", [])
                        if aliases:
                            hint += f" (also known as: {', '.join(aliases)})"
                        alias_parts.append(hint)
                    if alias_parts:
                        schema_hints += "\n\nCOLUMN REFERENCE (from schema definition):\n" + "\n".join(alias_parts)
                except Exception:
                    pass

        # Detect actual date formats in sample data for date columns
        date_format_hints = []
        for col in columns:
            dtype = str(dtypes.get(col, "VARCHAR")).upper()
            is_date = any(t in dtype for t in ["DATE", "TIMESTAMP", "TIME"])
            if is_date and not sample.empty and col in sample.columns:
                sample_vals = sample[col].dropna().astype(str).head(3).tolist()
                if sample_vals:
                    date_format_hints.append(
                        f"Column \"{col}\" contains date values like: {', '.join(sample_vals)}. "
                        f"Use TRY_CAST(\"{col}\" AS DATE) for safe date filtering."
                    )
        date_format_hint = "DATE FORMAT INFO:\n" + "\n".join(date_format_hints) if date_format_hints else ""

        prompt = safe_render_prompt(
            self.SQL_GENERATION_PROMPT,
            user_query=expanded_question,
            table_name=table_name,
            row_count=str(row_count),
            column_info=column_info,
            sample_data=sample_str,
            max_rows=str(MAX_UI_ROWS),
            jargon_context=jargon_context,
            normalization_hint=normalization_hint,
            table_context=table_context,
            schema_hints=schema_hints,
            date_format_hint=date_format_hint,
        )
        system = build_system_prompt("You are a DuckDB SQL query generator. Return only valid DuckDB SQL.")

        resp = llm_client.generate_text(prompt, system=system, max_tokens=512, provider=provider)

        # Record telemetry
        from .telemetry import get_current_trace
        trace = get_current_trace()
        if trace:
            trace.record_llm_call(resp.usage)

        sql = resp.text.strip()

        # Clean up common LLM artifacts
        sql = sql.replace('```sql', '').replace('```', '').strip()
        if sql.startswith("'") or sql.startswith('"'):
            sql = sql[1:]
        if sql.endswith("'") or sql.endswith('"'):
            sql = sql[:-1]

        return sql.strip()

    def _retry_sql_generation(self, previous_sql: str, error: str, table_name: str,
                              provider: str = "gemini") -> Optional[str]:
        """Self-correct: retry SQL generation once with error feedback."""
        from . import llm_client
        from .prompt_security import build_system_prompt

        info = self.tables.get(table_name, {})
        columns = info.get('columns', [])

        prompt = self.SQL_RETRY_PROMPT.format(
            previous_sql=previous_sql,
            error=error,
            table_name=table_name,
            columns=', '.join(columns),
        )
        system = build_system_prompt("You fix broken SQL queries. Return only valid DuckDB SQL.")

        try:
            resp = llm_client.generate_text(prompt, system=system, max_tokens=512, provider=provider)

            from .telemetry import get_current_trace
            trace = get_current_trace()
            if trace:
                trace.record_llm_call(resp.usage)

            sql = resp.text.strip()
            sql = sql.replace('```sql', '').replace('```', '').strip()
            if sql.startswith("'") or sql.startswith('"'):
                sql = sql[1:]
            if sql.endswith("'") or sql.endswith('"'):
                sql = sql[:-1]

            return sql.strip()
        except Exception as e:
            logger.warning(f"   SQL retry failed: {e}")
            return None

    # ── Lazy summary ──────────────────────────────────────────

    def _should_lazy_summarize(self, result_df: pd.DataFrame) -> bool:
        """Check if result is small enough to skip LLM summary.
        We now always use LLM for richer, contextualized answers.
        Only skip LLM for truly trivial cases (empty or single scalar value).
        """
        if result_df.empty:
            return True
        # Single scalar value with no meaningful context - still use LLM
        # We want LLM to provide construction context for ALL results
        return False

    def _lazy_summary(self, question: str, sql: str, result_df: pd.DataFrame,
                      table_name: str = None, detail_df: pd.DataFrame = None) -> str:
        """Format an enhanced text summary without calling the LLM."""
        if result_df.empty:
            return "The query returned no results."

        # Get table narrative and source file for context
        narrative = ""
        source_file = ""
        if table_name:
            info = self.tables.get(table_name, {})
            narrative = info.get("insight", {}).get("narrative", "")
            if not narrative:
                narrative = info.get("description", "")
            source_file = info.get("file_name", "")

        source_tag = f"\n\n*Source: {source_file}*" if source_file else ""
        prefix = f"Based on {narrative} data, " if narrative else ""

        rows = len(result_df)
        cols = len(result_df.columns)

        # Single-column results — enumerate as bullet list
        if cols == 1 and rows > 1 and rows <= 30:
            col_name = result_df.columns[0].replace("_", " ").title()
            values = result_df.iloc[:, 0].tolist()
            bullet_list = "\n".join(f"- {v}" for v in values)
            return f"{prefix}Found {rows} {col_name} values:\n\n{bullet_list}{source_tag}"

        # Aggregate result with proactive detail
        if rows == 1 and cols == 1:
            val = result_df.iloc[0, 0]
            col = result_df.columns[0].replace("_", " ").title()
            base = f"{prefix}The value of {col} is **{val}**."
            if detail_df is not None and not detail_df.empty:
                detail_col = detail_df.columns[0].replace("_", " ").title()
                detail_values = detail_df.iloc[:, 0].tolist()
                detail_list = ", ".join(str(v) for v in detail_values[:30])
                base += f"\n\n**{detail_col} list ({len(detail_values)}):** {detail_list}"
            return base + source_tag

        if rows == 1:
            parts = [f"**{col.replace('_', ' ').title()}**: {result_df.iloc[0][col]}"
                     for col in result_df.columns]
            base = f"{prefix}" + " | ".join(parts)
            if detail_df is not None and not detail_df.empty:
                detail_col = detail_df.columns[0].replace("_", " ").title()
                detail_values = detail_df.iloc[:, 0].tolist()
                detail_list = ", ".join(str(v) for v in detail_values[:30])
                base += f"\n\n**{detail_col} list ({len(detail_values)}):** {detail_list}"
            return base + source_tag

        preview = result_df.to_string(index=False)
        return f"{prefix}Found {rows} results:\n\n```\n{preview}\n```{source_tag}"

    def _generate_summary(self, question: str, sql: str, result_df: pd.DataFrame,
                          provider: str = "gemini", table_name: str = None,
                          detail_df: pd.DataFrame = None) -> str:
        """Generate natural language summary - lazy if result is small."""
        # Lazy path: skip LLM for small results
        if self._should_lazy_summarize(result_df):
            logger.info(f"   Lazy summary ({len(result_df)} rows, {len(result_df) * len(result_df.columns)} cells)")
            return self._lazy_summary(question, sql, result_df, table_name,
                                      detail_df=detail_df)

        # LLM path for larger results
        from . import llm_client
        from .prompt_security import safe_render_prompt, build_system_prompt

        # For enumeration queries, send more data to LLM
        enum_keywords = ["how many", "list all", "types", "categories"]
        is_enum = any(kw in question.lower() for kw in enum_keywords)
        if is_enum and len(result_df) <= 50:
            preview = result_df.to_string(index=False)
        elif not result_df.empty:
            preview = result_df.head(20).to_string(index=False)
        else:
            preview = "Empty result"
        table_context = self._build_table_context(table_name) if table_name else ""
        jargon_hints = self.jargon.build_column_context(list(result_df.columns))

        # Append proactive detail data to preview
        detail_section = ""
        if detail_df is not None and not detail_df.empty:
            detail_preview = detail_df.to_string(index=False)
            detail_section = f"\n\nSUPPLEMENTARY DETAIL DATA ({len(detail_df)} rows):\n{detail_preview}"

        # Source file info
        source_file_info = ""
        if table_name:
            info = self.tables.get(table_name, {})
            sf = info.get("file_name", "")
            if sf:
                source_file_info = f"\nSource file: {sf}"

        prompt = safe_render_prompt(
            self.SUMMARY_PROMPT,
            user_query=question,
            sql=sql,
            row_count=str(len(result_df)),
            result_preview=preview + detail_section + source_file_info,
            table_context=table_context,
            jargon_hints=jargon_hints,
        )
        system = build_system_prompt("You are a construction data analyst. Provide meaningful answers.")

        resp = llm_client.generate_text(prompt, system=system, max_tokens=512, provider=provider)

        from .telemetry import get_current_trace
        trace = get_current_trace()
        if trace:
            trace.record_llm_call(resp.usage)

        return resp.text

    # ── Main query entry point ────────────────────────────────

    def query(self, question: str, table_name: Optional[str] = None,
              allowed_tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Query data using safe SQL execution.
        Self-corrects once on SQL errors.
        Uses lazy summary for small results.
        If allowed_tables is provided, only consider those tables.
        """
        log_separator("SQL Data Query")
        logger.info(f"Question: {question[:100]}...")

        if not self.tables:
            return {
                "answer": "No data tables loaded. Please upload Excel or CSV files first.",
                "sources": [],
                "sql": None,
                "result_data": None,
            }

        # Select table
        if table_name is None:
            table_name = self.select_table(question, allowed_tables=allowed_tables)

        logger.info(f"   Using table: {table_name}")
        info = self.tables.get(table_name, {})

        # Try deterministic shortcut (no LLM)
        shortcut = self._try_deterministic_shortcut(question, table_name)
        if shortcut is not None:
            logger.info("   Answered via deterministic shortcut (no LLM)")
            return shortcut

        sql = None
        try:
            # Step 1: Generate SQL
            logger.info("   Generating SQL query...")
            start_time = time.time()
            sql = self._generate_sql(question, table_name)
            gen_time = time.time() - start_time
            logger.info(f"   Generated SQL ({gen_time:.2f}s): {sql[:100]}...")

            # Step 1.5: Fix common LLM SQL issues
            sql = self._fix_sql_syntax(sql)

            # Step 2: Validate SQL
            is_valid, error = validate_sql(sql)
            if not is_valid:
                logger.warning(f"   SQL validation failed: {error}, attempting self-correction...")
                corrected = self._retry_sql_generation(sql, error, table_name)
                if corrected:
                    is_valid, error = validate_sql(corrected)
                    if is_valid:
                        sql = corrected
                        logger.info(f"   Self-corrected SQL: {sql[:100]}...")

                if not is_valid:
                    logger.error(f"   SQL validation failed after retry: {error}")
                    return {
                        "answer": f"Cannot execute this query: {error}",
                        "sources": [{"error": error}],
                        "sql": sql,
                        "result_data": None,
                    }

            # Also validate table references (include normalized views)
            from .prompt_security import validate_sql_tables
            all_known = list(self.tables.keys())
            if not validate_sql_tables(sql, all_known):
                logger.warning("   SQL references unknown tables")

            # Validate column references against actual table columns
            actual_cols = set(self.tables.get(table_name, {}).get("columns", []))
            if actual_cols:
                quoted_cols = re.findall(r'"([^"]+)"', sql)
                for qc in quoted_cols:
                    if qc not in actual_cols and qc not in self.tables:
                        close = [c for c in actual_cols if qc.lower().replace(" ", "_") == c.lower().replace(" ", "_")]
                        if close:
                            sql = sql.replace(f'"{qc}"', f'"{close[0]}"')
                            logger.info(f"   [SQL] Auto-corrected column: {qc} → {close[0]}")

            # Step 3: Execute SQL
            logger.info("   Executing SQL...")
            start_time = time.time()
            try:
                result_df = self.conn.execute(sql).fetchdf()
            except Exception as exec_err:
                # Self-correct on execution error
                logger.warning(f"   SQL execution failed: {exec_err}, attempting self-correction...")
                corrected = self._retry_sql_generation(sql, str(exec_err), table_name)
                if corrected:
                    is_valid, error = validate_sql(corrected)
                    if is_valid:
                        sql = corrected
                        result_df = self.conn.execute(sql).fetchdf()
                        logger.info(f"   Self-corrected SQL executed OK: {sql[:100]}...")
                    else:
                        logger.warning(f"   [SQL] Self-correction validation failed: {error}")
                        raise exec_err
                else:
                    logger.warning("   [SQL] Self-correction returned no result")
                    raise exec_err

            exec_time = time.time() - start_time
            logger.info(f"   Executed in {exec_time:.3f}s, returned {len(result_df)} rows")

            # Step 3.5: Proactive detail query
            detail_df = self._generate_proactive_detail(
                question, sql, result_df, table_name
            )

            # Step 4: Generate summary (lazy or LLM)
            summary = self._generate_summary(question, sql, result_df,
                                             table_name=table_name,
                                             detail_df=detail_df)

            # Detect key columns from SQL for highlighting
            highlight_columns = self._detect_key_columns(sql)

            # Build sources metadata
            source_file = info.get('source_file', info.get('file_name', table_name))
            file_path = self.file_paths.get(table_name, '')
            from .document_rag import generate_doc_id
            sources = [{
                "type": "structured_data",
                "doc_id": generate_doc_id(file_path) if file_path else "",
                "file_name": info.get('file_name', table_name),
                "source_file": source_file,
                "file_path": file_path,
                "table_name": table_name,
                "columns_used": info.get('columns', []),
                "all_columns": info.get('columns', []),
                "row_count_returned": len(result_df),
                "total_rows": info.get('row_count', 0),
                "sql_query": sql,
                "execution_time_ms": round(exec_time * 1000, 2),
                # Enhanced reference data
                "result_columns": list(result_df.columns),
                "result_preview": result_df.head(20).to_dict('records'),
                "highlight_columns": highlight_columns,
                "table_narrative": info.get("insight", {}).get("narrative", "")
                                   or info.get("description", ""),
                "target_schema": info.get("header_metadata", {}).get("target_schema", ""),
                "date_range": info.get("insight", {}).get("date_range", ""),
            }]

            return {
                "answer": summary,
                "sources": sources,
                "sql": sql,
                "result_data": result_df.to_dict('records') if len(result_df) <= 100 else result_df.head(100).to_dict('records'),
                "result_columns": list(result_df.columns),
            }

        except Exception as e:
            logger.error(f"   Query error: {e}")
            return {
                "answer": f"Error executing query: {str(e)}",
                "sources": [{"error": str(e), "table_name": table_name}],
                "sql": sql,
                "result_data": None,
            }

    def query_with_provider(self, question: str, provider: str,
                            table_name: Optional[str] = None,
                            allowed_tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """Query data using a specific LLM provider for SQL gen and summary."""
        log_separator(f"SQL Data Query ({provider})")
        logger.info(f"[{provider}] Question: {question[:100]}...")

        if not self.tables:
            return {
                "answer": "No data tables loaded. Please upload Excel or CSV files first.",
                "sources": [], "sql": None, "result_data": None,
            }

        if table_name is None:
            table_name = self.select_table(question, allowed_tables=allowed_tables)

        logger.info(f"   [{provider}] Using table: {table_name}")
        info = self.tables.get(table_name, {})

        # Try deterministic shortcut (SQL is deterministic, summary uses provider's LLM)
        shortcut = self._try_deterministic_shortcut(question, table_name, provider=provider)
        if shortcut is not None:
            logger.info(f"   [{provider}] Answered via deterministic shortcut")
            return shortcut

        sql = None
        try:
            sql = self._generate_sql(question, table_name, provider=provider)
            sql = self._fix_sql_syntax(sql)
            logger.info(f"   [{provider}] SQL: {sql[:100]}...")

            is_valid, error = validate_sql(sql)
            if not is_valid:
                corrected = self._retry_sql_generation(sql, error, table_name, provider=provider)
                if corrected:
                    is_valid, error = validate_sql(corrected)
                    if is_valid:
                        sql = corrected
                if not is_valid:
                    return {
                        "answer": f"Cannot execute this query: {error}",
                        "sources": [{"error": error}], "sql": sql, "result_data": None,
                    }

            from .prompt_security import validate_sql_tables
            if not validate_sql_tables(sql, list(self.tables.keys())):
                logger.warning(f"   [{provider}] SQL references unknown tables")

            try:
                result_df = self.conn.execute(sql).fetchdf()
            except Exception as exec_err:
                corrected = self._retry_sql_generation(sql, str(exec_err), table_name, provider=provider)
                if corrected:
                    is_valid, error = validate_sql(corrected)
                    if is_valid:
                        sql = corrected
                        result_df = self.conn.execute(sql).fetchdf()
                    else:
                        raise exec_err
                else:
                    raise exec_err

            # Proactive detail query (same as main query() path)
            detail_df = self._generate_proactive_detail(
                question, sql, result_df, table_name
            )

            summary = self._generate_summary(question, sql, result_df,
                                             provider=provider, table_name=table_name,
                                             detail_df=detail_df)

            highlight_columns = self._detect_key_columns(sql)

            from .document_rag import generate_doc_id
            file_path_p = self.file_paths.get(table_name, '')
            sources = [{
                "type": "structured_data",
                "doc_id": generate_doc_id(file_path_p) if file_path_p else "",
                "file_name": info.get('file_name', table_name),
                "file_path": file_path_p,
                "table_name": table_name,
                "columns_used": info.get('columns', []),
                "row_count_returned": len(result_df),
                "total_rows": info.get('row_count', 0),
                "sql_query": sql,
            }]

            return {
                "answer": summary,
                "sources": sources,
                "sql": sql,
                "result_data": result_df.to_dict('records') if len(result_df) <= 100 else result_df.head(100).to_dict('records'),
                "result_columns": list(result_df.columns),
                "highlight_columns": highlight_columns,
            }

        except Exception as e:
            logger.error(f"   [{provider}] Query error: {e}")
            return {
                "answer": f"Error executing query: {str(e)}",
                "sources": [{"error": str(e), "table_name": table_name}],
                "sql": sql, "result_data": None,
            }

    def query_dual(self, question: str, table_name: Optional[str] = None,
                   allowed_tables: Optional[List[str]] = None) -> dict:
        """Query with both OpenAI and Claude in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .config import LLM_PROVIDERS

        results = {}

        def _query_provider(prov):
            return prov, self.query_with_provider(question, prov, table_name, allowed_tables=allowed_tables)

        with ThreadPoolExecutor(max_workers=len(LLM_PROVIDERS)) as executor:
            futures = {executor.submit(_query_provider, p): p for p in LLM_PROVIDERS}
            for future in as_completed(futures):
                try:
                    prov, result = future.result()
                    results[prov] = result
                except Exception as e:
                    prov = futures[future]
                    logger.error(f"   [{prov}] Dual query failed: {e}")
                    results[prov] = {
                        "answer": f"Error from {prov}: {e}",
                        "sources": [], "sql": None, "result_data": None,
                    }

        return results

    def query_with_context(
        self,
        question: str,
        context: str = "",
        table_name: Optional[str] = None,
        provider: str = "gemini",
        allowed_tables: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Query data with additional context from previous steps.
        Used by the planner/executor for multi-step SQL chains.
        """
        if context:
            enriched = f"Context from previous analysis:\n{context[:500]}\n\nNew task: {question}"
            return self.query_with_provider(enriched, provider, table_name, allowed_tables=allowed_tables) if provider != "gemini" else self.query(enriched, table_name, allowed_tables=allowed_tables)
        return self.query_with_provider(question, provider, table_name, allowed_tables=allowed_tables) if provider != "gemini" else self.query(question, table_name, allowed_tables=allowed_tables)

    def get_tables_for_doc_ids(self, doc_ids: List[str]) -> List[str]:
        """Get DuckDB table names belonging to the given doc_ids."""
        from .document_rag import generate_doc_id
        matching = []
        for table_name, info in self.tables.items():
            source_file = info.get('source_file', info.get('file_path', ''))
            if source_file:
                table_doc_id = generate_doc_id(source_file)
                if table_doc_id in doc_ids:
                    matching.append(table_name)
        return matching

    TABLE_SELECTION_PROMPT = (
        "You are a table selector for a DuckDB data warehouse.\n\n"
        "USER QUESTION: {question}\n\n"
        "AVAILABLE TABLES:\n{table_descriptions}\n\n"
        "RULES:\n"
        "1. Choose the SINGLE best table that can answer the question\n"
        "2. Match column names to what the user is asking about\n"
        "3. If the question mentions a time period (month/year), prefer tables with "
        "Date, _sheet_name, date_key, or month_num columns\n"
        "4. Prefer grouped/combined views over individual tables when scope is dataset-wide\n"
        "5. Return ONLY the exact table name, nothing else\n\n"
        "TABLE NAME:"
    )

    def _select_preferred_grouped_view(
        self, question: str, search_space: Dict[str, Any]
    ) -> Optional[str]:
        """
        Deterministically prefer grouped multi-file views for broad dataset questions.
        """
        grouped = {
            name: info for name, info in search_space.items() if info.get("is_grouped")
        }
        if not grouped:
            return None

        q = question.lower()
        broad_terms = {
            "all", "overall", "trend", "history", "between", "range",
            "month", "months", "year", "years", "period", "latest", "earliest",
        }
        manpower_terms = {"manpower", "workforce", "workers", "labor"}
        wants_broad = any(t in q for t in broad_terms)

        best_name = None
        best_score = -1
        query_words = set(re.findall(r"\b\w{3,}\b", q))
        for name, info in grouped.items():
            hay = " ".join([
                name,
                info.get("file_name", ""),
                info.get("description", ""),
                " ".join(info.get("semantic_tags", [])),
                info.get("header_metadata", {}).get("target_schema", ""),
                info.get("header_metadata", {}).get("dataset_key", ""),
            ]).lower()
            hay_words = set(re.findall(r"\b\w{3,}\b", hay))

            score = len(query_words & hay_words)
            if wants_broad:
                score += 2
            if any(t in q for t in manpower_terms) and "manpower" in hay:
                score += 4
            if info.get("row_count", 0) > 0:
                score += min(3, int(info.get("row_count", 0) / 1000))

            if score > best_score:
                best_score = score
                best_name = name

        if best_name and best_score > 0 and (wants_broad or any(t in q for t in manpower_terms)):
            logger.info(f"[TableSelect] Preferred grouped view: {best_name}")
            return best_name
        return None

    def select_table(self, question: str, allowed_tables: Optional[List[str]] = None) -> Optional[str]:
        """
        Select the best table for a question.
        Strategy: LLM-based selection with heuristic fallback.
        """
        search_space = self.tables
        if allowed_tables is not None:
            search_space = {k: v for k, v in self.tables.items() if k in allowed_tables}
        if not search_space:
            return None
        if len(search_space) == 1:
            return list(search_space.keys())[0]

        # Quick check: exact table name match in question
        question_lower = question.lower()
        for name in search_space.keys():
            if name.lower() in question_lower:
                return name

        preferred_grouped = self._select_preferred_grouped_view(question, search_space)
        if preferred_grouped:
            return preferred_grouped

        # Build table descriptions for LLM
        table_descs = []
        for name, info in search_space.items():
            columns = info.get('columns', [])
            desc = info.get('description', '')
            rows = info.get('row_count', 0)
            is_combined = info.get('is_combined', False)
            is_grouped = info.get('is_grouped', False)
            combined_tag = " [COMBINED VIEW]" if is_combined else ""
            grouped_tag = " [GROUPED VIEW]" if is_grouped else ""
            col_str = ', '.join(columns[:15])
            if len(columns) > 15:
                col_str += f"... (+{len(columns)-15} more)"
            table_descs.append(
                f"- {name}{combined_tag}{grouped_tag} ({rows} rows): {desc}\n"
                f"  Columns: {col_str}"
            )
        table_descriptions = '\n'.join(table_descs)

        # LLM-based selection
        try:
            from . import llm_client
            prompt = self.TABLE_SELECTION_PROMPT.format(
                question=question,
                table_descriptions=table_descriptions,
            )
            response = llm_client.generate_text(
                prompt=prompt,
                system="You are a precise table selector. Return ONLY the table name.",
                provider="gemini",
                temperature=0.0,
                max_tokens=100,
            )
            selected = response.text.strip().strip('"').strip("'").strip('`')
            if selected in search_space:
                logger.info(f"[TableSelect] LLM selected: {selected}")
                return selected
            # Try fuzzy match (LLM might return partial name)
            for name in search_space:
                if selected.lower() in name.lower() or name.lower() in selected.lower():
                    logger.info(f"[TableSelect] LLM fuzzy match: {selected} -> {name}")
                    return name
            logger.warning(f"[TableSelect] LLM returned unknown table: {selected}")
        except Exception as e:
            logger.warning(f"[TableSelect] LLM selection failed: {e}")

        # Fallback: heuristic scoring
        return self._select_table_heuristic(question, search_space)

    def select_tables(self, question: str, max_tables: int = 3,
                      allowed_tables: Optional[List[str]] = None) -> List[str]:
        """Select multiple relevant tables for a query, ranked by relevance.
        Used for multi-table queries that may need data from several sources.
        Filters out _clean/_raw view duplicates to avoid querying same data twice.
        """
        search_space = self.tables
        if allowed_tables is not None:
            search_space = {k: v for k, v in self.tables.items() if k in allowed_tables}
        # Filter out _clean and _raw suffixed views to avoid duplicates
        base_names = set()
        filtered = {}
        for name in sorted(search_space.keys()):
            base = name
            for suffix in ("_clean", "_raw"):
                if name.endswith(suffix):
                    base = name[:-len(suffix)]
                    break
            if base not in base_names:
                base_names.add(base)
                filtered[name] = search_space[name]
        search_space = filtered

        if not search_space:
            return []
        if len(search_space) == 1:
            return list(search_space.keys())

        question_lower = question.lower()
        question_words = set(re.findall(r'\b\w{3,}\b', question_lower))
        expanded_words = set()
        for w in question_words:
            expanded_words.add(w)
            meaning = self.jargon.expand(w.upper())
            if meaning:
                expanded_words.update(meaning.lower().split())

        stemmed_query = {_simple_stem(w) for w in expanded_words}

        scored = []
        for name, info in search_space.items():
            score = 0
            columns = info.get('columns', [])
            col_words = set()
            for c in columns:
                col_words.update(c.lower().split('_'))
                col_words.update(c.lower().split())
            stemmed_cols = {_simple_stem(w) for w in col_words}
            score += len(stemmed_query & stemmed_cols)

            tags = set(info.get('semantic_tags', []))
            tag_words = set()
            for t in tags:
                tag_words.update(t.lower().split('_'))
            score += len(expanded_words & tag_words) * 3

            desc = info.get('description', '').lower()
            desc_words = set(re.findall(r'\b\w{3,}\b', desc))
            score += len(expanded_words & desc_words) * 2

            if score > 0:
                scored.append((name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scored[:max_tables]]

    def _select_table_heuristic(self, question: str, search_space: Dict[str, Any]) -> Optional[str]:
        """Fallback heuristic table selection (keyword matching)."""
        question_lower = question.lower()
        question_words = set(re.findall(r'\b\w{3,}\b', question_lower))
        expanded_words = set()
        for w in question_words:
            expanded_words.add(w)
            meaning = self.jargon.expand(w.upper())
            if meaning:
                expanded_words.update(meaning.lower().split())

        stemmed_query = {_simple_stem(w) for w in expanded_words}

        best_match = None
        best_score = 0
        for name, info in search_space.items():
            score = 0
            columns = info.get('columns', [])
            col_words = set()
            for c in columns:
                col_words.update(c.lower().split('_'))
                col_words.update(c.lower().split())
            stemmed_cols = {_simple_stem(w) for w in col_words}
            score += len(stemmed_query & stemmed_cols)

            tags = set(info.get('semantic_tags', []))
            tag_words = set()
            for t in tags:
                tag_words.update(t.lower().split('_'))
            score += len(expanded_words & tag_words) * 3

            desc = info.get('description', '').lower()
            desc_words = set(re.findall(r'\b\w{3,}\b', desc))
            score += len(expanded_words & desc_words) * 2

            if info.get('is_combined'):
                score += 2
            if info.get('is_grouped'):
                score += 4
            if score > best_score:
                best_score = score
                best_match = name

        if best_match and best_score > 0:
            return best_match

        for name, info in search_space.items():
            if info.get('is_grouped'):
                return name
        for name, info in search_space.items():
            if info.get('is_combined'):
                return name

        # Fallback: select the table with the most rows
        return max(search_space.keys(), key=lambda n: self.tables.get(n, {}).get("row_count", 0))

    def execute_raw_sql(self, sql: str) -> Tuple[Optional[pd.DataFrame], str]:
        """Execute raw SQL with validation."""
        is_valid, error = validate_sql(sql)
        if not is_valid:
            return None, error

        try:
            result = self.conn.execute(sql).fetchdf()
            return result, ""
        except Exception as e:
            return None, str(e)


# Singleton
_data_analyzer: Optional[DataAnalyzerSQL] = None


def get_data_analyzer() -> DataAnalyzerSQL:
    """Get or create DataAnalyzerSQL singleton."""
    global _data_analyzer
    if _data_analyzer is None:
        _data_analyzer = DataAnalyzerSQL()
    return _data_analyzer
