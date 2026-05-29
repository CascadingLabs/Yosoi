"""Package import smoke tests."""


def test_import_yosoi_package():
    import yosoi

    assert yosoi.__version__
