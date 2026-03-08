"""Author type for Yosoi contracts."""

from typing import Any

from yosoi.types.field import Field


def Author(
    description: str = 'Author or creator name',
    **kwargs: Any,
) -> Any:
    """Configure an author field.

    Args:
        description: Field description for schema/manifest.
        **kwargs: Additional arguments forwarded to Field.

    Example::

        class Blog(Contract):
            author: str = ys.Author()
    """
    return Field(
        description=description,
        json_schema_extra={'yosoi_type': 'author'},
        **kwargs,
    )
