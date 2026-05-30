"""Package import smoke tests."""


def test_import_yosoi_package():
    import yosoi

    assert yosoi.__version__


def test_version_falls_back_to_unknown_when_package_not_installed(monkeypatch):
    """__version__ = 'unknown' when importlib.metadata.version raises PackageNotFoundError (lines 76-77)."""
    import importlib
    import sys
    from importlib.metadata import PackageNotFoundError

    # Patch version() inside the yosoi package namespace so the reload hits the except branch
    monkeypatch.setattr('importlib.metadata.version', lambda _name: (_ for _ in ()).throw(PackageNotFoundError(_name)))

    # Force a fresh import of yosoi.__init__ to re-execute the try/except block
    if 'yosoi' in sys.modules:
        del sys.modules['yosoi']
    import yosoi

    assert yosoi.__version__ == 'unknown'

    # Restore the real version so other tests aren't affected
    importlib.reload(yosoi)
