"""CLI package for Yosoi.

Kept eager (not lazy): the exported ``main`` shares its name with the ``main``
submodule, so a lazy re-export would be clobbered whenever the submodule is
imported. The CLI entry point needs ``main`` immediately anyway.
"""

from dotenv import load_dotenv

load_dotenv()

from yosoi.cli.args import SchemaParamType
from yosoi.cli.main import main

__all__ = ['SchemaParamType', 'main']
