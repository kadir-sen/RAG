"""
Safe SQL-based Data Analyzer using DuckDB.
NO arbitrary Python execution from LLM - only validated SELECT queries.
"""
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import duckdb
import pandas as pd
from llama_index.llms.gemini import Gemini

from .config import GOOGLE_API_KEY, GEMINI_MODEL
from .logger import logger, log_separator, log_document_processing


# SQL validation patterns
DANGEROUS_PATTERNS = [
    r'\bDROP\b', r'\bDELETE\b', r'\bINSERT\b', r'\bUPDATE\b',
    r'\bCREATE\b', r'\bALTER\b', r'\bTRUNCATE\b', r'\bGRANT\b',
    r'\bREVOKE\b', r'\bEXEC\b', r'\bEXECUTE\b', r'\bCALL\b',
    r'\bATTACH\b', r'\bDETACH\b', r'\bCOPY\b', r'\bEXPORT\b',
]

MAX_RESULT_ROWS = 200


def sanitize_table_name(name: str) -> str:
    """Create a safe SQL table name from file name."""
    # Remove extension, replace non-alphanumeric with underscore
    clean = Path(name).stem
    clean = re.sub(r'[^a-zA-Z0-9]', '_', clean)
    clean = re.sub(r'_+', '_', clean).strip('_')
    # Ensure starts with letter
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

    # Must start with SELECT
    if not sql_upper.startswith('SELECT'):
        return False, "Only SELECT queries are allowed"

    # Check for dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, sql_upper):
            return False, f"Dangerous SQL pattern detected: {pattern}"

    # Check for multiple statements
    if ';' in sql[:-1]:  # Allow trailing semicolon
        return False, "Multiple SQL statements not allowed"

    return True, ""


class DataAnalyzerSQL:
    """
    Safe data analysis using DuckDB SQL.
    Generates and validates SQL queries - never executes arbitrary code.
    """

    SQL_GENERATION_PROMPT = """You are a SQL query generator. Given a question about tabular data, generate a DuckDB SQL query.

RULES:
1. ONLY generate SELECT queries - no INSERT, UPDATE, DELETE, DROP, CREATE, etc.
2. Always use the exact table name provided: {table_name}
3. Available columns: {columns}
4. Sample data (first 5 rows):
{sample_data}

5. Add LIMIT {max_rows} to prevent huge results
6. Use DuckDB SQL syntax (similar to PostgreSQL)
7. Return ONLY the SQL query, nothing else - no explanations, no markdown

TIPS:
- For numeric operations on string columns, use TRY_CAST(column AS DOUBLE)
- For date grouping, extract month/year from date columns
- Use aggregate functions (SUM, AVG, MAX, MIN, COUNT) for calculations

USER QUESTION: {question}

SQL QUERY:"""

    SUMMARY_PROMPT = """Based on this data analysis result, provide a brief natural language summary.

Question: {question}
SQL Query: {sql}
Result ({row_count} rows):
{result_preview}

Provide a concise 2-3 sentence summary of the findings. Be factual and precise."""

    def __init__(self):
        """Initialize SQL-based data analyzer."""
        log_separator("Initializing SQL Data Analyzer")
        self.llm = Gemini(api_key=GOOGLE_API_KEY, model=GEMINI_MODEL)
        self.conn = duckdb.connect(':memory:')  # In-memory database
        self.tables: Dict[str, Dict[str, Any]] = {}  # table_name -> metadata
        self.file_paths: Dict[str, str] = {}  # table_name -> original file path
        logger.info("✅ SQL Data Analyzer initialized (DuckDB)")

    def _get_table_info(self, table_name: str) -> Dict[str, Any]:
        """Get schema and sample data for a table."""
        try:
            # Get columns
            cols_df = self.conn.execute(f"DESCRIBE {table_name}").fetchdf()
            columns = cols_df['column_name'].tolist()
            dtypes = dict(zip(cols_df['column_name'], cols_df['column_type']))

            # Get sample rows
            sample_df = self.conn.execute(f"SELECT * FROM {table_name} LIMIT 5").fetchdf()

            # Get row count
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
        """
        Find the actual header row in Excel (skip title/merged rows).
        Returns the row index (0-based) where headers are.
        """
        try:
            # Read first 20 rows to analyze
            df_preview = pd.read_excel(file_path, sheet_name=sheet_name, header=None, nrows=20)

            # Look for row with most non-null values that looks like headers
            best_row = 0
            best_score = 0

            for idx in range(min(10, len(df_preview))):
                row = df_preview.iloc[idx]
                non_null = row.notna().sum()
                # Check if values look like headers (strings, not numbers)
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
        """
        Process DataFrame: clean columns and handle data types.
        """
        # Remove completely empty rows
        df = df.dropna(how='all')

        # Clean column names
        new_columns = []
        for i, col in enumerate(df.columns):
            clean = re.sub(r'[^a-zA-Z0-9]', '_', str(col)).strip('_').lower()
            clean = re.sub(r'_+', '_', clean)
            if not clean or clean == 'nan' or clean == 'unnamed':
                clean = f"col_{i}"
            new_columns.append(clean)

        # Handle duplicate column names
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

        # Strip whitespace and handle nan strings
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
            # Find the actual header row (skip title rows)
            header_row = self._find_header_row(file_path, sheet_name)

            if sheet_name:
                table_name = f"{table_name}_{sanitize_table_name(sheet_name)}"

            # Read Excel with detected header row
            df = None
            try:
                df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)
            except Exception as e1:
                logger.warning(f"   Normal read failed: {e1}, trying with dtype=str")
                df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row, dtype=str)

            if df is None or df.empty:
                logger.error("   Empty DataFrame after reading")
                return False

            # Process the DataFrame (clean columns and data types)
            df = self._process_dataframe(df)

            # Drop existing table if exists
            self.conn.execute(f"DROP TABLE IF EXISTS {table_name}")

            # Try to register and create table
            try:
                self.conn.register('temp_df', df)
                self.conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM temp_df")
                self.conn.unregister('temp_df')
            except Exception as e2:
                # If still fails, force all columns to string
                logger.warning(f"   DuckDB create failed: {e2}, converting all to string")
                df = df.astype(str)
                df = df.replace(['nan', 'None'], None)
                self.conn.register('temp_df', df)
                self.conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM temp_df")
                self.conn.unregister('temp_df')

            # Store metadata
            info = self._get_table_info(table_name)
            self.tables[table_name] = {
                "file_name": path.name,
                "file_path": str(file_path),
                **info,
            }
            self.file_paths[table_name] = str(file_path)

            logger.info(f"   Table: {table_name}")
            logger.info(f"   Rows: {info.get('row_count', 0)}, Columns: {len(info.get('columns', []))}")
            log_document_processing(path.name, "✅ Loaded to SQL")
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
            # DuckDB can read CSV directly
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
            log_document_processing(path.name, "✅ Loaded to SQL")
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
        else:
            logger.warning(f"Unsupported file type: {ext}")
            return False

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
                    continue  # Skip temp files
                if self.load_file(str(file_path)):
                    count += 1

        logger.info(f"📊 Loaded {count} data files")
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

    def _generate_sql(self, question: str, table_name: str) -> str:
        """Use LLM to generate SQL query."""
        info = self.tables.get(table_name, {})
        columns = info.get('columns', [])

        # Get sample rows for better context
        try:
            sample = self.conn.execute(f"SELECT * FROM {table_name} LIMIT 5").fetchdf()
        except Exception:
            sample = info.get('sample', pd.DataFrame())

        sample_str = sample.to_string(index=False) if not sample.empty else "No sample data"

        prompt = self.SQL_GENERATION_PROMPT.format(
            table_name=table_name,
            columns=', '.join(columns),
            sample_data=sample_str,
            max_rows=MAX_RESULT_ROWS,
            question=question,
        )

        response = self.llm.complete(prompt)
        sql = response.text.strip()

        # Clean up common LLM artifacts
        sql = sql.replace('```sql', '').replace('```', '').strip()
        if sql.startswith("'") or sql.startswith('"'):
            sql = sql[1:]
        if sql.endswith("'") or sql.endswith('"'):
            sql = sql[:-1]

        return sql.strip()

    def _generate_summary(self, question: str, sql: str, result: pd.DataFrame) -> str:
        """Generate natural language summary of results."""
        preview = result.head(10).to_string(index=False) if not result.empty else "Empty result"

        prompt = self.SUMMARY_PROMPT.format(
            question=question,
            sql=sql,
            row_count=len(result),
            result_preview=preview,
        )

        response = self.llm.complete(prompt)
        return response.text.strip()

    def query(self, question: str, table_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Query data using safe SQL execution.
        Returns answer, sources, SQL query, and result data.
        """
        log_separator("SQL Data Query")
        logger.info(f"🔍 Question: {question[:100]}...")

        if not self.tables:
            return {
                "answer": "No data tables loaded. Please upload Excel or CSV files first.",
                "sources": [],
                "sql": None,
                "result_data": None,
            }

        # Select table
        if table_name is None:
            if len(self.tables) == 1:
                table_name = list(self.tables.keys())[0]
            else:
                # Try to infer from question
                question_lower = question.lower()
                for name in self.tables.keys():
                    if name.lower() in question_lower:
                        table_name = name
                        break
                if table_name is None:
                    table_name = list(self.tables.keys())[0]

        logger.info(f"   Using table: {table_name}")
        info = self.tables.get(table_name, {})

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
                logger.error(f"   SQL validation failed: {error}")
                return {
                    "answer": f"Cannot execute this query: {error}",
                    "sources": [{"error": error}],
                    "sql": sql,
                    "result_data": None,
                }

            # Ensure LIMIT
            if 'LIMIT' not in sql.upper():
                sql = f"{sql.rstrip(';')} LIMIT {MAX_RESULT_ROWS}"

            # Step 3: Execute SQL
            logger.info("   Executing SQL...")
            start_time = time.time()
            result_df = self.conn.execute(sql).fetchdf()
            exec_time = time.time() - start_time
            logger.info(f"   Executed in {exec_time:.3f}s, returned {len(result_df)} rows")

            # Step 4: Generate summary
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
                "sql": sql if 'sql' in dir() else None,
                "result_data": None,
            }

    def execute_raw_sql(self, sql: str) -> Tuple[Optional[pd.DataFrame], str]:
        """
        Execute raw SQL with validation.
        Returns (result_df, error_message).
        """
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
