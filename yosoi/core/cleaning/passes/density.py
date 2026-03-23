"""Prune low-density subtrees that contribute noise without useful content."""

from bs4 import BeautifulSoup, Tag

# Tags whose descendants should never be pruned by density scoring
_SEMANTIC_TAGS: frozenset[str] = frozenset(
    {
        'article',
        'main',
        'section',
        'details',
        'figure',
        'blockquote',
    }
)

_BLOCK_TARGETS: list[str] = ['div', 'section', 'aside', 'fieldset']

# Minimum text-to-markup ratio; subtrees below this are noise candidates
_MIN_DENSITY: float = 0.05

# Don't prune elements smaller than this (bytes of HTML) — too small to matter
_MIN_SIZE: int = 200


def prune_by_density(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove block-level subtrees with very low text-to-markup ratio.

    A subtree is pruned when:
    - Its ``text_length / html_length`` ratio is below ``_MIN_DENSITY``
    - It is at least ``_MIN_SIZE`` bytes of HTML
    - It contains no semantic child elements (``article``, ``main``, etc.)
    - It has no ``id`` attribute

    This catches noise with unusual class names that the class-based
    ``remove_noise`` pass cannot recognise.

    Args:
        soup: Parsed HTML tree to prune in-place.

    Returns:
        The same (mutated) soup object.

    """
    # Process bottom-up so child removals don't affect parent scores
    for tag in reversed(soup.find_all(_BLOCK_TARGETS)):
        if not isinstance(tag, Tag):
            continue
        if _is_protected(tag):
            continue
        html_len = len(str(tag))
        if html_len < _MIN_SIZE:
            continue
        text_len = len(tag.get_text(strip=True))
        density = text_len / html_len if html_len > 0 else 0
        if density < _MIN_DENSITY:
            tag.decompose()
    return soup


def _is_protected(tag: Tag) -> bool:
    """Return True if the tag or any descendant carries semantic signals."""
    if 'id' in tag.attrs:
        return True
    if tag.name in _SEMANTIC_TAGS:
        return True
    for child in tag.descendants:
        if isinstance(child, Tag):
            if child.name in _SEMANTIC_TAGS:
                return True
            if 'id' in child.attrs:
                return True
    return False
