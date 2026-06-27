"""Contract resolution utilities — core logic without CLI dependencies."""

from __future__ import annotations

import ast
import difflib
import importlib.util
import inspect
import os
import pathlib
from typing import TYPE_CHECKING, Any

from yosoi.models.contract import _CONTRACT_REGISTRY, Contract
from yosoi.models.defaults import BUILTIN_SCHEMAS

if TYPE_CHECKING:
    from yosoi.models.spec import ContractSpec

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
        Mapping of class_name -> ``file_path:ClassName`` string.
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


def _load_contract_from_file(schema_str: str) -> type[Contract]:
    """Load a Contract class from a ``path/to/file.py:ClassName`` string.

    Args:
        schema_str: Dynamic import path in ``file:ClassName`` format.

    Returns:
        The Contract subclass.

    Raises:
        FileNotFoundError: If the schema file does not exist.
        ValueError: If the class cannot be found or is not a Contract.

    """
    if ':' not in schema_str:
        raise ValueError(f'Dynamic schema must use path:ClassName format, got {schema_str!r}')

    file_path, class_name = schema_str.rsplit(':', 1)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f'Schema file not found: {file_path}')

    spec = importlib.util.spec_from_file_location('_yosoi_schema', file_path)
    if spec is None or spec.loader is None:
        raise ValueError(f'Could not load schema from {file_path}')

    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    try:
        loader.exec_module(module)
    except Exception as e:
        raise ValueError(f'Failed to load {file_path}: {e}') from e

    cls = getattr(module, class_name, None)
    if cls is None:
        contract_classes = _find_contract_classes(module)
        available = [
            name for name in dir(module) if not name.startswith('_') and isinstance(getattr(module, name), type)
        ]
        msg = f'Class {class_name!r} not found in {file_path}'
        close = difflib.get_close_matches(class_name, available, n=3, cutoff=0.5)
        if close:
            msg += f'\nDid you mean: {close[0]}'
        elif contract_classes:
            msg += f'\nAvailable Contract subclasses: {", ".join(contract_classes)}'
        raise ValueError(msg)

    if not (isinstance(cls, type) and issubclass(cls, Contract)):
        msg = f'Found {class_name!r} in {file_path}, but it is not a Contract subclass'
        contract_classes = _find_contract_classes(module)
        if contract_classes:
            msg += f'\nAvailable Contract subclasses: {", ".join(contract_classes)}'
        raise ValueError(msg)

    return cls


def resolve_contract(name: str | dict[str, Any] | ContractSpec) -> type[Contract]:
    """Resolve a contract to a Contract class.

    This is the programmatic API. No fuzzy matching or file scanning is
    performed — those are CLI-only DX features in ``SchemaParamType``.

    Resolution order:
    1. ContractSpec / dict → rehydrate via ``ContractSpec.to_contract()``
    2. Exact match in BUILTIN_SCHEMAS
    3. Exact match in _CONTRACT_REGISTRY (custom schemas)
    4. Dynamic import via ``path:ClassName``

    Args:
        name: Contract name, ``path:ClassName`` string, inline ContractSpec, or dict.

    Returns:
        The resolved Contract subclass.

    Raises:
        ValueError: If no matching contract is found.

    """
    # 1. ContractSpec or dict — rehydrate
    if not isinstance(name, str):
        from yosoi.models.spec import ContractSpec as _Spec

        spec = name if isinstance(name, _Spec) else _Spec.model_validate(name)
        # Dedup: if a registered contract with the same fingerprint exists, return it.
        fp = spec.fingerprint
        for cls in list(BUILTIN_SCHEMAS.values()) + list(_CONTRACT_REGISTRY.values()):
            try:
                if cls.to_spec().fingerprint == fp:
                    return cls
            except Exception:  # noqa: BLE001, PERF203
                pass
        return spec.to_contract()

    # 2. Exact match in builtins
    if name in BUILTIN_SCHEMAS:
        return BUILTIN_SCHEMAS[name]

    # 3. Exact match in registry
    if name in _CONTRACT_REGISTRY:
        return _CONTRACT_REGISTRY[name]

    # 4. Dynamic import (path:ClassName)
    if ':' in name:
        return _load_contract_from_file(name)

    available_str = ', '.join(sorted(set(BUILTIN_SCHEMAS) | set(_CONTRACT_REGISTRY)))
    raise ValueError(f'Unknown contract {name!r}. Available: {available_str}')
