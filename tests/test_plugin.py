"""Verify the plugin loads correctly."""


def test_plugin_loads(pytestconfig):
    """Plugin should register the sql marker."""
    markers = pytestconfig.getini("markers")
    assert any("sql" in m for m in markers)
