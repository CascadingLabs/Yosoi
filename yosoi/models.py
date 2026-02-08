"""Pydantic models for structured CSS selector data."""

from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField

# =============================================================================
# BASE FIELD KIND SYSTEM
# =============================================================================


class FieldKindBase:
    """Base class for field kinds (default or custom).

    A FieldKind tells Yosoi:
    1. What to look for in HTML
    2. How to guide the LLM discovery
    3. What processing to apply (optional)
    """

    def __init__(self, name: str, discovery_hints: str, processor: Callable | None = None):
        """Create a field kind.

        Args:
            name: Identifier (e.g., "text", "stock_ticker")
            discovery_hints: Instructions for LLM discovery
            processor: Optional function to process extracted data

        """
        self.name = name
        self.discovery_hints = discovery_hints
        self.processor = processor

    def __str__(self) -> str:
        """Return string representation of field kind name."""
        return self.name

    def __repr__(self) -> str:
        """Return detailed string representation for debugging."""
        return f'FieldKind({self.name})'


# =============================================================================
# FIELD KIND REGISTRY - Users can register custom kinds
# =============================================================================


class FieldKindRegistry:
    """Global registry of field kinds (default + custom)."""

    _kinds: dict[str, FieldKindBase] = {}

    @classmethod
    def register(cls, kind: FieldKindBase) -> FieldKindBase:
        """Register a field kind."""
        cls._kinds[kind.name] = kind
        return kind

    @classmethod
    def get(cls, name: str) -> FieldKindBase | None:
        """Get a registered field kind by name."""
        return cls._kinds.get(name)

    @classmethod
    def get_all(cls) -> dict[str, FieldKindBase]:
        """Get all registered field kinds."""
        return cls._kinds.copy()


# =============================================================================
# CUSTOM FIELD KIND CREATOR
# =============================================================================


def create_field_kind(
    name: str, discovery_hints: str, processor: Callable | None = None, examples: list[str] | None = None
) -> FieldKindBase:
    """Create and register a custom field kind.

    Args:
        name: Unique identifier for this kind
        discovery_hints: Instructions for LLM to find this field
        processor: Optional function to process extracted data
        examples: Optional example values to help LLM

    Returns:
        Registered FieldKindBase instance

    Example:
        >>> STOCK_TICKER = create_field_kind(
        ...     name="stock_ticker",
        ...     discovery_hints="Look for stock ticker symbols like $AAPL, $TSLA in text or links",
        ...     examples=["$AAPL", "TSLA", "NASDAQ:MSFT"]
        ... )

    """
    if examples:
        discovery_hints += f'\n\nExamples: {", ".join(examples)}'

    kind = FieldKindBase(name=name, discovery_hints=discovery_hints, processor=processor)
    return FieldKindRegistry.register(kind)


# =============================================================================
# DECORATOR FOR CUSTOM FIELD KINDS
# =============================================================================


def field_kind(name: str, discovery_hints: str, examples: list[str] | None = None):
    """Create a custom field kind with processor using decorator syntax.

    Example:
        >>> @field_kind(
        ...     name="stock_ticker",
        ...     discovery_hints="Look for ticker symbols",
        ...     examples=["$AAPL", "TSLA"]
        ... )
        ... def process_ticker(value: str) -> str:
        ...     # Remove $ prefix if present
        ...     return value.lstrip('$').upper()

    """

    def decorator(func: Callable) -> FieldKindBase:
        return create_field_kind(name=name, discovery_hints=discovery_hints, processor=func, examples=examples)

    return decorator


# =============================================================================
# FIELD METADATA & BLUEPRINT
# =============================================================================


class Selectors(BaseModel):
    """Selectors discovered by Yosoi for a single field."""

    primary: str = PydanticField(description='Most specific selector')
    fallback: str = PydanticField(description='Less specific but reliable')
    tertiary: str = PydanticField(description="Generic selector or 'NA'")


class FieldMetadata(BaseModel):
    """Metadata for a BluePrint field."""

    kind: str = PydanticField(description='Field kind name')
    description: str | None = None
    required: bool = True
    selector_hints: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def get_field_kind(self) -> FieldKindBase | None:
        """Get the registered FieldKind."""
        return FieldKindRegistry.get(self.kind)


def Field(
    kind: FieldKindBase,
    description: str | None = None,
    required: bool = True,
    selector_hints: str | None = None,
    **kwargs: Any,
) -> Any:
    """Create a field with metadata for BluePrint."""
    metadata = FieldMetadata(
        kind=kind.name,
        description=description,
        required=required,
        selector_hints=selector_hints,
    )

    return PydanticField(description=description, json_schema_extra={'yosoi_metadata': metadata.model_dump()})


class BluePrint(BaseModel):
    """Base class for declarative scraping schemas."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def get_field_metadata(cls, field_name: str) -> FieldMetadata | None:
        """Get Yosoi metadata for a field."""
        field_info = cls.model_fields.get(field_name)
        if not field_info:
            return None

        extra = field_info.json_schema_extra or {}
        metadata_dict = extra.get('yosoi_metadata')

        if metadata_dict:
            return FieldMetadata(**metadata_dict)
        return None

    @classmethod
    def get_all_fields(cls) -> dict[str, tuple[type, FieldMetadata]]:
        """Get all fields with their types and metadata."""
        type_hints = get_type_hints(cls)
        fields = {}

        for field_name, field_type in type_hints.items():
            if field_name.startswith('_'):
                continue

            metadata = cls.get_field_metadata(field_name)
            if metadata:
                fields[field_name] = (field_type, metadata)

        return fields

    @classmethod
    def to_discovery_schema(cls) -> dict[str, Any]:
        """Convert BluePrint to schema for LLM discovery."""
        fields_list = cls.get_all_fields()
        schema = {'schema_name': cls.__name__, 'fields': []}

        for field_name, (field_type, metadata) in fields_list.items():
            field_kind = metadata.get_field_kind()

            field_schema = {
                'name': field_name,
                'type': field_type.__name__,
                'kind': metadata.kind,
                'description': metadata.description or f'Extract {field_name}',
                'discovery_hints': (metadata.selector_hints or (field_kind.discovery_hints if field_kind else '')),
                'required': metadata.required,
            }
            schema['fields'].append(field_schema)

        return schema


# =============================================================================
# DYNAMIC MODEL GENERATION
# =============================================================================


def create_scraping_config_model(blueprint: type[BluePrint]) -> type[BaseModel]:
    """Dynamically create a ScrapingConfig model from a BluePrint.

    Args:
        blueprint: BluePrint class defining the fields to scrape

    Returns:
        A Pydantic model class with Selectors fields for each BluePrint field

    """
    annotations = {}
    field_definitions = {}
    all_fields = blueprint.get_all_fields()

    for field_name in all_fields:
        # Set the type annotation
        annotations[field_name] = Selectors
        # Set the field definition
        field_definitions[field_name] = PydanticField(description=f'Selectors for {field_name}')

    # Create the model dynamically with proper annotations
    ScrapingConfigModel = type(
        f'{blueprint.__name__}ScrapingConfig',
        (BaseModel,),
        {
            '__annotations__': annotations,
            **field_definitions,
            'model_config': ConfigDict(arbitrary_types_allowed=True),
        },
    )

    return ScrapingConfigModel


# =============================================================================
# DEFAULT FIELD KINDS - Built-in primitives
# =============================================================================


class DefaultFieldKinds:
    """Default field kinds provided by Yosoi.

    These cover common scraping scenarios.
    """

    # Headline content
    HEADLINE = FieldKindRegistry.register(
        FieldKindBase(name='headline', discovery_hints='Look for the headline of the article in HTML')
    )

    # Authors
    AUTHOR = FieldKindRegistry.register(
        FieldKindBase(
            name='author',
            discovery_hints="Look for bylines, author links, or elements with 'author', 'byline', 'written-by' in class names.",
        )
    )

    # Dates/times
    DATETIME = FieldKindRegistry.register(
        FieldKindBase(
            name='datetime',
            discovery_hints="Look for tags with datetime attributes, or date-formatted text. Check for relative dates like '2 hours ago'.",
        )
    )

    # Text content
    BODY = FieldKindRegistry.register(
        FieldKindBase(name='body_text', discovery_hints='Look for body text content in HTML')
    )


# Convenience alias
FieldKind = DefaultFieldKinds


# =============================================================================
# DEFAULT BLUEPRINT - Standard article scraping
# =============================================================================


class ArticleBluePrint(BluePrint):
    """Default blueprint for article scraping.

    Contains standard fields for news articles and blog posts.
    """

    headline: str = Field(
        kind=FieldKind.HEADLINE,
        description='Main article headline',
        required=True,
    )

    author: str = Field(
        kind=FieldKind.AUTHOR,
        description='Article author name',
        required=False,
    )

    date: str = Field(
        kind=FieldKind.DATETIME,
        description='Publication date',
        required=False,
    )

    body_text: str = Field(
        kind=FieldKind.BODY,
        description='Main article content',
        required=True,
    )


# Default instance to use throughout the codebase
DEFAULT_BLUEPRINT = ArticleBluePrint
