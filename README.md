# pytest-duckdb

[![CI](https://github.com/AnnasMazhar/pytest-duckdb/actions/workflows/ci.yml/badge.svg)](https://github.com/AnnasMazhar/pytest-duckdb/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pytest-duckdb.svg)](https://pypi.org/project/pytest-duckdb/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-duckdb.svg)](https://pypi.org/project/pytest-duckdb/)

A pytest plugin for testing SQL pipelines. Drop CSVs in a folder, write SQL, assert on results. Optional Parquet snapshot testing for regression detection.

No Docker. No dbt. No ORM.

## Install

```bash
pip install pytest-duckdb
```

## How it works

1. Place CSV files in `tests/fixtures/` — each becomes a DuckDB table (filename = table name)
2. Write tests using the `duckdb_session` fixture — a fresh in-memory DuckDB per test
3. Optionally snapshot results to Parquet for regression testing

## Fixtures

### `duckdb_session` (function-scoped)

A fresh `:memory:` DuckDB connection with all CSVs from the fixtures directory auto-loaded as tables.

```python
def test_orders_exist(duckdb_session):
    count = duckdb_session.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert count == 10
```

Each test gets complete isolation — tables created in one test don't leak to another.

### `sql_snapshot` (function-scoped)

Callable fixture for Parquet-based snapshot testing:

```python
def test_revenue(duckdb_session, sql_snapshot):
    result = duckdb_session.execute("""
        SELECT customer_id, SUM(amount) as total
        FROM orders GROUP BY customer_id
    """).fetchdf()
    sql_snapshot(result)
```

- **First run:** saves result to `tests/__snapshots__/{module}_{test}.parquet`
- **Subsequent runs:** compares against stored snapshot, raises `AssertionError` with a clear diff on mismatch (shows which rows/columns differ)
- **Regenerate:** `pytest --snapshot-update`

### `sql_result` (function-scoped)

Executes a `.sql` file referenced by the `@pytest.mark.sql` marker:

```python
@pytest.mark.sql("queries/revenue_by_customer.sql")
def test_revenue_query(sql_result):
    assert len(sql_result) > 0
```

The SQL file runs against `duckdb_session`, so it has access to all loaded CSV tables.

## Return types

- **pandas installed:** fixtures return `DataFrame`
- **pandas not installed:** fixtures return `QueryResult` (list-of-tuples with a `.columns` attribute)

## Configuration

In `pyproject.toml` or `pytest.ini`:

```toml
[tool.pytest.ini_options]
duckdb_fixtures_dir = "tests/fixtures"    # default
duckdb_snapshots_dir = "tests/__snapshots__"  # default
```

### CLI options

```
--snapshot-update          Regenerate all Parquet snapshots
--duckdb-fixtures-dir=PATH Override fixture directory
```

## Example project structure

```
tests/
├── fixtures/
│   ├── orders.csv          → becomes `orders` table
│   └── customers.csv       → becomes `customers` table
├── queries/
│   ├── simple.sql
│   └── join.sql
├── __snapshots__/          → auto-created on first snapshot run
├── test_queries.py
└── test_transforms.py
```

## Combining fixtures

```python
@pytest.mark.sql("queries/monthly_revenue.sql")
def test_monthly_revenue(sql_result, sql_snapshot):
    # sql_result runs the SQL file against loaded CSVs
    # sql_snapshot saves/compares the result
    sql_snapshot(sql_result)
```

## Requirements

- Python 3.9+
- pytest ≥ 7.0
- duckdb ≥ 0.9.0
- pandas (optional — for DataFrame returns)

## License

MIT
