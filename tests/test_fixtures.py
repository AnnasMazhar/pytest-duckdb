"""Tests for CSV fixture auto-loading via the duckdb_session fixture."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Basic smoke tests using the auto-loaded duckdb_session
# ---------------------------------------------------------------------------


class TestCsvAutoLoad:
    """Verify that CSV files in ``tests/fixtures/`` are loaded as tables."""

    def test_csv_auto_loaded(self, duckdb_session) -> None:
        """The ``orders`` table should exist after duckdb_session starts."""
        tables = duckdb_session.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
        table_names = {r[0] for r in tables}
        assert "orders" in table_names, f"orders table not found: {table_names}"

    def test_correct_columns(self, duckdb_session) -> None:
        """Column names should match the CSV header row."""
        cols = duckdb_session.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'orders' AND table_schema = 'main' "
            "ORDER BY ordinal_position"
        ).fetchall()
        col_names = [c[0] for c in cols]
        assert col_names == ["id", "customer_id", "amount", "created_at"]

    def test_correct_row_count(self, duckdb_session) -> None:
        """Orders CSV has 10 rows; customers has 5."""
        assert duckdb_session.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 10
        assert duckdb_session.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0] == 5

    def test_type_inference(self, duckdb_session) -> None:
        """``amount`` should be inferred as a numeric type, not VARCHAR."""
        types = duckdb_session.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'orders' AND column_name = 'amount'"
        ).fetchall()
        assert len(types) == 1
        dtype = types[0][0]
        assert "BIGINT" in dtype or "INT" in dtype or "DOUBLE" in dtype or (
            "FLOAT" in dtype or "NUMERIC" in dtype or "DECIMAL" in dtype
        ), (
            f"amount has unexpected type: {dtype}"
        )

    def test_customers_loaded(self, duckdb_session) -> None:
        """Customers table should have the expected columns."""
        cols = duckdb_session.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'customers' AND table_schema = 'main' "
            "ORDER BY ordinal_position"
        ).fetchall()
        col_names = [c[0] for c in cols]
        assert col_names == ["id", "name", "email"]

    def test_can_query_orders(self, duckdb_session) -> None:
        """Basic query against orders table works."""
        rows = duckdb_session.execute(
            "SELECT id, amount FROM orders WHERE amount > 100 ORDER BY id"
        ).fetchall()
        assert len(rows) == 4  # 150, 200, 500, 300
        amounts = [r[1] for r in rows]
        assert all(a > 100 for a in amounts)


# ---------------------------------------------------------------------------
# pytester-based tests (run in subprocess with custom config)
# ---------------------------------------------------------------------------


class TestCustomDir:
    """Tests using pytester to verify custom fixture directories."""

    def test_custom_dir(self, pytester: pytest.Pytester) -> None:
        """Custom fixture directory configured via pytest.ini."""
        pytester.makeini(
            """
            [pytest]
            duckdb_fixtures_dir = custom_fixtures
            """
        )
        pytester.mkdir("custom_fixtures")
        pytester.makefile(
            ".csv",
            **{"custom_fixtures/products": "id,name,price\n1,Gadget,19.99\n2,Widget,29.99\n"},
        )
        pytester.makepyfile(
            """
            def test_custom_dir(duckdb_session):
                tables = duckdb_session.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'main'"
                ).fetchall()
                names = {r[0] for r in tables}
                assert "products" in names
                count = duckdb_session.execute(
                    "SELECT COUNT(*) FROM products"
                ).fetchone()[0]
                assert count == 2
            """
        )
        result = pytester.runpytest("--no-header")
        result.assert_outcomes(passed=1)

    def test_missing_dir_no_error(self, pytester: pytest.Pytester) -> None:
        """Missing fixture directory should not error — empty DB works."""
        pytester.makeini(
            """
            [pytest]
            duckdb_fixtures_dir = nonexistent_fixtures
            """
        )
        pytester.makepyfile(
            """
            def test_empty_db(duckdb_session):
                tables = duckdb_session.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'main'"
                ).fetchall()
                assert len(tables) == 0
            """
        )
        result = pytester.runpytest("--no-header")
        result.assert_outcomes(passed=1)
