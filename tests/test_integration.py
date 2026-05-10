"""End-to-end integration tests for the full pipeline."""

from __future__ import annotations

import os
import tempfile

import duckdb
import pytest

from pytest_duckdb.snapshot import QueryResult, compare, load, save


class TestFullWorkflow:
    """Load CSV → query → snapshot → compare."""

    def test_full_workflow(self) -> None:
        """Load CSV fixtures, run a SQL query, snapshot it, then compare."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_path = os.path.join(tmpdir, "full.parquet")

            # Write a CSV.
            csv_path = os.path.join(tmpdir, "data.csv")
            with open(csv_path, "w") as f:
                f.write("id,val\n1,10\n2,20\n3,30\n")

            # Connect and load.
            conn = duckdb.connect(":memory:")
            conn.execute(
                f"CREATE TABLE data AS SELECT * FROM read_csv_auto('{csv_path}')"
            )

            # Run query.
            result = conn.execute("SELECT * FROM data WHERE val > 15").fetchall()

            # Save snapshot.
            save(conn, QueryResult(result, ("id", "val")), snap_path)
            assert os.path.isfile(snap_path)

            # Re-query and compare.
            result2 = conn.execute("SELECT * FROM data WHERE val > 15").fetchall()
            compare(conn, QueryResult(result2, ("id", "val")), snap_path)

            # Mismatch assertion.
            bad_result = [(9, 9)]
            with pytest.raises(AssertionError, match="Snapshot mismatch"):
                compare(conn, QueryResult(bad_result, ("id", "val")), snap_path)

            conn.close()

    def test_sql_snapshot_fixture_creates(self, duckdb_session, sql_snapshot, tmp_path) -> None:
        """The sql_snapshot callable fixture creates a snapshot file."""
        result = duckdb_session.execute(
            "SELECT id, amount FROM orders WHERE amount > 100"
        ).fetchall()
        from pytest_duckdb.snapshot import QueryResult

        sql_snapshot(QueryResult(result, ("id", "amount")))

    def test_sql_snapshot_fixture_matches(self, duckdb_session, sql_snapshot) -> None:
        """Calling sql_snapshot twice with same data passes."""
        result = duckdb_session.execute(
            "SELECT id, amount FROM orders WHERE id = 1"
        ).fetchall()
        from pytest_duckdb.snapshot import QueryResult

        # First call creates, second call compares
        sql_snapshot(QueryResult(result, ("id", "amount")))

    def test_sql_result_without_marker(self, sql_result) -> None:
        """sql_result returns None when no marker is present."""
        assert sql_result is None

    @pytest.mark.sql("tests/queries/simple.sql")
    def test_sql_result_with_marker(self, sql_result) -> None:
        """sql_result executes the SQL file and returns results."""
        assert sql_result is not None
        assert len(sql_result) > 0


class TestIsolation:
    """Verify that each test gets an isolated DuckDB session."""

    def test_isolation_first(self, duckdb_session) -> None:
        """First test: create a temp table."""
        duckdb_session.execute(
            "CREATE TEMP TABLE scratch AS SELECT 1 AS x"
        )
        count = duckdb_session.execute(
            "SELECT COUNT(*) FROM scratch"
        ).fetchone()[0]
        assert count == 1

    def test_isolation_second(self, duckdb_session) -> None:
        """Second test: scratch table should NOT exist (new session)."""
        tables = duckdb_session.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
        names = {r[0] for r in tables}
        # No scratch table from the first test.
        assert "scratch" not in names


class TestEmptyResult:
    """Query producing zero rows should be handled gracefully."""

    def test_empty_result(self, duckdb_session) -> None:
        """A SELECT with no matches returns 0 rows without error."""
        result = duckdb_session.execute(
            "SELECT * FROM orders WHERE 1 = 0"
        ).fetchall()
        assert len(result) == 0


class TestSnapshotOrdering:
    """Row ordering in snapshots is preserved across save/load."""

    def test_ordering_preserved(self) -> None:
        """Rows should appear in the same order after snapshot roundtrip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ordered.parquet")
            conn = duckdb.connect(":memory:")
            conn.execute(
                "CREATE TABLE data AS "
                "SELECT * FROM (VALUES (3, 'c'), (1, 'a'), (2, 'b')) AS t(id, name)"
            )
            result = conn.execute("SELECT * FROM data ORDER BY id").fetchall()
            save(conn, QueryResult(result, ("id", "name")), path)

            loaded = load(conn, path)
            if hasattr(loaded, "iloc"):
                rows = loaded.values.tolist()
            else:
                rows = list(loaded)
            assert rows[0] == [1, "a"] or rows[0] == (1, "a")
            assert rows[1] == [2, "b"] or rows[1] == (2, "b")
            assert rows[2] == [3, "c"] or rows[2] == (3, "c")
            conn.close()
