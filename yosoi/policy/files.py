"""JSON/YAML policy flash-file loading for Yosoi."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml

from yosoi.policy.core import Policy

PolicyFormat = Literal['json', 'yaml']
POLICY_SCHEMA_URL = 'https://cascadinglabs.com/yosoi/schemas/policy.schema.json'
_POLICY_SUFFIXES = ('.yaml', '.yml', '.json')
_ALLOWED_POLICY_KEYS = frozenset(Policy.model_fields)
_RESERVED_NAMESPACE_KEYS = frozenset({'yosoi', 'ys', 'yis'})


class PolicyFileError(ValueError):
    """Raised when a policy source cannot be parsed or validated."""


def default_global_policy_paths() -> tuple[Path, ...]:
    """Return global policy flash-file candidates in precedence order."""
    root = Path.home() / '.config' / 'yosoi'
    return (
        *(root / f'policy{suffix}' for suffix in _POLICY_SUFFIXES),
        *_policy_directory_files(root / 'policy'),
    )


def default_project_policy_paths(root: Path | str = '.') -> tuple[Path, ...]:
    """Return project policy flash-file candidates in precedence order."""
    base = Path(root)
    yosoi_root = base / '.yosoi'
    return (
        *(yosoi_root / f'policy{suffix}' for suffix in _POLICY_SUFFIXES),
        *_policy_directory_files(yosoi_root / 'policy'),
        *(base / f'yosoi.policy{suffix}' for suffix in _POLICY_SUFFIXES),
    )


def discover_policy_files(root: Path | str = '.') -> tuple[Path, ...]:
    """Return existing global and project policy flash files."""
    return tuple(
        path for path in (*default_global_policy_paths(), *default_project_policy_paths(root)) if path.is_file()
    )


def _policy_directory_files(path: Path) -> tuple[Path, ...]:
    """Return recursive JSON/YAML children sorted lexicographically; ignore other files."""
    if not path.is_dir():
        return ()
    return tuple(
        sorted(
            (child for child in path.rglob('*') if child.is_file() and child.suffix.lower() in _POLICY_SUFFIXES),
            key=lambda child: child.relative_to(path).as_posix(),
        )
    )


def load_policy_source(source: str | Path) -> Policy:
    """Load a policy from a file, directory, or inline JSON/YAML document."""
    if isinstance(source, Path):
        if source.is_dir():
            return load_policy_directory(source)
        return load_policy_file(source)
    path = Path(source).expanduser()
    if path.is_dir():
        return load_policy_directory(path)
    if path.is_file():
        return load_policy_file(path)
    return _policy_from_text(source, source_name='inline policy')


def load_policy_file(path: str | Path) -> Policy:
    """Load a policy from a JSON/YAML file."""
    resolved = Path(path).expanduser()
    try:
        text = resolved.read_text(encoding='utf-8')
    except OSError as exc:
        raise PolicyFileError(f'Cannot read policy file {str(resolved)!r}: {exc}') from exc
    return _policy_from_text(text, source_name=str(resolved), suffix=resolved.suffix.lower())


def load_policy_directory(path: str | Path) -> Policy:
    """Load and cascade direct JSON/YAML policy fragments from a directory."""
    resolved = Path(path).expanduser()
    if not resolved.is_dir():
        raise PolicyFileError(f'Policy directory {str(resolved)!r} does not exist')
    return Policy.cascade(*(load_policy_file(child) for child in _policy_directory_files(resolved)))


def load_policy_layers(
    sources: Iterable[str | Path], *, include_discovered: bool = True, root: Path | str = '.'
) -> Policy:
    """Load and cascade discovered policy files plus explicit sources."""
    discovered: Sequence[str | Path] = discover_policy_files(root) if include_discovered else ()
    policies = [load_policy_source(source) for source in (*discovered, *tuple(sources))]
    return Policy.cascade(*policies)


def dump_policy(policy: Policy, *, fmt: PolicyFormat = 'json') -> str:
    """Serialize a policy as JSON or YAML."""
    data = policy.model_dump(mode='json', exclude_unset=False)
    if fmt == 'json':
        return json.dumps(data, indent=2) + '\n'
    if fmt == 'yaml':
        return str(yaml.safe_dump(data, sort_keys=False))
    raise ValueError(f'Unsupported policy format {fmt!r}')


def policy_json_schema() -> dict[str, Any]:
    """Return the JSON Schema used by editors for policy JSON/YAML files."""
    schema = Policy.model_json_schema(mode='validation')
    return {
        **schema,
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        '$id': POLICY_SCHEMA_URL,
        'title': 'Yosoi Policy',
        'description': 'Yosoi policy file schema for JSON and YAML editors.',
        'additionalProperties': False,
    }


def dump_policy_schema() -> str:
    """Serialize the policy JSON Schema."""
    return json.dumps(policy_json_schema(), indent=2) + '\n'


def policy_init_document() -> str:
    """Return a readable starter policy with an editor schema directive."""
    return (
        f'# yaml-language-server: $schema={POLICY_SCHEMA_URL}\n'
        '# Yosoi policy: global files live in ~/.config/yosoi/; project files live in .yosoi/.\n'
        '# Keep only the keys you want this layer to override. Higher-precedence layers win.\n'
        'atom_reads: false\n'
        'trust_tier: strict\n'
        'output:\n'
        '  quiet: true\n'
        '  formats: []\n'
    )


def policy_init_targets(*, global_config: bool = False, local_config: bool = False) -> tuple[Path, ...]:
    """Return policy init target paths; default to the local project policy file."""
    if not global_config and not local_config:
        local_config = True
    targets: list[Path] = []
    if global_config:
        targets.append(Path.home() / '.config' / 'yosoi' / 'policy.yaml')
    if local_config:
        targets.append(Path('.yosoi') / 'policy.yaml')
    return tuple(targets)


def init_policy_files(
    *, global_config: bool = False, local_config: bool = False, force: bool = False
) -> tuple[Path, ...]:
    """Create starter policy files and return the written paths."""
    document = policy_init_document()
    written: list[Path] = []
    for path in policy_init_targets(global_config=global_config, local_config=local_config):
        if path.exists() and not force:
            raise PolicyFileError(f'Policy file {str(path)!r} already exists; pass --force to overwrite')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document, encoding='utf-8')
        written.append(path)
    return tuple(written)


def _policy_from_text(text: str, *, source_name: str, suffix: str | None = None) -> Policy:
    if suffix == '.json':
        data = _load_json(text, source_name)
    elif suffix in {'.yaml', '.yml'}:
        data = _load_yaml(text, source_name)
    elif suffix not in {None, ''}:
        raise PolicyFileError(f'Unsupported policy file extension {suffix!r}; use .json, .yaml, or .yml')
    else:
        data = _load_json_or_yaml(text, source_name)
    return _policy_from_data(data, source_name=source_name)


def _load_json(text: str, source_name: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyFileError(f'Invalid JSON policy {source_name!r}: {exc}') from exc


def _load_yaml(text: str, source_name: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PolicyFileError(f'Invalid YAML policy {source_name!r}: {exc}') from exc


def _load_json_or_yaml(text: str, source_name: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _load_yaml(text, source_name)


def _policy_from_data(data: Any, *, source_name: str) -> Policy:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise PolicyFileError(f'Policy {source_name!r} must be a JSON/YAML object')
    keys = set(data)
    reserved = keys & _RESERVED_NAMESPACE_KEYS
    if reserved:
        names = ', '.join(sorted(reserved))
        raise PolicyFileError(
            f'Policy {source_name!r} must use the Policy shape directly; remove namespace key(s): {names}'
        )
    unknown = keys - _ALLOWED_POLICY_KEYS
    if unknown:
        names = ', '.join(sorted(unknown))
        raise PolicyFileError(f'Unknown top-level policy key(s) in {source_name!r}: {names}')
    try:
        return Policy.model_validate(data)
    except Exception as exc:
        raise PolicyFileError(f'Invalid policy {source_name!r}: {exc}') from exc


__all__ = [
    'POLICY_SCHEMA_URL',
    'PolicyFileError',
    'PolicyFormat',
    'default_global_policy_paths',
    'default_project_policy_paths',
    'discover_policy_files',
    'dump_policy',
    'dump_policy_schema',
    'init_policy_files',
    'load_policy_directory',
    'load_policy_file',
    'load_policy_layers',
    'load_policy_source',
    'policy_init_document',
    'policy_init_targets',
    'policy_json_schema',
]
