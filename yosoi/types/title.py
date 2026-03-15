"""Title type for Yosoi contracts."""

from yosoi.types.registry import CoercionConfig, register_coercion


@register_coercion('title', description='A title or heading')
def Title(v: object, config: CoercionConfig, source_url: str | None = None) -> str:
    """Configure a title field.

    Example::

        class Blog(Contract):
            title: str = ys.Title()
    """
    return str(v).strip() if v is not None else ''
