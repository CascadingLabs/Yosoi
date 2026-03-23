"""Remove noise elements that are never useful for selector discovery."""

import re

from bs4 import BeautifulSoup, Tag

# CSS selectors for exact-match ad classes/ids
_AD_CSS_SELECTORS = [
    '.advertisement',
    '.ad',
    '.related-posts',
    '.useful-links',
]

# Word-boundary pattern: matches "ad" as a whole word in class/id values.
# Catches "ad-banner", "sidebar-ad", "ad_slot" but NOT "lead-paragraph",
# "head-banner", "pad-4", "road-map", "loading", "breadcrumb".
_AD_WORD_RE = re.compile(r'(?:^|[-_\s])ad(?:[-_\s]|$)', re.IGNORECASE)

_SIDEBAR_SELECTORS = [
    '.sidebar',
    '#sidebar',
]


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
    _remove_never_useful(soup)
    _remove_site_chrome(soup)
    _remove_ads(soup)
    _remove_sidebars(soup)
    return soup


def _remove_never_useful(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(['script', 'style', 'noscript', 'iframe']):
        tag.decompose()


def _remove_site_chrome(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(['header', 'nav', 'footer']):
        if not isinstance(tag, Tag):
            continue
        if _is_inside_content_region(tag):
            continue
        tag.decompose()


def _remove_ads(soup: BeautifulSoup) -> None:
    for selector in _AD_CSS_SELECTORS:
        for element in soup.select(selector):
            element.decompose()
    # Word-boundary matching on class/id
    for tag in list(soup.find_all(True)):
        if isinstance(tag, Tag) and tag.parent is not None and _has_ad_word(tag):
            tag.decompose()


def _remove_sidebars(soup: BeautifulSoup) -> None:
    for selector in _SIDEBAR_SELECTORS:
        for element in soup.select(selector):
            if isinstance(element, Tag) and _is_inside_content_region(element):
                continue
            element.decompose()


def _has_ad_word(tag: Tag) -> bool:
    """Return True if any class or the id contains 'ad' as a whole word."""
    classes = tag.get('class', [])
    for cls in classes:
        if _AD_WORD_RE.search(cls):
            return True
    tag_id = tag.get('id', '')
    return isinstance(tag_id, str) and bool(_AD_WORD_RE.search(tag_id))


def _is_inside_content_region(tag: Tag) -> bool:
    """Return True if *tag* is a descendant of ``<main>`` or ``<article>``."""
    return any(isinstance(parent, Tag) and parent.name in ('main', 'article') for parent in tag.parents)
