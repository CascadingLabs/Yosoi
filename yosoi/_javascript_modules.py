"""AST-backed linker for the confined JavaScript module subset."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

import tree_sitter_javascript
from tree_sitter import Language, Node, Parser

_MAX_MODULE_BYTES = 512_000
_MAX_GRAPH_BYTES = 2_000_000
_MAX_MODULES = 128

_LANGUAGE = Language(tree_sitter_javascript.language())
_DECLARATION_TYPES = {
    'class_declaration',
    'function_declaration',
    'lexical_declaration',
    'variable_declaration',
}
_FUNCTION_TYPES = {'arrow_function', 'function_expression'}
_FUNCTION_SCOPES = {
    'arrow_function',
    'function_declaration',
    'function_expression',
    'generator_function',
    'generator_function_declaration',
    'method_definition',
}


@dataclass(frozen=True)
class JavaScriptBundle:
    """One callable export linked into a browser-ready expression."""

    expression: str
    module: str
    export: str
    fingerprint: str


@dataclass(frozen=True)
class _Import:
    path: Path
    specifier: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class _ExportTarget:
    local: str | None = None
    path: Path | None = None
    imported: str | None = None


@dataclass
class _Module:
    path: Path
    source: bytes
    body: str
    imports: list[_Import] = field(default_factory=list)
    exports: dict[str, _ExportTarget] = field(default_factory=dict)
    bindings: set[str] = field(default_factory=set)
    callable_bindings: set[str] = field(default_factory=set)
    mutable_bindings: set[str] = field(default_factory=set)
    aliases: dict[str, str] = field(default_factory=dict)
    import_targets: dict[str, tuple[Path, str]] = field(default_factory=dict)
    identifiers: set[str] = field(default_factory=set)

    @property
    def dependencies(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys(item.path for item in self.imports))


class JavaScriptModuleLinker:
    """Link a safe, static subset of local ESM without flattening scopes."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f'JavaScript module root is not a directory: {self.root}')
        self._modules: dict[Path, _Module] = {}
        self._order: list[Path] = []
        self._stack: list[Path] = []
        self._graph_bytes = 0

    def function(self, module: str, *, export: str) -> JavaScriptBundle:
        """Link one named callable export from a confined module graph."""
        if not export.isidentifier():
            raise ValueError(f'invalid JavaScript export name: {export!r}')
        entry = self._resolve(self.root / module)
        self._load(entry)
        entry_module = self._modules[entry]
        if export not in entry_module.exports:
            raise ValueError(f'export {export!r} was not found in {module!r}')
        if not self._export_is_callable(entry, export):
            raise ValueError(f'export {export!r} is not statically callable')

        expression = self._emit(entry, export)
        if len(expression.encode('utf-8')) > _MAX_GRAPH_BYTES:
            raise ValueError(f'linked JavaScript bundle exceeds {_MAX_GRAPH_BYTES} bytes')
        fingerprint = hashlib.sha256(expression.encode('utf-8')).hexdigest()
        return JavaScriptBundle(
            expression=expression,
            module=entry.relative_to(self.root).as_posix(),
            export=export,
            fingerprint=fingerprint,
        )

    def _load(self, path: Path) -> None:
        path = self._resolve(path)
        if path in self._stack:
            start = self._stack.index(path)
            cycle = [*self._stack[start:], path]
            rendered = ' -> '.join(item.relative_to(self.root).as_posix() for item in cycle)
            raise ValueError(f'cyclic JavaScript imports are not supported: {rendered}')
        if path in self._modules:
            return
        if len(self._modules) >= _MAX_MODULES:
            raise ValueError(f'JavaScript module graph exceeds {_MAX_MODULES} files')

        source = self._read(path)
        module = self._parse(path, source)
        self._modules[path] = module
        self._stack.append(path)
        try:
            for dependency in module.dependencies:
                self._load(dependency)
            self._validate_links(module)
        except Exception:
            self._modules.pop(path, None)
            raise
        finally:
            self._stack.pop()
        self._order.append(path)

    def _parse(self, path: Path, source: bytes) -> _Module:
        tree = Parser(_LANGUAGE).parse(source)
        if tree.root_node.has_error:
            error = _first_parse_error(tree.root_node)
            point = error.start_point
            relative = path.relative_to(self.root).as_posix()
            raise ValueError(f'invalid JavaScript syntax in {relative}:{point.row + 1}:{point.column + 1}')

        module = _Module(path=path, source=source, body='')
        module.identifiers = {
            _node_text(node)
            for node in _walk(tree.root_node)
            if node.type in {'identifier', 'shorthand_property_identifier_pattern'}
        }
        _reject_runtime_module_syntax(tree.root_node, path)

        edits: list[tuple[int, int, bytes]] = []
        for statement in tree.root_node.named_children:
            if statement.type == 'import_statement':
                self._parse_import(module, statement)
                edits.append((statement.start_byte, statement.end_byte, b''))
                continue
            if statement.type == 'export_statement':
                replacement = self._parse_export(module, statement)
                edits.append((statement.start_byte, statement.end_byte, replacement))
                continue
            if statement.type in _DECLARATION_TYPES:
                self._record_declaration(module, statement)

        module.body = _apply_edits(source, edits).decode('utf-8').strip()
        return module

    def _parse_import(self, module: _Module, statement: Node) -> None:
        source = statement.child_by_field_name('source')
        clause = next((child for child in statement.named_children if child.type == 'import_clause'), None)
        named = (
            next((child for child in clause.named_children if child.type == 'named_imports'), None)
            if clause is not None
            else None
        )
        if source is None or named is None:
            self._unsupported(statement, module.path)
        specifier = _module_specifier(source, module.path)
        dependency = self._resolve_dependency(module.path, specifier)
        names: list[str] = []
        for item in named.named_children:
            if item.type != 'import_specifier':
                self._unsupported(statement, module.path)
            name_node = item.child_by_field_name('name')
            alias = item.child_by_field_name('alias')
            if name_node is None or alias is not None:
                raise ValueError(f'named JavaScript import/export aliases are not supported: {module.path}')
            name = _node_text(name_node)
            self._add_binding(module, name)
            module.import_targets[name] = (dependency, name)
            names.append(name)
        module.imports.append(_Import(dependency, specifier, tuple(names)))

    def _parse_export(self, module: _Module, statement: Node) -> bytes:
        if any(child.type == 'default' for child in statement.children):
            self._unsupported(statement, module.path)
        declaration = statement.child_by_field_name('declaration')
        if declaration is not None:
            if declaration.type not in _DECLARATION_TYPES:
                self._unsupported(statement, module.path)
            names = self._record_declaration(module, declaration)
            for name in names:
                self._add_export(module, name, _ExportTarget(local=name))
            return _node_bytes(declaration)

        clause = next((child for child in statement.named_children if child.type == 'export_clause'), None)
        if clause is None:
            self._unsupported(statement, module.path)
        source = statement.child_by_field_name('source')
        dependency: Path | None = None
        specifier: str | None = None
        if source is not None:
            specifier = _module_specifier(source, module.path)
            dependency = self._resolve_dependency(module.path, specifier)

        for item in clause.named_children:
            if item.type != 'export_specifier':
                self._unsupported(statement, module.path)
            name_node = item.child_by_field_name('name')
            alias = item.child_by_field_name('alias')
            if name_node is None or alias is not None:
                raise ValueError(f'named JavaScript import/export aliases are not supported: {module.path}')
            name = _node_text(name_node)
            target = (
                _ExportTarget(path=dependency, imported=name) if dependency is not None else _ExportTarget(local=name)
            )
            self._add_export(module, name, target)
        if dependency is not None and specifier is not None:
            module.imports.append(_Import(dependency, specifier, ()))
        return b''

    def _record_declaration(self, module: _Module, declaration: Node) -> tuple[str, ...]:
        if declaration.type in {'function_declaration', 'class_declaration'}:
            name_node = declaration.child_by_field_name('name')
            if name_node is None:
                self._unsupported(declaration, module.path)
            name = _node_text(name_node)
            self._add_binding(module, name)
            if declaration.type == 'function_declaration':
                module.callable_bindings.add(name)
            return (name,)

        if declaration.type not in {'lexical_declaration', 'variable_declaration'}:
            self._unsupported(declaration, module.path)
        mutable = declaration.type == 'variable_declaration' or any(
            child.type in {'let', 'var'} for child in declaration.children
        )
        names: list[str] = []
        for declarator in (child for child in declaration.named_children if child.type == 'variable_declarator'):
            pattern = declarator.child_by_field_name('name')
            if pattern is None:
                self._unsupported(declaration, module.path)
            declared = _pattern_bindings(pattern, module.path)
            value = declarator.child_by_field_name('value')
            for name in declared:
                self._add_binding(module, name)
                names.append(name)
                if mutable:
                    module.mutable_bindings.add(name)
            if len(declared) == 1 and value is not None:
                name = declared[0]
                if value.type in _FUNCTION_TYPES:
                    module.callable_bindings.add(name)
                elif value.type == 'identifier':
                    module.aliases[name] = _node_text(value)
        return tuple(names)

    def _validate_links(self, module: _Module) -> None:
        for item in module.imports:
            dependency = self._modules[item.path]
            for name in item.names:
                if name not in dependency.exports:
                    raise ValueError(f'export {name!r} was not found in {item.specifier!r}')
        for name, target in module.exports.items():
            if target.local is not None:
                if target.local not in module.bindings:
                    raise ValueError(f'export {name!r} references an undeclared binding in {module.path}')
                if target.local in module.mutable_bindings:
                    raise ValueError(f'export {name!r} uses a mutable live binding, which is not supported')
            elif target.path is not None and target.imported is not None:
                dependency = self._modules[target.path]
                if target.imported not in dependency.exports:
                    raise ValueError(f'export {target.imported!r} was not found in its re-exported module')

    def _export_is_callable(self, path: Path, name: str, seen: set[tuple[Path, str]] | None = None) -> bool:
        seen = set() if seen is None else seen
        key = (path, name)
        if key in seen:
            return False
        seen.add(key)
        module = self._modules[path]
        target = module.exports[name]
        if target.path is not None and target.imported is not None:
            return self._export_is_callable(target.path, target.imported, seen)
        assert target.local is not None
        return self._binding_is_callable(module, target.local, seen)

    def _binding_is_callable(self, module: _Module, name: str, seen: set[tuple[Path, str]]) -> bool:
        if name in module.callable_bindings:
            return True
        imported = module.import_targets.get(name)
        if imported is not None:
            return self._export_is_callable(imported[0], imported[1], seen)
        alias = module.aliases.get(name)
        if alias is not None:
            key = (module.path, alias)
            if key in seen:
                return False
            seen.add(key)
            return self._binding_is_callable(module, alias, seen)
        return False

    def _emit(self, entry: Path, export: str) -> str:
        all_identifiers = set().union(*(module.identifiers for module in self._modules.values()))
        digest = hashlib.sha256(
            b'\0'.join(
                path.relative_to(self.root).as_posix().encode() + b'\0' + self._modules[path].source
                for path in self._order
            )
        ).hexdigest()[:12]
        prefix = f'__yosoi_{digest}'
        while any(name.startswith(prefix) for name in all_identifiers):
            prefix += '_'
        variables = {path: f'{prefix}_m{index}' for index, path in enumerate(self._order)}

        chunks: list[str] = []
        for path in self._order:
            module = self._modules[path]
            lines = [f'const {variables[path]} = (function () {{', "'use strict';"]
            lines.extend(
                f'const {name} = {variables[item.path]}[{json.dumps(name)}];'
                for item in module.imports
                for name in item.names
            )
            relative = path.relative_to(self.root).as_posix()
            lines.append(f'// module: {json.dumps(relative)}')
            if module.body:
                lines.append(module.body)
            rendered_exports: list[str] = []
            for name, target in module.exports.items():
                key = json.dumps(name)
                if target.local is not None:
                    rendered_exports.append(f'[{key}]: {target.local}')
                else:
                    assert target.path is not None
                    assert target.imported is not None
                    imported = json.dumps(target.imported)
                    rendered_exports.append(f'[{key}]: {variables[target.path]}[{imported}]')
            lines.append(f'return {{{", ".join(rendered_exports)}}};')
            lines.append('})();')
            chunks.append('\n'.join(lines))

        body = '\n'.join(chunks)
        return f'(args => {{\n{body}\nreturn {variables[entry]}[{json.dumps(export)}](args);\n}})'

    def _add_binding(self, module: _Module, name: str) -> None:
        if name in module.bindings:
            raise ValueError(f'duplicate JavaScript binding {name!r} in {module.path}')
        module.bindings.add(name)

    def _add_export(self, module: _Module, name: str, target: _ExportTarget) -> None:
        if name in module.exports:
            raise ValueError(f'duplicate JavaScript export {name!r} in {module.path}')
        module.exports[name] = target

    def _read(self, path: Path) -> bytes:
        size = path.stat().st_size
        if size > _MAX_MODULE_BYTES:
            raise ValueError(f'JavaScript module exceeds {_MAX_MODULE_BYTES} bytes: {path}')
        self._graph_bytes += size
        if self._graph_bytes > _MAX_GRAPH_BYTES:
            raise ValueError(f'JavaScript module graph exceeds {_MAX_GRAPH_BYTES} bytes')
        source = path.read_bytes()
        try:
            source.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError(f'JavaScript module is not valid UTF-8: {path}') from exc
        return source

    def _resolve_dependency(self, importer: Path, specifier: str) -> Path:
        if not specifier.startswith('.'):
            raise ValueError(f'only relative JavaScript imports are supported: {specifier!r}')
        dependency = importer.parent / specifier
        if dependency.suffix not in {'.js', '.mjs'}:
            dependency = dependency.with_suffix('.mjs')
        return self._resolve(dependency)

    def _resolve(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f'JavaScript module escapes configured root: {path}') from exc
        if resolved.suffix not in {'.js', '.mjs'}:
            raise ValueError(f'JavaScript modules must use .js or .mjs: {resolved}')
        if not resolved.is_file():
            raise ValueError(f'JavaScript module does not exist: {resolved}')
        return resolved

    @staticmethod
    def _unsupported(node: Node, path: Path) -> NoReturn:
        point = node.start_point
        raise ValueError(f'unsupported JavaScript import/export syntax: {path}:{point.row + 1}:{point.column + 1}')


def _module_specifier(node: Node, path: Path) -> str:
    fragments = [child for child in node.named_children if child.type == 'string_fragment']
    if len(fragments) != 1 or any(child.type == 'escape_sequence' for child in node.named_children):
        point = node.start_point
        raise ValueError(f'unsupported JavaScript module specifier: {path}:{point.row + 1}:{point.column + 1}')
    return _node_text(fragments[0])


def _pattern_bindings(node: Node, path: Path) -> tuple[str, ...]:
    if node.type in {'identifier', 'shorthand_property_identifier_pattern'}:
        return (_node_text(node),)
    if node.type in {'array_pattern', 'object_pattern'}:
        names: list[str] = []
        for child in node.named_children:
            if child.type == 'pair_pattern':
                value = child.child_by_field_name('value')
                if value is None:
                    JavaScriptModuleLinker._unsupported(node, path)
                names.extend(_pattern_bindings(value, path))
            else:
                names.extend(_pattern_bindings(child, path))
        return tuple(names)
    if node.type == 'assignment_pattern':
        left = node.child_by_field_name('left')
        if left is None:
            JavaScriptModuleLinker._unsupported(node, path)
        return _pattern_bindings(left, path)
    if node.type == 'rest_pattern' and node.named_children:
        return _pattern_bindings(node.named_children[0], path)
    JavaScriptModuleLinker._unsupported(node, path)


def _reject_runtime_module_syntax(root: Node, path: Path) -> None:
    def visit(node: Node, *, in_function: bool) -> None:
        if node.type in {'hash_bang_line', 'meta_property', 'with_statement'}:
            JavaScriptModuleLinker._unsupported(node, path)
        if node.type == 'call_expression':
            function = node.child_by_field_name('function')
            if function is not None and function.type == 'import':
                JavaScriptModuleLinker._unsupported(node, path)
        if not in_function and (
            node.type in {'await_expression', 'return_statement', 'yield_expression'}
            or (node.type == 'identifier' and _node_text(node) == 'arguments')
        ):
            JavaScriptModuleLinker._unsupported(node, path)
        child_in_function = in_function or node.type in _FUNCTION_SCOPES
        for child in node.named_children:
            visit(child, in_function=child_in_function)

    visit(root, in_function=False)


def _apply_edits(source: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    output = source
    for start, end, replacement in sorted(edits, reverse=True):
        output = output[:start] + replacement + output[end:]
    return output


def _first_parse_error(node: Node) -> Node:
    if node.is_error or node.is_missing:
        return node
    for child in node.children:
        if child.has_error:
            return _first_parse_error(child)
    return node


def _walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _node_bytes(node: Node) -> bytes:
    text = node.text
    if text is None:  # pragma: no cover - parsed source-backed nodes always have text
        raise RuntimeError('JavaScript parser returned a node without source text')
    return text


def _node_text(node: Node) -> str:
    return _node_bytes(node).decode('utf-8')
