"""User-defined scraping contracts."""

from __future__ import annotations

from typing import Any

import pydantic
from pydantic import BaseModel, Field, model_validator


class Contract(BaseModel):
    """Base class for user-defined scraping contracts."""

    @model_validator(mode='before')
    @classmethod
    def _apply_inner_validators(cls, data: Any) -> Any:
        """Apply per-field transforms defined in a nested Validators class."""
        if not isinstance(data, dict):
            return data
        validators_cls = next(
            (klass.__dict__['Validators'] for klass in cls.__mro__ if 'Validators' in klass.__dict__),
            None,
        )
        if validators_cls is None:
            return data
        result = dict(data)
        for field_name, value in list(result.items()):
            fn = getattr(validators_cls, field_name, None)
            if callable(fn):
                result[field_name] = fn(value)
        return result

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
