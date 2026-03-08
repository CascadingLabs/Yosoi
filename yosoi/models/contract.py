"""User-defined scraping contracts."""

from __future__ import annotations

from typing import Any

import pydantic
from pydantic import BaseModel, Field


class Contract(BaseModel):
    """Base class for user-defined scraping contracts."""

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


class NewsArticle(Contract):
    """Default contract matching the original 5-field behavior."""

    headline: str = Field(description='Main article title (h1/h2 in article, NOT navigation)')
    author: str = Field(description='Author name (author/byline classes or links)')
    date: str = Field(description='Publication date (time tags or date/published classes)')
    body_text: str = Field(description='Article paragraphs (p tags in article, NOT sidebars/ads)')
    related_content: str = Field(description='Related article links (aside/sidebar sections)')


class ContractBuilder:
    """Fluent builder for creating Contract subclasses at runtime."""

    def __init__(self, name: str):
        """Initialize the builder with the contract name."""
        self._name = name
        self._fields: list[tuple[str, type, str]] = []

    def __getattr__(self, field_name: str):
        """Return an _add function that registers the named field."""

        def _add(description: str = '', type: type = str) -> ContractBuilder:
            self._fields.append((field_name, type, description))
            return self

        return _add

    def build(self) -> type[Contract]:
        """Build and return the Contract subclass."""
        field_defs: dict[str, Any] = {name: (ftype, Field(description=desc)) for name, ftype, desc in self._fields}
        return pydantic.create_model(self._name, __base__=Contract, **field_defs)
