"""Tests for v0.2.0 bug fixes and new features."""

from __future__ import annotations

import os

import duckdb
import pytest

from pytest_duckdb.fixtures import load_fixtures
from pytest_duckdb.snapshot import QueryResult, compare, load, save

# ---------------------------------------------------------------------------
# SQL injection fix — parameterized queries
# ---------------------------------------------------------------------------


class TestParameterizedQueries:
    """Verify file paths with special chars don't break SQL."""

    def test_fixture_path_with_quotes(self, tmp_path) -> None:
        """CSV path containing a single quote loads without SQL injection."""
        weird_dir = tmp_path / "it's a dir"
        weird_dir.mkdir()
        csv = weird_dir / "data.csv"
        csv.write_text("id,val\n1,hello\n")

        conn = duckdb.connect(":memory:")
        load_fixtures(conn, str(weird_dir))
        rows = conn.execute("SELECT * FROM data").fetchall()
        assert rows == [(1, "hello")]
        conn.close()

    def test_snapshot_save_path_with_quotes(self, tmp_path) -> None:
        """Snapshot save to a path with quotes works."""
        path = str(tmp_path / "it's a snap.parquet")
        conn = duckdb.connect(":memory:")
        save(conn, QueryResult([(1, "a")], ("id", "name")), path)
        assert os.path.isfile(path)
        conn.close()

    def test_snapshot_load_path_with_quotes(self, tmp_path) -> None:
        """Snapshot load from a path with quotes works."""
        path = str(tmp_path / "it's a snap.parquet")
        conn = duckdb.connect(":memory:")
        save(conn, QueryResult([(1, "a")], ("id", "name")), path)
        loaded = load(conn, path)
        assert len(loaded) == 1
        conn.close()

    def test_snapshot_compare_path_with_quotes(self, tmp_path) -> None:
        """Snapshot compare with a path containing quotes works."""
        path = str(tmp_path / "it's a snap.parquet")
        conn = duckdb.connect(":memory:")
        data = QueryResult([(1, "a")], ("id", "name"))
        save(conn, data, path)
        compare(conn, data, path)  # Should not raise
        conn.close()


# ---------------------------------------------------------------------------
# Empty snapshot schema mismatch
# ---------------------------------------------------------------------------


class TestEmptySnapshotSchema:
    """Empty QueryResult should save/load/compare without schema errors."""

    def test_empty_result_roundtrip(self, tmp_path) -> None:
        """Empty QueryResult saves and loads back correctly."""
        path = str(tmp_path / "empty.parquet")
        conn = duckdb.connect(":memory:")
        save(conn, QueryResult([], ("id", "name")), path)
        loaded = load(conn, path)
        assert len(loaded) == 0
        conn.close()

    def test_empty_result_compare_passes(self, tmp_path) -> None:
        """Two empty QueryResults with same schema compare equal."""
        path = str(tmp_path / "empty.parquet")
        conn = duckdb.connect(":memory:")
        save(conn, QueryResult([], ("x", "y")), path)
        compare(conn, QueryResult([], ("x", "y")), path)
        conn.close()


# ---------------------------------------------------------------------------
# Empty list in _register_temp
# ---------------------------------------------------------------------------


class TestEmptyList:
    """Bare empty list [] should not produce invalid SQL."""

    def test_empty_list_saves(self, tmp_path) -> None:
        """Saving a bare empty list doesn't crash."""
        path = str(tmp_path / "empty_list.parquet")
        conn = duckdb.connect(":memory:")
        save(conn, [], path)
        assert os.path.isfile(path)
        conn.close()


# ---------------------------------------------------------------------------
# Empty marker path
# ---------------------------------------------------------------------------


class TestEmptyMarkerPath:
    """@pytest.mark.sql('') should raise ValueError."""

    def test_empty_string_raises(self, pytester: pytest.Pytester) -> None:
        """Empty path in sql marker raises ValueError with clear message."""
        pytester.makepyfile(
            """
            import pytest

            @pytest.mark.sql("")
            def test_empty(sql_result):
                pass
            """
        )
        result = pytester.runpytest("--no-header")
        result.stdout.fnmatch_lines(["*ValueError*non-empty path*"])

    def test_no_args_raises(self, pytester: pytest.Pytester) -> None:
        """No args in sql marker raises ValueError."""
        pytester.makepyfile(
            """
            import pytest

            @pytest.mark.sql()
            def test_no_args(sql_result):
                pass
            """
        )
        result = pytester.runpytest("--no-header")
        result.stdout.fnmatch_lines(["*ValueError*non-empty path*"])


# ---------------------------------------------------------------------------
# --duckdb-snapshots-dir CLI flag
# ---------------------------------------------------------------------------


class TestSnapshotsDirFlag:
    """--duckdb-snapshots-dir CLI flag works."""

    def test_cli_flag(self, pytester: pytest.Pytester) -> None:
        """Snapshots go to the directory specified by CLI flag."""
        snap_dir = pytester.mkdir("custom_snaps")
        pytester.mkdir("tests")
        pytester.mkdir("tests/fixtures")
        pytester.makefile(
            ".csv",
            **{"tests/fixtures/items": "id,name\n1,foo\n"},
        )
        pytester.makepyfile(
            """
            from pytest_duckdb.snapshot import QueryResult

            def test_snap(sql_snapshot, duckdb_session):
                result = duckdb_session.execute("SELECT * FROM items").fetchall()
                sql_snapshot(QueryResult(result, ("id", "name")))
            """
        )
        result = pytester.runpytest("--no-header", f"--duckdb-snapshots-dir={snap_dir}")
        result.assert_outcomes(passed=1)
        # Verify file was created in custom dir
        snaps = list(snap_dir.iterdir())
        assert len(snaps) == 1
        assert snaps[0].suffix == ".parquet"


# ---------------------------------------------------------------------------
# Parquet and JSON fixture loading
# ---------------------------------------------------------------------------


class TestMultiFormatFixtures:
    """Parquet and JSON files are loaded as tables."""

    def test_parquet_fixture(self, tmp_path) -> None:
        """Parquet files in fixtures dir are loaded as tables."""
        conn = duckdb.connect(":memory:")
        # Create a parquet file
        conn.execute("CREATE TABLE tmp AS SELECT 1 AS id, 'test' AS val")
        conn.execute(f"COPY tmp TO '{tmp_path / 'data.parquet'}' (FORMAT PARQUET)")
        conn.execute("DROP TABLE tmp")
        conn.close()

        conn = duckdb.connect(":memory:")
        load_fixtures(conn, str(tmp_path))
        rows = conn.execute("SELECT * FROM data").fetchall()
        assert rows == [(1, "test")]
        conn.close()

    def test_json_fixture(self, tmp_path) -> None:
        """JSON files in fixtures dir are loaded as tables."""
        json_file = tmp_path / "items.json"
        json_file.write_text('[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]')

        conn = duckdb.connect(":memory:")
        load_fixtures(conn, str(tmp_path))
        rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
        assert rows == [(1, "a"), (2, "b")]
        conn.close()

    def test_mixed_formats(self, tmp_path) -> None:
        """CSV, Parquet, and JSON all load together."""
        # CSV
        (tmp_path / "csv_table.csv").write_text("id,val\n1,x\n")
        # JSON
        (tmp_path / "json_table.json").write_text('[{"id": 2, "val": "y"}]')
        # Parquet
        conn = duckdb.connect(":memory:")
        conn.execute("CREATE TABLE tmp AS SELECT 3 AS id, 'z' AS val")
        conn.execute(f"COPY tmp TO '{tmp_path / 'parquet_table.parquet'}' (FORMAT PARQUET)")
        conn.close()

        conn = duckdb.connect(":memory:")
        load_fixtures(conn, str(tmp_path))
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
        names = [r[0] for r in tables]
        assert "csv_table" in names
        assert "json_table" in names
        assert "parquet_table" in names
        conn.close()
