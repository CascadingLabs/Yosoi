"""Generic link extraction for crawl expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import lxml.html

from yosoi.core.crawler.frontier import canonicalize_url

_PAGINATION_RE = re.compile(r'\b(next|older|more|load more|page\s+\d+)\b|[>»]', re.IGNORECASE)
_CONTENT_HINT_RE = re.compile(r'\b(article|story|post|news|detail|item|product|profile)\b', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CrawlLink:
    """A normalized link candidate from a page."""

    url: str
    text: str
    score: float
    is_pagination: bool = False


class LinkExtractor:
    """Extract crawlable links without site-specific selectors."""

    def extract(self, html: str, *, base_url: str, allowed_hosts: set[str] | None = None) -> list[CrawlLink]:
        """Return de-duplicated HTTP(S) links in document order."""
        try:
            root = lxml.html.fromstring(html)
        except (ValueError, TypeError):
            return []

        seen: set[str] = set()
        links: list[CrawlLink] = []
        for anchor in root.xpath('//a[@href]'):
            href = anchor.get('href')
            if not href:
                continue
            canonical = canonicalize_url(urljoin(base_url, href))
            if canonical is None or canonical in seen:
                continue
            host = urlparse(canonical).hostname
            if allowed_hosts is not None and host not in allowed_hosts:
                continue

            text = ' '.join(anchor.text_content().split())
            is_pagination = self._is_pagination(anchor, text)
            links.append(
                CrawlLink(
                    url=canonical,
                    text=text,
                    score=self._score(canonical, text, is_pagination),
                    is_pagination=is_pagination,
                )
            )
            seen.add(canonical)
        return links

    def _is_pagination(self, anchor: object, text: str) -> bool:
        label = ''
        if hasattr(anchor, 'get'):
            raw_label = anchor.get('aria-label')  # type: ignore[attr-defined]
            label = raw_label if isinstance(raw_label, str) else ''
        return bool(_PAGINATION_RE.search(f'{text} {label}'))

    def _score(self, url: str, text: str, is_pagination: bool) -> float:
        if is_pagination:
            return 0.95
        parsed = urlparse(url)
        haystack = f'{parsed.path} {text}'
        if _CONTENT_HINT_RE.search(haystack):
            return 0.8
        return 0.5
