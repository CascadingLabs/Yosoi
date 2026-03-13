"""Author type for Yosoi contracts."""

from typing import Any

from yosoi.types.registry import register_coercion


@register_coercion('author', description='Author or creator name')
def Author(v: object, config: dict[str, Any], source_url: str | None = None) -> str:
    """Configure an author field.

    Example::

        class Blog(Contract):
            author: str = ys.Author()
    """
    return str(v).strip() if v is not None else ''
