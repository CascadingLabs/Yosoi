"""Remove noise elements that are never useful for selector discovery."""

from bs4 import BeautifulSoup, Tag


def remove_noise(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove scripts, styles, site-level chrome, and ad elements.

    Only removes ``<header>``, ``<nav>``, and ``<footer>`` tags that sit at the
    top level of ``<body>`` (site-level chrome).  Tags nested inside ``<main>``
    or ``<article>`` are kept — they may contain content-bearing metadata.

    Sidebar/widget removal is limited to elements outside ``<main>`` to avoid
    stripping content-bearing sidebars (e.g. rankings, stats panels).

    Args:
        soup: Parsed HTML tree to clean in-place.

    Returns:
        The same (mutated) soup object.

    """
    # Step 1: Remove elements that are never useful
    for tag in soup.find_all(['script', 'style', 'noscript', 'iframe']):
        tag.decompose()

    # Step 2: Remove site-level header, nav, footer (only top-level, not inside main/article)
    for tag in soup.find_all(['header', 'nav', 'footer']):
        if not isinstance(tag, Tag):
            continue
        if _is_inside_content_region(tag):
            continue
        tag.decompose()

    # Step 3: Remove sidebars, widgets, ads (only outside main content region)
    _AD_SELECTORS = [
        '.advertisement',
        '.ad',
        '[class*="ad-"]',
        '[id*="ad-"]',
        '.related-posts',
        '.useful-links',
    ]
    _SIDEBAR_SELECTORS = [
        '.sidebar',
        '#sidebar',
    ]

    # Ads are always noise — remove everywhere
    for selector in _AD_SELECTORS:
        for element in soup.select(selector):
            element.decompose()

    # Sidebar/widget removal — only if outside <main>/<article>
    for selector in _SIDEBAR_SELECTORS:
        for element in soup.select(selector):
            if isinstance(element, Tag) and _is_inside_content_region(element):
                continue
            element.decompose()

    return soup


def _is_inside_content_region(tag: Tag) -> bool:
    """Return True if *tag* is a descendant of ``<main>`` or ``<article>``."""
    return any(isinstance(parent, Tag) and parent.name in ('main', 'article') for parent in tag.parents)
