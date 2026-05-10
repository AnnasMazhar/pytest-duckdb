"""Parquet snapshot save / load / compare.

Snapshots provide deterministic regression testing for SQL queries.  The first
run saves the result as a Parquet file.  Subsequent runs compare against the
stored snapshot and raise ``AssertionError`` with a clear diff on mismatch.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Sequence

import duckdb

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def save(conn: duckdb.DuckDBPyConnection, result: Any, path: str) -> None:
    """Save *result* (DataFrame or list-of-tuples) to a Parquet file.

    The parent directory is created if it does not exist.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _register_temp(conn, result, "__snapshot_to_save__")
    conn.execute(f"COPY __snapshot_to_save__ TO '{path}' (FORMAT PARQUET)")
    conn.execute("DROP TABLE IF EXISTS __snapshot_to_save__")


def load(conn: duckdb.DuckDBPyConnection, path: str) -> Any:
    """Load a Parquet snapshot as a pandas DataFrame (if available) or
    :class:`QueryResult`."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Snapshot file not found: {path}")
    cur = conn.execute(f"SELECT * FROM read_parquet('{path}')")
    return _cursor_to_result(cur)


def compare(
    conn: duckdb.DuckDBPyConnection,
    actual: Any,
    path: str,
) -> None:
    """Compare *actual* against the Parquet snapshot at *path*.

    Raises ``AssertionError`` with a human-readable diff if they differ.

    Args:
        conn: DuckDB connection used for comparison queries.
        actual: DataFrame or list-of-tuples (the current query result).
        path: Path to the stored Parquet snapshot.

    Raises:
        FileNotFoundError: The snapshot has not been created yet.
        AssertionError: The result does not match the snapshot.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Snapshot does not exist yet — run without --snapshot-update "
            f"to create it first (expected: {path})"
        )

    _register_temp(conn, actual, "__snapshot_actual__")

    # Load the snapshot into a temp table for SQL-based comparison.
    conn.execute(
        "CREATE TEMP TABLE __snapshot_expected__ AS "
        f"SELECT * FROM read_parquet('{path}')"
    )

    try:
        # 1. Column / type matching.
        actual_cols = _describe(conn, "__snapshot_actual__")
        expected_cols = _describe(conn, "__snapshot_expected__")

        if actual_cols != expected_cols:
            _raise_schema_diff(actual_cols, expected_cols)

        # 2. Row-level comparison via EXCEPT.
        differing = conn.execute(
            "SELECT * FROM __snapshot_actual__ "
            "EXCEPT "
            "SELECT * FROM __snapshot_expected__"
        ).fetchall()

        missing = conn.execute(
            "SELECT * FROM __snapshot_expected__ "
            "EXCEPT "
            "SELECT * FROM __snapshot_actual__"
        ).fetchall()

        if differing or missing:
            col_names = [c[0] for c in expected_cols] if expected_cols else []
            _raise_row_diff(differing, missing, col_names)

    finally:
        conn.execute("DROP TABLE IF EXISTS __snapshot_actual__")
        conn.execute("DROP TABLE IF EXISTS __snapshot_expected__")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class QueryResult:
    """Wrapper around a list of result rows with a ``.columns`` attribute.

    Used when pandas is not installed so that consumers can access column
    metadata in a uniform way.
    """

    __slots__ = ("_rows", "columns")

    def __init__(self, rows: Sequence[tuple], columns: Sequence[str]) -> None:
        self._rows = list(rows)
        self.columns = tuple(columns)

    def __iter__(self):  # noqa: ANN201
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    def __getitem__(self, idx: int) -> tuple:
        return self._rows[idx]

    def __repr__(self) -> str:  # noqa: D105
        return f"QueryResult(rows={len(self)}, columns={self.columns})"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _register_temp(conn: duckdb.DuckDBPyConnection, result: Any, name: str) -> None:
    """Register *result* as a temporary DuckDB table called *name*."""
    # If it has a `columns` attribute it's a QueryResult (list-of-tuples).
    if hasattr(result, "_rows"):
        rows = list(result)
        if not rows:
            columns = list(result.columns)
            # Create an empty table with VARCHAR columns.
            col_defs = ",\n".join(f'"{c}" VARCHAR' for c in columns)
            conn.execute(f"CREATE TEMP TABLE {name} ({col_defs})")
        else:
            _register_tuple_list(conn, rows, list(result.columns), name)
        return

    # Check for pandas DataFrame.
    try:
        import pandas as pd

        if isinstance(result, pd.DataFrame):
            conn.register(name, result)
            return
    except ImportError:
        pass

    # Fallback: treat as list-of-tuples with no column metadata.
    if isinstance(result, (list, tuple)):
        rows = list(result)
        if rows:
            cols = [f"col{i}" for i in range(len(rows[0]))]
        else:
            cols = []
        _register_tuple_list(conn, rows, cols, name)
        return

    # DuckDB-compatible type (e.g. a relation).
    conn.execute(f"CREATE TEMP TABLE {name} AS SELECT * FROM result")


def _register_tuple_list(
    conn: duckdb.DuckDBPyConnection,
    rows: list,
    columns: List[str],
    name: str,
) -> None:
    """Create a temp table from a list of Python tuples, preserving types."""
    col_list = ", ".join(f'"{c}"' for c in columns)
    quoted = ", ".join("?" for _ in columns)
    head = rows[0]

    # Let DuckDB infer types from the first row.
    placeholders = "(" + ", ".join(
        _py_value_repr(v) for v in head
    ) + ")"
    conn.execute(
        f"CREATE TEMP TABLE {name} AS "
        f"SELECT * FROM (VALUES {placeholders}) AS t ({col_list}) WHERE FALSE"
    )
    conn.executemany(
        f"INSERT INTO {name} ({col_list}) VALUES ({quoted})",
        rows,
    )


def _py_value_repr(val: Any) -> str:
    """Return a DuckDB-compatible literal for a Python value."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("'", "''")
        return f"'{escaped}'"
    return f"'{val}'"


def _cursor_to_result(cur: duckdb.DuckDBPyConnection) -> Any:
    """Convert a DuckDB cursor to a DataFrame (preferred) or QueryResult."""
    columns = [desc[0] for desc in cur.description] if cur.description else []
    rows = cur.fetchall()
    try:
        import pandas as pd

        return pd.DataFrame(rows, columns=columns)
    except ImportError:
        return QueryResult(rows, columns)


def _describe(conn: duckdb.DuckDBPyConnection, table: str) -> List[tuple]:
    """Return ``[(column_name, data_type), ...]`` for *table*."""
    return conn.execute(f"DESCRIBE {table}").fetchall()


def _raise_schema_diff(
    actual: List[tuple],
    expected: List[tuple],
) -> None:
    """Raise ``AssertionError`` with a schema diff message."""
    actual_map = {r[0]: r[1] for r in actual}
    expected_map = {r[0]: r[1] for r in expected}
    lines: list[str] = []

    for col in sorted(set(list(actual_map) + list(expected_map))):
        a_type = actual_map.get(col, "<missing>")
        e_type = expected_map.get(col, "<missing>")
        if a_type != e_type:
            lines.append(f"  {col}:  expected={e_type}  actual={a_type}")

    msg = "Schema mismatch:\n" + "\n".join(lines)
    raise AssertionError(msg)


def _raise_row_diff(
    differing: List[tuple],
    missing: List[tuple],
    col_names: List[str],
) -> None:
    """Raise ``AssertionError`` with a row-level diff message."""
    lines: list[str] = []
    if differing:
        lines.append(f"Rows in actual but not expected ({len(differing)}):")
        for row in differing[:10]:
            lines.append(f"  {row}")
        if len(differing) > 10:
            lines.append(f"  ... and {len(differing) - 10} more")
    if missing:
        lines.append(f"Rows in expected but not actual ({len(missing)}):")
        for row in missing[:10]:
            lines.append(f"  {row}")
        if len(missing) > 10:
            lines.append(f"  ... and {len(missing) - 10} more")
    if col_names:
        lines.insert(0, f"Columns: {col_names}")
    msg = "Snapshot mismatch:\n" + "\n".join(lines)
    raise AssertionError(msg)
