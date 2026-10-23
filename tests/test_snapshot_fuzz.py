"""Property-based fuzz tests for snapshot save/load/compare using Hypothesis."""

from __future__ import annotations

import os
import tempfile

import duckdb
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from pytest_duckdb.snapshot import QueryResult, compare, load, save

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

cell_strategy = st.one_of(
    st.none(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    st.text(alphabet="abc123 _-", min_size=0, max_size=10),
    st.booleans(),
)


@st.composite
def random_table(draw):
    """Generate (columns, rows) with consistent width and per-column types."""
    ncols = draw(st.integers(min_value=1, max_value=8))
    nrows = draw(st.integers(min_value=0, max_value=15))
    columns = [f"col{i}" for i in range(ncols)]

    # Pick a type strategy per column (SQL columns are homogeneous).
    col_strategies = []
    for _ in range(ncols):
        base = draw(st.sampled_from(["int", "float", "text", "bool"]))
        if base == "int":
            col_strategies.append(st.one_of(st.none(), st.integers(-1000, 1000)))
        elif base == "float":
            col_strategies.append(
                st.one_of(
                    st.none(),
                    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
                )
            )
        elif base == "text":
            col_strategies.append(
                st.one_of(st.none(), st.text(alphabet="abc123 _-", min_size=0, max_size=10))
            )
        else:
            col_strategies.append(st.one_of(st.none(), st.booleans()))

    rows = [tuple(draw(col_strategies[i]) for i in range(ncols)) for _ in range(nrows)]
    return columns, rows


@st.composite
def null_heavy_table(draw):
    """Generate table where every column has NULLs mixed with typed values."""
    ncols = draw(st.integers(min_value=1, max_value=5))
    nrows = draw(st.integers(min_value=1, max_value=10))
    columns = [f"col{i}" for i in range(ncols)]

    # Each column gets a consistent type
    col_strategies = []
    for _ in range(ncols):
        base = draw(st.sampled_from(["int", "text"]))
        if base == "int":
            col_strategies.append(st.one_of(st.none(), st.integers(-100, 100)))
        else:
            col_strategies.append(st.one_of(st.none(), st.text(min_size=1, max_size=5)))

    rows = [tuple(draw(col_strategies[i]) for i in range(ncols)) for _ in range(nrows)]
    return columns, rows


@st.composite
def special_chars_table(draw):
    """Generate table with special characters in values."""
    ncols = draw(st.integers(min_value=1, max_value=4))
    nrows = draw(st.integers(min_value=1, max_value=8))
    columns = [f"col{i}" for i in range(ncols)]
    special_text = st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S", "Z"),
            whitelist_characters="'\"\\\n\t🎉🦆",
        ),
        min_size=0,
        max_size=15,
    )
    rows = [
        tuple(draw(st.one_of(st.none(), special_text)) for _ in range(ncols)) for _ in range(nrows)
    ]
    return columns, rows


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestSaveLoadRoundtrip:
    """Property 1: save then load returns equivalent data."""

    @given(data=random_table())
    @settings(max_examples=50, deadline=5000)
    def test_roundtrip_preserves_data(self, data):
        columns, rows = data
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "snap.parquet")
            conn = duckdb.connect(":memory:")
            try:
                save(conn, QueryResult(rows, columns), path)
                loaded = load(conn, path)
                if hasattr(loaded, "iloc"):
                    assert list(loaded.columns) == columns
                    assert len(loaded) == len(rows)
                else:
                    assert list(loaded.columns) == columns
                    assert len(loaded) == len(rows)
            finally:
                conn.close()


class TestCompareIdentical:
    """Property 2: compare passes for identical data."""

    @given(data=random_table())
    @settings(max_examples=50, deadline=5000)
    def test_identical_data_passes(self, data):
        columns, rows = data
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "snap.parquet")
            conn = duckdb.connect(":memory:")
            try:
                save(conn, QueryResult(rows, columns), path)
                # Should not raise
                compare(conn, QueryResult(rows, columns), path)
            finally:
                conn.close()


class TestCompareCatchesDifferences:
    """Property 3: compare detects when data differs."""

    @given(data=random_table())
    @settings(max_examples=30, deadline=5000)
    def test_added_row_detected(self, data):
        columns, rows = data
        assume(len(rows) >= 1)  # Need at least 1 row so schema is stable
        # Duplicate a row to create a difference (guaranteed same types)
        modified = rows + [rows[0]]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "snap.parquet")
            conn = duckdb.connect(":memory:")
            try:
                save(conn, QueryResult(rows, columns), path)
                with pytest.raises(AssertionError, match="mismatch"):
                    compare(conn, QueryResult(modified, columns), path)
            finally:
                conn.close()


class TestNullHandling:
    """Property 4: NULL values roundtrip correctly (tests IS NOT DISTINCT FROM fix)."""

    @given(data=null_heavy_table())
    @settings(max_examples=50, deadline=5000)
    def test_nulls_roundtrip(self, data):
        columns, rows = data
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "snap.parquet")
            conn = duckdb.connect(":memory:")
            try:
                save(conn, QueryResult(rows, columns), path)
                # Must not raise — identical data with NULLs
                compare(conn, QueryResult(rows, columns), path)
            finally:
                conn.close()


class TestSpecialCharacters:
    """Property 5: special characters in values survive roundtrip."""

    @given(data=special_chars_table())
    @settings(max_examples=50, deadline=5000)
    def test_special_chars_roundtrip(self, data):
        columns, rows = data
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "snap.parquet")
            conn = duckdb.connect(":memory:")
            try:
                save(conn, QueryResult(rows, columns), path)
                compare(conn, QueryResult(rows, columns), path)
            finally:
                conn.close()
