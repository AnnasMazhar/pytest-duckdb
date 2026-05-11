"""Tests for fixture schema parsing and integration."""

from __future__ import annotations

import os

import duckdb
import pytest

from pytest_duckdb.fixtures import _parse_fixture_schemas, load_csvs


class TestParseFixtureSchemas:
    """Unit tests for the ``_parse_fixture_schemas`` helper."""

    def test_empty_string(self) -> None:
        """Empty string returns an empty dict."""
        assert _parse_fixture_schemas("") == {}

    def test_blank_lines(self) -> None:
        """Blank lines are ignored."""
        assert _parse_fixture_schemas("  \n\n \n") == {}

    def test_single_table(self) -> None:
        """A single table: col TYPE pair is parsed correctly."""
        result = _parse_fixture_schemas("orders: order_id INTEGER")
        assert result == {"orders": [("order_id", "INTEGER")]}

    def test_multiple_columns(self) -> None:
        """Multiple columns for one table, comma-separated."""
        result = _parse_fixture_schemas(
            "orders: order_id INTEGER, amount DOUBLE, customer_id INTEGER"
        )
        assert result == {
            "orders": [
                ("order_id", "INTEGER"),
                ("amount", "DOUBLE"),
                ("customer_id", "INTEGER"),
            ]
        }

    def test_multiple_tables(self) -> None:
        """Multiple tables, one per line."""
        result = _parse_fixture_schemas(
            "orders: order_id INTEGER, amount DOUBLE\n"
            "customers: id INTEGER, name VARCHAR"
        )
        assert result == {
            "orders": [("order_id", "INTEGER"), ("amount", "DOUBLE")],
            "customers": [("id", "INTEGER"), ("name", "VARCHAR")],
        }

    def test_whitespace_tolerant(self) -> None:
        """Extra whitespace around table name and columns is tolerated."""
        result = _parse_fixture_schemas(
            "  orders  :  order_id  INTEGER ,  amount  DOUBLE  "
        )
        assert result == {
            "orders": [("order_id", "INTEGER"), ("amount", "DOUBLE")]
        }

    def test_comment_lines_ignored(self) -> None:
        """Lines starting with ``#`` are ignored."""
        result = _parse_fixture_schemas(
            "# this is a comment\n"
            "orders: id INTEGER\n"
            "  # indented comment\n"
        )
        assert result == {"orders": [("id", "INTEGER")]}

    def test_table_name_with_underscore(self) -> None:
        """Table names with underscores are handled."""
        result = _parse_fixture_schemas(
            "order_items: id INTEGER, product_name VARCHAR"
        )
        assert result == {
            "order_items": [("id", "INTEGER"), ("product_name", "VARCHAR")]
        }

    def test_type_with_parameters(self) -> None:
        """Types with parameters (e.g. VARCHAR(255)) are handled."""
        result = _parse_fixture_schemas(
            "users: name VARCHAR(255), score DECIMAL(10,2)"
        )
        assert result == {
            "users": [
                ("name", "VARCHAR(255)"),
                ("score", "DECIMAL(10,2)"),
            ]
        }


class TestLoadCsvsWithSchemas:
    """Integration tests for ``load_csvs`` with explicit schemas."""

    def _make_csv(self, path: str, header: str, *rows: str) -> None:
        """Write a CSV file with header and rows."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(header + "\n")
            for row in rows:
                f.write(row + "\n")

    def test_schema_overrides_inferred_type(self, tmp_path: str) -> None:
        """Explicit VARCHAR schema overrides read_csv_auto INTEGER inference."""
        csv_dir = os.path.join(tmp_path, "fixtures")
        self._make_csv(
            os.path.join(csv_dir, "items.csv"),
            "value",
            "1",
            "2",
            "3",
        )

        conn = duckdb.connect(":memory:")
        schemas = {"items": [("value", "VARCHAR")]}
        load_csvs(conn, csv_dir, schemas=schemas)

        rows = conn.execute(
            "SELECT typeof(value) AS t, value FROM items ORDER BY value"
        ).fetchall()
        conn.close()

        assert len(rows) == 3
        for t, _value in rows:
            assert t == "VARCHAR", f"Expected VARCHAR, got {t}"

    def test_schema_not_matching_columns_still_loads(self, tmp_path: str) -> None:
        """Schema with a subset of columns still loads; only declared cols."""
        csv_dir = os.path.join(tmp_path, "fixtures")
        self._make_csv(
            os.path.join(csv_dir, "data.csv"),
            "a,b,c",
            "1,x,true",
            "2,y,false",
        )

        conn = duckdb.connect(":memory:")
        schemas = {"data": [("a", "INTEGER"), ("b", "VARCHAR")]}
        load_csvs(conn, csv_dir, schemas=schemas)

        cols = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'data' ORDER BY ordinal_position"
        ).fetchall()
        conn.close()

        # Only 2 columns because schema only declares 2;
        # BY NAME matching silently drops undeclared column ``c``.
        assert len(cols) == 2, f"Expected 2 columns, got {len(cols)}"
        assert cols[0] == ("a", "INTEGER")
        assert cols[1] == ("b", "VARCHAR")

    def test_no_schema_fallback(self, tmp_path: str) -> None:
        """Tables without a schema entry use read_csv_auto as before."""
        csv_dir = os.path.join(tmp_path, "fixtures")
        self._make_csv(
            os.path.join(csv_dir, "nums.csv"),
            "x",
            "42",
            "99",
        )
        self._make_csv(
            os.path.join(csv_dir, "labels.csv"),
            "name",
            "hello",
        )

        conn = duckdb.connect(":memory:")
        schemas = {"nums": [("x", "VARCHAR")]}  # only nums gets a schema
        load_csvs(conn, csv_dir, schemas=schemas)

        nums_type = conn.execute("SELECT typeof(x) FROM nums").fetchone()
        labels_type = conn.execute("SELECT typeof(name) FROM labels").fetchone()
        conn.close()

        assert nums_type[0] == "VARCHAR", f"Expected VARCHAR, got {nums_type[0]}"
        assert labels_type[0] == "VARCHAR", (
            f"Expected VARCHAR, got {labels_type[0]}"
        )

    def test_multiple_tables_with_schemas(self, tmp_path: str) -> None:
        """Multiple tables each get their own explicit schema."""
        csv_dir = os.path.join(tmp_path, "fixtures")
        self._make_csv(os.path.join(csv_dir, "a.csv"), "v", "1", "2")
        self._make_csv(os.path.join(csv_dir, "b.csv"), "w", "3.14", "2.71")

        conn = duckdb.connect(":memory:")
        schemas = {
            "a": [("v", "BIGINT")],
            "b": [("w", "DOUBLE")],
        }
        load_csvs(conn, csv_dir, schemas=schemas)

        a_type = conn.execute("SELECT typeof(v) FROM a").fetchone()
        b_type = conn.execute("SELECT typeof(w) FROM b").fetchone()
        conn.close()

        assert a_type[0] == "BIGINT", f"Expected BIGINT, got {a_type[0]}"
        assert b_type[0] == "DOUBLE", f"Expected DOUBLE, got {b_type[0]}"


class TestFixtureSchemasPytester:
    """End-to-end pytester integration for ``duckdb_fixture_schemas`` ini."""

    def test_schema_from_ini_file(self, pytester: pytest.Pytester) -> None:
        """``duckdb_fixture_schemas`` in ini applies explicit types."""
        pytester.makefile(".csv", items="value\n1\n2\n")
        os.makedirs(os.path.join(pytester.path, "tests"), exist_ok=True)

        pytester.makeini(
            "[pytest]\n"
            "duckdb_fixtures_dir = .\n"
            "duckdb_fixture_schemas =\n"
            "    items: value VARCHAR\n"
        )

        pytester.makepyfile(
            test_schema="""
                def test_type_override(duckdb_session):
                    conn = duckdb_session
                    result = conn.execute(
                        "SELECT typeof(value) FROM items"
                    ).fetchone()
                    assert result[0] == 'VARCHAR', f"got {result[0]}"
            """,
        )

        result = pytester.runpytest_subprocess("-v")
        result.assert_outcomes(passed=1)

    def test_schema_prevents_timestamp_mismatch(
        self, pytester: pytest.Pytester
    ) -> None:
        """Explicit type prevents date-like strings being inferred as DATE."""
        pytester.makefile(
            ".csv",
            events="ts,event\n2024-01-15,login\n2024-06-20,logout\n",
        )
        os.makedirs(os.path.join(pytester.path, "tests"), exist_ok=True)

        pytester.makeini(
            "[pytest]\n"
            "duckdb_fixtures_dir = .\n"
            "duckdb_fixture_schemas =\n"
            "    events: ts VARCHAR, event VARCHAR\n"
        )

        pytester.makepyfile(
            test_text_dates="""
                def test_ts_is_text(duckdb_session):
                    conn = duckdb_session
                    t = conn.execute("SELECT typeof(ts) FROM events"
                    ).fetchone()[0]
                    assert t == 'VARCHAR', f"got {t}"
            """,
        )

        result = pytester.runpytest_subprocess("-v")
        result.assert_outcomes(passed=1)
