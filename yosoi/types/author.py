"""Author type for Yosoi contracts."""

from yosoi.types.registry import CoercionConfig, register_coercion


@register_coercion('author', description='Author or creator name')
def Author(v: object, config: CoercionConfig, source_url: str | None = None) -> str:
    """Configure an author field.

    Example::

        class Blog(Contract):
            author: str = ys.Author()
    """
    return str(v).strip() if v is not None else ''
