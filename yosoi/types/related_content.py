"""RelatedContent type for Yosoi contracts."""

from yosoi.types.registry import CoercionConfig, register_coercion


@register_coercion('related_content', description='Related links (text + href pairs)')
def RelatedContent(v: object, config: CoercionConfig, source_url: str | None = None) -> str:
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
                if text and href:
                    parts.append(f'{text} ({href})')
                elif text:
                    parts.append(text)
                elif href:
                    parts.append(href)
            else:
                parts.append(str(item))
        return '\n'.join(p for p in parts if p)
    return str(v).strip() if v is not None else ''
