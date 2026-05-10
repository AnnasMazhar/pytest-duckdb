"""pytest plugin registration — fixtures and markers."""

import pytest


def pytest_configure(config):
    """Register the sql marker."""
    config.addinivalue_line("markers", "sql: mark test as SQL pipeline test")
