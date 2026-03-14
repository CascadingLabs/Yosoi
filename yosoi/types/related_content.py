"""RelatedContent type for Yosoi contracts."""

from typing import Any

from yosoi.types.registry import register_coercion


@register_coercion('related_content', description='Related links (text + href pairs)')
def RelatedContent(v: object, config: dict[str, Any], source_url: str | None = None) -> str:
    """Configure a related content / links field.

    The extractor returns a list of dicts with 'text' and 'href' keys.
    Coercion converts that to a newline-joined string of link texts.

    Example::

        class NewsArticle(Contract):
            related_content: str = ys.RelatedContent()
    """
    if isinstance(v, list):
        parts = []
        for item in v:
            if isinstance(item, dict):
                text = item.get('text', '')
                href = item.get('href', '')
                parts.append(f'{text} ({href})' if text and href else text)
            else:
                parts.append(str(item))
        return '\n'.join(p for p in parts if p)
    return str(v).strip() if v is not None else ''
