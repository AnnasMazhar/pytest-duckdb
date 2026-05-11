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

## Config Reference

You can configure DuckDB behaviour via `pyproject.toml` or `pytest.ini`:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `duckdb_fixtures_dir` | `string` | `tests/fixtures` | CSV fixture directory |
| `duckdb_snapshots_dir` | `string` | `tests/__snapshots__` | Parquet snapshot directory |
| `duckdb_config` | `string` (multiline) | `""` | DuckDB session config (see below) |
| `duckdb_fixture_schemas` | `string` (multiline) | `""` | Explicit CSV column types |

### `duckdb_config`

Pass DuckDB configuration options at connection time:

```ini
# pyproject.toml or pytest.ini
[tool.pytest.ini_options]
duckdb_config = """
    default_order = desc
    threads = 4
"""
```

Or via the CLI:

```bash
pytest --duckdb-config default_order=desc
```

### `duckdb_fixture_schemas`

Prevent non-deterministic `read_csv_auto` type inference by declaring column types explicitly:

```ini
[tool.pytest.ini_options]
duckdb_fixture_schemas = """
    orders: order_id INTEGER, amount DOUBLE, customer_id INTEGER
    customers: id INTEGER, name VARCHAR
"""
```

When a schema is provided, the specified types are enforced at table creation time.
Columns not listed in the schema are silently dropped. Types with parameters
(e.g., `VARCHAR(255)`, `DECIMAL(10,2)`) are fully supported.

## Dialect Compatibility

If you're migrating SQL queries to DuckDB, watch for these common gotchas:

### 1. Double-quoted strings → column identifiers

DuckDB follows the SQL standard: `"text"` is a **column identifier**, not a string.

```sql
-- ❌ DuckDB: "hello" looks for a column called hello
SELECT "hello" AS greeting;

-- ✅ Use single quotes
SELECT 'hello' AS greeting;
```

Enable `strict_mysql_compatibility` mode to allow double-quoted strings:

```ini
[tool.pytest.ini_options]
duckdb_config = """
    strict_mysql_compatibility = true
"""
```

### 2. `read_csv_auto` — non-deterministic type inference

DuckDB infers CSV column types from sampling. Results can differ between
DuckDB versions or platforms — integers sampled as `VARCHAR` on one machine,
`BIGINT` on another. This breaks snapshot tests.

**Fix:** declare explicit types with `duckdb_fixture_schemas` (see Config Reference above).

### 3. Implicit casting is strict

DuckDB raises an error where other databases silently coerce:

```sql
-- ❌ DuckDB: Binder Error — no implicit cast from VARCHAR to INTEGER
SELECT '1' + 1;

-- ✅ Cast explicitly
SELECT '1'::INTEGER + 1;
```

This affects snapshot-based tests: a column typed as `BIGINT` on one run might
be `VARCHAR` on another, causing query failures. Another reason to use
`duckdb_fixture_schemas`.

### 4. Date/time function argument order

DuckDB's `DATEADD`, `DATEDIFF`, and `DATE_TRUNC` use a different argument
convention than PostgreSQL/Redshift:

```sql
-- PostgreSQL: DATEDIFF(unit, start, end)
-- DuckDB:     DATEDIFF(unit, start, end)  ✓  same convention

-- But DATE_TRUNC in DuckDB expects the timestamp first, not the part:
-- DuckDB:     DATE_TRUNC(timestamp, part) ← swapped!
```

Write queries with named parameters or alias functions for portability.

### 5. JSON extraction operators differ

DuckDB uses `json_extract_*` functions, not PostgreSQL's `->>`, `#>>`
operators:

```sql
-- ❌ PostgreSQL operators (not supported in DuckDB)
SELECT data ->> 'name' FROM events;
SELECT data #>> '{user, id}' FROM events;

-- ✅ DuckDB equivalents
SELECT json_extract_string(data, '$.name') FROM events;
SELECT json_extract_string(data, '$.user.id') FROM events;
```

### Summary

| Gotcha | Symptom | Fix |
|--------|---------|-----|
| Double-quoted strings | Binder/`column "X" not found` | Single quotes or `strict_mysql_compatibility=true` |
| `read_csv_auto` inference | Flaky types across runs | `duckdb_fixture_schemas` with explicit types |
| Strict casting | `Binder Error: no implicit cast` | Explicit `::TYPE` casts |
| Date function args | Wrong results or errors | Verify args against DuckDB docs |
| JSON extraction | `Parser Error: syntax error` | Use `json_extract_*` functions |

## License

MIT
