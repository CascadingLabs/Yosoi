"""User-defined scraping contracts."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Any, ClassVar, get_args, get_origin

import pydantic
from pydantic import BaseModel, Field, TypeAdapter, ValidationInfo, model_validator
from pydantic_core import PydanticUndefined
from typing_extensions import Self

from yosoi.models.selectors import SelectorEntry
from yosoi.types.coerce import dispatch as _coerce_dispatch

# Global registry of all Contract subclasses, populated via __init_subclass__.
# Builtins are registered when yosoi.models.defaults is imported; custom schemas
# are registered when their module is loaded (e.g. via load_schema in the CLI).
_CONTRACT_REGISTRY: dict[str, type[Contract]] = {}


def _unwrap_list_annotation(annotation: object) -> type | None:
    """If annotation is list[T], return T. Otherwise return None."""
    if get_origin(annotation) is list:
        args = get_args(annotation)
        if args:
            inner: type = args[0]
            return inner
    return None


def _coerce_list_field(
    raw_value: object,
    extra: dict[str, Any],
    source_url: str | None,
) -> list[Any]:
    """Normalize a raw value to a list, splitting delimited strings and coercing per-element."""
    yosoi_type = extra.get('yosoi_type')
    delimiter = extra.get('yosoi_delimiter')
    pattern = delimiter if isinstance(delimiter, str) else r'\s*[,;]\s*|\s+and\s+'

    if isinstance(raw_value, str):
        items = [s.strip() for s in re.split(pattern, raw_value) if s.strip()]
    elif isinstance(raw_value, list):
        if len(raw_value) == 1 and isinstance(raw_value[0], str):
            split = [s.strip() for s in re.split(pattern, raw_value[0]) if s.strip()]
            items = split if len(split) > 1 else raw_value
        else:
            items = list(raw_value)
    else:
        items = [raw_value]

    if isinstance(yosoi_type, str):
        items = [_coerce_dispatch(yosoi_type, item, extra, source_url) for item in items]

    return items


class Contract(BaseModel):
    """Base class for user-defined scraping contracts."""

    root: ClassVar[SelectorEntry | None] = None
    _validators_cls: ClassVar[type | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:  # pragma: no mutate
        """Register every Contract subclass in the global _CONTRACT_REGISTRY."""
        super().__init_subclass__(**kwargs)  # pragma: no mutate
        _CONTRACT_REGISTRY[cls.__name__] = cls  # pragma: no mutate

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Fail loudly at class definition time for invalid field configurations.

        Called by Pydantic after model_fields is fully populated — safe to inspect fields here.
        Checks:
        - Flat field names that collide with nested ``{parent}_{child}`` expansions.
        - ``list[Contract]`` fields, which are not yet supported (Phase 2).
        """
        super().__pydantic_init_subclass__(**kwargs)

        # Cache Validators class at class definition time to avoid per-call MRO walk
        cls._validators_cls = next(
            (klass.__dict__['Validators'] for klass in cls.__mro__ if 'Validators' in klass.__dict__),
            None,
        )

        # Reject list[Contract] fields — not yet supported
        for name, fi in cls.model_fields.items():
            inner = _unwrap_list_annotation(fi.annotation)
            if inner is not None and isinstance(inner, type) and issubclass(inner, Contract):
                raise TypeError(
                    f'{cls.__name__}: field {name!r} uses list[{inner.__name__}] which is not yet supported. '
                    f'Use a flat Contract field or wait for list[Contract] support.'
                )

        flat_names = {
            n
            for n, fi in cls.model_fields.items()
            if not (isinstance(fi.annotation, type) and issubclass(fi.annotation, Contract))
        }
        for parent_name, child_cls in cls.nested_contracts().items():
            for child_name in child_cls.model_fields:
                expanded = f'{parent_name}_{child_name}'
                if expanded in flat_names:
                    raise TypeError(
                        f'{cls.__name__}: field {expanded!r} collides with nested expansion '
                        f'of {parent_name}.{child_name}. Rename either the flat field or the nested field.'
                    )

    @model_validator(mode='wrap')
    @classmethod
    def _apply_validators_and_coerce(
        cls,
        data: Any,
        handler: pydantic.ModelWrapValidatorHandler[Self],
        info: ValidationInfo,
    ) -> Self:
        """Run inner Validators class, then dispatch Yosoi type coercion, then validate."""
        if not isinstance(data, dict):
            return handler(data)

        result = dict(data)

        # Step 1: Apply per-field transforms from nested Validators class (cached at class definition)
        validators_cls = cls._validators_cls
        if validators_cls is not None:
            for field_name, value in list(result.items()):
                fn = getattr(validators_cls, field_name, None)
                if callable(fn):
                    result[field_name] = fn(value)

        # Step 2: Yosoi semantic type coercion (scalar fields only)
        source_url: str | None = info.context.get('source_url') if info.context else None
        _list_field_names = {
            n for n in cls.model_fields if _unwrap_list_annotation(cls.model_fields[n].annotation) is not None
        }
        for field_name, field_info in cls.model_fields.items():
            if field_name not in result or field_name in _list_field_names:
                continue
            raw_extra = field_info.json_schema_extra
            if not isinstance(raw_extra, dict):
                continue
            yosoi_type = raw_extra.get('yosoi_type')
            if not isinstance(yosoi_type, str):
                continue
            result[field_name] = _coerce_dispatch(yosoi_type, result[field_name], raw_extra, source_url)

        # Step 2.5: List field coercion — normalize to list, split single strings, coerce per-element
        for field_name in _list_field_names:
            if field_name not in result or result[field_name] is None:
                continue
            raw_extra = cls.model_fields[field_name].json_schema_extra
            extra = raw_extra if isinstance(raw_extra, dict) else {}
            result[field_name] = _coerce_list_field(result[field_name], extra, source_url)

        # Step 3: Core pydantic validation
        return handler(result)

    @classmethod
    def coerce_field(cls, name: str, value: object, source_url: str = '') -> object:
        """Coerce + validate a single field's value the way the full model would.

        Runs the same per-field pipeline as :meth:`_apply_validators_and_coerce`
        for one field: the inner ``Validators`` transform, Yosoi semantic-type
        coercion, then the field's Pydantic type + ``Annotated`` validators (via a
        ``TypeAdapter``). Raises ``pydantic.ValidationError`` / ``ValueError`` on a
        type or validator failure.

        This is the single per-field value oracle reused by JS discovery (reject a
        script whose output the declared type rejects) and scrape-time enforcement,
        so a ``ys.js()`` field is validated by its declared type — not a heuristic.
        """
        field_info = cls.model_fields.get(name)
        if field_info is None:
            return value

        # Step 1: inner Validators class transform (e.g. strip/clean).
        validators_cls = cls._validators_cls
        if validators_cls is not None:
            fn = getattr(validators_cls, name, None)
            if callable(fn):
                value = fn(value)

        # Step 2: Yosoi semantic-type coercion (scalar fields with a declared type).
        raw_extra = field_info.json_schema_extra
        if isinstance(raw_extra, dict) and _unwrap_list_annotation(field_info.annotation) is None:
            yosoi_type = raw_extra.get('yosoi_type')
            if isinstance(yosoi_type, str):
                value = _coerce_dispatch(yosoi_type, value, raw_extra, source_url or None)

        # Step 3: Pydantic type + Annotated (Before/After) validators. The
        # ``Annotated`` metadata (BeforeValidator/AfterValidator/constraints) lives
        # on ``field_info.metadata``, not ``.annotation`` — rebuild the full type so
        # the field's own validators actually run.
        metadata = tuple(field_info.metadata or ())
        annotation = Annotated[(field_info.annotation, *metadata)] if metadata else field_info.annotation
        return TypeAdapter(annotation).validate_python(value)

    @classmethod
    def field_default(cls, name: str) -> object:
        """Return a field's default value (or None when it has no static default)."""
        field_info = cls.model_fields.get(name)
        if field_info is None:
            return None
        if field_info.default is not PydanticUndefined:
            return field_info.default
        if field_info.default_factory is not None:
            return field_info.default_factory()  # type: ignore[call-arg]
        return None

    @classmethod
    def undiscovered_action_fields(cls) -> dict[str, str]:
        """Return {field_name: description} for JS action fields with no pre-authored script.

        These fields require LLM-driven JS discovery (CAS-92) before they can be
        evaluated on a live browser tab.
        """
        result: dict[str, str] = {}
        for name, fi in cls.model_fields.items():
            extra = fi.json_schema_extra
            if not isinstance(extra, dict):
                continue
            cfg = extra.get('yosoi_action')
            if not isinstance(cfg, dict) or cfg.get('type') != 'js':
                continue
            if cfg.get('script'):
                continue  # hand-authored, already has a script
            desc = cfg.get('description') or fi.description or ''
            if desc:
                result[name] = str(desc)
        return result

    @classmethod
    def action_fields(cls) -> dict[str, dict[str, Any]]:
        """Return {field_name: action_config} for fields annotated with yosoi_action.

        These fields are excluded from CSS selector discovery and verification —
        their values are captured by running the action during fetch.
        """
        result: dict[str, dict[str, Any]] = {}
        for name, fi in cls.model_fields.items():
            extra = fi.json_schema_extra
            if isinstance(extra, dict) and 'yosoi_action' in extra:
                cfg = extra['yosoi_action']
                if isinstance(cfg, dict):
                    result[name] = cfg
        return result

    @classmethod
    def nested_contracts(cls) -> dict[str, type[Contract]]:
        """Return a mapping of field name → child Contract class for Contract-typed fields."""
        result: dict[str, type[Contract]] = {}
        for name, fi in cls.model_fields.items():
            ann = fi.annotation
            if isinstance(ann, type) and issubclass(ann, Contract):
                result[name] = ann
        return result

    @classmethod
    def list_fields(cls) -> dict[str, type]:
        """Return {field_name: inner_type} for fields annotated as list[T]."""
        result: dict[str, type] = {}
        for name, fi in cls.model_fields.items():
            inner = _unwrap_list_annotation(fi.annotation)
            if inner is not None:
                result[name] = inner
        return result

    @classmethod
    def discovery_field_names(cls) -> set[str]:
        """Return the set of flattened field names used for discovery and cache keys.

        Non-Contract fields keep their original name; nested Contract fields are
        expanded to ``{parent}_{child}`` keys.  This matches the key format used
        by snapshots, ``field_descriptions()``, and ``get_selector_overrides()``.
        Action fields (yosoi_action) are excluded — they have no CSS selector.
        """
        action_names = set(cls.action_fields().keys())
        names: set[str] = set()
        for name, fi in cls.model_fields.items():
            if name in action_names:
                continue
            ann = fi.annotation
            if isinstance(ann, type) and issubclass(ann, Contract):
                for child_name in ann.model_fields:
                    names.add(f'{name}_{child_name}')
            else:
                names.add(name)
        return names

    @classmethod
    def to_selector_model(cls) -> type[BaseModel]:
        """Generate a Pydantic model mapping each contract field to FieldSelectors.

        This ensures that the LLM agent knows exactly which fields to find selectors for,
        preserving any descriptions or hints provided in the contract.
        Fields with a ``yosoi_selector`` override are excluded — their selectors are
        provided directly and do not require AI discovery.
        Nested Contract-typed fields are expanded to flat ``{parent}_{child}`` entries.
        """
        from yosoi.models.selectors import FieldSelectors

        overridden = cls.get_selector_overrides()
        field_defs: dict[str, Any] = {}
        for name, field_info in cls.model_fields.items():
            if name in overridden:
                continue

            ann = field_info.annotation
            if isinstance(ann, type) and issubclass(ann, Contract):
                child_overridden = ann.get_selector_overrides()
                for child_name, child_fi in ann.model_fields.items():
                    flat_name = f'{name}_{child_name}'
                    if flat_name in overridden or child_name in child_overridden:
                        continue
                    child_desc = child_fi.description or f'Selectors for {flat_name}'
                    field_defs[flat_name] = (FieldSelectors, Field(description=child_desc))
            else:
                # Copy the field description onto the selector field
                description = field_info.description or f'Selectors for {name}'
                field_defs[name] = (FieldSelectors, Field(description=description))

        # Add optional root field for multi-item pages
        field_defs['root'] = (
            FieldSelectors | None,
            Field(
                default=None,
                description=(
                    'Selector for the repeating wrapper element that contains one complete item '
                    '(e.g., .product-card, article.listing). '
                    'Should match each individual item on the page. Set to null for single-item pages.'
                ),
            ),
        )

        return pydantic.create_model(f'{cls.__name__}SelectorConfig', **field_defs)

    @classmethod
    def get_selector_overrides(cls) -> dict[str, dict[str, str]]:
        """Return selector overrides defined on fields via ``yosoi_selector``.

        Returns:
            Mapping of field name to selector dict (e.g. ``{"primary": "h1.title"}``).
            Nested contract overrides use flat ``{parent}_{child}`` keys.

        """
        overrides: dict[str, dict[str, str]] = {}
        for name, field_info in cls.model_fields.items():
            ann = field_info.annotation
            extra = field_info.json_schema_extra
            if isinstance(ann, type) and issubclass(ann, Contract):
                for child_name, child_override in ann.get_selector_overrides().items():
                    overrides[f'{name}_{child_name}'] = child_override
            elif isinstance(extra, dict):
                sel = extra.get('yosoi_selector')
                if isinstance(sel, str) and sel:
                    overrides[name] = {'primary': sel}
        return overrides

    @classmethod
    def field_descriptions(cls) -> dict[str, str]:
        """Return a mapping of field name to description, excluding selector overrides.

        Nested Contract-typed fields are expanded to flat ``{parent}_{child}`` keys.
        When the child contract has a pinned root, the description includes a scoping hint.
        When the child has ``root = ys.discover()``, a co-location hint is added.
        """
        from yosoi.models.selectors import is_discover_sentinel

        overridden = cls.get_selector_overrides()
        action_names = set(cls.action_fields().keys())
        result: dict[str, str] = {}
        for name, fi in cls.model_fields.items():
            if name in overridden or name in action_names:
                continue
            ann = fi.annotation
            if isinstance(ann, type) and issubclass(ann, Contract):
                child_overridden = ann.get_selector_overrides()
                child_root = ann.root
                for child_name, child_fi in ann.model_fields.items():
                    key = f'{name}_{child_name}'
                    if key in overridden or child_name in child_overridden:
                        continue
                    desc = child_fi.description or child_name
                    if child_root is not None and not is_discover_sentinel(child_root):
                        desc = f'{desc} (within: {child_root.value})'
                    elif is_discover_sentinel(child_root):
                        desc = f'{desc} (co-located with other {name} fields)'
                    result[key] = desc
            else:
                desc = fi.description or name
                if _unwrap_list_annotation(fi.annotation) is not None:
                    desc = f'{desc} (multiple expected — find selector matching each individual item, not the wrapper)'
                result[name] = desc
        return result

    @classmethod
    def generate_manifest(cls) -> str:
        """Return a markdown table documenting all contract fields and their config."""
        lines = [f'# {cls.__name__} Contract Manifest\n']
        if cls.__doc__:
            lines.append(f'> {cls.__doc__.strip()}\n')
        lines.append('| Field | Semantic Type | Required | Config | Description | Selector Override |')
        lines.append('|-------|---------------|----------|--------|-------------|-------------------|')
        _SKIP_KEYS = ('yosoi_type', 'yosoi_frozen', 'yosoi_selector')
        for name, field_info in cls.model_fields.items():
            raw_extra = field_info.json_schema_extra
            extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
            yosoi_type = extra.get('yosoi_type', 'text')
            description = field_info.description or '—'
            required = 'Yes' if field_info.is_required() else 'No'
            config_items = {k: v for k, v in extra.items() if k not in _SKIP_KEYS}
            config_str = ', '.join(f'{k}={v!r}' for k, v in config_items.items()) or '—'
            override = f'`{extra["yosoi_selector"]}`' if extra.get('yosoi_selector') else '—'
            lines.append(f'| `{name}` | `{yosoi_type}` | {required} | {config_str} | {description} | {override} |')
        return '\n'.join(lines)

    @classmethod
    def get_root(cls) -> SelectorEntry | None:
        """Return the root selector if explicitly set on the contract class.

        Returns:
            SelectorEntry for the repeating container element, or None.

        """
        return cls.root

    @classmethod
    def is_grouped(cls) -> bool:
        """Return True if the contract explicitly configures multi-item mode."""
        return cls.root is not None

    @classmethod
    def define(cls, name: str) -> ContractBuilder:
        """Start a fluent ContractBuilder for the given contract name."""
        return ContractBuilder(name)


class ContractBuilder:
    """Fluent builder for creating Contract subclasses at runtime."""

    def __init__(self, name: str):
        """Initialize the builder with the contract name."""
        self._name = name
        self._fields: list[tuple[str, type, str]] = []
        self._root: SelectorEntry | None = None

    def __getattr__(self, field_name: str) -> Callable[..., ContractBuilder]:
        """Return an _add function that registers the named field."""
        if field_name.startswith('__'):
            raise AttributeError(field_name)

        def _add(description: str = '', type: type = str) -> ContractBuilder:
            self._fields.append((field_name, type, description))
            return self

        return _add

    def with_root(self, selector: SelectorEntry) -> ContractBuilder:
        """Set the root selector for multi-item mode."""
        self._root = selector
        return self

    def build(self) -> type[Contract]:
        """Build and return the Contract subclass."""
        field_defs: dict[str, Any] = {name: (ftype, Field(description=desc)) for name, ftype, desc in self._fields}
        cls = pydantic.create_model(self._name, __base__=Contract, **field_defs)
        if self._root is not None:
            cls.root = self._root  # type: ignore[attr-defined]
        return cls
