"""CSV fixture loading — reads CSV files from a directory into DuckDB tables."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb


def _parse_fixture_schemas(schemas_str: str) -> dict[str, list[tuple[str, str]]]:
    """Parse a multiline fixture schema string into a structured dict.

    Format per line: ``table_name: col1 TYPE1, col2 TYPE2, ...``

    Blank lines and lines starting with ``#`` are ignored.
    Commas inside parentheses (e.g. ``DECIMAL(10,2)``) are treated as
    part of the type, not as column separators.
    """
    result: dict[str, list[tuple[str, str]]] = {}

    def _split_columns(text: str) -> list[str]:
        """Split on commas, respecting parentheses grouping."""
        parts: list[str] = []
        current: list[str] = []
        depth = 0
        for ch in text:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        remainder = "".join(current).strip()
        if remainder:
            parts.append(remainder)
        return parts

    for line in schemas_str.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        table_name, _, cols_part = line.partition(":")
        table_name = table_name.strip()
        if not table_name or not cols_part.strip():
            continue

        columns: list[tuple[str, str]] = []
        for col_def in _split_columns(cols_part):
            col_def = col_def.strip()
            if not col_def:
                continue
            # Split on last space: "amount DOUBLE" → ["amount", "DOUBLE"]
            *name_parts, type_name = col_def.rsplit(None, 1)
            col_name = name_parts[0] if name_parts else col_def
            columns.append((col_name, type_name if name_parts else "VARCHAR"))

        if columns:
            result[table_name] = columns

    return result


def load_csvs(
    conn: duckdb.DuckDBPyConnection,
    fixtures_dir: str,
    schemas: dict[str, list[tuple[str, str]]] | None = None,
) -> None:
    """Load all CSV files from *fixtures_dir* as DuckDB tables.

    Each CSV file becomes a table named after its stem (filename without extension).
    Uses ``read_csv_auto`` for schema inference.  Non-existent directories are
    silently ignored so that tests without fixtures work out of the box.

    When *schemas* contains an entry for a table, the explicit column types
    are used instead of ``read_csv_auto`` inference, ensuring deterministic
    types across platforms and DuckDB versions.

    Args:
        conn: An open DuckDB connection.
        fixtures_dir: Absolute or project-relative path to the CSV directory.
        schemas: Optional mapping of ``{table_name: [(col_name, type), ...]}``.
    """
    path = Path(fixtures_dir)
    if not path.is_dir():
        return

    csv_files = sorted(path.glob("*.csv"))
    for csv_file in csv_files:
        table_name = csv_file.stem
        col_schema = (schemas or {}).get(table_name)
        if col_schema:
            col_names = [f'"{col_name}"' for col_name, _ in col_schema]
            col_defs = ", ".join(
                f'"{col_name}" {type_name}' for col_name, type_name in col_schema
            )
            select_cols = ", ".join(col_names)
            conn.execute(f'CREATE TABLE "{table_name}" ({col_defs})')
            conn.execute(
                f'INSERT INTO "{table_name}" ({select_cols}) '
                f"SELECT {select_cols} FROM read_csv_auto('{csv_file}')"
            )
        else:
            conn.execute(
                f'CREATE TABLE "{table_name}" AS '
                f"SELECT * FROM read_csv_auto('{csv_file}')"
            )


def read_sql_file(path: str) -> str:
    """Read and return the contents of a SQL file.

    Args:
        path: Absolute or relative path to the ``.sql`` file.

    Returns:
        The file contents as a string.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"SQL file not found: {path}")
    with open(path) as fh:
        return fh.read()
