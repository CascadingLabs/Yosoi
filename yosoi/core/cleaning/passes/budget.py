"""Token budget enforcement with progressive truncation."""

from bs4 import BeautifulSoup, Tag


def estimate_tokens(text: str) -> int:
    """Rough token count estimate for HTML content.

    Uses ``len(text) / 4`` as a fast approximation suitable for budget checks.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count.

    """
    return len(text) // 4


def enforce_budget(html: str, token_budget: int) -> str:
    """Progressively truncate HTML until it fits within the token budget.

    Applies increasingly aggressive strategies:
    1. Strip all non-class/id attributes
    2. Remove elements from the bottom of the DOM tree

    Args:
        html: Cleaned HTML string to truncate.
        token_budget: Maximum estimated token count.

    Returns:
        HTML string within the token budget.

    """
    if token_budget <= 0 or estimate_tokens(html) <= token_budget:
        return html

    soup = BeautifulSoup(html, 'lxml')

    # Strategy 1: Strip all attributes except class and id
    if estimate_tokens(str(soup)) > token_budget:
        _strip_to_essentials(soup)

    result = str(soup)
    if estimate_tokens(result) <= token_budget:
        return result

    # Strategy 2: Remove elements from the bottom of the DOM
    _truncate_from_bottom(soup, token_budget)

    return str(soup)


def _strip_to_essentials(soup: BeautifulSoup) -> None:
    """Keep only class and id attributes on all elements."""
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and tag.attrs:
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in ('class', 'id')}


def _truncate_from_bottom(soup: BeautifulSoup, token_budget: int) -> None:
    """Remove leaf-ward elements until the soup fits the budget."""
    # Collect all leaf-adjacent block elements, deepest first
    while estimate_tokens(str(soup)) > token_budget:
        # Find the last block-level element in document order
        candidates = soup.find_all(['div', 'section', 'aside', 'ul', 'ol', 'table', 'p', 'span'])
        if not candidates:
            break
        # Remove the last one (bottom of DOM in document order)
        last = candidates[-1]
        if isinstance(last, Tag):
            last.decompose()
        else:
            break
