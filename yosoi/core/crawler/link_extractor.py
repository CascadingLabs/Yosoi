"""Generic link extraction and structure fingerprinting for the crawl frontier.

Design constraints (CAS-51):
- Zero hardcoded domains or per-site rules.
- Any site-specific behaviour is data, not code.
- Leans on HTMLCleaner output which already strips nav/footer/sidebars, so
  boilerplate separation is upstream of this module.
- Detects repeated listing patterns structurally (same parent tag + class prefix).
- Detects pagination generically via text / aria-label signals.
- Uses contract field_descriptions to keyword-boost links that look like
  content URLs — without hardcoding any domain or path pattern.

Scoring philosophy:
- Content URLs (individual articles, products, jobs) can be identified by
  matching keywords extracted from the contract's ``url`` field description.
  If the contract says "URL of the NFL news article or story", then links
  whose path contains "story" or "article" score higher.
- LinkExtractor's structural job: find listing/index pages (pagination,
  category links) to seed the frontier with.
- Contract keyword job: boost links that look like content URLs so they
  are prioritised over section homepages in the frontier.

Structure fingerprinting (Layer 2):
- Hashes the DOM skeleton (tag names + normalised class prefixes, no content).
- The hash is stable across domains with the same layout template.
- Stored on SelectorSnapshot / SnapshotMap so the discovery orchestrator can
  short-circuit LLM calls on a fingerprint hit.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import lxml.html
from lxml.html import HtmlElement

# ---------------------------------------------------------------------------
# Pagination signals — text or aria-label matches trigger high score + no
# depth increment. All lowercase; matching is case-insensitive substring.
# ---------------------------------------------------------------------------
_PAGINATION_TEXTS: frozenset[str] = frozenset(
    {
        'next',
        'next page',
        'older posts',
        'older entries',
        'load more',
        'more results',
        '»',
        '›',
        '→',
        '>',
    }
)

# Minimum number of sibling links that share the same structural key before
# we treat them as a "listing" pattern.
_LISTING_MIN_SIBLINGS = 3

# Class prefix length used for normalisation — keeps "product-card-1" and
# "product-card-2" in the same bucket.
_CLASS_PREFIX_LEN = 12

# Score constants
_SCORE_PAGINATION = 0.95  # next/prev page — high priority, same depth
_SCORE_LISTING = 0.70  # repeated structural pattern — likely an index page
_SCORE_CONTENT = 0.40  # one-off link — lower priority
_SCORE_FLOOR = 0.05  # minimum score for any link past boilerplate

# Keyword boost multiplier — applied when a link matches url field keywords.
# Capped at 0.95 to stay below pagination score.
_KEYWORD_BOOST = 1.4
_SCORE_CAP = 0.94

# Stop words to strip from keyword extraction — these carry no signal.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        'a',
        'an',
        'the',
        'of',
        'in',
        'on',
        'at',
        'to',
        'for',
        'with',
        'and',
        'or',
        'is',
        'are',
        'be',
        'this',
        'that',
        'url',
        'link',
        'href',
        'path',
        'page',
        'containing',
        'contains',
        'which',
        'has',
        'its',
        'their',
        'from',
        'by',
        'as',
        'it',
        'into',
        'via',
    }
)


@dataclass(frozen=True)
class LinkScore:
    """A candidate URL and its heuristic score.

    Attributes:
        url:           Absolute, normalised URL.
        score:         0.0-1.0 heuristic relevance estimate.
        is_pagination: True when this link is a "next page" signal.
            The frontier uses this to avoid incrementing depth.
        anchor_text:   Visible text of the link (for debugging).
        context_text:  Surrounding paragraph text (for debugging).
    """

    url: str
    score: float
    is_pagination: bool = False
    anchor_text: str = ''
    context_text: str = ''


class LinkExtractor:
    """Extract and score candidate links from an HTML page.

    Scoring is structural by default. If ``field_descriptions`` contains a
    ``url`` field, keywords from its description are extracted and used to
    boost links whose URL path or anchor text match — without any hardcoded
    domain or path rules.

    Usage::

        extractor = LinkExtractor()
        links = extractor.extract(
            html,
            base_url="https://example.com",
            field_descriptions={"url": "The URL of the NFL news article or story"},
        )
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        html: str,
        base_url: str,
        field_descriptions: dict[str, str] | None = None,
    ) -> list[LinkScore]:
        """Return scored candidate links from *html*.

        Args:
            html:               HTML string (raw or cleaned).
            base_url:           Absolute URL of the source page, used to
                                resolve relative hrefs.
            field_descriptions: Optional mapping of field name → description
                                from the scraping contract. If a ``url`` key
                                is present, its description is parsed for
                                keywords used to boost content link scores.

        Returns:
            List of :class:`LinkScore`, sorted descending by score.
            Deduped by URL; the highest score wins.
        """
        if not html or not html.strip():
            return []

        # Extract keywords from the url field description if provided
        url_keywords = _extract_url_keywords(field_descriptions)

        tree = lxml.html.document_fromstring(html)

        # Collect raw link data
        raw: list[_RawLink] = self._collect_links(tree, base_url)

        # Detect listing groups (shared structural key, >= _LISTING_MIN_SIBLINGS)
        listing_urls = _detect_listing_groups(raw)

        # Score each link
        scored: dict[str, LinkScore] = {}
        for rl in raw:
            ls = self._score_link(rl, listing_urls, url_keywords)
            if ls.url not in scored or scored[ls.url].score < ls.score:
                scored[ls.url] = ls

        return sorted(scored.values(), key=lambda x: x.score, reverse=True)

    # ------------------------------------------------------------------
    # Structure fingerprinting
    # ------------------------------------------------------------------

    @staticmethod
    def fingerprint(html: str) -> str:
        """Return a stable hex digest of the DOM skeleton.

        Hashes tag names and normalised class prefixes — no content, no IDs,
        no dynamic attributes. Two pages with the same layout template
        (even on different domains) produce the same fingerprint.

        Args:
            html: Raw or cleaned HTML string.

        Returns:
            32-character hex digest (MD5 of the skeleton string).
        """
        if not html or not html.strip():
            return hashlib.md5(b'').hexdigest()
        tree = lxml.html.document_fromstring(html)
        skeleton = _build_skeleton(tree)
        return hashlib.md5(skeleton.encode('utf-8')).hexdigest()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_links(self, tree: HtmlElement, base_url: str) -> list[_RawLink]:
        """Walk the tree and collect every <a href> with its structural context."""
        links: list[_RawLink] = []
        for anchor in tree.xpath('.//a[@href]'):
            href = anchor.get('href', '').strip()
            if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue

            abs_url = _resolve_url(href, base_url)
            if not abs_url:
                continue

            anchor_text = _node_text(anchor)
            aria_label = anchor.get('aria-label', '')
            title = anchor.get('title', '')
            context_text = _nearest_paragraph_text(anchor)

            parent = anchor.getparent()
            struct_key = _structural_key(parent) if parent is not None else ('', '')

            links.append(
                _RawLink(
                    url=abs_url,
                    anchor_text=anchor_text,
                    aria_label=aria_label,
                    title=title,
                    context_text=context_text,
                    struct_key=struct_key,
                )
            )
        return links

    def _score_link(
        self,
        rl: _RawLink,
        listing_urls: frozenset[str],
        url_keywords: frozenset[str],
    ) -> LinkScore:
        """Compute a heuristic score for one raw link.

        Base scoring is structural:
        - Pagination signals → 0.95, is_pagination=True
        - Repeated listing pattern → 0.70
        - One-off link → 0.40

        If url_keywords are provided, links whose URL path or anchor text
        contain any keyword are boosted by _KEYWORD_BOOST (capped at
        _SCORE_CAP to stay below pagination).
        """
        display = (rl.anchor_text or rl.aria_label or rl.title).lower().strip()

        # Pagination check — keywords don't override pagination detection
        if any(display == p or display.startswith(p) for p in _PAGINATION_TEXTS):
            return LinkScore(
                url=rl.url,
                score=_SCORE_PAGINATION,
                is_pagination=True,
                anchor_text=rl.anchor_text,
                context_text=rl.context_text,
            )

        # Structural base score
        score = _SCORE_LISTING if rl.url in listing_urls else _SCORE_CONTENT

        # Keyword boost — check URL path and anchor text
        if url_keywords and _matches_keywords(rl.url, rl.anchor_text, url_keywords):
            score = min(score * _KEYWORD_BOOST, _SCORE_CAP)

        return LinkScore(
            url=rl.url,
            score=max(score, _SCORE_FLOOR),
            is_pagination=False,
            anchor_text=rl.anchor_text,
            context_text=rl.context_text,
        )


# ---------------------------------------------------------------------------
# Keyword extraction and matching
# ---------------------------------------------------------------------------


def _extract_url_keywords(
    field_descriptions: dict[str, str] | None,
) -> frozenset[str]:
    """Extract meaningful keywords from the url field description.

    Strips stop words, punctuation, and short tokens. Returns an empty
    frozenset if no url field description is available.

    Args:
        field_descriptions: Mapping of field name → description string.

    Returns:
        Frozenset of lowercase keyword strings.
    """
    if not field_descriptions:
        return frozenset()

    url_desc = field_descriptions.get('url', '')
    if not url_desc:
        return frozenset()

    # Split on whitespace and punctuation, lowercase
    tokens = re.split(r'[\s\-_/.,;:\'\"()\[\]{}]+', url_desc.lower())

    keywords = frozenset(t for t in tokens if t and len(t) >= 3 and t not in _STOP_WORDS)
    return keywords


def _matches_keywords(url: str, anchor_text: str, keywords: frozenset[str]) -> bool:
    """Return True if the URL path or anchor text contains any keyword.

    Matching is substring-based and case-insensitive — "story" matches
    "/nfl/story/_/id/123" and "Read the full story".

    Args:
        url:         Absolute URL string.
        anchor_text: Visible link text.
        keywords:    Keywords to match against.

    Returns:
        True if any keyword appears in the URL path or anchor text.
    """
    path = urlparse(url).path.lower()
    text = anchor_text.lower()
    return any(kw in path or kw in text for kw in keywords)


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------


@dataclass
class _RawLink:
    """Intermediate representation before scoring."""

    url: str
    anchor_text: str
    aria_label: str
    title: str
    context_text: str
    struct_key: tuple[str, str]  # (parent-tag, normalised-class-prefix)


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def _resolve_url(href: str, base_url: str) -> str | None:
    """Resolve *href* against *base_url*, returning None for non-HTTP results."""
    try:
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in ('http', 'https'):
            return None
        return abs_url.split('#')[0].rstrip('/')
    except ValueError:
        return None


def _node_text(el: HtmlElement) -> str:
    """Return visible text of *el* (all descendant text nodes joined)."""
    parts = el.xpath('.//text()')
    return ' '.join(p.strip() for p in parts if p.strip())


def _nearest_paragraph_text(anchor: HtmlElement) -> str:
    """Walk up ancestors to find the nearest block element and return its text."""
    _BLOCK_TAGS = {'p', 'li', 'td', 'dd', 'blockquote', 'article', 'section'}
    current = anchor.getparent()
    for _ in range(6):
        if current is None:
            break
        tag = current.tag if isinstance(current.tag, str) else ''
        if tag.lower() in _BLOCK_TAGS:
            return _node_text(current)[:300]
        current = current.getparent()
    return ''


def _structural_key(el: HtmlElement) -> tuple[str, str]:
    """Return (tag, normalised-class-prefix) for *el*."""
    tag = el.tag if isinstance(el.tag, str) else ''
    classes = el.get('class', '')
    first_class = classes.split()[0] if classes.strip() else ''
    prefix = first_class[:_CLASS_PREFIX_LEN]
    return (tag.lower(), prefix)


def _detect_listing_groups(raw: list[_RawLink]) -> frozenset[str]:
    """Return URLs that belong to repeated listing patterns.

    A listing pattern is >= _LISTING_MIN_SIBLINGS links sharing the same
    (parent-tag, class-prefix) structural key.
    """
    from collections import Counter

    key_counts: Counter[tuple[str, str]] = Counter(rl.struct_key for rl in raw)
    listing_keys = {k for k, count in key_counts.items() if count >= _LISTING_MIN_SIBLINGS}
    return frozenset(rl.url for rl in raw if rl.struct_key in listing_keys)


def _build_skeleton(tree: HtmlElement) -> str:
    """Recursively build a compact skeleton string from *tree*.

    Format: ``tag[class-prefix]{children...}``
    Content text, IDs, data attributes, and style are intentionally omitted
    so the skeleton is purely structural.
    """
    parts: list[str] = []
    _walk_skeleton(tree, parts)
    return ''.join(parts)


def _walk_skeleton(el: Any, parts: list[str]) -> None:
    """Depth-first walk emitting skeleton tokens."""
    if not isinstance(el.tag, str):
        return
    tag = el.tag.lower()
    if tag in ('script', 'style', 'noscript', 'svg', 'canvas'):
        return
    classes = el.get('class', '')
    first_class = classes.split()[0][:_CLASS_PREFIX_LEN] if classes.strip() else ''
    parts.append(f'{tag}[{first_class}]{{')
    for child in el:
        _walk_skeleton(child, parts)
    parts.append('}')
