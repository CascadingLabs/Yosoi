"""Reject hard-coded selectors in examples.

Examples are supposed to describe data contracts and let Yosoi discover selectors.
This hook intentionally makes selector literals hard to sneak in by checking both
obvious APIs (``ys.css(...)``, ``selector=...``) and browser-selector calls embedded
in Python strings.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_ROOTS = (Path('examples'),)

SELECTOR_FACTORY_NAMES = {'css', 'xpath'}
SELECTOR_KEYWORDS = {'selector', 'selectors', 'root_selector', 'row_selector'}
ROOT_ASSIGN_NAMES = {'root'}
DOM_SELECTOR_METHODS = {'querySelector', 'querySelectorAll', 'closest', 'matches'}
SUSPICIOUS_NAME_PARTS = ('selector', 'selectors', 'root', 'xpath', 'css')
JS_SELECTOR_APIS = (
    'querySelector(',
    'querySelectorAll(',
    '.closest(',
    '.matches(',
    'XPathEvaluator',
    'document.evaluate(',
)
SELECTOR_LITERAL = re.compile(
    r'(^|[\s,(])('
    r'[.#][A-Za-z_-][\w-]*|'
    r'[A-Za-z][\w-]*(?:\[[^\]]+\]|[.#][A-Za-z_-][\w-]*)|'
    r'//[A-Za-z*]|'
    r'::(?:attr|text)\b'
    r')'
)


@dataclass(frozen=True)
class Violation:
    """One hard-coded selector finding."""

    path: Path
    line: int
    col: int
    reason: str
    value: str


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f'{base}.{node.attr}' if base else node.attr
    return None


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_strings(node: ast.AST) -> list[str]:
    return [child.value for child in ast.walk(node) if isinstance(child, ast.Constant) and isinstance(child.value, str)]


def _is_selector_factory(call_name: str | None) -> bool:
    if not call_name:
        return False
    return call_name in SELECTOR_FACTORY_NAMES or any(call_name.endswith(f'.{name}') for name in SELECTOR_FACTORY_NAMES)


def _looks_like_selector(value: str) -> bool:
    return bool(SELECTOR_LITERAL.search(value))


def _short(value: str) -> str:
    value = value.replace('\n', '\\n')
    return value if len(value) <= 100 else f'{value[:97]}...'


class SelectorVisitor(ast.NodeVisitor):
    """AST visitor that records hard-coded selector patterns."""

    def __init__(self, path: Path) -> None:
        """Create a visitor for one source file."""
        self.path = path
        self.violations: list[Violation] = []

    def _add(self, node: ast.AST, reason: str, value: str) -> None:
        self.violations.append(
            Violation(
                path=self.path,
                line=getattr(node, 'lineno', 1),
                col=getattr(node, 'col_offset', 0) + 1,
                reason=reason,
                value=_short(value),
            )
        )

    def visit_Call(self, node: ast.Call) -> Any:
        """Check function calls that can smuggle selector literals."""
        call_name = _call_name(node.func)
        if _is_selector_factory(call_name):
            self._add(node, f'hard-coded selector factory call `{call_name}`', call_name or '')
        if call_name and call_name.rsplit('.', 1)[-1] in DOM_SELECTOR_METHODS:
            self._add(node, f'hard-coded browser selector API `{call_name}`', call_name)
        for keyword in node.keywords:
            if keyword.arg in SELECTOR_KEYWORDS:
                value = _literal_string(keyword.value)
                if value is not None:
                    self._add(keyword.value, f'hard-coded `{keyword.arg}=...` selector literal', value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> Any:
        """Check plain assignments such as ``root = ...``."""
        self._check_assignment(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        """Check annotated assignments such as ``root: str = ...``."""
        self._check_assignment([node.target], node.value)
        self.generic_visit(node)

    def _check_assignment(self, targets: list[ast.AST], value: ast.AST | None) -> None:
        if value is None:
            return
        target_names = {_target_name(target) for target in targets}
        target_names.discard(None)
        if target_names & ROOT_ASSIGN_NAMES:
            self._add(value, 'hard-coded contract root selector assignment', ast.unparse(value))
            return
        literal = _literal_string(value)
        literals = [literal] if literal is not None else _literal_strings(value)
        for literal_value in literals:
            if any(any(part in name.lower() for part in SUSPICIOUS_NAME_PARTS) for name in target_names) and (
                _looks_like_selector(literal_value) or any(api in literal_value for api in JS_SELECTOR_APIS)
            ):
                self._add(value, 'selector-looking literal assigned to selector-like name', literal_value)
                return

    def visit_Constant(self, node: ast.Constant) -> Any:
        """Check string literals for embedded browser selector APIs."""
        if isinstance(node.value, str) and any(api in node.value for api in JS_SELECTOR_APIS):
            self._add(node, 'browser selector API embedded in string literal', node.value)
        self.generic_visit(node)


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _python_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob('*.py') if not _ignored(p)))
        elif path.suffix == '.py' and not _ignored(path):
            files.append(path)
    return files


def _ignored(path: Path) -> bool:
    return any(part in {'.venv', '__pycache__', '.git'} for part in path.parts)


def check_files(paths: list[Path]) -> list[Violation]:
    """Return hard-coded selector violations under the provided files or directories."""
    violations: list[Violation] = []
    for path in _python_files(paths):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except SyntaxError as exc:
            violations.append(Violation(path, exc.lineno or 1, exc.offset or 1, 'syntax error', exc.msg))
            continue
        visitor = SelectorVisitor(path)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return violations


def main(argv: list[str] | None = None) -> int:
    """Run the selector policy check as a command-line hook."""
    raw_args = sys.argv[1:] if argv is None else argv
    paths = [Path(arg) for arg in raw_args] if raw_args else list(DEFAULT_ROOTS)
    violations = check_files(paths)
    if violations:
        print('Hard-coded selectors are not allowed in examples. Describe contracts and let Yosoi discover them.')
        for violation in violations:
            print(f'{violation.path}:{violation.line}:{violation.col}: {violation.reason}: {violation.value}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
