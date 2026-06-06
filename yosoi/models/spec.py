"""Canonical serializable Contract data (CAS-97).

A ContractSpec is a JSON-round-trippable description of a Contract that:
  - Has a stable structural fingerprint (description excluded — it's advisory).
  - Can be rehydrated into a working Contract subclass via ``to_contract()``.
  - Is accepted by ``resolve_contract()`` alongside names and ``path:Class`` strings.

Fingerprint inputs (no description — it has no enforcement teeth):
  schema_version + sorted field names + per-field (yosoi_type, selector, delimiter, frozen)
  + root selector + nested fingerprints + validators ref
"""

from __future__ import annotations

import hashlib
import importlib
import json
from typing import Any

from pydantic import BaseModel, Field, model_validator

CURRENT_SCHEMA_VERSION = 1


class FieldSpec(BaseModel):
    """Serializable description of one contract field."""

    yosoi_type: str | None = None
    description: str | None = None  # advisory/provenance — excluded from fingerprint
    selector: str | None = None  # yosoi_selector override
    delimiter: str | None = None  # yosoi_delimiter
    frozen: bool = False  # yosoi_frozen
    required: bool = True
    python_type: str = 'str'  # type annotation string used when rehydrating
    action: dict[str, Any] | None = None  # yosoi_action config (action fields only)

    def fingerprint_dict(self) -> dict[str, Any]:
        """Return the subset of this field that contributes to the contract fingerprint."""
        return {
            'yosoi_type': self.yosoi_type,
            'selector': self.selector,
            'delimiter': self.delimiter,
            'frozen': self.frozen,
            'python_type': self.python_type,
            'action_type': self.action.get('type') if self.action else None,
        }


class ContractSpec(BaseModel):
    """Canonical serializable representation of a Yosoi Contract."""

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION)
    name: str
    fields: dict[str, FieldSpec] = Field(default_factory=dict)
    root: dict[str, Any] | None = None  # SelectorEntry serialized, or None
    nested: dict[str, ContractSpec] = Field(default_factory=dict)
    validators: str | None = None  # "module.path:ClassName"

    @model_validator(mode='after')
    def _validate_schema_version(self) -> ContractSpec:
        if self.schema_version > CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f'schema_version {self.schema_version} is newer than this yosoi '
                f'version supports ({CURRENT_SCHEMA_VERSION}). Upgrade yosoi.'
            )
        return self

    @property
    def fingerprint(self) -> str:
        """Stable SHA-256 structural fingerprint (description excluded).

        Two specs with identical structure but different names or descriptions
        produce the same fingerprint and share a selector cache entry.
        """
        return _fingerprint(self)

    def to_contract(self) -> type[Contract]:
        """Rehydrate a working Contract subclass from this spec.

        Raises:
            ValueError: If an unknown yosoi_type is encountered.
            ImportError: If the validators ref cannot be imported.
        """
        from yosoi.models.contract import Contract as _Contract

        _validate_spec(self)

        validators_cls = _load_validators(self.validators) if self.validators else None

        field_defs: dict[str, Any] = {}
        import pydantic

        for field_name, fspec in self.fields.items():
            if fspec.action is not None:
                # Action field — rebuild ys.js() / ys.File() FieldInfo
                fi = _action_field_info(fspec)
            else:
                extra: dict[str, Any] = {}
                if fspec.yosoi_type:
                    extra['yosoi_type'] = fspec.yosoi_type
                if fspec.selector:
                    extra['yosoi_selector'] = fspec.selector
                if fspec.delimiter:
                    extra['yosoi_delimiter'] = fspec.delimiter
                if fspec.frozen:
                    extra['yosoi_frozen'] = True
                fi = pydantic.Field(
                    description=fspec.description,
                    json_schema_extra=extra or None,
                )
            ann = _python_type_to_annotation(fspec.python_type, fspec.required)
            field_defs[field_name] = (ann, fi)

        # Resolve nested contracts
        nested_defs: dict[str, Any] = {}
        for nested_name, nested_spec in self.nested.items():
            nested_cls = nested_spec.to_contract()
            nested_defs[nested_name] = (nested_cls, pydantic.Field())

        field_defs.update(nested_defs)

        cls = pydantic.create_model(self.name, __base__=_Contract, **field_defs)

        if self.root is not None:
            from yosoi.models.selectors import SelectorEntry

            cls.root = SelectorEntry.model_validate(self.root)  # type: ignore[attr-defined]

        if validators_cls is not None:
            cls._validators_cls = validators_cls  # type: ignore[attr-defined]

        return cls

    @classmethod
    def from_contract(cls, contract: type[Contract]) -> ContractSpec:
        """Reflect a Contract class into a serializable ContractSpec."""
        from yosoi.models.contract import Contract as _Contract

        fields: dict[str, FieldSpec] = {}
        nested: dict[str, ContractSpec] = {}

        for field_name, fi in contract.model_fields.items():
            ann = fi.annotation
            is_nested = isinstance(ann, type) and issubclass(ann, _Contract)

            if is_nested:
                if isinstance(ann, type) and issubclass(ann, _Contract):
                    nested[field_name] = cls.from_contract(ann)
                continue

            extra: dict[str, Any] = fi.json_schema_extra if isinstance(fi.json_schema_extra, dict) else {}
            action = extra.get('yosoi_action')

            # Derive a simple python_type string
            python_type = _annotation_to_python_type(ann, fi)

            fields[field_name] = FieldSpec(
                yosoi_type=extra.get('yosoi_type'),
                description=fi.description,
                selector=extra.get('yosoi_selector'),
                delimiter=extra.get('yosoi_delimiter'),
                frozen=bool(extra.get('yosoi_frozen', False)),
                required=fi.is_required(),
                python_type=python_type,
                action=action if isinstance(action, dict) else None,
            )

        root_dict = contract.root.model_dump() if contract.root is not None else None

        validators_ref: str | None = None
        if contract._validators_cls is not None:
            m = contract._validators_cls.__module__
            n = contract._validators_cls.__qualname__
            validators_ref = f'{m}:{n}'

        return cls(
            name=contract.__name__,
            fields=fields,
            root=root_dict,
            nested=nested,
            validators=validators_ref,
        )

    # Convenience alias
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContractSpec:
        """Parse a ContractSpec from a raw dict (e.g. parsed from JSON)."""
        return cls.model_validate(data)


# ── helpers ──────────────────────────────────────────────────────────────────


def _fingerprint(spec: ContractSpec) -> str:
    """Compute a stable 16-char fingerprint for a ContractSpec."""
    payload = _fingerprint_dict(spec)
    serialized = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def _fingerprint_dict(spec: ContractSpec) -> dict[str, Any]:
    return {
        'v': spec.schema_version,
        'fields': {name: fspec.fingerprint_dict() for name, fspec in sorted(spec.fields.items())},
        'root': spec.root,
        'nested': {name: _fingerprint_dict(ns) for name, ns in sorted(spec.nested.items())},
        'validators': spec.validators,
    }


def _validate_spec(spec: ContractSpec) -> None:
    """Fail-fast on unknown yosoi_types and unresolvable validators."""
    from yosoi.types.registry import _registry as _coerce_registry

    for field_name, fspec in spec.fields.items():
        if fspec.yosoi_type is not None and fspec.yosoi_type not in _coerce_registry:
            raise ValueError(
                f'Unknown yosoi_type {fspec.yosoi_type!r} on field {field_name!r}. '
                f'Register it with @register_coercion before using it in a spec.'
            )

    if spec.validators:
        _load_validators(spec.validators)  # raises ImportError if unresolvable

    for nested_spec in spec.nested.values():
        _validate_spec(nested_spec)


def _load_validators(ref: str) -> type[object]:
    """Import a Validators class from a ``module:ClassName`` reference."""
    if ':' not in ref:
        raise ImportError(f'validators ref must be "module.path:ClassName", got {ref!r}')
    module_path, class_name = ref.rsplit(':', 1)
    try:
        mod = importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(f'Cannot import validators module {module_path!r}: {e}') from e
    cls: type[object] | None = getattr(mod, class_name, None)
    if cls is None:
        raise ImportError(f'Class {class_name!r} not found in {module_path!r}')
    return cls


def _action_field_info(fspec: FieldSpec) -> Any:
    """Reconstruct a pydantic FieldInfo for an action field from its spec."""
    import pydantic

    assert fspec.action is not None
    extra: dict[str, Any] = {'yosoi_action': fspec.action}
    return pydantic.Field(description=fspec.description, json_schema_extra=extra)


def _python_type_to_annotation(type_str: str, required: bool) -> Any:
    """Convert a stored python_type string back to a Python type annotation."""
    _SIMPLE: dict[str, Any] = {
        'str': str,
        'int': int,
        'float': float,
        'bool': bool,
        'dict': dict,
        'list': list,
    }
    base = _SIMPLE.get(type_str, str)
    if not required:
        return base | None
    return base


def _annotation_to_python_type(ann: Any, fi: Any) -> str:
    """Convert a field annotation to a simple string for storage."""
    import typing

    if ann is None:
        return 'str'
    origin = typing.get_origin(ann)
    if origin is typing.Union:
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        inner: Any = args[0] if args else str
        result: str = getattr(inner, '__name__', None) or 'str'
        return result
    attr_name: str | None = getattr(ann, '__name__', None)
    if attr_name:
        return attr_name
    return 'str'


# Avoid circular import — Contract imported at function call sites above.
# Type alias for doc/hint purposes only.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yosoi.models.contract import Contract
