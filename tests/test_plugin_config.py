from __future__ import annotations

from unittest.mock import Mock

import pytest

from pytest_duckdb.plugin import _parse_duckdb_config, _resolve_duckdb_config


class TestParseDuckdbConfig:
    """Unit tests for the ``_parse_duckdb_config`` helper."""

    def test_empty_string(self) -> None:
        """Empty string returns an empty dict."""
        assert _parse_duckdb_config("") == {}

    def test_blank_lines(self) -> None:
        """Blank lines and whitespace are ignored."""
        assert _parse_duckdb_config("  \n\n \n  ") == {}

    def test_single_pair(self) -> None:
        """A single key=value pair is parsed correctly."""
        result = _parse_duckdb_config("default_order=desc")
        assert result == {"default_order": "desc"}

    def test_multiple_pairs(self) -> None:
        """Multiple key=value pairs, one per line."""
        result = _parse_duckdb_config(
            "default_order=desc\npreserve_insertion_order=false\nthreads=4"
        )
        assert result == {
            "default_order": "desc",
            "preserve_insertion_order": "false",
            "threads": "4",
        }

    def test_whitespace_around_equals(self) -> None:
        """Spaces around = are tolerated."""
        result = _parse_duckdb_config("memory_limit = 2GB")
        assert result == {"memory_limit": "2GB"}

    def test_comment_lines_ignored(self) -> None:
        """Lines starting with ``#`` are ignored."""
        result = _parse_duckdb_config(
            "# this is a comment\n"
            "default_order=desc\n"
            "  # indented comment\n"
            "threads=2\n"
        )
        assert result == {"default_order": "desc", "threads": "2"}

    def test_trim_whitespace_from_keys_and_values(self) -> None:
        """Keys and values are stripped of leading/trailing whitespace."""
        result = _parse_duckdb_config("  key  =  value  ")
        assert result == {"key": "value"}

    def test_value_contains_equals(self) -> None:
        """A value that itself contains ``=`` is handled (partition on first)."""
        result = _parse_duckdb_config("custom_option=foo=bar")
        assert result == {"custom_option": "foo=bar"}


class TestResolveDuckdbConfig:
    """Tests for the ini+CLI merge logic."""

    def _make_config(
        self, ini_value: str = "", cli_value: list[str] | None = None
    ) -> Mock:
        config = Mock(spec=["getini", "option"])
        config.getini.return_value = ini_value
        config.option.duckdb_config_cli = cli_value
        return config

    def test_ini_only(self) -> None:
        """Config from ini is returned when no CLI flags are given."""
        config = self._make_config(
            ini_value="default_order=desc\nthreads=4"
        )
        result = _resolve_duckdb_config(config)
        assert result == {"default_order": "desc", "threads": "4"}

    def test_cli_only(self) -> None:
        """Config from CLI flags works."""
        config = self._make_config(
            cli_value=["default_order=desc", "memory_limit=2GB"]
        )
        result = _resolve_duckdb_config(config)
        assert result == {"default_order": "desc", "memory_limit": "2GB"}

    def test_cli_overrides_ini(self) -> None:
        """CLI takes precedence over ini on key conflict."""
        config = self._make_config(
            ini_value="default_order=asc\nthreads=2",
            cli_value=["default_order=desc"],
        )
        result = _resolve_duckdb_config(config)
        assert result == {"default_order": "desc", "threads": "2"}

    def test_no_config(self) -> None:
        """No config returns empty dict."""
        config = self._make_config()
        assert _resolve_duckdb_config(config) == {}


class TestDuckdbConfigIntegration:
    """Integration tests exercising ``--duckdb-config`` via pytester."""

    def test_config_affects_connection(self, pytester: pytest.Pytester) -> None:
        """``default_order`` config option changes ORDER BY behaviour."""
        pytester.makefile(
            ".py",
            test_example="""
                def test_order(duckdb_session):
                    conn = duckdb_session
                    conn.execute('CREATE TABLE t (v INTEGER)')
                    conn.execute('INSERT INTO t VALUES (1), (NULL), (2)')
                    result = conn.execute(
                        'SELECT v FROM t ORDER BY v'
                    ).fetchall()
                    rows = [r[0] for r in result]
                    # With ``default_order=desc``, ``ORDER BY v`` sorts
                    # descending with NULLs last → ``[2, 1, None]``
                    assert rows == [2, 1, None], f"got {rows}"
            """,
        )
        result = pytester.runpytest_subprocess(
            "--duckdb-config", "default_order=desc",
            "-v",
        )
        result.assert_outcomes(passed=1)

    def test_cli_override_ini(self, pytester: pytest.Pytester) -> None:
        """CLI ``--duckdb-config`` overrides ``duckdb_config`` ini value."""
        pytester.makefile(
            ".cfg",
            pytest="""
                [pytest]
                duckdb_config =
                    default_order=asc
                    threads=2
            """,
        )
        pytester.makefile(
            ".py",
            test_example="""
                def test_cli_wins(duckdb_session):
                    conn = duckdb_session
                    conn.execute('CREATE TABLE t (v INTEGER)')
                    conn.execute('INSERT INTO t VALUES (1), (NULL)')
                    result = conn.execute(
                        'SELECT v FROM t ORDER BY v'
                    ).fetchall()
                    rows = [r[0] for r in result]
                    # ``default_order=desc`` gives descending sort
                    assert rows == [1, None], f"got {rows}"
            """,
        )
        result = pytester.runpytest_subprocess(
            "--duckdb-config", "default_order=desc",
            "--override-ini=duckdb_config=\ndefault_order=asc\nthreads=2",
            "-v",
        )
        result.assert_outcomes(passed=1)
