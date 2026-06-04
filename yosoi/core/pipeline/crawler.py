"""Crawler mixin — frontier/crawl helpers and future CAS-52 gating methods.

Contains: _discover_and_push and related link expansion logic.
CAS-52 (related-link expansion with relevance gating) will add gating
methods here without touching the rest of the pipeline.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from yosoi.utils import observability

if TYPE_CHECKING:
    from yosoi.core.fetcher import HTMLFetcher

logger = logging.getLogger(__name__)


class PipelineCrawlerMixin:
    """Frontier and crawl-related helpers."""

    async def _discover_and_push(
        self,
        url: str,
        fetcher: HTMLFetcher,
        cleaner: Any,
        extractor: Any,
        frontier: Any,
        current_depth: int,
        max_fetch_retries: int,
    ) -> None:
        """Fetch a page, extract links, and push qualifying ones into the frontier.

        Separated from scrape() to keep complexity manageable. Failures are
        logged and swallowed — a link discovery failure should never abort the
        whole crawl.

        Args:
            url: Page to extract links from.
            fetcher: Active fetcher instance (shared across the crawl).
            cleaner: HTMLCleaner instance.
            extractor: LinkExtractor instance.
            frontier: Active Frontier instance.
            current_depth: Depth of the page we just scraped.
            max_depth: Maximum crawl depth configured for this run.
            max_fetch_retries: Max fetch retry attempts.
        """
        try:
            fetch_result = await self._fetch(url, fetcher, max_retries=max_fetch_retries)  # type: ignore[attr-defined]
            if not fetch_result or not fetch_result.html:
                return
            cleaned = cleaner.clean_html(fetch_result.html)
            links = extractor.extract(
                cleaned,
                base_url=url,
                field_descriptions=self.contract.field_descriptions(),  # type: ignore[attr-defined]
            )
            pushed = 0
            for link in links:
                # Pagination links stay at the same depth, content links increment
                new_depth = current_depth if link.is_pagination else current_depth + 1
                if frontier.push(link.url, new_depth, link.score):
                    pushed += 1
            if pushed:
                logger.info('Discovered %d new links from %s', pushed, url)
        except Exception as exc:  # noqa: BLE001
            observability.warning('Link discovery failed', url=url, error=str(exc))
            logger.warning('Link discovery failed for %s: %s', url, exc)
