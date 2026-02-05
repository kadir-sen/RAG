"""
Excel Table Extractor with native table detection and block detection.
Extracts tabular regions from Excel files without relying on OCR.
"""
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass

import pandas as pd
import numpy as np
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from .logger import logger
from .catalog import get_catalog, TableMetadata


@dataclass
class ExtractedTable:
    """Represents an extracted table from Excel."""
    df: pd.DataFrame
    sheet_name: str
    start_row: int
    start_col: int
    end_row: int
    end_col: int
    extraction_method: str  # "native_table" | "block_detect" | "full_sheet"
    table_name: Optional[str] = None  # Excel native table name if available


class ExcelTableExtractor:
    """
    Extracts tables from Excel files using multiple strategies:
    1. Native Excel tables (ListObjects)
    2. Block detection for non-table regions
    3. Full sheet fallback
    """

    # Block detection thresholds
    MIN_BLOCK_ROWS = 3
    MIN_BLOCK_COLS = 2
    MAX_EMPTY_ROWS_IN_BLOCK = 2
    MAX_EMPTY_COLS_IN_BLOCK = 1

    def __init__(self):
        """Initialize Excel table extractor."""
        self.catalog = get_catalog()

    def extract_tables(self, file_path: str) -> List[ExtractedTable]:
        """
        Extract all tables from an Excel file.

        Args:
            file_path: Path to Excel file

        Returns:
            List of extracted tables
        """
        path = Path(file_path)
        logger.info(f"[ExcelExtractor] Processing: {path.name}")

        tables = []

        try:
            # Try openpyxl for native tables first
            wb = load_workbook(file_path, read_only=False, data_only=True)

            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]

                # Skip empty sheets
                if ws.max_row is None or ws.max_row < 2:
                    continue

                logger.info(f"[ExcelExtractor] Sheet: {sheet_name} ({ws.max_row} rows, {ws.max_column} cols)")

                # Strategy 1: Extract native Excel tables
                native_tables = self._extract_native_tables(ws, sheet_name)
                if native_tables:
                    tables.extend(native_tables)
                    logger.info(f"[ExcelExtractor] Found {len(native_tables)} native tables")

                # Strategy 2: Block detection for non-table areas
                block_tables = self._extract_block_tables(ws, sheet_name, native_tables)
                if block_tables:
                    tables.extend(block_tables)
                    logger.info(f"[ExcelExtractor] Found {len(block_tables)} block tables")

                # Strategy 3: If no tables found, treat entire sheet as one table
                if not native_tables and not block_tables:
                    full_sheet = self._extract_full_sheet(file_path, sheet_name)
                    if full_sheet:
                        tables.append(full_sheet)
                        logger.info(f"[ExcelExtractor] Using full sheet as table")

            wb.close()

        except Exception as e:
            logger.error(f"[ExcelExtractor] Error with openpyxl: {e}")
            # Fallback to pandas for simple extraction
            try:
                xls = pd.ExcelFile(file_path)
                for sheet_name in xls.sheet_names:
                    full_sheet = self._extract_full_sheet(file_path, sheet_name)
                    if full_sheet:
                        tables.append(full_sheet)
            except Exception as e2:
                logger.error(f"[ExcelExtractor] Fallback also failed: {e2}")

        logger.info(f"[ExcelExtractor] Total tables extracted: {len(tables)}")
        return tables

    def _extract_native_tables(self, ws: Worksheet, sheet_name: str) -> List[ExtractedTable]:
        """Extract native Excel tables (ListObjects)."""
        tables = []

        try:
            # Check for Excel tables
            if hasattr(ws, 'tables') and ws.tables:
                for table_name, table_obj in ws.tables.items():
                    try:
                        # Parse table range (e.g., "A1:D10")
                        ref = table_obj.ref
                        start, end = ref.split(":")

                        # Convert to row/col indices
                        start_col, start_row = self._parse_cell_ref(start)
                        end_col, end_row = self._parse_cell_ref(end)

                        # Read data from range
                        data = []
                        for row in ws.iter_rows(min_row=start_row, max_row=end_row,
                                                min_col=start_col, max_col=end_col):
                            data.append([cell.value for cell in row])

                        if len(data) < 2:
                            continue

                        # First row as header
                        df = pd.DataFrame(data[1:], columns=data[0])
                        df = self._clean_dataframe(df)

                        if not df.empty:
                            tables.append(ExtractedTable(
                                df=df,
                                sheet_name=sheet_name,
                                start_row=start_row,
                                start_col=start_col,
                                end_row=end_row,
                                end_col=end_col,
                                extraction_method="native_table",
                                table_name=table_name,
                            ))

                    except Exception as e:
                        logger.warning(f"[ExcelExtractor] Error parsing table {table_name}: {e}")

        except Exception as e:
            logger.warning(f"[ExcelExtractor] Error accessing tables: {e}")

        return tables

    def _extract_block_tables(self, ws: Worksheet, sheet_name: str,
                              existing_tables: List[ExtractedTable]) -> List[ExtractedTable]:
        """
        Detect table-like blocks in the worksheet.
        Uses contiguous non-empty regions with consistent column structure.
        """
        tables = []

        try:
            # Convert worksheet to numpy array for faster processing
            max_row = min(ws.max_row or 1, 10000)  # Limit for performance
            max_col = min(ws.max_column or 1, 100)

            # Build matrix of cell values
            matrix = []
            for row in ws.iter_rows(min_row=1, max_row=max_row,
                                    min_col=1, max_col=max_col):
                matrix.append([cell.value for cell in row])

            if not matrix:
                return tables

            # Convert to numpy for easier manipulation
            arr = np.array(matrix, dtype=object)

            # Find non-empty mask
            non_empty = pd.DataFrame(arr).notna() & (pd.DataFrame(arr) != "")
            non_empty = non_empty.values

            # Find connected regions
            blocks = self._find_table_blocks(non_empty, existing_tables)

            for block in blocks:
                start_row, start_col, end_row, end_col = block

                # Extract data
                data = arr[start_row:end_row + 1, start_col:end_col + 1].tolist()

                if len(data) < self.MIN_BLOCK_ROWS:
                    continue

                # Detect header row
                header_idx = self._detect_header_row(data)

                if header_idx >= len(data) - 1:
                    continue

                # Create DataFrame
                headers = data[header_idx]
                body = data[header_idx + 1:]

                df = pd.DataFrame(body, columns=headers)
                df = self._clean_dataframe(df)

                if df.empty or len(df.columns) < self.MIN_BLOCK_COLS:
                    continue

                tables.append(ExtractedTable(
                    df=df,
                    sheet_name=sheet_name,
                    start_row=start_row + 1,  # 1-indexed
                    start_col=start_col + 1,
                    end_row=end_row + 1,
                    end_col=end_col + 1,
                    extraction_method="block_detect",
                ))

        except Exception as e:
            logger.warning(f"[ExcelExtractor] Block detection error: {e}")

        return tables

    def _find_table_blocks(self, non_empty: np.ndarray,
                           existing_tables: List[ExtractedTable]) -> List[Tuple[int, int, int, int]]:
        """
        Find table-like rectangular blocks in the non-empty mask.
        Returns list of (start_row, start_col, end_row, end_col).
        """
        blocks = []
        visited = np.zeros_like(non_empty, dtype=bool)

        # Mark existing table regions as visited
        for table in existing_tables:
            r1, c1 = table.start_row - 1, table.start_col - 1
            r2, c2 = table.end_row - 1, table.end_col - 1
            r1, r2 = max(0, r1), min(non_empty.shape[0] - 1, r2)
            c1, c2 = max(0, c1), min(non_empty.shape[1] - 1, c2)
            visited[r1:r2 + 1, c1:c2 + 1] = True

        # Find dense regions
        rows, cols = non_empty.shape

        for start_row in range(rows):
            for start_col in range(cols):
                if visited[start_row, start_col] or not non_empty[start_row, start_col]:
                    continue

                # Try to expand block
                end_row, end_col = self._expand_block(
                    non_empty, visited, start_row, start_col
                )

                block_rows = end_row - start_row + 1
                block_cols = end_col - start_col + 1

                if block_rows >= self.MIN_BLOCK_ROWS and block_cols >= self.MIN_BLOCK_COLS:
                    blocks.append((start_row, start_col, end_row, end_col))

                # Mark as visited
                visited[start_row:end_row + 1, start_col:end_col + 1] = True

        return blocks

    def _expand_block(self, non_empty: np.ndarray, visited: np.ndarray,
                      start_row: int, start_col: int) -> Tuple[int, int]:
        """Expand a block as far as possible while maintaining table structure."""
        rows, cols = non_empty.shape

        # Find column extent (first row's non-empty columns)
        end_col = start_col
        for c in range(start_col, cols):
            if not visited[start_row, c] and non_empty[start_row, c]:
                end_col = c
            elif not non_empty[start_row, c]:
                break

        # Find row extent
        end_row = start_row
        empty_row_count = 0

        for r in range(start_row, rows):
            # Count non-empty cells in this row within column range
            row_non_empty = sum(
                1 for c in range(start_col, end_col + 1)
                if non_empty[r, c]
            )
            row_total = end_col - start_col + 1

            # Row should have at least 30% non-empty cells
            if row_non_empty / row_total >= 0.3:
                end_row = r
                empty_row_count = 0
            else:
                empty_row_count += 1
                if empty_row_count > self.MAX_EMPTY_ROWS_IN_BLOCK:
                    break

        return end_row, end_col

    def _detect_header_row(self, data: List[List]) -> int:
        """Detect which row is the header based on heuristics."""
        for i, row in enumerate(data[:5]):  # Check first 5 rows
            if row is None:
                continue

            # Count string values (likely headers)
            string_count = sum(1 for v in row if isinstance(v, str) and v and len(str(v)) > 0)
            non_null_count = sum(1 for v in row if v is not None)

            # Header should have mostly strings
            if non_null_count > 0 and string_count / non_null_count >= 0.5:
                # Check that next row has different pattern (more numbers/values)
                if i + 1 < len(data):
                    next_row = data[i + 1]
                    next_string_count = sum(1 for v in next_row if isinstance(v, str))
                    if next_string_count < string_count:
                        return i

        return 0  # Default to first row

    def _extract_full_sheet(self, file_path: str, sheet_name: str) -> Optional[ExtractedTable]:
        """Extract entire sheet as a single table."""
        try:
            # Find header row
            df_preview = pd.read_excel(file_path, sheet_name=sheet_name, header=None, nrows=20)

            header_row = 0
            for i in range(min(10, len(df_preview))):
                row = df_preview.iloc[i]
                string_count = sum(1 for v in row if isinstance(v, str) and v)
                if string_count >= len(row) * 0.3:
                    header_row = i
                    break

            # Read with detected header
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)
            df = self._clean_dataframe(df)

            if df.empty:
                return None

            return ExtractedTable(
                df=df,
                sheet_name=sheet_name,
                start_row=header_row + 1,
                start_col=1,
                end_row=header_row + len(df) + 1,
                end_col=len(df.columns),
                extraction_method="full_sheet",
            )

        except Exception as e:
            logger.warning(f"[ExcelExtractor] Full sheet extraction failed: {e}")
            return None

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and normalize DataFrame."""
        if df.empty:
            return df

        # Drop completely empty rows/columns
        df = df.dropna(how='all')
        df = df.dropna(axis=1, how='all')

        if df.empty:
            return df

        # Clean column names
        new_columns = []
        for i, col in enumerate(df.columns):
            if col is None or pd.isna(col) or str(col).strip() == '':
                clean = f"col_{i}"
            else:
                clean = str(col).strip()
                clean = re.sub(r'[^a-zA-Z0-9_]', '_', clean)
                clean = re.sub(r'_+', '_', clean).strip('_').lower()
                if not clean:
                    clean = f"col_{i}"
            new_columns.append(clean)

        # Handle duplicates
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

        return df

    @staticmethod
    def _parse_cell_ref(ref: str) -> Tuple[int, int]:
        """Parse cell reference like 'A1' to (col, row) 1-indexed."""
        match = re.match(r'([A-Z]+)(\d+)', ref.upper())
        if not match:
            return 1, 1

        col_str, row_str = match.groups()

        # Convert column letters to number
        col = 0
        for char in col_str:
            col = col * 26 + (ord(char) - ord('A') + 1)

        return col, int(row_str)

    def save_to_parquet(self, table: ExtractedTable, source_file: str) -> Optional[TableMetadata]:
        """
        Save extracted table to Parquet and register in catalog.

        Returns:
            TableMetadata if successful, None otherwise
        """
        try:
            # Generate table ID
            table_id = self.catalog.generate_table_id(
                source_file,
                sheet_name=table.sheet_name,
                table_index=0,  # Could be enhanced for multiple tables per sheet
            )

            # Generate parquet path
            parquet_path = self.catalog.generate_parquet_path(table_id)

            # Save to parquet
            table.df.to_parquet(parquet_path, index=False)

            logger.info(f"[ExcelExtractor] Saved parquet: {parquet_path.name}")

            # Create metadata
            meta = TableMetadata(
                table_id=table_id,
                source_file=source_file,
                source_type="excel",
                table_name=table_id,
                parquet_path=str(parquet_path),
                sheet_name=table.sheet_name,
                row_count=len(table.df),
                column_count=len(table.df.columns),
                columns=list(table.df.columns),
                extraction_method=table.extraction_method,
                file_hash=self.catalog.compute_file_hash(source_file),
            )

            return meta

        except Exception as e:
            logger.error(f"[ExcelExtractor] Error saving parquet: {e}")
            return None


# Convenience function
def extract_excel_tables(file_path: str, save_parquet: bool = True) -> List[TableMetadata]:
    """
    Extract tables from Excel file and optionally save to parquet.

    Args:
        file_path: Path to Excel file
        save_parquet: If True, save tables to parquet files

    Returns:
        List of TableMetadata for extracted tables
    """
    extractor = ExcelTableExtractor()
    tables = extractor.extract_tables(file_path)

    if not save_parquet:
        return []

    catalog = get_catalog()
    entry = catalog.add_entry(file_path, "excel")

    metadata_list = []
    for table in tables:
        meta = extractor.save_to_parquet(table, file_path)
        if meta:
            catalog.add_table(entry, meta)
            metadata_list.append(meta)

    return metadata_list
