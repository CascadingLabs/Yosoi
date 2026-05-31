"""BodyText type for Yosoi contracts."""

from yosoi.types.registry import KIND_TEXT, CoercionConfig, SemanticRule, register_coercion


@register_coercion(
    'body_text',
    description='Main body text content',
    semantic=SemanticRule(kind=KIND_TEXT, distinct=True),
)
def BodyText(v: object, config: CoercionConfig, source_url: str | None = None) -> str:
    """Configure a body text field.

    Example::

        class Blog(Contract):
            body: str = ys.BodyText()
    """
    return str(v).strip() if v is not None else ''
