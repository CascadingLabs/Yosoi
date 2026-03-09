"""BodyText type for Yosoi contracts."""

from typing import Any

from yosoi.types.registry import register_coercion


@register_coercion('body_text', description='Main body text content')
def BodyText(v: object, config: dict[str, Any], source_url: str | None = None) -> str:
    """Configure a body text field.

    Example::

        class Blog(Contract):
            body: str = ys.BodyText()
    """
    return str(v).strip() if v is not None else ''
