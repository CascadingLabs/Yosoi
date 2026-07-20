"""Canonical serializable Contract data (CAS-97).

A ContractSpec is a JSON-round-trippable description of a Contract that:
  - Has a stable identity fingerprint that DISCRIMINATES contracts by structure + intent.
  - Can be rehydrated into a working Contract subclass via ``to_contract()``.
  - Is accepted by ``resolve_contract()`` alongside names and ``path:Class`` strings.

Fingerprint inputs:
  contract ``name`` + normalized ``doc`` (the discovery-time disambiguator — two
  structurally identical contracts with different NL intent, e.g. ``AdLink`` vs
  ``OrganicLink`` both ``{url, title}``, MUST get distinct cache slots)
  + schema_version + sorted field entities + root selector + nested fingerprints
  + validators ref.

Per-FIELD ``description`` is INCLUDED through each field entity fingerprint. Fields
are first-class schema entities; a contract is identified by the collection of field
fingerprints it references plus its own name/docstring intent.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import operator
import types
import typing
from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticUndefined

from yosoi.models.extraction import (
    ExtractorResolutionError,
    ExtractorSpec,
    annotation_identity,
    callable_reference,
    resolve_extractor_bindings,
)
from yosoi.utils.signatures import _normalize

CURRENT_SCHEMA_VERSION = 2


class AnnotationSpec(BaseModel):
    """Structured, import-aware Python annotation representation (schema v2)."""

    kind: typing.Literal['any', 'none', 'ellipsis', 'literal', 'reference', 'generic', 'union']
    module: str | None = None
    qualname: str | None = None
    args: list[AnnotationSpec] = Field(default_factory=list)
    literal_values: list[Any] = Field(default_factory=list)

    def to_annotation(self) -> Any:
        """Rehydrate the annotation, failing fast on stale import references."""
        if self.kind == 'any':
            return Any
        if self.kind == 'none':
            return type(None)
        if self.kind == 'ellipsis':
            return Ellipsis
        if self.kind == 'literal':
            if not self.literal_values:
                raise ImportError('Literal annotation has no values')
            return operator.getitem(typing.cast(Any, typing.Literal), tuple(self.literal_values))
        if self.kind == 'union':
            members = [arg.to_annotation() for arg in self.args]
            if not members:
                raise ImportError('annotation union has no members')
            result = members[0]
            for member in members[1:]:
                result = result | member
            return result
        if not self.module or not self.qualname:
            raise ImportError(f'annotation {self.kind!r} requires module and qualname')
        target = _load_annotation_reference(self.module, self.qualname)
        if self.kind == 'reference':
            return target
        args = tuple(arg.to_annotation() for arg in self.args)
        try:
            return target[args[0] if len(args) == 1 else args]
        except (TypeError, AttributeError) as exc:
            raise ImportError(f'cannot apply annotation arguments to {self.module}:{self.qualname}: {exc}') from exc

    def render(self) -> str:
        """Render an importable expression for generated contract Python."""
        if self.kind == 'any':
            return 'Any'
        if self.kind == 'none':
            return 'None'
        if self.kind == 'ellipsis':
            return '...'
        if self.kind == 'literal':
            values = ', '.join(repr(value) for value in self.literal_values)
            return f"_load_ref('typing:Literal')[{values}]"
        if self.kind == 'union':
            return ' | '.join(arg.render() for arg in self.args)
        assert self.module
        assert self.qualname
        simple = {
            ('builtins', 'str'): 'str',
            ('builtins', 'int'): 'int',
            ('builtins', 'float'): 'float',
            ('builtins', 'bool'): 'bool',
            ('builtins', 'dict'): 'dict',
            ('builtins', 'list'): 'list',
            ('builtins', 'tuple'): 'tuple',
            ('builtins', 'set'): 'set',
            ('builtins', 'frozenset'): 'frozenset',
        }.get((self.module, self.qualname))
        base = simple or f'_load_ref({f"{self.module}:{self.qualname}"!r})'
        if self.kind == 'generic':
            return f'{base}[{", ".join(arg.render() for arg in self.args)}]'
        return base


class AnnotationMetadataValueSpec(BaseModel):
    """One serializable constructor argument for ``Annotated`` metadata."""

    kind: typing.Literal['json', 'callable', 'annotation']
    value: Any = None
    reference: str | None = None
    annotation: AnnotationSpec | None = None

    def to_value(self) -> Any:
        """Rehydrate one metadata constructor argument."""
        if self.kind == 'json':
            return self.value
        if self.kind == 'callable':
            if self.reference is None:
                raise ImportError('callable annotation metadata value requires a reference')
            return _load_ref_callable(self.reference)
        if self.annotation is None:
            raise ImportError('annotation metadata value requires an annotation')
        return self.annotation.to_annotation()

    def render(self) -> str:
        """Render one metadata constructor argument for generated Python."""
        if self.kind == 'json':
            return repr(self.value)
        if self.kind == 'callable':
            return f'_load_ref({self.reference!r})'
        assert self.annotation is not None
        return self.annotation.render()


class AnnotationMetadataSpec(BaseModel):
    """Import-aware representation of one dataclass-based ``Annotated`` marker."""

    reference: str
    kwargs: dict[str, AnnotationMetadataValueSpec] = Field(default_factory=dict)

    def to_metadata(self) -> Any:
        """Rehydrate the metadata marker and its constructor arguments."""
        target = _load_ref_callable(self.reference)
        try:
            return target(**{name: value.to_value() for name, value in self.kwargs.items()})
        except TypeError as exc:
            raise ImportError(f'cannot reconstruct annotation metadata {self.reference}: {exc}') from exc

    def render(self) -> str:
        """Render the metadata marker for generated contract Python."""
        kwargs = ', '.join(f'{name}={value.render()}' for name, value in self.kwargs.items())
        return f'_load_ref({self.reference!r})({kwargs})'


class FieldSpec(BaseModel):
    """Serializable description of one contract field."""

    yosoi_type: str | None = None
    description: str | None = None  # field-entity prose — included in fingerprint
    selector: str | None = None  # yosoi_selector override
    delimiter: str | None = None  # yosoi_delimiter
    frozen: bool = False  # yosoi_frozen
    required: bool = True
    python_type: str = 'str'  # v1 compatibility for ordinary selector/action fields
    annotation: AnnotationSpec | None = None  # lossless v2 annotation (extractor fields)
    annotation_metadata: list[AnnotationMetadataSpec] = Field(default_factory=list)
    action: dict[str, Any] | None = None  # yosoi_action config (action fields only)
    extractor: ExtractorSpec | None = None  # deterministic strategy identity/config
    has_default: bool = False
    default: Any = None
    default_factory: str | None = None

    @property
    def fingerprint(self) -> str:
        """Stable field-entity fingerprint including its description."""
        payload = json.dumps(self.fingerprint_dict(), sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def fingerprint_dict(self) -> dict[str, Any]:
        """Return the subset of this field that contributes to its fingerprint."""
        payload: dict[str, Any] = {
            'description': _normalize(self.description),
            'yosoi_type': self.yosoi_type,
            'selector': self.selector,
            'delimiter': self.delimiter,
            'frozen': self.frozen,
            'python_type': self.python_type,
            'action_type': self.action.get('type') if self.action else None,
        }
        # Preserve the v1 identity of ordinary selector/action fields. Extractor
        # identity has its own independently versioned inputs.
        if self.extractor is not None:
            payload.update(
                {
                    'annotation': self.annotation.model_dump(mode='json') if self.annotation else None,
                    'annotation_metadata': [item.model_dump(mode='json') for item in self.annotation_metadata],
                    'extractor': self.extractor.model_dump(mode='json'),
                    'has_default': self.has_default,
                    'default': self.default if self.has_default else None,
                    'default_factory': self.default_factory,
                }
            )
        return payload


class ContractSpec(BaseModel):
    """Canonical serializable representation of a Yosoi Contract."""

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION)
    name: str
    doc: str | None = None  # contract-level docstring — discovery-time intent disambiguator (in fingerprint)
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
        """Stable 16-hex identity fingerprint for this contract schema.

        Two structurally identical contracts that differ by ``name`` or contract-level
        ``doc`` produce DIFFERENT fingerprints. Per-field descriptions also contribute
        through field fingerprints because fields are first-class schema entities.
        """
        payload = json.dumps(
            {
                'name': _normalize(self.name),
                'doc': _normalize(self.doc),
                'struct': _fingerprint_dict(self),
            },
            sort_keys=True,
            separators=(',', ':'),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

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
            elif fspec.extractor is not None:
                fi = _extractor_field_info(fspec)
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
            ann = (
                fspec.annotation.to_annotation()
                if fspec.annotation is not None
                else _python_type_to_annotation(fspec.python_type, fspec.required)
            )
            if fspec.annotation_metadata:
                metadata = tuple(item.to_metadata() for item in fspec.annotation_metadata)
                ann = typing.Annotated[(ann, *metadata)]
            field_defs[field_name] = (ann, fi)

        # Resolve nested contracts
        nested_defs: dict[str, Any] = {}
        for nested_name, nested_spec in self.nested.items():
            nested_cls = nested_spec.to_contract()
            nested_defs[nested_name] = (nested_cls, pydantic.Field())

        field_defs.update(nested_defs)

        cls = pydantic.create_model(self.name, __base__=_Contract, **field_defs)
        # Preserve the contract-level docstring (create_model drops it) so a rehydrated
        # contract's intent — and its contract_signature — match the original.
        cls.__doc__ = self.doc

        if self.root is not None:
            from yosoi.models.selectors import SelectorEntry

            cls.root = SelectorEntry.model_validate(self.root)

        if validators_cls is not None:
            cls._validators_cls = validators_cls

        return cls

    @classmethod
    def from_contract(cls, contract: type[Contract]) -> ContractSpec:
        """Reflect a Contract class into a serializable ContractSpec."""
        from yosoi.models.contract import Contract as _Contract

        fields: dict[str, FieldSpec] = {}
        nested: dict[str, ContractSpec] = {}
        extractor_configs = contract.extractor_fields()
        bindings = resolve_extractor_bindings(contract, fail_required=False) if extractor_configs else {}

        for field_name, fi in contract.model_fields.items():
            ann = fi.annotation
            is_nested = isinstance(ann, type) and issubclass(ann, _Contract)

            if is_nested:
                if isinstance(ann, type) and issubclass(ann, _Contract):
                    nested[field_name] = cls.from_contract(ann)
                continue

            extra: dict[str, Any] = fi.json_schema_extra if isinstance(fi.json_schema_extra, dict) else {}
            action = extra.get('yosoi_action')
            binding = bindings.get(field_name)
            extractor: ExtractorSpec | None = None
            annotation_spec: AnnotationSpec | None = None
            annotation_metadata: list[AnnotationMetadataSpec] = []
            has_default = False
            default: Any = None
            default_factory: str | None = None
            if field_name in extractor_configs:
                annotation_spec = _annotation_to_spec(ann)
                annotation_metadata = [_annotation_metadata_to_spec(item) for item in fi.metadata]
                if binding is not None:
                    extractor = binding.spec
                else:
                    extractor = ExtractorSpec(
                        resolver_id=f'unresolved:{annotation_identity(ann)}',
                        version='1',
                        source='registry',
                        reference='unresolved',
                        config=dict(extractor_configs[field_name].get('config') or {}),
                    )
                if fi.default is not PydanticUndefined:
                    has_default = True
                    default = fi.default
                    try:
                        json.dumps(default)
                    except (TypeError, ValueError) as exc:
                        raise TypeError(
                            f'{contract.__name__}.{field_name} extractor default must be JSON-serializable'
                        ) from exc
                elif fi.default_factory is not None:
                    default_factory = callable_reference(fi.default_factory)

            # Derive the v1 python_type string for compatibility/readability.
            python_type = _annotation_to_python_type(ann, fi)

            fields[field_name] = FieldSpec(
                yosoi_type=extra.get('yosoi_type'),
                description=fi.description,
                selector=extra.get('yosoi_selector'),
                delimiter=extra.get('yosoi_delimiter'),
                frozen=bool(extra.get('yosoi_frozen', False)),
                required=fi.is_required(),
                python_type=python_type,
                annotation=annotation_spec,
                annotation_metadata=annotation_metadata,
                action=action if isinstance(action, dict) else None,
                extractor=extractor,
                has_default=has_default,
                default=default,
                default_factory=default_factory,
            )

        root_dict = contract.root.model_dump() if contract.root is not None else None

        validators_ref: str | None = None
        if contract._validators_cls is not None:
            m = contract._validators_cls.__module__
            n = contract._validators_cls.__qualname__
            validators_ref = f'{m}:{n}'

        return cls(
            schema_version=2 if extractor_configs else 1,
            name=contract.__name__,
            doc=contract.__doc__,
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


def _fingerprint_dict(spec: ContractSpec) -> dict[str, Any]:
    # Schema v2 adds extractor representation only. Ordinary v1 selector/action
    # contracts retain their exact identity when read/migrated under a v2 runtime.
    has_extractors = any(field.extractor is not None for field in spec.fields.values())
    identity_version = spec.schema_version if has_extractors or spec.schema_version not in {1, 2} else 1
    return {
        'v': identity_version,
        'fields': {name: fspec.fingerprint for name, fspec in sorted(spec.fields.items())},
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
        if fspec.extractor is not None:
            if fspec.annotation is None:
                raise ValueError(f'Extractor field {field_name!r} requires a structured annotation in schema v2')
            fspec.annotation.to_annotation()
            for metadata in fspec.annotation_metadata:
                metadata.to_metadata()
            if fspec.extractor.plan is not None:
                from yosoi.models.extraction import validate_extraction_plan

                validate_extraction_plan(fspec.extractor.plan)
            if (
                fspec.extractor.plan is None
                and fspec.extractor.reference not in {'unresolved'}
                and not fspec.extractor.reference.startswith('runtime:')
            ):
                _load_ref_callable(fspec.extractor.reference)
            if fspec.default_factory is not None:
                _load_ref_callable(fspec.default_factory)

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


def _extractor_field_info(fspec: FieldSpec) -> Any:
    """Reconstruct an extractor FieldInfo without embedding executable values."""
    import pydantic

    assert fspec.extractor is not None
    spec = fspec.extractor
    marker = {
        'reference': None if spec.reference == 'unresolved' or spec.plan is not None else spec.reference,
        'key': None if spec.resolver_id.startswith('unresolved:') else spec.resolver_id,
        'version': spec.version,
        'source': spec.source,
        'config': {**spec.config, **({'__yosoi_plan__': spec.plan} if spec.plan is not None else {})},
        'batch_fields': spec.batch_fields,
    }
    extra: dict[str, Any] = {'yosoi_extractor': marker}
    if fspec.yosoi_type:
        extra['yosoi_type'] = fspec.yosoi_type
    kwargs: dict[str, Any] = {'description': fspec.description, 'json_schema_extra': extra}
    if fspec.default_factory is not None:
        kwargs['default_factory'] = _load_ref_callable(fspec.default_factory)
        return pydantic.Field(**kwargs)
    if fspec.has_default:
        return pydantic.Field(fspec.default, **kwargs)
    return pydantic.Field(**kwargs)


def _annotation_to_spec(annotation: Any) -> AnnotationSpec:
    """Convert a complete annotation into schema-v2 structured form."""
    if annotation is Any:
        return AnnotationSpec(kind='any')
    if annotation is type(None):
        return AnnotationSpec(kind='none')
    if annotation is Ellipsis:
        return AnnotationSpec(kind='ellipsis')
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return AnnotationSpec(kind='union', args=[_annotation_to_spec(arg) for arg in typing.get_args(annotation)])
    if origin is typing.Literal:
        values = list(typing.get_args(annotation))
        try:
            json.dumps(values)
        except (TypeError, ValueError) as exc:
            raise TypeError(f'Literal annotation {annotation!r} contains non-serializable values') from exc
        return AnnotationSpec(kind='literal', literal_values=values)
    target = origin or annotation
    module = getattr(target, '__module__', None)
    qualname = getattr(target, '__qualname__', None)
    if not module or not qualname:
        raise TypeError(f'annotation {annotation!r} is not importable and cannot be stored in ContractSpec v2')
    return AnnotationSpec(
        kind='generic' if origin is not None else 'reference',
        module=module,
        qualname=qualname,
        args=[_annotation_to_spec(arg) for arg in typing.get_args(annotation)],
    )


def _annotation_metadata_to_spec(metadata: Any) -> AnnotationMetadataSpec:
    """Serialize importable dataclass-based Pydantic/``annotated-types`` metadata."""
    metadata_type = type(metadata)
    module = getattr(metadata_type, '__module__', None)
    qualname = getattr(metadata_type, '__qualname__', None)
    if not module or not qualname or not dataclasses.is_dataclass(metadata):
        raise TypeError(
            f'annotation metadata {metadata!r} is not a portable dataclass marker and cannot be stored in ContractSpec v2'
        )
    reference = f'{module}:{qualname}'
    if _load_annotation_reference(module, qualname) is not metadata_type:
        raise TypeError(f'annotation metadata type {reference!r} is not import-stable')

    kwargs: dict[str, AnnotationMetadataValueSpec] = {}
    for field in dataclasses.fields(metadata):
        value = getattr(metadata, field.name)
        if value is PydanticUndefined:
            continue
        kwargs[field.name] = _annotation_metadata_value_to_spec(value)
    return AnnotationMetadataSpec(reference=reference, kwargs=kwargs)


def _annotation_metadata_value_to_spec(value: Any) -> AnnotationMetadataValueSpec:
    """Serialize one metadata constructor argument without executable source text."""
    if value is Any or value is type(None) or isinstance(value, type) or typing.get_origin(value) is not None:
        return AnnotationMetadataValueSpec(kind='annotation', annotation=_annotation_to_spec(value))
    if callable(value):
        try:
            reference = callable_reference(value)
        except ExtractorResolutionError as exc:
            raise TypeError(f'annotation metadata callable {value!r} must be importable') from exc
        return AnnotationMetadataValueSpec(kind='callable', reference=reference)
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f'annotation metadata value {value!r} is not JSON-serializable') from exc
    return AnnotationMetadataValueSpec(kind='json', value=value)


def _load_annotation_reference(module: str, qualname: str) -> Any:
    """Load one importable annotation reference with an actionable error."""
    try:
        obj: Any = importlib.import_module(module)
        for part in qualname.split('.'):
            obj = getattr(obj, part)
        return obj
    except (ImportError, AttributeError) as exc:
        raise ImportError(
            f'Cannot rehydrate extractor annotation {module}:{qualname}; '
            'ensure the defining package/model is installed and importable'
        ) from exc


def _load_ref_callable(ref: str) -> Any:
    if ':' not in ref:
        raise ImportError(f'callable ref must be "module.path:qualname", got {ref!r}')
    module, qualname = ref.split(':', 1)
    value = _load_annotation_reference(module, qualname)
    if not callable(value):
        raise ImportError(f'callable ref {ref!r} did not resolve to a callable')
    return value


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
    if ann is None:
        return 'str'
    origin = typing.get_origin(ann)
    if origin in (typing.Union, types.UnionType):
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
