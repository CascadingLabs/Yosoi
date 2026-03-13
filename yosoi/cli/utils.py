"""Shared utilities: console instances, schema loading, URL file loading."""

import ast
import difflib
import importlib.util
import json
import os
import pathlib
import re

import rich_click as click
from rich.console import Console

try:
    import pandas as pd

    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

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
    """Return names of all Contract subclasses in a module."""
    return [
        name
        for name in dir(module)
        if not name.startswith('_')
        and isinstance(getattr(module, name), type)
        and issubclass(getattr(module, name), Contract)
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


_URL_RE = re.compile(r'https?://[^\s\'"<>]+')
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\((https?://[^)]+)\)')


def _extract_urls_from_text(text: str) -> list[str]:
    """Extract http/https URLs from arbitrary text, stripping trailing punctuation."""
    urls = []
    for match in _URL_RE.finditer(text):
        url = match.group().rstrip('.,;:)\'"')
        urls.append(url)
    return urls


def _load_urls_from_csv(filepath: str) -> list[str]:
    """Load URLs from a CSV file using pandas."""
    if not HAS_PANDAS:
        raise click.ClickException('pandas is required to read CSV files. Install it with: pip install pandas')
    df = pd.read_csv(filepath)
    url_col = next((c for c in df.columns if c.lower() == 'url'), None)
    if url_col:
        return [str(v) for v in df[url_col].dropna() if str(v)]
    urls: list[str] = []
    for col in df.columns:
        for val in df[col].dropna():
            urls.extend(_extract_urls_from_text(str(val)))
    return urls


def _load_urls_from_excel(filepath: str) -> list[str]:
    """Load URLs from all sheets of an Excel file using pandas."""
    if not HAS_PANDAS:
        raise click.ClickException(
            'pandas is required to read Excel files. Install it with: pip install pandas openpyxl'
        )
    sheets = pd.read_excel(filepath, sheet_name=None)
    urls: list[str] = []
    for df in sheets.values():
        url_col = next((c for c in df.columns if c.lower() == 'url'), None)
        if url_col:
            urls.extend(str(v) for v in df[url_col].dropna() if str(v))
        else:
            for col in df.columns:
                for val in df[col].dropna():
                    urls.extend(_extract_urls_from_text(str(val)))
    return urls


def _load_urls_from_parquet(filepath: str) -> list[str]:
    """Load URLs from a Parquet file using pandas."""
    if not HAS_PANDAS:
        raise click.ClickException(
            'pandas is required to read Parquet files. Install it with: add it with uv add yosoi[pandas, pyarrow]'
        )
    df = pd.read_parquet(filepath)
    url_col = next((c for c in df.columns if c.lower() == 'url'), None)
    if url_col:
        return [str(v) for v in df[url_col].dropna() if str(v)]
    urls: list[str] = []
    for col in df.columns:
        for val in df[col].dropna():
            urls.extend(_extract_urls_from_text(str(val)))
    return urls


def _load_urls_from_markdown(filepath: str) -> list[str]:
    """Load URLs from a Markdown file (link syntax + bare URLs), deduplicated."""
    with open(filepath) as f:
        text = f.read()
    seen: set[str] = set()
    urls: list[str] = []
    for match in _MD_LINK_RE.finditer(text):
        url = match.group(2)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    remaining = _MD_LINK_RE.sub('', text)
    for url in _extract_urls_from_text(remaining):
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def load_urls_from_file(filepath: str) -> list[str]:
    """Load URLs from a file (JSON, plain text, CSV, Excel, Parquet, or Markdown).

    Args:
        filepath: Path to file containing URLs.

    Returns:
        List of URL strings.

    Raises:
        click.ClickException: If file is not found.

    """
    if not os.path.exists(filepath):
        raise click.ClickException(f'File not found: {filepath}')

    filepath_lower = filepath.lower()

    if filepath_lower.endswith('.csv'):
        return _load_urls_from_csv(filepath)

    if filepath_lower.endswith('.xlsx') or filepath_lower.endswith('.xls'):
        return _load_urls_from_excel(filepath)

    if filepath_lower.endswith('.parquet'):
        return _load_urls_from_parquet(filepath)

    if filepath_lower.endswith('.md'):
        return _load_urls_from_markdown(filepath)

    if filepath_lower.endswith('.json'):
        with open(filepath) as f:
            data = json.load(f)
        return _load_urls_from_json(data)

    with open(filepath) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]


def _load_urls_from_json(data: object) -> list[str]:
    """Extract URLs from a parsed JSON structure (list or dict)."""
    if isinstance(data, list):
        urls: list[str] = []
        for item in data:
            if isinstance(item, str) and item:
                urls.append(item)
            elif isinstance(item, dict):
                url = item.get('url')
                if url:
                    urls.append(url)
        return urls
    if isinstance(data, dict):
        urls = []
        for key in data:
            value = data.get(key, {})
            if isinstance(value, str) and value:
                urls.append(value)
            elif isinstance(value, dict) and 'url' in value:
                urls.append(value['url'])
        return urls
    return []
