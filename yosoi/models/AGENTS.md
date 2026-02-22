# Models Module Rules

## Purpose
Defines the strict data contracts and types used across the Yosoi application.

## Constraints
1. **No Business Logic**: Models must only contain data validation, type definitions, and simple computed properties (e.g., `@property`).
2. **Pydantic Default**: Use `pydantic.BaseModel` for complex nested structures (like `ScrapingConfig` or `FieldSelectors`).
3. **Dataclasses**: Use standard Python `@dataclass` for internal pipeline states (like `FetchResult` or `ContentMetadata`) that don't require strict JSON deserialization.
4. **Modern Typing**: Strictly use modern Python type hints (`str | None`, `list[str]`).
