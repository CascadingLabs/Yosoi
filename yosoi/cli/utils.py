"""Shared utilities: console instances, schema loading, URL file loading."""

import ast
import difflib
import importlib.util
import inspect
import os
import pathlib

import rich_click as click
from rich.console import Console

from yosoi.models.contract import Contract

console = Console()
console_err = Console(stderr=True)

_SCAN_SKIP_DIRS = frozenset(
    {
        '__pycache__',
        '.venv',
        'venv',
        'node_modules',
        '.git',
        'site-packages',
        '.mypy_cache',
        '.ruff_cache',
        'tests',
        'examples',
    }
)


def scan_for_contracts(search_dirs: list[str] | None = None) -> dict[str, str]:
    """Scan Python files for Contract subclasses using AST (no imports).

    Returns:
        Mapping of class_name -> ``file_path:ClassName`` string for use with load_schema.
    """
    found: dict[str, str] = {}
    for search_dir in search_dirs or ['.']:
        for py_file in pathlib.Path(search_dir).rglob('*.py'):
            if _SCAN_SKIP_DIRS.intersection(py_file.parts):
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding='utf-8', errors='ignore'), filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for base in node.bases:
                    base_name = (
                        base.id
                        if isinstance(base, ast.Name)
                        else (base.attr if isinstance(base, ast.Attribute) else None)
                    )
                    if base_name == 'Contract':
                        found[node.name] = f'{py_file}:{node.name}'
    return found


def _suggest_file(file_path: str, class_name: str) -> list[str]:
    """Return suggested ``file:class`` strings for a missing file path."""
    suggestions: list[str] = []

    if not file_path.endswith('.py'):
        py_path = file_path + '.py'
        if os.path.exists(py_path):
            suggestions.append(f'{py_path}:{class_name}')

    dir_part = os.path.dirname(file_path) or '.'
    base_name = os.path.basename(file_path)
    try:
        candidates = [f for f in os.listdir(dir_part) if f.endswith('.py')]
        matches = difflib.get_close_matches(base_name, candidates, n=3, cutoff=0.4)
        for m in matches:
            candidate = f'{os.path.join(dir_part, m)}:{class_name}'
            if candidate not in suggestions:
                suggestions.append(candidate)
    except OSError:
        pass

    return suggestions


def _find_contract_classes(module: object) -> list[str]:
    """Return names of concrete Contract subclasses in a module."""
    return [
        name
        for name in dir(module)
        if not name.startswith('_')
        and isinstance(getattr(module, name), type)
        and issubclass(getattr(module, name), Contract)
        and getattr(module, name) is not Contract
        and not inspect.isabstract(getattr(module, name))
    ]


def _raise_class_not_found(class_name: str, file_path: str, module: object, contract_classes: list[str]) -> None:
    """Raise a ClickException with helpful hints when a class is not found."""
    available = [name for name in dir(module) if not name.startswith('_') and isinstance(getattr(module, name), type)]
    msg = f'Class {class_name!r} not found in {file_path}'
    matches = difflib.get_close_matches(class_name, available, n=3, cutoff=0.5)
    if matches:
        msg += f'\nDid you mean: {matches[0]}'
        if len(matches) > 1:
            msg += f'\n  Other options: {", ".join(matches[1:])}'
    elif contract_classes:
        msg += f'\nAvailable Contract subclasses: {", ".join(contract_classes)}'
    elif available:
        msg += f'\nAvailable classes: {", ".join(available)}'
    raise click.ClickException(msg)


def load_schema(schema_str: str) -> type[Contract]:
    """Load a Contract class from a ``path/to/file.py:ClassName`` string.

    Args:
        schema_str: Dynamic import path in ``file:ClassName`` format.

    Returns:
        The Contract subclass.

    Raises:
        click.ClickException: If the schema cannot be found or loaded.

    """
    if ':' not in schema_str:
        raise click.ClickException(f'Dynamic schema must use path:ClassName format, got {schema_str!r}')

    file_path, class_name = schema_str.rsplit(':', 1)
    if not os.path.exists(file_path):
        msg = f'Schema file not found: {file_path}'
        suggestions = _suggest_file(file_path, class_name)
        if suggestions:
            msg += f'\nDid you mean: {suggestions[0]}'
            if len(suggestions) > 1:
                msg += f'\n  Other options: {", ".join(suggestions[1:])}'
        raise click.ClickException(msg)

    spec = importlib.util.spec_from_file_location('_yosoi_schema', file_path)
    if spec is None or spec.loader is None:
        raise click.ClickException(f'Could not load schema from {file_path}')

    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    try:
        loader.exec_module(module)
    except Exception as e:
        raise click.ClickException(f'Failed to load {file_path}: {e}') from e

    cls = getattr(module, class_name, None)
    contract_classes = _find_contract_classes(module)

    if cls is None:
        _raise_class_not_found(class_name, file_path, module, contract_classes)

    if not (isinstance(cls, type) and issubclass(cls, Contract)):
        msg = f'Found {class_name!r} in {file_path}, but it is not a Contract subclass'
        if contract_classes:
            msg += f'\nAvailable Contract subclasses: {", ".join(contract_classes)}'
        raise click.ClickException(msg)

    return cls


def load_urls_from_file(filepath: str) -> list[str]:
    """Load URLs from a file — CLI wrapper with Click error handling.

    Args:
        filepath: Path to file containing URLs.

    Returns:
        List of URL strings.

    Raises:
        click.ClickException: If file is not found or cannot be read.

    """
    from yosoi.utils.urls import load_urls_from_file as _core_load

    try:
        return _core_load(filepath)
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e)) from e
