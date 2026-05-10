# pytest-duckdb

[![CI](https://github.com/AnnasMazhar/pytest-duckdb/actions/workflows/ci.yml/badge.svg)](https://github.com/AnnasMazhar/pytest-duckdb/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pytest-duckdb.svg)](https://pypi.org/project/pytest-duckdb/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-duckdb.svg)](https://pypi.org/project/pytest-duckdb/)

SQL pipeline testing made trivial. Load fixture CSVs as tables, run your queries, snapshot the results.

## Install

```bash
pip install pytest-duckdb
```

## Quick Start

```python
def test_revenue_query(duckdb_session, sql_snapshot):
    result = duckdb_session.sql("SELECT * FROM orders WHERE amount > 100").df()
    assert result == sql_snapshot
```

First run saves the snapshot. Subsequent runs diff against it.

## Features

- **Zero config** — fixture CSVs in `tests/fixtures/` auto-load as tables
- **Snapshot testing** — first run saves output, subsequent runs diff
- **Raw SQL files** — test `.sql` files directly without dbt
- **Ephemeral** — each test gets a fresh in-memory DuckDB
- **Fast** — DuckDB is embedded, no Docker, no network

## Fixture Loading

Place CSV files in `tests/fixtures/`:

```
tests/
  fixtures/
    orders.csv
    customers.csv
  test_queries.py
```

They become tables automatically:

```python
def test_join(duckdb_session):
    result = duckdb_session.sql("""
        SELECT c.name, o.amount
        FROM orders o JOIN customers c ON o.customer_id = c.id
    """).df()
    assert len(result) > 0
```

## SQL File Testing

```python
@pytest.mark.sql("queries/revenue_by_month.sql")
def test_revenue_by_month(sql_result, sql_snapshot):
    assert sql_result == sql_snapshot
```

## License

MIT
