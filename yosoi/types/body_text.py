"""BodyText type for Yosoi contracts."""

from yosoi.types.registry import CoercionConfig, register_coercion


@register_coercion('body_text', description='Main body text content')
def BodyText(v: object, config: CoercionConfig, source_url: str | None = None) -> str:
    """Configure a body text field.

    Example::

        class Blog(Contract):
            body: str = ys.BodyText()
    """
    return str(v).strip() if v is not None else ''
