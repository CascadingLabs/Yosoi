"""Ensure stubs cover all public API exports."""

import ast
import importlib
from pathlib import Path

import pytest

YOSOI_ROOT = Path(__file__).parent.parent.parent / 'yosoi'


def _stub_reexports(source: str) -> list[tuple[str, str]]:
    """Return (module, name) pairs for every `from module import name` in a stub."""
    tree = ast.parse(source)
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            pairs.extend((node.module, alias.name) for alias in node.names)
    return pairs


def _extract_all_names(source: str) -> set[str]:
    """Extract names from __all__ assignment in source code."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == '__all__' and isinstance(node.value, ast.List):
                    return {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)}
    return set()


def _extract_stub_names(source: str) -> set[str]:
    """Extract all declared names from a .pyi stub file."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_init_stub_covers_all_exports() -> None:
    """Every name in yosoi/__init__.py __all__ must appear in __init__.pyi."""
    init_py = YOSOI_ROOT / '__init__.py'
    init_pyi = YOSOI_ROOT / '__init__.pyi'
    assert init_pyi.exists(), 'Missing yosoi/__init__.pyi'

    all_names = _extract_all_names(init_py.read_text())
    assert all_names, 'Could not extract __all__ from __init__.py'

    stub_names = _extract_stub_names(init_pyi.read_text())
    missing = all_names - stub_names
    assert not missing, f'Stubs missing exports: {missing}'


def test_types_stub_covers_all_exports() -> None:
    """Every name in yosoi/types/__init__.py __all__ must appear in types/__init__.pyi."""
    init_py = YOSOI_ROOT / 'types' / '__init__.py'
    init_pyi = YOSOI_ROOT / 'types' / '__init__.pyi'
    assert init_pyi.exists(), 'Missing yosoi/types/__init__.pyi'

    all_names = _extract_all_names(init_py.read_text())
    assert all_names, 'Could not extract __all__ from types/__init__.py'

    stub_names = _extract_stub_names(init_pyi.read_text())
    missing = all_names - stub_names
    assert not missing, f'Types stubs missing exports: {missing}'


@pytest.mark.parametrize('stub_path', ['__init__.pyi', 'types/__init__.pyi'])
def test_stub_reexports_resolve_at_runtime(stub_path: str) -> None:
    """Every `from X import Y` re-export in a stub must resolve at runtime.

    Guards against stubs that outlive the symbols they advertise — e.g. a stub
    importing from a module that was deleted, or a name that was removed from
    the public API. This is the reverse of the coverage checks above.
    """
    pyi = YOSOI_ROOT / stub_path
    for module, name in _stub_reexports(pyi.read_text()):
        try:
            mod = importlib.import_module(module)
        except ImportError as exc:
            pytest.fail(f'{stub_path}: re-exports {name!r} from missing module {module!r} ({exc})')
        assert hasattr(mod, name), f'{stub_path}: {module!r} has no attribute {name!r} (stale stub re-export)'


def test_py_typed_marker_exists() -> None:
    """PEP 561 py.typed marker must exist."""
    assert (YOSOI_ROOT / 'py.typed').exists(), 'Missing yosoi/py.typed marker file'
