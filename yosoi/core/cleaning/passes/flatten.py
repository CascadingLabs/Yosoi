"""Flatten meaningless wrapper elements to reduce DOM nesting."""

from bs4 import BeautifulSoup, NavigableString, Tag


def flatten_wrappers(soup: BeautifulSoup) -> BeautifulSoup:
    """Unwrap ``<div>`` and ``<span>`` elements that add no semantic value.

    A wrapper is unwrapped when it:
    - Has no class, id, or data-* attributes
    - Has exactly one child element (ignoring whitespace-only text nodes)

    This is especially effective on React/Next.js sites that produce deeply
    nested anonymous wrapper divs.

    Args:
        soup: Parsed HTML tree to flatten in-place.

    Returns:
        The same (mutated) soup object.

    """
    changed = True
    while changed:
        changed = False
        for tag in reversed(soup.find_all(['div', 'span'])):
            if not isinstance(tag, Tag):
                continue
            if _has_semantic_attrs(tag):
                continue
            children = _meaningful_children(tag)
            if len(children) == 1 and isinstance(children[0], Tag):
                tag.unwrap()
                changed = True
    return soup


def _has_semantic_attrs(tag: Tag) -> bool:
    """Check whether a tag carries attributes useful for selectors."""
    return bool('class' in tag.attrs or 'id' in tag.attrs or any(k.startswith('data-') for k in tag.attrs))


def _meaningful_children(tag: Tag) -> list[Tag | NavigableString]:
    """Return children that are not whitespace-only text nodes."""
    return [
        child
        for child in tag.children
        if isinstance(child, Tag) or (isinstance(child, NavigableString) and child.strip())
    ]
