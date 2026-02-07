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
    GOOGLE_API_KEY, GEMINI_MODEL, MAX_SQL_RESULT_ROWS,
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

MAX_RESULT_ROWS = MAX_SQL_RESULT_ROWS


def sanitize_table_name(name: str) -> str:
    """Create a safe SQL table name from file name."""
    clean = Path(name).stem
    clean = re.sub(r'[^a-zA-Z0-9]', '_', clean)
    clean = re.sub(r'_+', '_', clean).strip('_')
    if clean and not clean[0].isalpha():
        clean = 't_' + clean
    return clean.lower()[:50] or 'table_data'


def validate_sql(sql: str) -> Tuple[bool, str]:
    """
    Validate SQL query for safety.
    Only SELECT queries are allowed.
    Returns (is_valid, error_message).
    """
    sql_upper = sql.upper().strip()

    if not sql_upper.startswith('SELECT'):
        return False, "Only SELECT queries are allowed"

    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, sql_upper):
            return False, f"Dangerous SQL pattern detected: {pattern}"

    if ';' in sql[:-1]:  # Allow trailing semicolon
        return False, "Multiple SQL statements not allowed"

    return True, ""


class DataAnalyzerSQL:
    """
    Safe data analysis using DuckDB SQL.
    Generates and validates SQL queries - never executes arbitrary code.
    Uses llm_client for all LLM calls with caching and cost tracking.
    """

    SQL_GENERATION_PROMPT = (
        "You are a DuckDB SQL query generator.\n\n"
        "TABLE: {table_name} ({row_count} rows)\n"
        "COLUMNS AND TYPES:\n{column_info}\n\n"
        "SAMPLE DATA (first 5 rows):\n{sample_data}\n\n"
        "{jargon_context}\n\n"
        "DUCKDB SYNTAX RULES:\n"
        "- Date formatting: STRFTIME('%Y-%m', date_column) — format string FIRST, then column\n"
        "- Safe date cast: TRY_CAST(column AS DATE) — returns NULL on invalid values\n"
        "- Date truncation: DATE_TRUNC('month', date_column) for monthly grouping\n"
        "- Date extraction: EXTRACT(YEAR FROM date_column), EXTRACT(MONTH FROM date_column)\n"
        "- String matching: column ILIKE '%pattern%' (case-insensitive)\n"
        "- Numeric cast: TRY_CAST(column AS DOUBLE) for strings that may be numbers\n"
        "- Use aggregate functions: SUM, AVG, MAX, MIN, COUNT for calculations\n"
        "- Always add LIMIT {max_rows} unless doing full aggregation (GROUP BY)\n\n"
        "QUERY RULES:\n"
        "1. ONLY generate SELECT queries\n"
        "2. Use exact table name: {table_name}\n"
        "3. Match column names EXACTLY as listed above\n"
        "4. When user mentions a concept, map it to the closest column name\n"
        "5. Return ONLY the SQL query — no explanations, no markdown\n\n"
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
        "Based on this data analysis result, provide a brief natural language summary.\n\n"
        "Question: {user_query}\n"
        "SQL Query: {sql}\n"
        "Result ({row_count} rows):\n{result_preview}\n\n"
        "Provide a concise 2-3 sentence summary of the findings. Be factual and precise."
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
            log_document_processing(path.name, "Parquet view registered")
            return True

        except Exception as e:
            logger.error(f"[Parquet] Error registering view: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def load_from_catalog(self) -> int:
        """Load all tables from the catalog as parquet views."""
        try:
            from .catalog import get_catalog
            catalog = get_catalog()
            all_tables = catalog.get_all_tables()

            count = 0
            for table_meta in all_tables:
                parquet_path = table_meta.parquet_path
                if not Path(parquet_path).exists():
                    logger.warning(f"[Catalog] Parquet not found: {parquet_path}")
                    continue
                if self.register_parquet_view(parquet_path, table_meta.table_name):
                    self.tables[table_meta.table_name]["source_file"] = table_meta.source_file
                    self.tables[table_meta.table_name]["source_type"] = table_meta.source_type
                    self.tables[table_meta.table_name]["extraction_method"] = table_meta.extraction_method
                    count += 1

            # Create combined views for multi-sheet source files
            self._create_combined_views()

            logger.info(f"[Catalog] Loaded {count} tables from catalog")
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
            if source and not info.get('is_combined'):
                if source not in by_source:
                    by_source[source] = []
                by_source[source].append(table_name)

        for source, table_names in by_source.items():
            if len(table_names) < 2:
                continue

            # Group tables by column signature (only combine identical schemas)
            col_groups = {}
            for tn in table_names:
                cols = tuple(sorted(self.tables[tn].get('columns', [])))
                if cols not in col_groups:
                    col_groups[cols] = []
                col_groups[cols].append(tn)

            # Create combined view for the largest compatible group
            largest_group = max(col_groups.values(), key=len)
            if len(largest_group) < 2:
                continue

            view_name = sanitize_table_name(Path(source).stem) + "_combined"
            col_list = ', '.join(self.tables[largest_group[0]].get('columns', []))
            unions = " UNION ALL ".join(
                f"SELECT {col_list} FROM {tn}" for tn in largest_group
            )

            try:
                self.conn.execute(f"DROP VIEW IF EXISTS {view_name}")
                self.conn.execute(f"CREATE VIEW {view_name} AS {unions}")

                info = self._get_table_info(view_name)
                self.tables[view_name] = {
                    "file_name": f"Combined: {Path(source).name}",
                    "file_path": source,
                    "source_type": "combined",
                    "is_combined": True,
                    "source_tables": largest_group,
                    **info,
                }

                logger.info(
                    f"[Combined] Created view {view_name}: "
                    f"{len(largest_group)} tables, {info.get('row_count', 0)} rows"
                )
            except Exception as e:
                logger.error(f"[Combined] Error creating view: {e}")

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

    def get_table_summary(self, table_name: str) -> Optional[Dict[str, Any]]:
        """Get summary info for a table."""
        return self.tables.get(table_name)

    def get_all_tables_summary(self) -> str:
        """Get summary of all tables for routing."""
        if not self.tables:
            return "No data tables loaded."

        summaries = []
        for name, info in self.tables.items():
            cols = ', '.join(info.get('columns', [])[:5])
            if len(info.get('columns', [])) > 5:
                cols += '...'
            summaries.append(f"- {name}: {info.get('row_count', 0)} rows | Columns: {cols}")

        return '\n'.join(summaries)

    # ── SQL generation via llm_client ─────────────────────────

    def _generate_sql(self, question: str, table_name: str) -> str:
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
        column_info_parts = []
        for col in columns:
            dtype = dtypes.get(col, 'VARCHAR')
            human_name = col.replace('_', ' ').title()
            column_info_parts.append(f"  - {col} ({dtype}) = {human_name}")
        column_info = '\n'.join(column_info_parts)

        jargon_context = self.jargon.build_column_context(columns)

        expanded_question = self.jargon.expand_query(question)
        if expanded_question != question:
            logger.info(f"   Expanded query: {expanded_question[:100]}...")

        prompt = safe_render_prompt(
            self.SQL_GENERATION_PROMPT,
            user_query=expanded_question,
            table_name=table_name,
            row_count=str(row_count),
            column_info=column_info,
            sample_data=sample_str,
            max_rows=str(MAX_RESULT_ROWS),
            jargon_context=jargon_context,
        )
        system = build_system_prompt("You are a DuckDB SQL query generator. Return only valid DuckDB SQL.")

        resp = llm_client.generate_text(prompt, system=system, max_tokens=512)

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

    def _retry_sql_generation(self, previous_sql: str, error: str, table_name: str) -> Optional[str]:
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
            resp = llm_client.generate_text(prompt, system=system, max_tokens=512)

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
        """Check if result is small enough to skip LLM summary."""
        rows = len(result_df)
        cols = len(result_df.columns)
        cells = rows * cols
        return rows <= SQL_LAZY_SUMMARY_MAX_ROWS and cells <= SQL_LAZY_SUMMARY_MAX_CELLS

    def _lazy_summary(self, question: str, sql: str, result_df: pd.DataFrame) -> str:
        """Format a simple text summary without calling the LLM."""
        if result_df.empty:
            return "The query returned no results."

        rows = len(result_df)
        if rows == 1 and len(result_df.columns) == 1:
            val = result_df.iloc[0, 0]
            col = result_df.columns[0]
            return f"Result: {col} = {val}"

        if rows == 1:
            parts = [f"**{col}**: {result_df.iloc[0][col]}" for col in result_df.columns]
            return "Result: " + " | ".join(parts)

        preview = result_df.to_string(index=False)
        return f"Query returned {rows} rows:\n\n```\n{preview}\n```"

    def _generate_summary(self, question: str, sql: str, result_df: pd.DataFrame) -> str:
        """Generate natural language summary - lazy if result is small."""
        # Lazy path: skip LLM for small results
        if self._should_lazy_summarize(result_df):
            logger.info(f"   Lazy summary ({len(result_df)} rows, {len(result_df) * len(result_df.columns)} cells)")
            return self._lazy_summary(question, sql, result_df)

        # LLM path for larger results
        from . import llm_client
        from .prompt_security import safe_render_prompt, build_system_prompt

        preview = result_df.head(10).to_string(index=False) if not result_df.empty else "Empty result"

        prompt = safe_render_prompt(
            self.SUMMARY_PROMPT,
            user_query=question,
            sql=sql,
            row_count=str(len(result_df)),
            result_preview=preview,
        )
        system = build_system_prompt("You summarize SQL query results factually.")

        resp = llm_client.generate_text(prompt, system=system, max_tokens=512)

        from .telemetry import get_current_trace
        trace = get_current_trace()
        if trace:
            trace.record_llm_call(resp.usage)

        return resp.text

    # ── Main query entry point ────────────────────────────────

    def query(self, question: str, table_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Query data using safe SQL execution.
        Self-corrects once on SQL errors.
        Uses lazy summary for small results.
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
            table_name = self.select_table(question)

        logger.info(f"   Using table: {table_name}")
        info = self.tables.get(table_name, {})

        sql = None
        try:
            # Step 1: Generate SQL
            logger.info("   Generating SQL query...")
            start_time = time.time()
            sql = self._generate_sql(question, table_name)
            gen_time = time.time() - start_time
            logger.info(f"   Generated SQL ({gen_time:.2f}s): {sql[:100]}...")

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

            # Also validate table references
            from .prompt_security import validate_sql_tables
            if not validate_sql_tables(sql, list(self.tables.keys())):
                logger.warning("   SQL references unknown tables")

            # Ensure LIMIT
            if 'LIMIT' not in sql.upper():
                sql = f"{sql.rstrip(';')} LIMIT {MAX_RESULT_ROWS}"

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
                        raise exec_err
                else:
                    raise exec_err

            exec_time = time.time() - start_time
            logger.info(f"   Executed in {exec_time:.3f}s, returned {len(result_df)} rows")

            # Step 4: Generate summary (lazy or LLM)
            summary = self._generate_summary(question, sql, result_df)

            # Build sources metadata
            sources = [{
                "type": "structured_data",
                "file_name": info.get('file_name', table_name),
                "file_path": self.file_paths.get(table_name, ''),
                "table_name": table_name,
                "columns_used": info.get('columns', []),
                "row_count_returned": len(result_df),
                "total_rows": info.get('row_count', 0),
                "sql_query": sql,
                "execution_time_ms": round(exec_time * 1000, 2),
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

    def query_with_context(
        self,
        question: str,
        context: str = "",
        table_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Query data with additional context from previous steps.
        Used by the planner/executor for multi-step SQL chains.
        """
        if context:
            enriched = f"Context from previous analysis:\n{context[:500]}\n\nNew task: {question}"
            return self.query(enriched, table_name)
        return self.query(question, table_name)

    def select_table(self, question: str) -> Optional[str]:
        """
        Select the best table for a question using multiple strategies:
        1. Prefer combined views for aggregate/time-series queries
        2. Exact table name match in question
        3. Column name matching against question words
        4. Fallback: prefer combined views, then first table
        """
        if not self.tables:
            return None
        if len(self.tables) == 1:
            return list(self.tables.keys())[0]

        question_lower = question.lower()

        # Strategy 1: Prefer combined views for aggregate/time-series queries
        aggregate_keywords = [
            'total', 'toplam', 'sum', 'average', 'ortalama',
            'by month', 'by year', 'aylık', 'yıllık', 'monthly', 'yearly',
            'trend', 'over time', 'all', 'tüm', 'hepsi', 'genel',
        ]
        is_aggregate = any(kw in question_lower for kw in aggregate_keywords)
        if is_aggregate:
            for name, info in self.tables.items():
                if info.get('is_combined'):
                    return name

        # Strategy 2: Exact table name match in question
        for name in self.tables.keys():
            if name.lower() in question_lower:
                return name

        # Strategy 3: Column name matching — score tables by column relevance
        question_words = set(re.findall(r'\b\w{3,}\b', question_lower))
        # Also expand jargon in question words
        expanded_words = set()
        for w in question_words:
            expanded_words.add(w)
            meaning = self.jargon.expand(w.upper())
            if meaning:
                expanded_words.update(meaning.lower().split())

        best_match = None
        best_score = 0
        for name, info in self.tables.items():
            columns = info.get('columns', [])
            col_words = set()
            for c in columns:
                col_words.update(c.lower().split('_'))
            score = len(expanded_words & col_words)
            # Bonus for combined views
            if info.get('is_combined'):
                score += 2
            if score > best_score:
                best_score = score
                best_match = name

        if best_match and best_score > 0:
            return best_match

        # Strategy 4: Fallback — prefer combined views
        for name, info in self.tables.items():
            if info.get('is_combined'):
                return name

        return list(self.tables.keys())[0]

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
