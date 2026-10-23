# Changelog

## [0.2.0] — 2026-05-12

### Fixed
- SQL injection in fixture loading and snapshot save/load/compare (now uses parameterized queries)
- Empty snapshot schema mismatch — empty `QueryResult` no longer causes invalid comparisons
- Empty list `[]` passed to `_register_temp` no longer produces invalid SQL
- `@pytest.mark.sql("")` now raises a clear `ValueError` instead of a confusing `FileNotFoundError`

### Added
- `--duckdb-snapshots-dir` CLI flag (previously only configurable via ini)
- `.parquet` and `.json` fixture file support (in addition to CSV)
- CI pipeline with Python 3.9–3.13 matrix, ruff lint/format, coverage gate

### Changed
- CI uses `uv` instead of `pip` for dependency installation

## [0.1.0] — 2026-05-10

### Added
- Initial release
- `duckdb_session` fixture with CSV auto-loading
- `sql_result` fixture with `@pytest.mark.sql` marker
- `sql_snapshot` callable fixture for Parquet snapshot testing
- `--snapshot-update` CLI flag
- `--duckdb-fixtures-dir` CLI flag and `duckdb_fixtures_dir` ini option
- `duckdb_snapshots_dir` ini option
