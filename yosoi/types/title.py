"""Title type for Yosoi contracts."""

from typing import Any

from yosoi.types.registry import register_coercion


@register_coercion('title', description='A title or heading')
def Title(v: object, config: dict[str, Any], source_url: str | None = None) -> str:
    """Configure a title field.

    Example::

        class Blog(Contract):
            title: str = ys.Title()
    """
    return str(v).strip() if v is not None else ''
