"""CLI package for Yosoi."""

from dotenv import load_dotenv

load_dotenv()

from yosoi.cli.args import SchemaParamType
from yosoi.cli.main import main

__all__ = ['SchemaParamType', 'main']
