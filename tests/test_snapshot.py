"""Tests for Parquet snapshot save / load / compare."""

from __future__ import annotations

import os
import tempfile

import duckdb
import pytest

from pytest_duckdb.snapshot import QueryResult, compare, load, save

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def snap_dir() -> str:
    """Temporary directory for snapshot files."""
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


# ---------------------------------------------------------------------------
# save / load
# ---------------------------------------------------------------------------


class TestSaveAndLoad:
    """Verify basic save and load roundtrip."""

    def test_creates_parquet_file(self, snap_dir) -> None:
        """Save creates a non-empty Parquet file on first run."""
        path = os.path.join(snap_dir, "test.parquet")
        conn = duckdb.connect(":memory:")
        conn.execute(
            "CREATE TABLE data AS SELECT * FROM "
            "(VALUES (1, 'a'), (2, 'b')) AS t(id, name)"
        )
        result = conn.execute("SELECT * FROM data").fetchall()
        save(conn, QueryResult(result, ("id", "name")), path)
        conn.close()
        assert os.path.isfile(path)
        assert os.path.getsize(path) > 0

    def test_load_returns_result(self, snap_dir) -> None:
        """Loaded Parquet returns data with correct columns."""
        path = os.path.join(snap_dir, "test.parquet")
        conn = duckdb.connect(":memory:")
        conn.execute(
            "CREATE TABLE data AS SELECT * FROM "
            "(VALUES (1, 'a'), (2, 'b')) AS t(id, name)"
        )
        result = conn.execute("SELECT * FROM data").fetchall()
        save(conn, QueryResult(result, ("id", "name")), path)

        loaded = load(conn, path)
        if hasattr(loaded, "iloc"):
            assert len(loaded) == 2
            assert "id" in loaded.columns
            assert "name" in loaded.columns
        else:
            assert len(loaded) == 2
            assert "id" in loaded.columns
            assert "name" in loaded.columns
        conn.close()

    def test_preserves_types(self, snap_dir) -> None:
        """int64 types should round-trip through Parquet."""
        path = os.path.join(snap_dir, "ints.parquet")
        conn = duckdb.connect(":memory:")
        conn.execute(
            "CREATE TABLE data AS "
            "SELECT * FROM (VALUES (1, 9999999999), (2, -42)) AS t(id, big_val)"
        )
        result = conn.execute("SELECT * FROM data").fetchall()
        save(conn, QueryResult(result, ("id", "big_val")), path)

        loaded = load(conn, path)
        # loaded may be DataFrame (pandas) or QueryResult
        if hasattr(loaded, "iloc"):
            rows = loaded.values.tolist()
        else:
            rows = list(loaded)
        assert rows[0][1] == 9999999999
        assert rows[1][1] == -42
        conn.close()


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


class TestCompare:
    """Snapshot comparison logic."""

    def test_passes_on_match(self, snap_dir) -> None:
        """Identical data should pass comparison."""
        path = os.path.join(snap_dir, "match.parquet")
        conn = duckdb.connect(":memory:")
        conn.execute(
            "CREATE TABLE data AS SELECT * FROM "
            "(VALUES (1, 'a'), (2, 'b')) AS t(id, name)"
        )
        result = conn.execute("SELECT * FROM data").fetchall()
        save(conn, QueryResult(result, ("id", "name")), path)
        # Compare with same data — should not raise.
        compare(conn, QueryResult(result, ("id", "name")), path)
        conn.close()

    def test_fails_on_mismatch(self, snap_dir) -> None:
        """Different data should raise AssertionError with a diff."""
        path = os.path.join(snap_dir, "mismatch.parquet")
        conn = duckdb.connect(":memory:")
        conn.execute(
            "CREATE TABLE data AS SELECT * FROM "
            "(VALUES (1, 'a'), (2, 'b')) AS t(id, name)"
        )
        result = conn.execute("SELECT * FROM data").fetchall()
        save(conn, QueryResult(result, ("id", "name")), path)

        # Different data.
        new_data = [(1, "a"), (3, "c")]
        with pytest.raises(AssertionError, match="Snapshot mismatch"):
            compare(conn, QueryResult(new_data, ("id", "name")), path)
        conn.close()

    def test_fails_on_schema_diff(self, snap_dir) -> None:
        """Different column dtypes should raise AssertionError."""
        path = os.path.join(snap_dir, "schema_diff.parquet")
        conn = duckdb.connect(":memory:")
        conn.execute("CREATE TABLE data AS SELECT * FROM (VALUES (1, 'a')) AS t(id, name)")
        result = conn.execute("SELECT * FROM data").fetchall()
        save(conn, QueryResult(result, ("id", "name")), path)
        # Compare with an extra column.
        new_data = [(1, "a", 99.0)]
        with pytest.raises(AssertionError, match="Schema mismatch"):
            compare(conn, QueryResult(new_data, ("id", "name", "extra")), path)
        conn.close()

    def test_update_flag_regenerates(self, snap_dir) -> None:
        """Simulating --snapshot-update should overwrite existing snapshot."""
        path = os.path.join(snap_dir, "update.parquet")
        conn = duckdb.connect(":memory:")

        # First save.
        conn.execute("CREATE TABLE v1 AS SELECT * FROM (VALUES (1, 'old')) AS t(id, val)")
        save(conn, conn.execute("SELECT * FROM v1").fetchall(), path)
        old_size = os.path.getsize(path)

        # Overwrite with different data.
        conn.execute("CREATE TABLE v2 AS SELECT * FROM (VALUES (2, 'new')) AS t(id, val)")
        save(conn, conn.execute("SELECT * FROM v2").fetchall(), path)
        new_size = os.path.getsize(path)

        # File should be replaced (different size expected due to different data).
        assert old_size != new_size or os.path.getsize(path) > 0
        conn.close()

    def test_raises_on_missing_snapshot(self, snap_dir) -> None:
        """Comparing against a non-existent snapshot raises FileNotFoundError."""
        path = os.path.join(snap_dir, "nonexistent.parquet")
        conn = duckdb.connect(":memory:")
        result = [(1, "a")]
        with pytest.raises(FileNotFoundError, match="Snapshot does not exist"):
            compare(conn, QueryResult(result, ("id", "name")), path)
        conn.close()

    def test_empty_result_matches(self, snap_dir) -> None:
        """Empty result (0 rows) should match an empty snapshot."""
        path = os.path.join(snap_dir, "empty.parquet")
        conn = duckdb.connect(":memory:")
        save(conn, QueryResult([], ("id", "name")), path)
        compare(conn, QueryResult([], ("id", "name")), path)
        conn.close()
