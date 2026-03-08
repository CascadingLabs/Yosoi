"""Title type for Yosoi contracts."""

from typing import Any

from yosoi.types.field import Field


def Title(
    description: str = 'A title or heading',
    **kwargs: Any,
) -> Any:
    """Configure a title field.

    Args:
        description: Field description for schema/manifest.
        **kwargs: Additional arguments forwarded to Field.

    Example::

        class Blog(Contract):
            title: str = ys.Title()
    """
    return Field(
        description=description,
        json_schema_extra={'yosoi_type': 'title'},
        **kwargs,
    )
