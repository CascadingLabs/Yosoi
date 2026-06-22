"""Three-tier JS fetcher: Simple HTTP → Headless Chrome → Headful Chrome.

Fetch waterfall
---------------
1. **SimpleFetcher** (plain HTTP, no Chrome)
   - On success with no JS detected → return immediately.
   - On failure **or** ``result.metadata.requires_js`` → fall through.
2. **HeadlessFetcher** (headless Chrome, fast)
   - On success → return immediately.
   - On failure (empty content, DOM timeout, hard error) → fall through.
3. **HeadfulFetcher** (visible Chrome, best bot evasion)
   - Result is returned regardless (best-effort final tier).

The winning tier for each domain is saved to .yosoi/fetch/ via
:class:`~yosoi.storage.strategy.FetchStrategyStorage`. On the next run
the waterfall is skipped and the cached tier is used immediately.

Usage (drop-in for SimpleFetcher)::

    async with JSFetcher() as fetcher:
        result = await fetcher.fetch("https://finance.yahoo.com/article")
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx
from rich.console import Console

from yosoi.core.crawler.links import LinkExtractor
from yosoi.core.fetcher.base import HARD_BLOCK_STATUS, HTMLFetcher
from yosoi.core.fetcher.identity import (
    BrowserIdentity,
    IdentityCascade,
    IdentityFetcherPool,
    run_cascade,
)
from yosoi.core.fetcher.simple import SimpleFetcher
from yosoi.core.fetcher.voiddriver import HeadfulFetcher, HeadlessFetcher, _VoidCrawlFetcher
from yosoi.models.results import FetchResult
from yosoi.storage.strategy import FetchStrategy, FetchStrategyStorage
from yosoi.utils.exceptions import BotDetectionError
from yosoi.utils.urls import extract_domain

if TYPE_CHECKING:
    from yosoi.models.download import DownloadSpec


class JSFetcher(HTMLFetcher):
    """Three-tier JS fetcher: Simple HTTP → Headless Chrome → Headful Chrome.

    The winning tier for each domain is saved to .yosoi/fetch/ via
    FetchStrategyStorage. On the next run the waterfall is skipped
    and the cached tier is used immediately.

    Usage::

        async with JSFetcher() as fetcher:
            result = await fetcher.fetch("https://finance.yahoo.com/article")
    """

    def __init__(
        self,
        timeout: int = 30,
        rotate_user_agent: bool = True,
        use_session: bool = True,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
        randomize_headers: bool = True,
        allow_redirects: bool = True,
        max_concurrent: int = 5,
        min_content_length: int = 500,
        browser_executable_path: str | None = None,
        console: Console | None = None,
        force: bool = False,
        experimental_a3node: bool = False,
        allow_downloads: bool = False,
        download_dir: str | None = None,
        voidcrawl_user_agent: str | None = None,
        voidcrawl_accept_language: str | None = None,
        identity: BrowserIdentity | None = None,
        identity_cascade: IdentityCascade | None = None,
        max_live_identities: int = 3,
        cross_origin_dom: bool = False,
        chrome_ws_urls: tuple[str, ...] = (),
        accept_simple_requires_js: bool = False,
        crawl_frontier_only: bool = False,
    ):
        """Initialise the three-tier JS fetcher.

        Args:
            timeout: Tab load + DOM stability timeout in seconds.
            rotate_user_agent: Forwarded to SimpleFetcher for interface compat.
            use_session: Forwarded to SimpleFetcher for interface compat.
            min_delay: Minimum pause between requests (seconds).
            max_delay: Maximum pause between requests (seconds).
            randomize_headers: Forwarded to SimpleFetcher for interface compat.
            allow_redirects: Forwarded to SimpleFetcher. Browser tiers may still
                follow redirects; crawl policy blocks changed final URLs after fetch.
            max_concurrent: Max tabs open at once per Chrome tier.
            min_content_length: HTML shorter than this triggers Chrome fallback.
            browser_executable_path: Path to Chrome binary. Auto-detected if None.
            console: Optional Rich console for progress output.
            force: Skip fetcher strategy cache and re-run full waterfall. Defaults to False.
            experimental_a3node: Opt into experimental A3Node persistence/replay.
                Disabled by default so browser rendering always uses a fresh DOMLoader run.
            allow_downloads: Opt into ys.File() downloads on the browser tiers. Off by default.
            download_dir: Quarantine root for downloads. Defaults to ``.yosoi/downloads/``.
            voidcrawl_user_agent: Optional browser UA override. When omitted,
                VoidCrawl owns UA and matching Client Hints.
            voidcrawl_accept_language: Optional browser Accept-Language override.
            identity: Optional single browser identity. Converted to a one-entry
                ``IdentityCascade`` so ``fetcher_type='auto'`` accepts the same
                identity argument as the direct browser tiers.
            identity_cascade: Optional :class:`IdentityCascade` of browser
                identities (profile/proxy combos). When set, a bot-block on the
                terminal headful tier escalates into a per-identity rotation
                (W2) instead of returning best-effort. ``None`` keeps the legacy
                single-identity 3-tier behaviour.
            max_live_identities: Cap on simultaneously-live identity fetchers
                (each is its own Chrome process); losers are LRU-closed.
            cross_origin_dom: Opt the Chrome tiers into cross-origin DOM access
                (``ScrapePolicy.cross_origin_dom``): disables site-isolation field
                trials so ``evaluate_js_in_frame`` reaches isolated origins. Off
                by default; ignored by the simple tier.
            chrome_ws_urls: Optional CDP endpoints for a pre-running VoidCrawl
                docker/browser farm. When set, browser tiers attach instead of launching local Chrome.
            accept_simple_requires_js: Return simple-tier HTML even when it is marked
                JS-required. Off by default; callers should only use it when partial
                static HTML is explicitly acceptable.
            crawl_frontier_only: When browser tiers are needed for crawl discovery,
                navigate and capture rendered HTML without running scrape-grade DOMLoader.

        """
        self._simple = SimpleFetcher(
            timeout=timeout,
            rotate_user_agent=rotate_user_agent,
            use_session=use_session,
            min_delay=min_delay,
            max_delay=max_delay,
            randomize_headers=randomize_headers,
            allow_redirects=allow_redirects,
        )
        self._headless: HeadlessFetcher | None = None
        self._headful: HeadfulFetcher | None = None
        self._headless_lock = asyncio.Lock()
        self._headful_lock = asyncio.Lock()

        # In-memory cache populated from disk on __aenter__
        self._strategy_cache: dict[str, FetchStrategy] = {}
        self._strategy_lock = asyncio.Lock()
        self._strategy_storage = FetchStrategyStorage()

        self._console = console or Console()
        self.logger = logging.getLogger(__name__)
        self._force = force
        self._accept_simple_requires_js = accept_simple_requires_js
        self._crawl_frontier_only = crawl_frontier_only

        self._chrome_kwargs: dict[str, Any] = {
            'timeout': timeout,
            'min_delay': min_delay,
            'max_delay': max_delay,
            'max_concurrent': max_concurrent,
            'min_content_length': min_content_length,
            'browser_executable_path': browser_executable_path,
            'console': self._console,
            'experimental_a3node': experimental_a3node,
            'allow_downloads': allow_downloads,
            'download_dir': download_dir,
            'user_agent': voidcrawl_user_agent,
            'accept_language': voidcrawl_accept_language,
            'cross_origin_dom': cross_origin_dom,
            'chrome_ws_urls': chrome_ws_urls,
        }

        # W2 — profile cascade. Built lazily on first block so a run with no
        # bot-walled domains never pays for it.
        self._identity_cascade = identity_cascade or (IdentityCascade((identity,)) if identity is not None else None)
        self._max_live_identities = max_live_identities
        self._identity_pool: IdentityFetcherPool | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> JSFetcher:
        """Start the simple fetcher eagerly; Chrome tiers start lazily."""
        await self._simple.__aenter__()
        self._strategy_cache = await self._strategy_storage.load_all_strategies()
        self.logger.info(
            'JSFetcher ready (simple tier active, %d domain strategies cached)',
            len(self._strategy_cache),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context manager and close all tiers."""
        await self.close()

    async def close(self) -> None:
        """Close all active fetcher tiers."""
        await self._simple.close()
        if self._headless is not None:
            await self._headless.close()
            self._headless = None
        if self._headful is not None:
            await self._headful.close()
            self._headful = None
        if self._identity_pool is not None:
            await self._identity_pool.close()
            self._identity_pool = None

    @property
    def supports_browse(self) -> bool:
        """The waterfall escalates to a real browser tier, so a live tab is available.

        This makes ys.File() downloads work on ``fetcher_type='auto'`` (the download
        gate forces the browser tier for download specs; see ``_fetch_waterfall``).
        """
        return True

    # ------------------------------------------------------------------
    # Strategy cache helpers
    # ------------------------------------------------------------------

    def _preferred_strategy(self, domain: str) -> FetchStrategy | None:
        """Return the cached strategy for *domain*, or None if unknown."""
        return self._strategy_cache.get(domain)

    async def _record_success(self, domain: str, tier: str, identity_id: str | None = None) -> None:
        """Save the winning tier (and cascade identity) for *domain* if it changed."""
        if self._crawl_frontier_only:
            return
        async with self._strategy_lock:
            current = self._strategy_cache.get(domain)
            if current is None or current.fetcher != tier or current.identity_id != identity_id:
                selector_level = current.selector_level if current is not None else None
                self._strategy_cache[domain] = FetchStrategy(
                    fetcher=tier, selector_level=selector_level, identity_id=identity_id
                )
                await self._strategy_storage.save(domain, tier, selector_level=selector_level, identity_id=identity_id)
                ident_msg = f' (identity {identity_id})' if identity_id else ''
                self._console.print(f'[success]  ✓ Fetcher strategy saved: {domain} → {tier}{ident_msg}[/success]')
                self.logger.info('Fetch strategy cached: %s -> %s%s', domain, tier, ident_msg)

    async def update_selector_level(self, domain: str, selector_level: str) -> None:
        """Persist the selector escalation level that worked for this domain."""
        async with self._strategy_lock:
            current = self._strategy_cache.get(domain)
            if current is None:
                return
            if current.selector_level == selector_level:
                return
            updated = FetchStrategy(
                fetcher=current.fetcher, selector_level=selector_level, identity_id=current.identity_id
            )
            self._strategy_cache[domain] = updated
            await self._strategy_storage.save(
                domain, current.fetcher, selector_level=selector_level, identity_id=current.identity_id
            )
            self._console.print(f'[dim]  ↳ Selector level cached: {domain} → {selector_level}[/dim]')

    # ------------------------------------------------------------------
    # Lazy Chrome tier startup
    # ------------------------------------------------------------------

    async def _probe_requires_js(self, url: str) -> bool:
        """HEAD probe to detect JS-rendered pages before committing to a full fetch.

        Checks response headers and content-length for signals that the page
        is a SPA or dynamically rendered — without downloading the body at all.
        """
        try:
            async with httpx.AsyncClient() as client:
                r = await client.head(
                    url,
                    timeout=5.0,
                    follow_redirects=True,
                    headers={'User-Agent': 'Mozilla/5.0'},
                )

            headers = {k.lower(): v.lower() for k, v in r.headers.items()}

            # Hard block / bot gate status codes → Chrome required
            if r.status_code in HARD_BLOCK_STATUS:
                return True

            content_type = headers.get('content-type', '')
            if content_type and 'html' not in content_type:
                return False

            # Thin content-length on an HTML page = likely a shell with no body
            content_length = int(headers.get('content-length', -1))
            if 0 < content_length < 5_000:
                return True

            # Explicit framework headers
            powered_by = headers.get('x-powered-by', '')
            if any(fw in powered_by for fw in ('next.js', 'nuxt', 'gatsby', 'angular')):
                return True

            # Some CDNs advertise SSR/SPA origin behaviour
            server = headers.get('server', '')
            if 'vercel' in server or 'netlify' in server:
                return True

            # No content-length at all + chunked transfer often means streaming SSR
            transfer = headers.get('transfer-encoding', '')
            return 'chunked' in transfer and 'html' in content_type and 'content-length' not in headers

        except (httpx.HTTPError, OSError, ValueError):
            return False  # probe failed — let the waterfall decide naturally

    async def _ensure_headless(self) -> HeadlessFetcher:
        """Start headless Chrome lazily on first need."""
        if self._headless is None:
            async with self._headless_lock:
                if self._headless is None:
                    self._console.print('[dim]  ↳ Starting headless Chrome...[/dim]')
                    headless = HeadlessFetcher(**self._chrome_kwargs)
                    await headless.__aenter__()
                    self._headless = headless
        return self._headless

    async def _ensure_headful(self) -> HeadfulFetcher:
        """Start headful Chrome lazily on first need."""
        if self._headful is None:
            async with self._headful_lock:
                if self._headful is None:
                    self._console.print('[dim]  ↳ Starting headful Chrome...[/dim]')
                    headful = HeadfulFetcher(**self._chrome_kwargs)
                    await headful.__aenter__()
                    self._headful = headful
        return self._headful

    # ------------------------------------------------------------------
    # Profile cascade (W2)
    # ------------------------------------------------------------------

    async def _start_identity_fetcher(
        self, identity: BrowserIdentity, base_kwargs: dict[str, Any]
    ) -> _VoidCrawlFetcher:
        """Factory: start one entered _VoidCrawlFetcher bound to *identity*.

        Each identity gets its OWN Chrome process (VoidCrawl's pool is
        single-identity). Headful identities run a small pool; the cascade
        serializes escalation so we never fan out N headful processes at once.
        """
        kwargs = dict(base_kwargs)
        kwargs['identity'] = identity
        if identity.headful:
            kwargs['max_concurrent'] = min(int(kwargs.get('max_concurrent', 5)), 6)
            fetcher: _VoidCrawlFetcher = HeadfulFetcher(**kwargs)
        else:
            fetcher = HeadlessFetcher(**kwargs)
        await fetcher.__aenter__()
        return fetcher

    def _ensure_identity_pool(self) -> IdentityFetcherPool:
        if self._identity_pool is None:
            self._identity_pool = IdentityFetcherPool(
                factory=self._start_identity_fetcher,
                base_kwargs=self._chrome_kwargs,
                max_live=self._max_live_identities,
            )
        return self._identity_pool

    async def _fetch_cascade(
        self,
        url: str,
        domain: str,
        start_time: float,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult:
        """Rotate browser identities on a block until one wins, else fail-fast.

        Drives the configured :class:`IdentityCascade` through the tenacity-based
        :func:`run_cascade`, preferring this domain's previously-winning identity
        first. On success the winning identity is persisted via
        ``_record_success`` so the next visit retries it directly. On cascade
        exhaustion the last :class:`BotDetectionError` propagates (fail-fast — no
        heuristic fallback).
        """
        assert self._identity_cascade is not None
        pool = self._ensure_identity_pool()
        cached = self._strategy_cache.get(domain)
        prefer = cached.identity_id if cached is not None else None

        async def do_fetch(fetcher: _VoidCrawlFetcher, ident: BrowserIdentity) -> FetchResult:
            self._console.print(f'[dim]    ↳ cascade identity [bold]{ident.id}[/bold] for {domain}[/dim]')
            return await fetcher._do_fetch(
                url,
                start_time,
                f'cascade:{ident.id}',
                action_scripts=action_scripts,
                download_specs=download_specs,
            )

        result, winner = await run_cascade(
            cascade=self._identity_cascade,
            pool=pool,
            do_fetch=do_fetch,
            prefer=prefer,
        )
        if result.html:
            await self._record_success(domain, 'headful', identity_id=winner.id)
            self._console.print(f'[success]    ✓ Cascade identity {winner.id} won for {domain}[/success]')
        return result

    # ------------------------------------------------------------------
    # Public fetch interface
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Public fetch interface
    # ------------------------------------------------------------------

    async def fetch(
        self,
        url: str,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult:
        """Fetch a page using the Simple → Headless → Headful waterfall.

        If a winning tier is cached for this domain it is used directly.
        When ``force=True`` the cache is ignored and the full waterfall runs.

        Args:
            url: The URL to fetch.
            action_scripts: Optional {field: js_expression} map evaluated after
                page load on L2 tiers. Ignored by the simple HTTP tier.
            download_specs: Optional {field: DownloadSpec} for ys.File() fields. Forces a
                browser tier (the simple HTTP tier can't download) and runs on the live tab.

        Returns:
            FetchResult with rendered HTML and metadata on success.

        """
        start_time = time.time()
        domain = extract_domain(url)
        cached_strategy = None if self._force else self._preferred_strategy(domain)

        if cached_strategy is not None:
            level_msg = f', selector level {cached_strategy.selector_level}' if cached_strategy.selector_level else ''
            self._console.print(
                f'[dim]  ↳ {domain} — using cached tier [bold]{cached_strategy.fetcher}[/bold]{level_msg}[/dim]'
            )
            cached_result = await self._fetch_cached_tier(
                url,
                domain,
                cached_strategy.fetcher,
                start_time,
                action_scripts=action_scripts,
                download_specs=download_specs,
            )
            if cached_result is not None:
                return cached_result

        return await self._fetch_waterfall(
            url, domain, start_time, action_scripts=action_scripts, download_specs=download_specs
        )

    async def _fetch_cached_tier(
        self,
        url: str,
        domain: str,
        cached_tier: str,
        start_time: float,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult | None:
        """Attempt fetch using the cached winning tier for this domain.

        Returns the result if the cached tier succeeded, or None if it
        failed/was gated (caller should fall through to the full waterfall).

        Args:
            url: The URL to fetch.
            domain: Extracted domain name.
            cached_tier: Previously cached tier name ('simple', 'headless', 'headful').
            start_time: Monotonic start time for fetch timing.
            action_scripts: Optional {field: js_expression} map forwarded to L2 tiers.
            download_specs: Optional ys.File() download specs forwarded to L2 tiers.

        Returns:
            FetchResult on success, or None if the cached tier should be bypassed.

        """
        if cached_tier == 'simple':
            if download_specs:
                # The simple HTTP tier has no browser tab — ys.File() needs one. Escalate.
                self._console.print(
                    f"[warning]  ✗ Cached simple tier can't download for {domain} — escalating to browser[/warning]"
                )
                return None
            try:
                if await self._probe_requires_js(url):
                    self._console.print(
                        f'[warning]  ✗ HEAD probe overrides cached simple tier for {domain} — escalating[/warning]'
                    )
                    return None
                result = await self._simple.fetch(url)
                if result.html and not result.requires_js:
                    return result
                self._console.print(
                    f'[warning]  ✗ Cached simple tier gated for {domain} — re-running waterfall[/warning]'
                )
            except BotDetectionError:
                self._console.print(
                    f'[warning]  ✗ Cached simple tier blocked for {domain} — re-running waterfall[/warning]'
                )
            return None

        if cached_tier == 'headless':
            try:
                headless = await self._ensure_headless()
                result = await self._fetch_browser_tier(
                    headless,
                    url,
                    start_time,
                    'headless',
                    action_scripts=action_scripts,
                    download_specs=download_specs,
                )
                if result.html:
                    return result
                self._console.print(f'[warning]  ✗ Cached headless tier failed for {domain} — trying headful[/warning]')
            except BotDetectionError:
                self._console.print(
                    f'[warning]  ✗ Cached headless tier blocked for {domain} — re-running waterfall[/warning]'
                )
            headful = await self._ensure_headful()
            result = await self._fetch_browser_tier(
                headful,
                url,
                start_time,
                'headful',
                action_scripts=action_scripts,
                download_specs=download_specs,
            )
            if result.html:
                await self._record_success(domain, 'headful')
            return result

        if cached_tier == 'headful':
            if self._identity_cascade is not None:
                # Cached identity is retried first inside the cascade; a block
                # rotates to the next identity rather than returning a challenge page.
                return await self._fetch_cascade(
                    url, domain, start_time, action_scripts=action_scripts, download_specs=download_specs
                )
            headful = await self._ensure_headful()
            return await self._fetch_browser_tier(
                headful,
                url,
                start_time,
                'headful',
                action_scripts=action_scripts,
                download_specs=download_specs,
            )

        return None

    async def _fetch_waterfall(
        self,
        url: str,
        domain: str,
        start_time: float,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult:
        """Run the full Simple → Headless → Headful waterfall for a new domain.

        Args:
            url: The URL to fetch.
            domain: Extracted domain name.
            start_time: Monotonic start time for fetch timing.
            action_scripts: Optional {field: js_expression} map forwarded to L2 tiers.
            download_specs: Optional ys.File() download specs forwarded to L2 tiers.

        Returns:
            FetchResult from whichever tier succeeded, or an empty result
            if all three tiers failed.

        """
        # ys.File() downloads need a browser tab — never settle on the simple HTTP tier.
        requires_js = bool(download_specs) or await self._probe_requires_js(url)

        if requires_js:
            self._console.print('[dim]    [1/3] HEAD probe detected JS-rendered page — skipping simple HTTP[/dim]')
        else:
            simple_result = await self._try_simple_tier(
                url,
                domain,
                action_scripts=action_scripts,
                download_specs=download_specs,
            )
            if simple_result is not None:
                return simple_result

        # Tier 2: Headless
        self._console.print('[dim]    [2/3] Trying headless Chrome...[/dim]')
        try:
            headless = await self._ensure_headless()
            result = await self._fetch_browser_tier(
                headless,
                url,
                start_time,
                'headless',
                action_scripts=action_scripts,
                download_specs=download_specs,
            )
            if result.html:
                self._console.print('[success]    ✓ Headless Chrome worked[/success]')
                await self._record_success(domain, 'headless')
                return result
            self._console.print(
                f'[warning]    ✗ Headless Chrome failed ({result.block_reason or "no content"})[/warning]'
            )
            if self._crawl_frontier_only and not action_scripts and not download_specs:
                return result
        except BotDetectionError:
            self._console.print('[warning]    ✗ Headless Chrome blocked by bot protection[/warning]')

        # Tier 3: Headful — or, when an identity cascade is configured, rotate
        # profiles/proxies on a block (W2) instead of best-effort single identity.
        if self._identity_cascade is not None:
            self._console.print('[dim]    [3/3] Escalating to profile cascade...[/dim]')
            return await self._fetch_cascade(
                url, domain, start_time, action_scripts=action_scripts, download_specs=download_specs
            )

        self._console.print('[dim]    [3/3] Trying headful Chrome...[/dim]')
        headful = await self._ensure_headful()
        result = await self._fetch_browser_tier(
            headful,
            url,
            start_time,
            'headful',
            action_scripts=action_scripts,
            download_specs=download_specs,
        )

        if result.html:
            self._console.print('[success]    ✓ Headful Chrome worked[/success]')
            await self._record_success(domain, 'headful')
        else:
            self._console.print(f'[warning]    ✗ All three tiers failed for {domain}[/warning]')

        return result

    async def _try_simple_tier(
        self,
        url: str,
        domain: str,
        *,
        action_scripts: dict[str, str] | None,
        download_specs: dict[str, DownloadSpec] | None,
    ) -> FetchResult | None:
        self._console.print('[dim]    [1/3] Trying simple HTTP...[/dim]')
        try:
            result = await self._simple.fetch(url)
        except BotDetectionError:
            self._console.print('[warning]    ✗ Simple fetcher blocked by bot protection[/warning]')
            return None

        if result.html and not result.requires_js:
            self._console.print('[success]    ✓ Simple fetcher worked[/success]')
            await self._record_success(domain, 'simple')
            return result

        if result.html and result.requires_js:
            framework = getattr(result.metadata, 'js_framework', None) if result.metadata is not None else None
            if self._accept_simple_requires_js and framework != 'bot-gate':
                self._console.print(
                    '[dim]    ↳ Simple fetcher returned JS-marked HTML; accepting partial static HTML[/dim]'
                )
                return result
            if self._accept_simple_js_marked_result(
                result,
                framework=framework,
                action_scripts=action_scripts,
                download_specs=download_specs,
            ):
                self._console.print(
                    '[dim]    ↳ Simple fetcher returned JS-marked HTML with crawl links; accepting frontier HTML[/dim]'
                )
                return result
            self._console.print('[warning]    ✗ Simple fetcher returned bot gate — JS required[/warning]')
        else:
            self._console.print(
                f'[warning]    ✗ Simple fetcher failed ({result.block_reason or "no content"})[/warning]'
            )
        return None

    def _accept_simple_js_marked_result(
        self,
        result: FetchResult,
        *,
        framework: str | None,
        action_scripts: dict[str, str] | None,
        download_specs: dict[str, DownloadSpec] | None,
    ) -> bool:
        return (
            self._crawl_frontier_only
            and not action_scripts
            and not download_specs
            and framework != 'bot-gate'
            and result.html is not None
            and _has_crawlable_links(result.html, base_url=result.url or '')
        )

    async def _fetch_browser_tier(
        self,
        fetcher: _VoidCrawlFetcher,
        url: str,
        start_time: float,
        tier: str,
        *,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult:
        """Run one browser tier, retrying transient tab/page timeouts.

        VoidCrawl owns tab pooling; this wrapper only handles a failed fetch result
        that already escaped the pool as a timeout-shaped page error. Downloads are
        not retried because a partial click/download may have side effects.
        """
        use_crawl_frontier = self._crawl_frontier_only and not action_scripts and not download_specs
        attempts = 1 if download_specs or use_crawl_frontier else 3
        result: FetchResult | None = None
        for attempt in range(1, attempts + 1):
            if use_crawl_frontier:
                result = await fetcher._do_fetch_crawl(url, start_time, tier)
            else:
                result = await fetcher._do_fetch(
                    url,
                    start_time,
                    tier,
                    action_scripts=action_scripts,
                    download_specs=download_specs,
                )
            if not _retryable_browser_timeout(result) or attempt == attempts:
                return result
            self._console.print(
                f'[warning]    ↻ {tier} page timeout for {url} — retrying ({attempt + 1}/{attempts})[/warning]'
            )
            await asyncio.sleep(min(4.0, 0.5 * attempt))
        assert result is not None
        return result


def _has_crawlable_links(html: str, *, base_url: str) -> bool:
    return LinkExtractor().has_crawlable_links(html, base_url=base_url, min_links=3, min_path_shapes=2)


def _retryable_browser_timeout(result: FetchResult) -> bool:
    """Return True when a browser-tier failed result looks like a transient tab timeout."""
    if result.html:
        return False
    reason = (result.block_reason or '').lower()
    return any(marker in reason for marker in ('request timed out', 'navigation failed', 'page error'))
