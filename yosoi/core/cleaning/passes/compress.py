"""Compress HTML by stripping non-essential attributes and pruning non-semantic elements."""

from bs4 import BeautifulSoup, Comment, Tag

KEEP_ATTRIBUTES: frozenset[str] = frozenset({'class', 'id', 'href', 'src', 'datetime', 'alt', 'name', 'type'})


def compress_html(soup: BeautifulSoup) -> BeautifulSoup:
    """Strip non-CSS attributes, remove comments, hidden elements, and non-semantic bloat.

    Args:
        soup: Parsed HTML tree to compress in-place.

    Returns:
        The same (mutated) soup object.

    """
    _remove_comments(soup)
    _strip_attributes(soup)
    _deduplicate_lists(soup)
    _deduplicate_tables(soup)
    _remove_hidden(soup)
    _prune_non_semantic(soup)
    return soup


def _remove_comments(soup: BeautifulSoup) -> None:
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()


def _strip_attributes(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and tag.attrs:
            tag.attrs = {
                attr: value for attr, value in tag.attrs.items() if attr in KEEP_ATTRIBUTES or attr.startswith('data-')
            }


def _deduplicate_lists(soup: BeautifulSoup, keep: int = 3) -> None:
    for list_tag in soup.find_all(['ul', 'ol']):
        items = list_tag.find_all('li', recursive=False)
        if len(items) > keep:
            for item in items[keep:]:
                item.decompose()


def _deduplicate_tables(soup: BeautifulSoup, keep: int = 5) -> None:
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if len(rows) > keep:
            for row in rows[keep:]:
                row.decompose()


def _remove_hidden(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(True):
        if isinstance(tag, Tag):
            if tag.get('hidden') is not None:
                tag.decompose()
                continue
            if tag.get('aria-hidden') == 'true':
                tag.decompose()


def _prune_non_semantic(soup: BeautifulSoup) -> None:
    """Remove SVG, canvas, base64 data URIs, and deeply nested empty anonymous divs."""
    for tag in soup.find_all(['svg', 'canvas']):
        tag.decompose()

    for tag in soup.find_all(True):
        if isinstance(tag, Tag):
            src = tag.get('src', '')
            if isinstance(src, str) and src.startswith('data:'):
                tag['src'] = '[data-uri-removed]'

    for tag in reversed(soup.find_all(['div', 'span'])):
        if not isinstance(tag, Tag):
            continue
        has_semantic_attrs = 'class' in tag.attrs or 'id' in tag.attrs or any(k.startswith('data-') for k in tag.attrs)
        if has_semantic_attrs:
            continue
        depth = sum(1 for _ in tag.parents)
        if depth > 8 and len(tag.get_text(strip=True)) == 0:
            tag.decompose()
