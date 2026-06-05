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

import logging
import time
from typing import TYPE_CHECKING, Any

import httpx
from rich.console import Console

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
        identity_cascade: IdentityCascade | None = None,
        max_live_identities: int = 3,
    ):
        """Initialise the three-tier JS fetcher.

        Args:
            timeout: Tab load + DOM stability timeout in seconds.
            rotate_user_agent: Forwarded to SimpleFetcher for interface compat.
            use_session: Forwarded to SimpleFetcher for interface compat.
            min_delay: Minimum pause between requests (seconds).
            max_delay: Maximum pause between requests (seconds).
            randomize_headers: Forwarded to SimpleFetcher for interface compat.
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
            identity_cascade: Optional :class:`IdentityCascade` of browser
                identities (profile/proxy combos). When set, a bot-block on the
                terminal headful tier escalates into a per-identity rotation
                (W2) instead of returning best-effort. ``None`` keeps the legacy
                single-identity 3-tier behaviour.
            max_live_identities: Cap on simultaneously-live identity fetchers
                (each is its own Chrome process); losers are LRU-closed.

        """
        self._simple = SimpleFetcher(
            timeout=timeout,
            rotate_user_agent=rotate_user_agent,
            use_session=use_session,
            min_delay=min_delay,
            max_delay=max_delay,
            randomize_headers=randomize_headers,
        )
        self._headless: HeadlessFetcher | None = None
        self._headful: HeadfulFetcher | None = None

        # In-memory cache populated from disk on __aenter__
        self._strategy_cache: dict[str, FetchStrategy] = {}
        self._strategy_storage = FetchStrategyStorage()

        self._console = console or Console()
        self.logger = logging.getLogger(__name__)
        self._force = force

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
        }

        # W2 — profile cascade. Built lazily on first block so a run with no
        # bot-walled domains never pays for it.
        self._identity_cascade = identity_cascade
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

        This makes ys.File() downloads work on ``fetcher_type='waterfall'`` (the download
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
        current = self._strategy_cache.get(domain)
        if current is None:
            return
        if current.selector_level == selector_level:
            return
        updated = FetchStrategy(fetcher=current.fetcher, selector_level=selector_level, identity_id=current.identity_id)
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
            content_type = headers.get('content-type', '')
            return 'chunked' in transfer and 'html' in content_type and 'content-length' not in headers

        except (httpx.HTTPError, OSError, ValueError):
            return False  # probe failed — let the waterfall decide naturally

    async def _ensure_headless(self) -> HeadlessFetcher:
        """Start headless Chrome lazily on first need."""
        if self._headless is None:
            self._console.print('[dim]  ↳ Starting headless Chrome...[/dim]')
            self._headless = HeadlessFetcher(**self._chrome_kwargs)
            await self._headless.__aenter__()
        return self._headless

    async def _ensure_headful(self) -> HeadfulFetcher:
        """Start headful Chrome lazily on first need."""
        if self._headful is None:
            self._console.print('[dim]  ↳ Starting headful Chrome...[/dim]')
            self._headful = HeadfulFetcher(**self._chrome_kwargs)
            await self._headful.__aenter__()
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
                result = await headless._do_fetch(
                    url, start_time, 'headless', action_scripts=action_scripts, download_specs=download_specs
                )
                if result.html:
                    return result
                self._console.print(f'[warning]  ✗ Cached headless tier failed for {domain} — trying headful[/warning]')
            except BotDetectionError:
                self._console.print(
                    f'[warning]  ✗ Cached headless tier blocked for {domain} — re-running waterfall[/warning]'
                )
            headful = await self._ensure_headful()
            result = await headful._do_fetch(
                url, start_time, 'headful', action_scripts=action_scripts, download_specs=download_specs
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
            return await headful._do_fetch(
                url, start_time, 'headful', action_scripts=action_scripts, download_specs=download_specs
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
            self._console.print('[dim]    [1/3] Trying simple HTTP...[/dim]')
            result: FetchResult | None = None
            try:
                result = await self._simple.fetch(url)
            except BotDetectionError:
                self._console.print('[warning]    ✗ Simple fetcher blocked by bot protection[/warning]')

            if result and result.html and not result.requires_js:
                self._console.print('[success]    ✓ Simple fetcher worked[/success]')
                await self._record_success(domain, 'simple')
                return result

            if result and result.html and result.requires_js:
                self._console.print('[warning]    ✗ Simple fetcher returned bot gate — JS required[/warning]')
            elif result:
                self._console.print(
                    f'[warning]    ✗ Simple fetcher failed ({result.block_reason or "no content"})[/warning]'
                )

        # Tier 2: Headless
        self._console.print('[dim]    [2/3] Trying headless Chrome...[/dim]')
        try:
            headless = await self._ensure_headless()
            result = await headless._do_fetch(
                url, start_time, 'headless', action_scripts=action_scripts, download_specs=download_specs
            )
            if result.html:
                self._console.print('[success]    ✓ Headless Chrome worked[/success]')
                await self._record_success(domain, 'headless')
                return result
            self._console.print(
                f'[warning]    ✗ Headless Chrome failed ({result.block_reason or "no content"})[/warning]'
            )
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
        result = await headful._do_fetch(
            url, start_time, 'headful', action_scripts=action_scripts, download_specs=download_specs
        )

        if result.html:
            self._console.print('[success]    ✓ Headful Chrome worked[/success]')
            await self._record_success(domain, 'headful')
        else:
            self._console.print(f'[warning]    ✗ All three tiers failed for {domain}[/warning]')

        return result
