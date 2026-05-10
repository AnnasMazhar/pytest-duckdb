"""Tests for the ``@pytest.mark.sql`` marker and ``sql_result`` fixture."""

from __future__ import annotations

import pytest

from pytest_duckdb.fixtures import read_sql_file


class TestReadSqlFile:
    """Unit tests for the ``read_sql_file`` helper."""

    def test_reads_sql_content(self) -> None:
        """simple.sql should be readable and contain valid SQL."""
        sql = read_sql_file("tests/queries/simple.sql")
        assert "SELECT" in sql
        assert "orders" in sql

    def test_file_not_found(self) -> None:
        """Non-existent file raises ``FileNotFoundError``."""
        with pytest.raises(FileNotFoundError, match="SQL file not found"):
            read_sql_file("tests/queries/nonexistent.sql")


class TestSqlMarkerPytester:
    """Integration tests using pytester to exercise the marker + fixture."""

    def test_executes_sql_file(self, pytester: pytest.Pytester) -> None:
        """``sql_result`` executes the SQL file referenced by the marker."""
        # Create fixtures and queries inside pytester's temp dir
        pytester.mkdir("tests")
        pytester.mkdir("tests/fixtures")
        pytester.mkdir("tests/queries")
        pytester.makefile(
            ".csv",
            **{"tests/fixtures/orders": (
                "id,customer_id,amount,created_at\n"
                "1,1,25.50,2024-01-01\n"
                "2,1,150.00,2024-01-02\n"
            )},
        )
        pytester.makefile(
            ".sql",
            **{"tests/queries/simple": "SELECT * FROM orders WHERE amount > 50"},
        )
        pytester.makepyfile(
            test_simple="""
            import pytest

            @pytest.mark.sql("tests/queries/simple.sql")
            def test_returns_rows(sql_result):
                assert sql_result is not None
                assert len(sql_result) > 0
            """
        )
        result = pytester.runpytest("--no-header", "-v")
        result.assert_outcomes(passed=1)

    def test_uses_fixture_tables(self, pytester: pytest.Pytester) -> None:
        """SQL query references the auto-loaded CSV tables."""
        pytester.mkdir("tests")
        pytester.mkdir("tests/fixtures")
        pytester.mkdir("tests/queries")
        pytester.makefile(
            ".csv",
            **{
                "tests/fixtures/orders": (
                    "id,customer_id,amount,created_at\n"
                    "1,1,25.50,2024-01-01\n"
                    "2,1,150.00,2024-01-02\n"
                    "3,2,75.00,2024-01-03\n"
                ),
                "tests/fixtures/customers": (
                    "id,name,email\n"
                    "1,Alice,alice@example.com\n"
                    "2,Bob,bob@example.com\n"
                ),
            },
        )
        pytester.makefile(
            ".sql",
            **{"tests/queries/join": (
                "SELECT c.name, SUM(o.amount) as total\n"
                "FROM orders o\n"
                "JOIN customers c ON o.customer_id = c.id\n"
                "GROUP BY c.name\n"
                "ORDER BY total DESC"
            )},
        )
        pytester.makepyfile(
            test_join="""
            import pytest

            @pytest.mark.sql("tests/queries/join.sql")
            def test_join_works(sql_result):
                assert sql_result is not None
                rows = list(sql_result)
                assert len(rows) == 2
            """
        )
        result = pytester.runpytest("--no-header", "-v")
        result.assert_outcomes(passed=1)

    def test_missing_file_error(self, pytester: pytest.Pytester) -> None:
        """Missing SQL file should produce a clear error message."""
        pytester.makepyfile(
            test_missing="""
            import pytest

            @pytest.mark.sql("tests/queries/missing.sql")
            def test_missing(sql_result):
                pass
            """
        )
        result = pytester.runpytest("--no-header")
        result.assert_outcomes(errors=1)
        result.stdout.fnmatch_lines(["*FileNotFoundError*"])
