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
def test_revenue_query(duckdb_session, sql_snapshot):
    result = duckdb_session.execute(
        "SELECT * FROM orders WHERE amount > 100"
    ).fetchall()

    # First run saves the snapshot, subsequent runs diff against it
    sql_snapshot(result)
```

## Features

- **Zero config** — fixture CSVs in `tests/fixtures/` auto-load as tables
- **Snapshot testing** — first run saves output, subsequent runs diff
- **Raw SQL files** — test `.sql` files directly without dbt
- **Ephemeral** — each test gets a fresh in-memory DuckDB
- **Fast** — DuckDB is embedded, no Docker, no network

## Fixture Loading

CSVs loaded by file stem become table names. `orders.csv` → `orders` table.

```python
def test_join(duckdb_session):
    result = duckdb_session.execute("""
        SELECT c.name, o.amount
        FROM orders o JOIN customers c ON o.customer_id = c.id
    """).fetchall()
    assert len(result) > 0
```

## SQL File Testing

```python
@pytest.mark.sql("queries/revenue_by_month.sql")
def test_revenue_by_month(sql_result, sql_snapshot):
    sql_snapshot(sql_result)
```

## Snapshot Update

Regenerate all snapshots when your expected output changes:

```bash
pytest --snapshot-update
```

## License

MIT
