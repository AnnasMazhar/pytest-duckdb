"""pytest plugin registration — fixtures, markers, and CLI options.

Provides three fixtures:

* ``duckdb_session`` – function-scoped in-memory DuckDB with CSV fixtures
  auto-loaded.
* ``sql_result`` – executes a ``.sql`` file referenced via ``@pytest.mark.sql``.
* ``sql_snapshot`` – callable fixture for Parquet snapshot testing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from .fixtures import _parse_fixture_schemas, load_csvs, read_sql_file
from .snapshot import compare, save


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register CLI options and ini-file keys."""
    parser.addini(
        "duckdb_fixtures_dir",
        type="string",
        default="tests/fixtures",
        help="Directory containing CSV fixture files",
    )
    parser.addini(
        "duckdb_snapshots_dir",
        type="string",
        default="tests/__snapshots__",
        help="Directory for Parquet snapshot files",
    )
    parser.addini(
        "duckdb_config",
        type="string",
        default="",
        help="DuckDB configuration as multiline ``key=value`` (optional); "
        "overridden by ``--duckdb-config`` CLI flags",
    )
    parser.addini(
        "duckdb_fixture_schemas",
        type="string",
        default="",
        help="Explicit column types for CSV fixtures as multiline "
        "``table_name: col TYPE, ...`` (optional); prevents "
        "non-deterministic ``read_csv_auto`` type inference",
    )
    group = parser.getgroup("duckdb")
    group.addoption(
        "--snapshot-update",
        action="store_true",
        default=False,
        help="Regenerate all Parquet snapshots instead of comparing",
    )
    group.addoption(
        "--duckdb-fixtures-dir",
        action="store",
        default=None,
        metavar="PATH",
        help="Directory containing CSV fixture files (default: tests/fixtures)",
    )
    group.addoption(
        "--duckdb-config",
        action="append",
        type=str,
        default=None,
        metavar="KEY=VALUE",
        dest="duckdb_config_cli",
        help="DuckDB configuration option (may be repeated; "
        "overrides ini-file ``duckdb_config`` on conflict)",
    )


def _resolve_duckdb_config(config: pytest.Config) -> dict[str, str]:
    """Merge ini-file and CLI ``duckdb_config`` settings.

    CLI values are parsed from ``--duckdb-config KEY=VALUE`` (repeated).
    Ini values are parsed from a multiline ``duckdb_config`` key.
    CLI values take precedence over ini values on key conflict.
    """
    merged: dict[str, str] = {}
    # Read ini config first.
    ini_raw = config.getini("duckdb_config")
    if isinstance(ini_raw, str) and ini_raw.strip():
        merged.update(_parse_duckdb_config(ini_raw))
    # CLI overrides.
    cli_raw = config.option.duckdb_config_cli
    if cli_raw:
        for item in cli_raw:
            merged.update(_parse_duckdb_config(item))
    return merged


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``sql`` marker and expand docstring."""
    config.addinivalue_line(
        "markers",
        "sql(path): mark a test to run a SQL file; "
        "the path is resolved relative to the project root.",
    )

    # Persist resolved config options.
    config.duckdb_fixtures_dir = _resolve_option(
        config,
        cli_name="--duckdb-fixtures-dir",
        ini_name="duckdb_fixtures_dir",
        default="tests/fixtures",
    )

    config.duckdb_snapshots_dir = _resolve_ini_option(
        config,
        ini_name="duckdb_snapshots_dir",
        default="tests/__snapshots__",
    )

    config.duckdb_kwargs = {}
    db_config = _resolve_duckdb_config(config)
    if db_config:
        config.duckdb_kwargs = {"config": db_config}

    raw_schemas = config.getini("duckdb_fixture_schemas")
    config.duckdb_fixture_schemas = (
        _parse_fixture_schemas(raw_schemas) if isinstance(raw_schemas, str) else {}
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def duckdb_session(request: pytest.FixtureRequest):
    """Function-scoped DuckDB in-memory session with auto-loaded CSV fixtures.

    CSVs in the configured fixtures directory are loaded as tables named
    after the file stem.  If the directory does not exist the session is
    returned empty with no error.

    Yields:
        ``duckdb.DuckDBPyConnection`` -- close on teardown.
    """
    import duckdb

    conn = duckdb.connect(":memory:", **request.config.duckdb_kwargs)
    fixtures_dir = _resolve_path(
        request.config.duckdb_fixtures_dir,
        request.config.rootpath,
    )
    load_csvs(conn, fixtures_dir, schemas=request.config.duckdb_fixture_schemas)
    yield conn
    conn.close()


@pytest.fixture(scope="function")
def sql_result(
    duckdb_session,        # noqa: ANN001, ANN201
    request: pytest.FixtureRequest,
):
    """Fixture that executes a SQL file referenced by ``@pytest.mark.sql``.

    Usage::

        @pytest.mark.sql("tests/queries/my_query.sql")
        def test_something(sql_result):
            assert len(sql_result) > 0

    Returns a ``pandas.DataFrame`` if pandas is installed, otherwise a
    :class:`~pytest_duckdb.snapshot.QueryResult` with ``.columns``.

    Raises:
        FileNotFoundError: The referenced SQL file does not exist.
    """
    marker = request.node.get_closest_marker("sql")
    if marker is None:
        return None

    sql_path = _resolve_marker_path(marker, request)
    query = read_sql_file(sql_path)
    result = duckdb_session.execute(query)

    from .snapshot import _cursor_to_result

    return _cursor_to_result(result)


@pytest.fixture(scope="function")
def sql_snapshot(
    duckdb_session,        # noqa: ANN001, ANN201
    request: pytest.FixtureRequest,
) -> Callable[..., None]:
    """Callable fixture for Parquet snapshot testing.

    Usage::

        def test_query(sql_snapshot):
            result = duckdb_session.execute("SELECT ...").fetchdf()
            sql_snapshot(result)

    **First run:** saves the result to ``{snapshots_dir}/{module}_{test}.parquet``
    and passes.

    **Subsequent runs:** loads the Parquet snapshot and asserts equality.  Raises
    ``AssertionError`` with a clear diff on mismatch.

    Pass ``--snapshot-update`` on the CLI to regenerate all snapshots.
    """
    snapshots_dir = _resolve_path(
        request.config.duckdb_snapshots_dir,
        request.config.rootpath,
    )
    update = request.config.getoption("--snapshot-update", default=False)

    # Build a deterministic snapshot file name.
    module_name = _module_name(request.node)
    test_name = _test_name(request.node)
    snapshot_path = os.path.join(
        snapshots_dir, f"{module_name}_{test_name}.parquet",
    )

    def _snapshot(result: Any, name: Optional[str] = None) -> None:
        """Save or compare *result* against the Parquet snapshot.

        Args:
            result: DataFrame or list-of-tuples to snapshot.
            name: Optional override for the snapshot file name stem.

        Raises:
            AssertionError: On mismatch (when not updating).
        """
        nonlocal snapshot_path
        if name is not None:
            snapshot_path = os.path.join(
                snapshots_dir, f"{module_name}_{name}.parquet",
            )

        if update or not os.path.isfile(snapshot_path):
            save(duckdb_session, result, snapshot_path)
        else:
            compare(duckdb_session, result, snapshot_path)

    return _snapshot


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_option(
    config: pytest.Config,
    cli_name: str,
    ini_name: str,
    default: str,
) -> str:
    """Resolve a config value from CLI → ini → default."""
    cli_val = config.getoption(cli_name.replace("--", "").replace("-", "_"))
    if cli_val is not None:
        return cli_val
    ini_val = config.getini(ini_name)
    if ini_val:
        return ini_val
    return default


def _resolve_ini_option(
    config: pytest.Config,
    ini_name: str,
    default: str,
) -> str:
    """Resolve a config value from ini → default."""
    ini_val = config.getini(ini_name)
    if ini_val:
        return ini_val
    return default


def _resolve_path(path_str: str, root: Path) -> str:
    """Resolve a possibly-relative path against the project root."""
    if not os.path.isabs(path_str):
        return os.path.join(str(root), path_str)
    return path_str


def _resolve_marker_path(marker: pytest.Mark, request: pytest.FixtureRequest) -> str:
    """Resolve the path from a ``@pytest.mark.sql`` marker."""
    path = marker.args[0] if marker.args else marker.kwargs.get("path", "")
    if not os.path.isabs(path):
        return os.path.join(str(request.config.rootpath), path)
    return path


def _parse_duckdb_config(config_str: str) -> dict[str, str]:
    """Parse a multiline ``key=value`` config string into a dict.

    Blank lines and lines starting with ``#`` are ignored.  Keys and values
    are stripped of leading/trailing whitespace.  If a value contains ``=``
    the first ``=`` is treated as the delimiter.
    """
    result: dict[str, str] = {}
    for line in config_str.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def _module_name(node: pytest.Item) -> str:
    """Return a sanitised module name for snapshot file naming."""
    # node.path gives the file path, e.g. tests/test_fixtures.py
    fspath = getattr(node, "path", None) or getattr(node, "fspath", None)
    if fspath:
        stem = Path(str(fspath)).stem  # e.g. test_fixtures
        return stem
    return "unknown_module"


def _test_name(node: pytest.Item) -> str:
    """Return a sanitised test function name."""
    return node.name.replace("[", "_").replace("]", "_").replace("/", "_")
