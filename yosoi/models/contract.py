"""User-defined scraping contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

import pydantic
from pydantic import BaseModel, Field, ValidationInfo, model_validator
from typing_extensions import Self

from yosoi.models.selectors import SelectorEntry
from yosoi.types.coerce import dispatch as _coerce_dispatch

# Global registry of all Contract subclasses, populated via __init_subclass__.
# Builtins are registered when yosoi.models.defaults is imported; custom schemas
# are registered when their module is loaded (e.g. via load_schema in the CLI).
_CONTRACT_REGISTRY: dict[str, type[Contract]] = {}


class Contract(BaseModel):
    """Base class for user-defined scraping contracts."""

    root: ClassVar[SelectorEntry | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:  # pragma: no mutate
        """Register every Contract subclass in the global _CONTRACT_REGISTRY."""
        super().__init_subclass__(**kwargs)  # pragma: no mutate
        _CONTRACT_REGISTRY[cls.__name__] = cls  # pragma: no mutate

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

        # Step 1: Apply per-field transforms from nested Validators class
        validators_cls = next(
            (klass.__dict__['Validators'] for klass in cls.__mro__ if 'Validators' in klass.__dict__),
            None,
        )
        if validators_cls is not None:
            for field_name, value in list(result.items()):
                fn = getattr(validators_cls, field_name, None)
                if callable(fn):
                    result[field_name] = fn(value)

        # Step 2: Yosoi semantic type coercion
        source_url: str | None = info.context.get('source_url') if info.context else None
        for field_name, field_info in cls.model_fields.items():
            if field_name not in result:
                continue
            raw_extra = field_info.json_schema_extra
            if not isinstance(raw_extra, dict):
                continue
            yosoi_type = raw_extra.get('yosoi_type')
            if not isinstance(yosoi_type, str):
                continue
            result[field_name] = _coerce_dispatch(yosoi_type, result[field_name], raw_extra, source_url)

        # Step 3: Core pydantic validation
        return handler(result)

    @classmethod
    def to_selector_model(cls) -> type[BaseModel]:
        """Generate a Pydantic model mapping each contract field to FieldSelectors.

        This ensures that the LLM agent knows exactly which fields to find selectors for,
        preserving any descriptions or hints provided in the contract.
        Fields with a ``yosoi_selector`` override are excluded — their selectors are
        provided directly and do not require AI discovery.
        """
        from yosoi.models.selectors import FieldSelectors

        overridden = cls.get_selector_overrides()
        field_defs: dict[str, Any] = {}
        for name, field_info in cls.model_fields.items():
            if name in overridden:
                continue

            # Copy description and yosoi_hint to the selector field
            extra = field_info.json_schema_extra or {}
            description = field_info.description or f'Selectors for {name}'
            hint = extra.get('yosoi_hint') if isinstance(extra, dict) else None

            selector_field = Field(
                description=description,
                json_schema_extra={'yosoi_hint': hint} if hint else None,
            )
            field_defs[name] = (FieldSelectors, selector_field)

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
            Mapping of field name → selector dict (compatible with ``FieldSelectors``
            structure, e.g. ``{"primary": "h1.title"}``).

        """
        overrides: dict[str, dict[str, str]] = {}
        for name, field_info in cls.model_fields.items():
            extra = field_info.json_schema_extra
            if isinstance(extra, dict):
                sel = extra.get('yosoi_selector')
                if isinstance(sel, str) and sel:
                    overrides[name] = {'primary': sel}
        return overrides

    @classmethod
    def field_descriptions(cls) -> dict[str, str]:
        """Return a mapping of field name to description, excluding selector overrides."""
        overridden = cls.get_selector_overrides()
        return {name: (fi.description or name) for name, fi in cls.model_fields.items() if name not in overridden}

    @classmethod
    def generate_manifest(cls) -> str:
        """Return a markdown table documenting all contract fields and their config."""
        lines = [f'# {cls.__name__} Contract Manifest\n']
        if cls.__doc__:
            lines.append(f'> {cls.__doc__.strip()}\n')
        lines.append('| Field | Semantic Type | Required | Config | AI Hint | Selector Override |')
        lines.append('|-------|---------------|----------|--------|---------|-------------------|')
        _SKIP_KEYS = ('yosoi_type', 'yosoi_hint', 'yosoi_frozen', 'yosoi_selector')
        for name, field_info in cls.model_fields.items():
            raw_extra = field_info.json_schema_extra
            extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
            yosoi_type = extra.get('yosoi_type', 'text')
            hint = extra.get('yosoi_hint', field_info.description or '—')
            required = 'Yes' if field_info.is_required() else 'No'
            config_items = {k: v for k, v in extra.items() if k not in _SKIP_KEYS}
            config_str = ', '.join(f'{k}={v!r}' for k, v in config_items.items()) or '—'
            override = f'`{extra["yosoi_selector"]}`' if extra.get('yosoi_selector') else '—'
            lines.append(f'| `{name}` | `{yosoi_type}` | {required} | {config_str} | {hint} | {override} |')
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
