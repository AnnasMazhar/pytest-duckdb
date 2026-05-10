"""CSV fixture loading — reads CSV files from a directory into DuckDB tables."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb


def load_csvs(conn: duckdb.DuckDBPyConnection, fixtures_dir: str) -> None:
    """Load all CSV files from *fixtures_dir* as DuckDB tables.

    Each CSV file becomes a table named after its stem (filename without extension).
    Uses ``read_csv_auto`` for schema inference.  Non-existent directories are
    silently ignored so that tests without fixtures work out of the box.

    Args:
        conn: An open DuckDB connection.
        fixtures_dir: Absolute or project-relative path to the CSV directory.
    """
    path = Path(fixtures_dir)
    if not path.is_dir():
        return

    csv_files = sorted(path.glob("*.csv"))
    for csv_file in csv_files:
        table_name = csv_file.stem
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
