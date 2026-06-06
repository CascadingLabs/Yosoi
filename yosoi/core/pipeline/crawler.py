"""Crawler mixin — frontier/crawl helpers and CAS-52 gating methods.

Contains: _scrape_single, _scrape_crawl, _discover_and_push.

The crawl loop uses two URL sources:
1. Contract ``url`` field values extracted from scraped items — high confidence,
   score 1.0, these are the actual content URLs the contract identified.
2. LinkExtractor pagination/listing detection — finds new index pages to seed
   from, not individual content URLs. Contract field_descriptions are passed
   to LinkExtractor so it can keyword-boost content-like URLs.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from yosoi.utils import observability

if TYPE_CHECKING:
    from yosoi.core.fetcher import HTMLFetcher

logger = logging.getLogger(__name__)


class PipelineCrawlerMixin:
    """Frontier and crawl-related helpers."""

    async def _scrape_single(
        self,
        url: str,
        force_flag: bool,
        max_fetch_retries: int,
        max_discovery_retries: int,
        skip_verification: bool,
        fetcher_type: str,
        format_to_use: list[str],
        fetcher: Any | None,
    ) -> AsyncIterator[Any]:
        """Single-URL scrape path — the original pre-CAS-49 behavior."""
        from contextlib import ExitStack
        from urllib.parse import urlparse

        parsed = urlparse(url)
        trace_name = f'scrape {parsed.netloc}{parsed.path or "/"}'
        sess_id = observability.process_session_id()
        user_id = observability.normalize_user_id(url)

        with ExitStack() as stack:
            stack.enter_context(observability.session(sess_id, tags=['yosoi', 'script']))
            if user_id is not None:
                stack.enter_context(observability.user(user_id, tags=[user_id]))
            root_span = stack.enter_context(
                observability.span(trace_name, url=url, force=force_flag, fetcher_type=fetcher_type)
            )
            observability.set_trace_input(
                root_span,
                {
                    'url': url,
                    'contract': {
                        'name': self.contract.__name__,  # type: ignore[attr-defined]
                        'fields': self.contract.field_descriptions(),  # type: ignore[attr-defined]
                        'overrides': self.contract.get_selector_overrides(),  # type: ignore[attr-defined]
                        'discovery_field_names': sorted(self.contract.discovery_field_names()),  # type: ignore[attr-defined]
                    },
                },
            )
            self.logger.info('Processing URL: %s (force=%s, fetcher=%s)', url, force_flag, fetcher_type)  # type: ignore[attr-defined]
            domain = self._extract_domain(url)  # type: ignore[attr-defined]

            _owns_fetcher = fetcher is None
            if _owns_fetcher:
                fetcher = self._create_fetcher(fetcher_type, console=self.console)  # type: ignore[attr-defined]
                if not fetcher:
                    raise RuntimeError(f'Invalid fetcher type: {fetcher_type}')
            if fetcher is None:
                raise RuntimeError('No fetcher available')
            ctx = fetcher if _owns_fetcher else nullcontext(fetcher)

            async with ctx:
                if not force_flag:
                    cache_gen = await self._try_cached(  # type: ignore[attr-defined]
                        url, domain, fetcher, skip_verification, format_to_use, root_span=root_span
                    )
                    if cache_gen is not None:
                        async for item in cache_gen:
                            yield item
                        return

                async for item in self._scrape_fresh(  # type: ignore[attr-defined]
                    url=url,
                    domain=domain,
                    fetcher=fetcher,
                    force_flag=force_flag,
                    max_fetch_retries=max_fetch_retries,
                    max_discovery_retries=max_discovery_retries,
                    skip_verification=skip_verification,
                    format_to_use=format_to_use,
                    root_span=root_span,
                ):
                    yield item

    async def _scrape_crawl(
        self,
        url: str,
        force_flag: bool,
        max_fetch_retries: int,
        max_discovery_retries: int,
        skip_verification: bool,
        fetcher_type: str,
        format_to_use: list[str],
        fetcher: Any | None,
        depth: int,
        max_pages: int,
        score_threshold: float,
        session_id: str | None,
    ) -> AsyncIterator[Any]:
        """Frontier-based multi-page crawl path (CAS-49).

        Two URL sources feed the frontier:
        1. Contract ``url`` field values from scraped items — score 1.0, these
           are the content URLs the contract already identified with AI precision.
        2. LinkExtractor pagination/listing detection — finds new index pages,
           not individual content URLs. Contract field_descriptions are passed
           so LinkExtractor can keyword-boost content-like URLs.
        """
        from yosoi.core.crawler.frontier import Frontier
        from yosoi.core.crawler.frontier import normalize_url as _norm
        from yosoi.core.crawler.link_extractor import LinkExtractor

        sid = session_id or str(uuid.uuid4())

        # Derive seed domain for cross-domain score penalty
        seed_domain = (urlparse(_norm(url) or '').hostname or '').removeprefix('www.')

        frontier = Frontier(
            session_id=sid,
            score_threshold=score_threshold,
            seed_domain=seed_domain,
        )
        frontier.push(url, depth=0, score=1.0)

        _owns_fetcher = fetcher is None
        if _owns_fetcher:
            fetcher = self._create_fetcher(fetcher_type, console=self.console)  # type: ignore[attr-defined]
            if not fetcher:
                raise RuntimeError(f'Invalid fetcher type: {fetcher_type}')
        if fetcher is None:
            raise RuntimeError('No fetcher available')

        extractor = LinkExtractor()

        # Extract field_descriptions from the contract for keyword-boosted scoring
        _field_descs = self.contract.field_descriptions()  # type: ignore[attr-defined]
        print(f'DEBUG _field_descs at assignment: {_field_descs}')

        async with fetcher if _owns_fetcher else nullcontext(fetcher):
            while not frontier.is_empty() and frontier.pages_scraped < max_pages:
                current_url, current_depth = await frontier.popleft()
                domain = self._extract_domain(current_url)  # type: ignore[attr-defined]

                self.console.print(  # type: ignore[attr-defined]
                    f'[dim]  ↻ Crawl [{frontier.pages_scraped}/{max_pages}] depth={current_depth} {current_url}[/dim]'
                )

                try:
                    # Try cached selectors first
                    if not force_flag:
                        cache_gen = await self._try_cached(  # type: ignore[attr-defined]
                            current_url, domain, fetcher, skip_verification, format_to_use
                        )
                        if cache_gen is not None:
                            async for item in cache_gen:
                                yield item
                                # Source 1: push contract url field values directly
                                self._push_item_url(item, frontier, current_depth, depth)
                            # Source 2: find new listing/pagination pages
                            if current_depth < depth:
                                await self._discover_and_push(
                                    current_url,
                                    fetcher,
                                    extractor,
                                    frontier,
                                    current_depth,
                                    max_fetch_retries,
                                    _field_descs,
                                )
                            continue

                    # Fresh discovery path
                    async for item in self._scrape_fresh(  # type: ignore[attr-defined]
                        url=current_url,
                        domain=domain,
                        fetcher=fetcher,
                        force_flag=force_flag,
                        max_fetch_retries=max_fetch_retries,
                        max_discovery_retries=max_discovery_retries,
                        skip_verification=skip_verification,
                        format_to_use=format_to_use,
                        root_span=None,
                    ):
                        yield item
                        # Source 1: push contract url field values directly
                        self._push_item_url(item, frontier, current_depth, depth)

                except Exception as exc:  # noqa: BLE001
                    observability.warning('Crawl page failed', url=current_url, error=str(exc))
                    self.logger.warning('Crawl failed for %s: %s', current_url, exc)  # type: ignore[attr-defined]
                    continue

                # Source 2: find new listing/pagination pages
                if current_depth < depth:
                    await self._discover_and_push(
                        current_url,
                        fetcher,
                        extractor,
                        frontier,
                        current_depth,
                        max_fetch_retries,
                        _field_descs,
                    )

        await frontier.save()
        self.console.print(  # type: ignore[attr-defined]
            f'[success]Crawl complete: {frontier.pages_scraped} pages scraped, '
            f'{frontier.visited_count()} unique URLs seen[/success]'
        )

    def _push_item_url(
        self,
        item: dict[str, Any],
        frontier: Any,
        current_depth: int,
        max_depth: int,
    ) -> None:
        """Push the contract url field value from a scraped item into the frontier.

        These URLs are score 1.0 — the contract already identified them with
        AI precision, so no heuristic scoring needed. Only push if we're still
        within the depth budget.

        Args:
            item: Extracted content map from a scrape.
            frontier: Active Frontier instance.
            current_depth: Depth of the page this item was scraped from.
            max_depth: Maximum crawl depth.
        """
        if current_depth >= max_depth:
            return
        article_url = item.get('url')
        if not isinstance(article_url, str) or not article_url:
            return
        if frontier.push(article_url, current_depth + 1, score=1.0):
            logger.debug('Frontier: pushed contract URL %s', article_url)

    async def _discover_and_push(
        self,
        url: str,
        fetcher: HTMLFetcher,
        extractor: Any,
        frontier: Any,
        current_depth: int,
        max_fetch_retries: int,
        field_descriptions: dict[str, str] | None = None,
    ) -> None:
        """Fetch a page, extract links, push into the frontier.

        Passes field_descriptions to LinkExtractor so contract keywords can
        boost content-like URLs above generic section pages. The priority
        queue in Frontier then ensures boosted URLs are scraped first.

        Args:
            url: Page to extract links from.
            fetcher: Active fetcher instance (shared across the crawl).
            extractor: LinkExtractor instance.
            frontier: Active Frontier instance.
            current_depth: Depth of the page we just scraped.
            max_fetch_retries: Max fetch retry attempts.
            field_descriptions: Contract field descriptions for keyword scoring.
        """
        try:
            fetch_result = await self._fetch(url, fetcher, max_retries=max_fetch_retries)  # type: ignore[attr-defined]
            if not fetch_result or not fetch_result.html:
                return

            print(f'DEBUG field_descriptions keys: {list(field_descriptions.keys()) if field_descriptions else None}')
            links = extractor.extract(
                fetch_result.html,
                base_url=url,
                field_descriptions=field_descriptions,
            )

            pushed = 0
            for link in links:
                if (link.is_pagination and frontier.push(link.url, current_depth, link.score)) or (
                    link.score >= 0.7 and frontier.push(link.url, current_depth, link.score)
                ):
                    pushed += 1

            if pushed:
                logger.info('Discovered %d links from %s', pushed, url)
        except Exception as exc:  # noqa: BLE001
            observability.warning('Link discovery failed', url=url, error=str(exc))
            logger.warning('Link discovery failed for %s: %s', url, exc)
