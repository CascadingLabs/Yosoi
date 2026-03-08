"""BodyText type for Yosoi contracts."""

from typing import Any

from yosoi.types.field import Field


def BodyText(
    description: str = 'Main body text content',
    **kwargs: Any,
) -> Any:
    """Configure a body text field.

    Args:
        description: Field description for schema/manifest.
        **kwargs: Additional arguments forwarded to Field.

    Example::

        class Blog(Contract):
            body: str = ys.BodyText()
    """
    return Field(
        description=description,
        json_schema_extra={'yosoi_type': 'body_text'},
        **kwargs,
    )
