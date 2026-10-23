"""Edge case functional tests for the pytest-duckdb plugin."""

from __future__ import annotations

import os
import tempfile

import duckdb
import pytest

from pytest_duckdb.snapshot import QueryResult, compare, load, save


@pytest.fixture
def snap_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


class TestSnapshotDirectoryPermission:
    """What happens when the snapshot directory is read-only?"""

    def test_save_to_readonly_dir_raises(self, snap_dir):
        path = os.path.join(snap_dir, "readonly", "snap.parquet")
        os.makedirs(os.path.dirname(path))
        os.chmod(os.path.dirname(path), 0o555)
        conn = duckdb.connect(":memory:")
        try:
            with pytest.raises((PermissionError, OSError, duckdb.IOException)):
                save(conn, QueryResult([(1,)], ("x",)), path)
        finally:
            os.chmod(os.path.dirname(path), 0o755)
            conn.close()


class TestCorruptSnapshot:
    """What happens when a snapshot Parquet file is corrupted?"""

    def test_load_corrupt_file_raises(self, snap_dir):
        path = os.path.join(snap_dir, "corrupt.parquet")
        with open(path, "wb") as f:
            f.write(b"NOT A PARQUET FILE AT ALL")
        conn = duckdb.connect(":memory:")
        try:
            with pytest.raises((duckdb.IOException, duckdb.InvalidInputException, Exception)):
                load(conn, path)
        finally:
            conn.close()

    def test_compare_corrupt_file_raises(self, snap_dir):
        path = os.path.join(snap_dir, "corrupt.parquet")
        with open(path, "wb") as f:
            f.write(b"\x00" * 100)
        conn = duckdb.connect(":memory:")
        try:
            with pytest.raises((duckdb.IOException, duckdb.InvalidInputException, Exception)):
                compare(conn, QueryResult([(1,)], ("x",)), path)
        finally:
            conn.close()


class TestEmptyEdgeCases:
    """Edge cases around empty data."""

    def test_empty_queryresult_save_load(self, snap_dir):
        """Empty QueryResult with columns saves/loads with schema intact."""
        path = os.path.join(snap_dir, "empty.parquet")
        conn = duckdb.connect(":memory:")
        try:
            save(conn, QueryResult([], ("id", "name", "value")), path)
            loaded = load(conn, path)
            if hasattr(loaded, "iloc"):
                assert list(loaded.columns) == ["id", "name", "value"]
                assert len(loaded) == 0
            else:
                assert list(loaded.columns) == ["id", "name", "value"]
                assert len(loaded) == 0
        finally:
            conn.close()

    def test_single_row_single_col(self, snap_dir):
        """Minimal table: 1 row, 1 column."""
        path = os.path.join(snap_dir, "minimal.parquet")
        conn = duckdb.connect(":memory:")
        try:
            save(conn, QueryResult([(42,)], ("x",)), path)
            compare(conn, QueryResult([(42,)], ("x",)), path)
        finally:
            conn.close()

    def test_all_nulls(self, snap_dir):
        """Table where every value is NULL."""
        path = os.path.join(snap_dir, "nulls.parquet")
        conn = duckdb.connect(":memory:")
        try:
            rows = [(None, None, None)] * 5
            save(conn, QueryResult(rows, ("a", "b", "c")), path)
            compare(conn, QueryResult(rows, ("a", "b", "c")), path)
        finally:
            conn.close()


class TestDuplicateRows:
    """Duplicate row handling."""

    def test_duplicate_rows_match(self, snap_dir):
        """Tables with duplicate rows should match if counts are equal."""
        path = os.path.join(snap_dir, "dupes.parquet")
        conn = duckdb.connect(":memory:")
        try:
            rows = [(1, "a"), (1, "a"), (2, "b")]
            save(conn, QueryResult(rows, ("id", "name")), path)
            compare(conn, QueryResult(rows, ("id", "name")), path)
        finally:
            conn.close()

    def test_different_duplicate_counts_fail(self, snap_dir):
        """Different number of duplicate rows should fail."""
        path = os.path.join(snap_dir, "dupes.parquet")
        conn = duckdb.connect(":memory:")
        try:
            original = [(1, "a"), (1, "a"), (2, "b")]
            modified = [(1, "a"), (2, "b")]
            save(conn, QueryResult(original, ("id", "name")), path)
            with pytest.raises(AssertionError, match="Snapshot mismatch"):
                compare(conn, QueryResult(modified, ("id", "name")), path)
        finally:
            conn.close()


class TestLargeData:
    """Larger datasets."""

    def test_1000_rows(self, snap_dir):
        """1000-row table roundtrips correctly."""
        path = os.path.join(snap_dir, "large.parquet")
        conn = duckdb.connect(":memory:")
        try:
            rows = [(i, f"val_{i}", float(i) * 1.5) for i in range(1000)]
            save(conn, QueryResult(rows, ("id", "name", "score")), path)
            compare(conn, QueryResult(rows, ("id", "name", "score")), path)
        finally:
            conn.close()


class TestMixedTypes:
    """Mixed type columns."""

    def test_bool_int_float_str(self, snap_dir):
        """Mixed types in a single table."""
        path = os.path.join(snap_dir, "mixed.parquet")
        conn = duckdb.connect(":memory:")
        try:
            rows = [
                (True, 1, 1.5, "hello"),
                (False, -1, 0.0, "world"),
            ]
            save(conn, QueryResult(rows, ("flag", "count", "score", "label")), path)
            compare(conn, QueryResult(rows, ("flag", "count", "score", "label")), path)
        finally:
            conn.close()

    def test_special_strings(self, snap_dir):
        """Strings with quotes, backslashes, newlines."""
        path = os.path.join(snap_dir, "special.parquet")
        conn = duckdb.connect(":memory:")
        try:
            rows = [
                ("it's",),
                ('say "hello"',),
                ("back\\slash",),
                ("new\nline",),
                ("tab\there",),
                ("emoji 🦆",),
            ]
            save(conn, QueryResult(rows, ("val",)), path)
            compare(conn, QueryResult(rows, ("val",)), path)
        finally:
            conn.close()


class TestConcurrentTableNames:
    """Verify temp table names don't collide across calls."""

    def test_multiple_compares_same_connection(self, snap_dir):
        """Multiple compare() calls on same connection don't conflict."""
        conn = duckdb.connect(":memory:")
        try:
            for i in range(5):
                path = os.path.join(snap_dir, f"snap_{i}.parquet")
                rows = [(i, f"v{i}")]
                save(conn, QueryResult(rows, ("id", "val")), path)
                compare(conn, QueryResult(rows, ("id", "val")), path)
        finally:
            conn.close()
