"""Check the installed distribution, including the native extension and typing."""

from importlib.metadata import version
from importlib.resources import files

import yosoi


def test_installed_distribution() -> None:
    assert yosoi.__version__ == version("yosoi")
    assert files("yosoi").joinpath("py.typed").is_file()
    assert files("yosoi").joinpath("_native.pyi").is_file()
