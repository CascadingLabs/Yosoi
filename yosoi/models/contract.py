"""User-defined scraping contracts."""

from __future__ import annotations

from typing import Any

import pydantic
from pydantic import BaseModel, Field, ValidationInfo, model_validator
from typing_extensions import Self

from yosoi.types.coerce import dispatch as _coerce_dispatch


class Contract(BaseModel):
    """Base class for user-defined scraping contracts."""

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
        """Generate a Pydantic model mapping each contract field to FieldSelectors."""
        from yosoi.models.selectors import FieldSelectors

        field_defs: dict[str, Any] = dict.fromkeys(cls.model_fields, (FieldSelectors, ...))
        return pydantic.create_model(f'{cls.__name__}SelectorConfig', **field_defs)

    @classmethod
    def field_descriptions(cls) -> dict[str, str]:
        """Return a mapping of field name to description."""
        return {name: (fi.description or name) for name, fi in cls.model_fields.items()}

    @classmethod
    def generate_manifest(cls) -> str:
        """Return a markdown table documenting all contract fields and their config."""
        lines = [f'# {cls.__name__} Contract Manifest\n']
        if cls.__doc__:
            lines.append(f'> {cls.__doc__.strip()}\n')
        lines.append('| Field | Semantic Type | Required | Config | AI Hint |')
        lines.append('|-------|---------------|----------|--------|---------|')
        for name, field_info in cls.model_fields.items():
            raw_extra = field_info.json_schema_extra
            extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
            yosoi_type = extra.get('yosoi_type', 'text')
            hint = extra.get('yosoi_hint', field_info.description or '—')
            required = 'Yes' if field_info.is_required() else 'No'
            config_items = {k: v for k, v in extra.items() if k not in ('yosoi_type', 'yosoi_hint', 'yosoi_frozen')}
            config_str = ', '.join(f'{k}={v!r}' for k, v in config_items.items()) or '—'
            lines.append(f'| `{name}` | `{yosoi_type}` | {required} | {config_str} | {hint} |')
        return '\n'.join(lines)

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

    def __getattr__(self, field_name: str):
        """Return an _add function that registers the named field."""
        if field_name.startswith('__'):
            raise AttributeError(field_name)

        def _add(description: str = '', type: type = str) -> ContractBuilder:
            self._fields.append((field_name, type, description))
            return self

        return _add

    def build(self) -> type[Contract]:
        """Build and return the Contract subclass."""
        field_defs: dict[str, Any] = {name: (ftype, Field(description=desc)) for name, ftype, desc in self._fields}
        return pydantic.create_model(self._name, __base__=Contract, **field_defs)
