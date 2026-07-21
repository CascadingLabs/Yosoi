"""Typed executor descriptors and local JavaScript module loading."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import pydantic
from pydantic_core import PydanticUndefined

from yosoi.types.field import js as js_field

_IMPORT_RE = re.compile(r"^\s*import\s+\{[^}]+\}\s+from\s+['\"]([^'\"]+)['\"]\s*;?\s*$", re.MULTILINE)
_REEXPORT_RE = re.compile(r"^\s*export\s+\{[^}]+\}\s+from\s+['\"]([^'\"]+)['\"]\s*;?\s*$", re.MULTILINE)
_EXPORT_DECL_RE = re.compile(r'\bexport\s+(?=(?:async\s+)?function\b|(?:const|let|var|class)\b)')
_MAX_MODULE_BYTES = 512_000


@dataclass(frozen=True)
class InputRef:
    """A runtime Flow input referenced by an executor or browser act."""

    name: str


@dataclass(frozen=True)
class Settle:
    """Readiness condition applied to a JavaScript result."""

    kind: str
    value: int | None = None
    timeout: float = 5.0
    poll_interval: float = 0.25


class _Until:
    """Factories for evaluator readiness conditions."""

    @staticmethod
    def non_null(*, timeout: float = 5.0, poll_interval: float = 0.25) -> Settle:
        """Require a non-null result before the browser settle budget expires."""
        _validate_settle_timing(timeout, poll_interval)
        return Settle('non_null', timeout=timeout, poll_interval=poll_interval)

    @staticmethod
    def length_at_least(value: int, *, timeout: float = 5.0, poll_interval: float = 0.25) -> Settle:
        """Require an array-like result with at least ``value`` entries."""
        if value < 0:
            raise ValueError('length_at_least must be >= 0')
        _validate_settle_timing(timeout, poll_interval)
        return Settle('length_at_least', value=value, timeout=timeout, poll_interval=poll_interval)


def _validate_settle_timing(timeout: float, poll_interval: float) -> None:
    if timeout < 0:
        raise ValueError('settle timeout must be >= 0')
    if poll_interval <= 0:
        raise ValueError('settle poll_interval must be > 0')


until = _Until()


def input(name: str) -> InputRef:
    """Reference one named runtime input in a Flow declaration."""
    if not name:
        raise ValueError('input name must not be empty')
    return InputRef(name)


@dataclass(frozen=True)
class JavaScriptFunction:
    """One named callable bundled from a confined local ESM graph."""

    expression: str
    module: str
    export: str
    fingerprint: str

    def bind(self, args: Any) -> str:
        """Return a browser expression invoking this function with JSON arguments."""
        payload = json.dumps(args, sort_keys=True, separators=(',', ':'))
        return f'({self.expression})({payload})'


class JavaScriptModules:
    """Confined loader for small static relative ESM module trees."""

    def __init__(self, root: str | Path) -> None:
        """Create a module loader confined to ``root``."""
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f'JavaScript module root is not a directory: {self.root}')

    def function(self, module: str, *, export: str) -> JavaScriptFunction:
        """Bundle one named function export and its static relative imports."""
        if not export.isidentifier():
            raise ValueError(f'invalid JavaScript export name: {export!r}')
        entry = self._resolve(self.root / module)
        chunks: list[tuple[Path, str]] = []
        visited: set[Path] = set()
        self._visit(entry, visited, chunks)
        source = '\n'.join(f'// {path.relative_to(self.root).as_posix()}\n{text}' for path, text in chunks)
        if re.search(rf'\b(?:function|const|let|var|class)\s+{re.escape(export)}\b', source) is None:
            raise ValueError(f'export {export!r} was not found in {module!r}')
        expression = f'(args => {{\n{source}\nreturn {export}(args);\n}})'
        fingerprint = hashlib.sha256(expression.encode('utf-8')).hexdigest()
        return JavaScriptFunction(expression, entry.relative_to(self.root).as_posix(), export, fingerprint)

    def _visit(self, path: Path, visited: set[Path], chunks: list[tuple[Path, str]]) -> None:
        path = self._resolve(path)
        if path in visited:
            return
        visited.add(path)
        if path.stat().st_size > _MAX_MODULE_BYTES:
            raise ValueError(f'JavaScript module exceeds {_MAX_MODULE_BYTES} bytes: {path}')
        text = path.read_text(encoding='utf-8')
        dependency_specs = [*_IMPORT_RE.findall(text), *_REEXPORT_RE.findall(text)]
        for spec in dependency_specs:
            if not spec.startswith('.'):
                raise ValueError(f'only relative JavaScript imports are supported: {spec!r}')
            dependency = path.parent / spec
            if dependency.suffix not in {'.js', '.mjs'}:
                dependency = dependency.with_suffix('.mjs')
            self._visit(dependency, visited, chunks)
        stripped = _IMPORT_RE.sub('', text)
        stripped = _REEXPORT_RE.sub('', stripped)
        stripped = _EXPORT_DECL_RE.sub('', stripped)
        if re.search(r'\b(?:import|export)\s*\(', stripped) or re.search(r"\bimport\s+[^'{]", stripped):
            raise ValueError(f'dynamic/default JavaScript imports are not supported: {path}')
        chunks.append((path, stripped.strip()))

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


def _encode_refs(value: Any) -> Any:
    if isinstance(value, InputRef):
        return {'$input': value.name}
    if isinstance(value, dict):
        return {str(key): _encode_refs(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode_refs(item) for item in value]
    return value


def resolve_refs(value: Any, inputs: dict[str, Any]) -> Any:
    """Resolve serialized InputRef markers against runtime Flow inputs."""
    if isinstance(value, dict) and set(value) == {'$input'}:
        name = value['$input']
        if name not in inputs:
            raise ValueError(f'missing required Flow input: {name}')
        return inputs[name]
    if isinstance(value, dict):
        return {key: resolve_refs(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_refs(item, inputs) for item in value]
    return value


class _JavaScriptExecutor:
    """Callable public ``ys.Executor.js`` namespace."""

    @staticmethod
    def modules(root: str | Path) -> JavaScriptModules:
        """Open a confined local JavaScript module tree."""
        return JavaScriptModules(root)

    def __call__(
        self,
        program: str | JavaScriptFunction | None = None,
        *,
        args: Any = None,
        description: str | None = None,
        scope: str = 'page',
        settle: Settle | None = None,
        default: Any = PydanticUndefined,
        **kwargs: Any,
    ) -> pydantic.fields.FieldInfo:
        """Declare a typed JavaScript field or Flow EVAL node.

        Literal arguments compile immediately for ordinary Contract fields. InputRef
        arguments remain JSON-safe metadata and are bound when a Flow compiles.
        """
        if scope != 'page':
            raise ValueError("ys.Executor.js currently supports only scope='page'")
        encoded_args = _encode_refs({} if args is None else args)
        has_refs = _contains_refs(encoded_args)
        function: JavaScriptFunction | None = program if isinstance(program, JavaScriptFunction) else None
        source = function.expression if function is not None else None
        field: pydantic.fields.FieldInfo

        if program is None:
            field = js_field(None, description=description, default=default, **kwargs)
        elif isinstance(program, str) and not has_refs and args is None:
            field = js_field(program, description=description, default=default, **kwargs)
        elif isinstance(program, str) and not has_refs:
            payload = json.dumps(encoded_args, sort_keys=True, separators=(',', ':'))
            script = _apply_settle(f'({program})({payload})', settle)
            field = js_field(script, description=description, default=default, **kwargs)
        elif function is not None and not has_refs:
            script = _apply_settle(function.bind(encoded_args), settle)
            field = js_field(script, description=description, default=default, **kwargs)
        else:
            if source is None:
                source = str(program)
            extra = dict(kwargs.pop('json_schema_extra', {}) or {})
            extra['yosoi_action'] = {
                'type': 'js',
                'script': None,
                'description': description,
                'program': source,
                'args': encoded_args,
                'settle': asdict(settle) if settle is not None else None,
                'module': function.module if function is not None else None,
                'export': function.export if function is not None else None,
                'fingerprint': function.fingerprint if function is not None else None,
                'flow_inputs': sorted(_input_names(encoded_args)),
            }
            field = cast(
                pydantic.fields.FieldInfo,
                pydantic.Field(default, description=description, json_schema_extra=extra, **kwargs),
            )

        raw_extra = field.json_schema_extra
        marker = raw_extra.get('yosoi_action') if isinstance(raw_extra, dict) else None
        if isinstance(marker, dict):
            marker['scope'] = scope
            marker['settle'] = asdict(settle) if settle is not None else None
            if function is not None:
                marker['module'] = function.module
                marker['export'] = function.export
                marker['fingerprint'] = function.fingerprint
        return field


def bind_executor_action(config: dict[str, Any], inputs: dict[str, Any]) -> str:
    """Bind one Executor.js action config into a browser-ready expression."""
    script = config.get('script')
    if isinstance(script, str) and script:
        return script
    program = config.get('program')
    if not isinstance(program, str) or not program:
        raise ValueError('Executor.js action has neither a script nor a callable program')
    args = resolve_refs(config.get('args') or {}, inputs)
    payload = json.dumps(args, sort_keys=True, separators=(',', ':'))
    bound = f'({program})({payload})'
    raw_settle = config.get('settle')
    settle = Settle(**raw_settle) if isinstance(raw_settle, dict) else None
    return _apply_settle(bound, settle)


def _input_names(value: Any) -> set[str]:
    if isinstance(value, dict) and set(value) == {'$input'}:
        return {str(value['$input'])}
    if isinstance(value, dict):
        return set().union(*(_input_names(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_input_names(item) for item in value)) if value else set()
    return set()


def _contains_refs(value: Any) -> bool:
    if isinstance(value, dict):
        return set(value) == {'$input'} or any(_contains_refs(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_refs(item) for item in value)
    return False


def _apply_settle(script: str, settle: Settle | None) -> str:
    if settle is None or settle.kind == 'non_null':
        return script
    if settle.kind == 'length_at_least':
        minimum = int(settle.value or 0)
        return f'(() => {{ const value = ({script}); return value?.length >= {minimum} ? value : null; }})()'
    raise ValueError(f'unsupported JavaScript settle condition: {settle.kind}')


class Executor:
    """Namespaces for typed executable contract and Flow fields."""

    js = _JavaScriptExecutor()
