"""Chrome-based fetchers using a persistent browser instance via voidcrawl.

A3Node replay
-------------
On each fetch the caller (_VoidCrawlFetcher) checks A3NodeStorage for a
stored scoped stability recipe. If one exists for the exact URL/intent/profile
scope, the acts are replayed in order before capturing HTML — skipping the full
probe phase entirely.

If replay produces less content than the stored recipe previously achieved
(or the recipe is empty / no acts needed), the result is accepted as-is.

After any full probe run (no stored node, or replay failed), the new acts
are saved via A3NodeStorage so the next visit skips the probe.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import random
import time
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import lxml.html
from rich.console import Console

from yosoi.core.fetcher.base import ContentAnalyzer, HTMLFetcher
from yosoi.core.fetcher.dom import DOMLoader
from yosoi.core.fetcher.dom.ax import AxSnapshot
from yosoi.core.fetcher.dom.probes import capture_ax_snapshot
from yosoi.core.fetcher.downloads import execute_downloads
from yosoi.core.fetcher.identity import BrowserIdentity
from yosoi.models.download import DownloadResult, DownloadSpec
from yosoi.models.replay import ReplayPlan
from yosoi.models.results import FetchResult, JsOutputs
from yosoi.storage.a3node import A3_FRAGMENT_BANK_KINDS, A3Fragment, A3Node, A3NodeScope, A3NodeStorage, ActRecord
from yosoi.utils import observability as obs
from yosoi.utils.exceptions import BotDetectionError, DownloadError
from yosoi.utils.retry import get_async_retryer, log_retry
from yosoi.utils.urls import extract_domain

logger = logging.getLogger(__name__)

# ── wait_for_js settle constants ───────────────────────────────────────────────
# Kind string written into A3Node acts when JS assert needed settle cycles.
_WAIT_FOR_JS_ACT = 'wait_for_js'
# Seconds between settle polls (also the unit stored in ActRecord.cycles).
_JS_POLL_INTERVAL_S: float = 0.5
# Maximum poll attempts before giving up and accepting whatever the DOM has.
_JS_MAX_SETTLE_CYCLES: int = 10
# Max random jitter injected before tab.goto() to stagger concurrent workers.
_JITTER_MAX_S: float = 1.5
_CRAWL_LINK_SETTLE_INTERVAL_S: float = 0.2
_CRAWL_LINK_SETTLE_CYCLES: int = 5


def _crawl_frontier_signature(html: str) -> tuple[frozenset[str], int]:
    try:
        root = lxml.html.fromstring(html)
    except (TypeError, ValueError):
        return (frozenset(), len(html))
    hrefs = frozenset(
        str(href).strip()
        for href in root.xpath('//a/@href')
        if isinstance(href, str) and str(href).strip() and not str(href).strip().startswith('#')
    )
    return (hrefs, len(html))


def _import_voidcrawl() -> tuple[Any, Any, Any]:
    # Chromium emits high-volume CDP notifications that older chromiumoxide builds
    # classify as invalid messages. They are ignored by the driver and should not
    # shred live crawl output when a Rust tracing subscriber is active.
    os.environ.setdefault('RUST_LOG', 'info,chromiumoxide::handler=error')
    try:
        from voidcrawl import BrowserConfig, BrowserPool, PoolConfig

        return BrowserPool, BrowserConfig, PoolConfig
    except ImportError as e:
        raise ImportError(
            'voidcrawl is required for browser-based fetching. '
            'Install it with: uv add voidcrawl\n'
            'Or build from source: https://github.com/CascadingLabs/VoidCrawl'
        ) from e


class _VoidCrawlFetcher(HTMLFetcher):
    _headless: bool

    def __init__(
        self,
        timeout: int = 30,
        max_concurrent: int = 5,
        min_content_length: int = 500,
        no_sandbox: bool = False,
        browser_executable_path: str | None = None,
        console: Console | None = None,
        experimental_a3node: bool = False,
        experimental_replay_plan: bool = False,
        allow_downloads: bool = False,
        download_dir: str | None = None,
        user_agent: str | None = None,
        accept_language: str | None = None,
        identity: BrowserIdentity | None = None,
        cross_origin_dom: bool = False,
        chrome_ws_urls: Sequence[str] = (),
        a3node_intent: str | None = None,
        lightweight_fetch: bool = False,
        **_kwargs: Any,
    ) -> None:
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.min_content_length = min_content_length
        self.no_sandbox = no_sandbox
        self.browser_executable_path = browser_executable_path
        self._console = console or Console()
        self._experimental_a3node = experimental_a3node
        self._experimental_replay_plan = experimental_replay_plan
        self._allow_downloads = allow_downloads
        self._download_dir = download_dir
        self._user_agent = user_agent
        self._accept_language = accept_language
        self._identity = identity
        self._cross_origin_dom = cross_origin_dom
        self._chrome_ws_urls = tuple(str(url).strip() for url in chrome_ws_urls if str(url).strip())
        self._a3node_intent = a3node_intent or 'fetch'
        self._lightweight_fetch = lightweight_fetch
        self._pool: Any = None
        self._pool_ctx: Any = None
        self._a3node_storage = A3NodeStorage() if experimental_a3node else None
        self._a3node_cache: dict[str, A3Node] = {}
        # Whether the installed VoidCrawl `goto` accepts `capture_endpoints` (CAS-169). Probed once
        # on first use and cached, so an older build degrades to a single plain goto (no double-nav).
        self._supports_endpoint_capture = True

    async def _goto_capture(self, tab: Any, url: str) -> Any:
        """``tab.goto`` requesting the data-plane endpoint set (CAS-169), back-compatibly.

        Returns the ``PageResponse`` (carrying ``headers``/``antibot``/``endpoints`` on a CAS-169
        build). Tolerates an older VoidCrawl whose ``goto`` lacks ``capture_endpoints``: the probe
        TypeErrors once, the flag is cleared, and every later call is a single plain goto.
        """
        if self._supports_endpoint_capture:
            try:
                return await tab.goto(url, timeout=float(self.timeout), capture_endpoints=True)
            except TypeError:
                self._supports_endpoint_capture = False
        return await tab.goto(url, timeout=float(self.timeout))

    async def __aenter__(self) -> _VoidCrawlFetcher:
        BrowserPool, BrowserConfig, PoolConfig = _import_voidcrawl()
        # CHROME_WS_URLS (voidcrawl's docker convention: comma-separated CDP URLs)
        # switches the pool from launching Chrome locally to attaching to the
        # already-running browsers, e.g. a VoidCrawl docker container.
        ws_urls = list(self._chrome_ws_urls) or [
            u.strip() for u in os.getenv('CHROME_WS_URLS', '').split(',') if u.strip()
        ]
        config = PoolConfig(
            browsers=1,
            tabs_per_browser=self.max_concurrent,
            tab_max_idle_secs=300,
            chrome_ws_urls=ws_urls,
            browser=BrowserConfig(**self._browser_config_kwargs(BrowserConfig)),
        )
        self._pool_ctx = BrowserPool(config)
        self._pool = await self._pool_ctx.__aenter__()
        if self._a3node_storage is not None:
            self._a3node_cache = await self._a3node_storage.load_all()
            self._console.print(f'[dim]  ↻ A3Node cache enabled ({len(self._a3node_cache)} recipes cached)[/dim]')
            logger.info('VoidCrawl fetcher ready (%d A3Nodes cached)', len(self._a3node_cache))
        else:
            self._console.print('[dim]  ↻ A3Node cache disabled — running DOMLoader fresh[/dim]')
            logger.info('VoidCrawl fetcher ready (A3Node disabled)')
        return self

    def _browser_config_kwargs(self, BrowserConfig: Any) -> dict[str, Any]:
        """Build BrowserConfig kwargs, only overriding UA / identity when requested.

        Identity passthrough (W2): when an identity is pinned, thread its proxy
        (egress IP), profile dir (raw ``--user-data-dir`` — VoidCrawl has no
        native ``user_data_dir`` field yet, so it goes through ``extra_args``,
        pool-wide for this fetcher's own single-identity pool), and
        locale/timezone. An identity may also force headful regardless of the
        class default (``HeadfulFetcher`` vs ``HeadlessFetcher``).
        """
        headless = self._headless
        if self._identity is not None and self._identity.headful:
            headless = False
        kwargs: dict[str, Any] = {
            'headless': headless,
            'stealth': True,
            'no_sandbox': self.no_sandbox,
            'chrome_executable': self.browser_executable_path,
        }
        fields = getattr(BrowserConfig, 'model_fields', None)
        if fields is None:
            fields = getattr(BrowserConfig, '__fields__', {})
        if self._user_agent is not None and 'user_agent' in fields:
            kwargs['user_agent'] = self._user_agent
        # accept_language / locale override (CLI knob) — identity.locale wins below.
        if self._accept_language is not None and 'locale' in fields:
            kwargs['locale'] = self._accept_language
        elif self._accept_language is not None and 'accept_language' in fields:
            kwargs['accept_language'] = self._accept_language

        if self._identity is not None:
            self._apply_identity_kwargs(kwargs, fields, self._identity)

        # Cross-origin DOM opt-in (ScrapePolicy.cross_origin_dom, VoidCrawl >= 0.3.5): disable
        # Chrome's site-isolation field trials so evaluate_js_in_frame reaches field-trial-
        # isolated origins. Weakens isolation for the whole pool — never set by default.
        if self._cross_origin_dom and 'extra_args' in fields:
            extra = list(kwargs.get('extra_args', []))
            extra.append('disable-site-isolation-trials')
            kwargs['extra_args'] = extra
        return kwargs

    @staticmethod
    def _apply_identity_kwargs(kwargs: dict[str, Any], fields: Any, ident: BrowserIdentity) -> None:
        """Thread a pinned identity's proxy/locale/timezone/geo/profile into BrowserConfig kwargs."""
        if ident.proxy is not None and 'proxy' in fields:
            kwargs['proxy'] = ident.proxy
        if ident.locale is not None and 'locale' in fields:
            kwargs['locale'] = ident.locale
        if ident.timezone_id is not None and 'timezone_id' in fields:
            kwargs['timezone_id'] = ident.timezone_id
        if ident.geo is not None and 'geolocation' in fields:
            # teleport-at-fetch: only when VoidCrawl's BrowserConfig exposes a geolocation
            # field. FUTURE: if it never does, apply ident.geo post-launch via the tab's
            # set_geolocation before the first navigate (Emulation.setGeolocationOverride).
            kwargs['geolocation'] = {'latitude': ident.geo[0], 'longitude': ident.geo[1]}
        if ident.profile_dir is not None and 'user_data_dir' in fields:
            kwargs['user_data_dir'] = ident.profile_dir
        elif ident.profile_dir is not None and 'extra_args' in fields:
            extra = list(kwargs.get('extra_args', []))
            extra.extend([f'--user-data-dir={ident.profile_dir}', '--profile-directory=Default'])
            kwargs['extra_args'] = extra

    async def _apply_identity_geo(self, tab: Any) -> None:
        """Teleport-at-fetch: spoof geolocation from the pinned identity BEFORE navigating.

        Complements the ``_browser_config_kwargs`` path (which only fires when VoidCrawl's
        ``BrowserConfig`` exposes a ``geolocation`` field). Setting it post-launch on the live
        tab via ``set_geolocation`` (Emulation.setGeolocationOverride) makes
        ``BrowserIdentity.geo`` take effect on EVERY build. Best-effort: a tab without
        ``set_geolocation`` skips it, and a spoof failure never fails the fetch.
        """
        ident = self._identity
        if ident is None or ident.geo is None or not hasattr(tab, 'set_geolocation'):
            return
        # geo spoof is best-effort; a failure must never fail the fetch
        with contextlib.suppress(Exception):
            await tab.set_geolocation(ident.geo[0], ident.geo[1])

    async def __aexit__(self, *exc: Any) -> None:
        if self._pool is not None:
            await self._pool_ctx.__aexit__(*exc)
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool_ctx.__aexit__(None, None, None)
            self._pool = None

    @property
    def supports_browse(self) -> bool:
        """Browser pool is available — JS discovery can open a live tab."""
        return True

    @asynccontextmanager
    async def browse(self, url: str) -> AsyncGenerator[Any, None]:
        """Open a browser tab, navigate to *url*, yield the live tab, then release.

        Intended for discovery workflows that need to run eval_js calls
        against the rendered DOM without capturing full HTML.
        """
        async with self._pool.acquire() as tab:
            # A cold tab from the pool can transiently time out on the first
            # navigation (slow Chrome cold-start, esp. in CI), surfacing as a
            # RuntimeError ("navigation failed: Request timed out"). Retry the
            # goto with backoff before failing — tenacity per AGENTS.md.
            async for attempt in get_async_retryer(
                max_attempts=3,
                wait_min=0.5,
                wait_max=4.0,
                exceptions=(RuntimeError,),
                log_callback=log_retry,
            ):
                with attempt:
                    await self._apply_identity_geo(tab)
                    await tab.goto(url, timeout=float(self.timeout))
            yield tab

    @staticmethod
    def _stable_short_hash(payload: object, *, prefix: str) -> str:
        """Return a compact stable fingerprint for A3Node scope components."""
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
        return f'{prefix}:{hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]}'

    def _a3node_browser_fingerprint(self, tier: str) -> str:
        """Fingerprint browser-tier/profile inputs that can affect rendered DOM shape."""
        ident = self._identity
        headless = bool(getattr(self, '_headless', tier == 'headless'))
        payload: dict[str, object] = {
            'tier': tier,
            'headless': headless,
            'identity_id': ident.id if ident is not None else '',
            'profile_dir_hash': self._stable_short_hash(ident.profile_dir, prefix='profile-dir')
            if ident is not None and ident.profile_dir
            else '',
            'profile_name': ident.profile_name if ident is not None and ident.profile_name else '',
            'headful': bool(ident.headful) if ident is not None else False,
            'locale': ident.locale if ident is not None else '',
            'timezone_id': ident.timezone_id if ident is not None else '',
            'geo_hash': self._stable_short_hash(ident.geo, prefix='geo') if ident is not None and ident.geo else '',
            'proxy_hash': self._stable_short_hash(ident.proxy, prefix='proxy')
            if ident is not None and ident.proxy
            else '',
            'user_agent_hash': self._stable_short_hash(self._user_agent, prefix='ua') if self._user_agent else '',
            'accept_language': self._accept_language or '',
        }
        return self._stable_short_hash(payload, prefix='browser')

    def _a3node_scope_intent(
        self,
        action_scripts: dict[str, str] | None,
        download_specs: dict[str, DownloadSpec] | None,
    ) -> str:
        """Fingerprint the contract/replay/action/download intent for A3Node replay."""
        payload: dict[str, object] = {
            'base': self._a3node_intent,
            'action_fields': sorted(action_scripts) if action_scripts else [],
            'action_scripts_hash': self._stable_short_hash(action_scripts, prefix='actions') if action_scripts else '',
            'download_fields': sorted(download_specs) if download_specs else [],
            'download_specs_hash': self._stable_short_hash(download_specs, prefix='downloads')
            if download_specs
            else '',
        }
        return self._stable_short_hash(payload, prefix='intent')

    def _a3node_scope(
        self,
        url: str,
        domain: str,
        tier: str,
        action_scripts: dict[str, str] | None,
        download_specs: dict[str, DownloadSpec] | None,
    ) -> A3NodeScope:
        """Build the exact A3Node scope for this fetch attempt."""
        return A3NodeScope.for_url(
            url,
            domain=domain,
            intent=self._a3node_scope_intent(action_scripts, download_specs),
            browser_fingerprint=self._a3node_browser_fingerprint(tier),
        )

    async def fetch(
        self,
        url: str,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult:
        start = time.time()
        tier = 'headless' if self._headless else 'headful'
        if self._lightweight_fetch and not action_scripts and not download_specs:
            return await self._do_fetch_crawl(url, start, tier)
        return await self._do_fetch(url, start, tier, action_scripts=action_scripts, download_specs=download_specs)

    async def fetch_with_plan(
        self,
        plan: ReplayPlan,
        params: dict[str, str] | None = None,
    ) -> FetchResult:
        """Drive a learned ReplayPlan over a pooled tab via the deterministic runtime.

        This is the hotpath wiring: instead of ``goto`` + eval'd JS strings, a
        discovered :class:`~yosoi.models.replay.ReplayPlan` is replayed through
        :func:`yosoi.core.replay.runtime.execute_plan` against a live
        :class:`PooledTab`. ``params`` (e.g. ``{'d': domain}``) parametrize the
        plan's ``url``/``text`` fields at dispatch time — one engine program
        replayed across N targets, LLM-free.

        Gated by ``experimental_replay_plan``: callers must opt in, mirroring the
        ``experimental_a3node`` flag. The plan's EVAL ``output_field`` captures land
        in ``FetchResult.js_outputs``; the final DOM is captured as ``html``. A
        fail-fast :class:`ReplayExecutionError` (missing param, antibot challenge,
        failed assertion) propagates — the runtime never returns garbage.
        """
        from yosoi.core.replay.runtime import execute_plan

        if not self._experimental_replay_plan:
            raise RuntimeError('replay-plan fetch is disabled; pass experimental_replay_plan=True to enable it')
        start_time = time.time()
        plan_url = next((node.act.url for node in plan.nodes if node.act.url), '') or ''
        async with self._pool.acquire() as tab:
            jitter = random.uniform(0, _JITTER_MAX_S)
            if jitter > 0.05:
                await asyncio.sleep(jitter)
            result = await execute_plan(tab, plan, params=params)
            html: str | None = None
            try:
                html = await tab.content()
            except (RuntimeError, OSError, ValueError) as exc:
                logger.debug('replay-plan content capture failed: %s', exc)

        js_outputs: JsOutputs | None = result.extracted_actions or None
        if not html or len(html) < self.min_content_length:
            return FetchResult(
                url=plan_url,
                html=html,
                status_code=None,
                is_blocked=False,
                block_reason=f'Content too short ({len(html or "")} chars)',
                fetch_time=time.time() - start_time,
                js_outputs=js_outputs,
            )
        metadata = ContentAnalyzer.analyze(html)
        return FetchResult(
            url=plan_url,
            html=html,
            status_code=200,
            is_blocked=False,
            fetch_time=time.time() - start_time,
            metadata=metadata,
            js_outputs=js_outputs,
        )

    async def _do_fetch_crawl(self, url: str, start_time: float, _tier: str) -> FetchResult:
        """Lightweight rendered fetch for crawl frontier discovery.

        Crawl only needs the post-navigation DOM for links/canonical/fingerprint.
        It should not pay scrape-grade DOMLoader/A3Node/action/download/AX costs
        for every URL in the frontier.
        """
        resp_headers: dict[str, str] | None = None
        resp_endpoints: list[str] | None = None
        captcha_kind: str | None = None
        async with self._pool.acquire() as tab:
            jitter = random.uniform(0, _JITTER_MAX_S)
            if jitter > 0.05:
                await asyncio.sleep(jitter)
            await self._apply_identity_geo(tab)
            async for attempt in get_async_retryer(
                max_attempts=1,
                wait_min=0.5,
                wait_max=4.0,
                exceptions=(RuntimeError,),
                log_callback=log_retry,
            ):
                with attempt:
                    page_resp = await self._goto_capture(tab, url)
            resp_headers = getattr(page_resp, 'headers', None) or None
            resp_endpoints = getattr(page_resp, 'endpoints', None) or None
            html = await self._crawl_frontier_content(tab)
            captcha_kind = await self._probe_captcha(tab)

        if not html or len(html) < self.min_content_length:
            return FetchResult(
                url=url,
                html=None,
                status_code=None,
                is_blocked=False,
                block_reason=f'Content too short ({len(html or "")} chars)',
                fetch_time=time.time() - start_time,
                headers=resp_headers,
                endpoints=resp_endpoints,
            )

        is_blocked, indicators = self._check_for_bot_detection(html, 200, {})
        if is_blocked:
            raise BotDetectionError(
                url,
                200,
                indicators,
                identity_id=self._identity.id if self._identity is not None else None,
                captcha_kind=captcha_kind,
            )

        return FetchResult(
            url=url,
            html=html,
            status_code=200,
            is_blocked=False,
            fetch_time=time.time() - start_time,
            metadata=ContentAnalyzer.analyze(html),
            headers=resp_headers,
            endpoints=resp_endpoints,
        )

    async def _crawl_frontier_content(self, tab: Any) -> str:
        """Capture rendered HTML after a short link-inventory settle window."""
        html = str(await tab.content())
        signature = _crawl_frontier_signature(html)
        for _ in range(_CRAWL_LINK_SETTLE_CYCLES):
            await asyncio.sleep(_CRAWL_LINK_SETTLE_INTERVAL_S)
            candidate = str(await tab.content())
            next_signature = _crawl_frontier_signature(candidate)
            if next_signature == signature:
                return candidate
            html = candidate
            signature = next_signature
        return html

    async def _do_fetch(
        self,
        url: str,
        start_time: float,
        _tier: str,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult:
        domain = extract_domain(url)
        scope = self._a3node_scope(url, domain, _tier, action_scripts, download_specs)
        stored_node = (
            self._a3node_cache.get(scope.scope_key) or self._a3node_cache.get(domain)
            if self._experimental_a3node
            else None
        )

        js_outputs: JsOutputs | None = None
        downloads: dict[str, DownloadResult] | None = None
        ax_snapshot: AxSnapshot | None = None
        # Navigation-time signals from the goto PageResponse (CAS-169). Read defensively so an
        # older VoidCrawl build (no headers/endpoints on PageResponse) simply leaves them None.
        resp_headers: dict[str, str] | None = None
        resp_endpoints: list[str] | None = None
        # Block-attribution (W2): probe the live tab for a named captcha BEFORE it
        # releases, so a BotDetectionError raised after the block can carry it.
        # This is a DIFFERENT signal from the html-marker heuristic below — it may
        # be None on a soft (200 + marker) block. Recorded distinctly; never
        # conflated. Captured inside the acquire() block because the DOM probe
        # needs a live tab/Page (a PooledTab may not even bind detect_captcha).
        captcha_kind: str | None = None
        async with self._pool.acquire() as tab:
            # Jitter: stagger concurrent workers so they don't land simultaneously
            # on the same origin and trigger bot-detection rate limiting.
            jitter = random.uniform(0, _JITTER_MAX_S)
            if jitter > 0.05:
                await asyncio.sleep(jitter)

            await self._apply_identity_geo(tab)
            # Capture the goto PageResponse instead of discarding it — its headers/endpoints feed
            # the waterfall fingerprint's L3 layers (the former blind spot).
            async for attempt in get_async_retryer(
                max_attempts=3,
                wait_min=0.5,
                wait_max=4.0,
                exceptions=(RuntimeError,),
                log_callback=log_retry,
            ):
                with attempt:
                    page_resp = await self._goto_capture(tab, url)
            resp_headers = getattr(page_resp, 'headers', None) or None
            resp_endpoints = getattr(page_resp, 'endpoints', None) or None

            if stored_node is not None:
                html = await self._fetch_with_replay(tab, scope, stored_node)
            else:
                if not self._experimental_a3node:
                    obs.annotate_a3node(obs.current_span(), mode=obs.A3_MODE_DISABLED)
                else:
                    obs.annotate_a3node(obs.current_span(), mode=obs.A3_MODE_PROBE)
                html = await self._fetch_with_probe(tab, scope)

            if action_scripts:
                js_outputs, wait_cycles = await self._eval_with_settle(tab, action_scripts)
                if wait_cycles > 0:
                    # JS assert needed settle time — the DOM loaded target content
                    # asynchronously after probe/replay captured HTML.  Re-capture
                    # now that the condition holds so the HTML includes the content.
                    try:
                        settled_html = await tab.content()
                        if settled_html and len(settled_html) >= self.min_content_length:
                            html = settled_html
                    except (RuntimeError, OSError, ValueError) as exc:
                        logger.debug('settle re-capture failed: %s', exc)

                    # Amend A3Node: record the settle cycles so replay skips
                    # the probe and just waits settle_seconds before content().
                    if self._a3node_storage is not None and self._experimental_a3node:
                        await self._amend_a3node_settle(scope, wait_cycles)

            # ys.File() downloads — run on the live tab (a download needs the open
            # browser context). Gated by the allow_downloads opt-in.
            downloads = await self._run_downloads(tab, download_specs, domain)

            # Capture the rendered AX tree (browser tier) as a semantic perception
            # layer for static discovery. Best-effort: None when the tab lacks CDP.
            ax_snapshot = await capture_ax_snapshot(tab)

            # Capture the captcha signal while the tab is still live. Best-effort:
            # detect_captcha is a Page method and may not be bound on a PooledTab,
            # so probe defensively — absence yields None (its own attribution
            # bucket), it is NOT treated as "no block".
            captcha_kind = await self._probe_captcha(tab)

        if not html or len(html) < self.min_content_length:
            return FetchResult(
                url=url,
                html=None,
                status_code=None,
                is_blocked=False,
                block_reason=f'Content too short ({len(html or "")} chars)',
                fetch_time=time.time() - start_time,
                js_outputs=js_outputs,
                downloads=downloads,
            )

        is_blocked, indicators = self._check_for_bot_detection(html, 200, {})
        if is_blocked:
            raise BotDetectionError(
                url,
                200,
                indicators,
                identity_id=self._identity.id if self._identity is not None else None,
                captcha_kind=captcha_kind,
            )

        metadata = ContentAnalyzer.analyze(html)
        return FetchResult(
            url=url,
            html=html,
            status_code=200,
            is_blocked=False,
            fetch_time=time.time() - start_time,
            metadata=metadata,
            js_outputs=js_outputs,
            downloads=downloads,
            ax_snapshot=ax_snapshot,
            headers=resp_headers,
            endpoints=resp_endpoints,
        )

    async def _probe_captcha(self, tab: Any) -> str | None:
        """Best-effort live-tab captcha probe for block attribution (W2).

        ``Page.detect_captcha`` returns the captcha kind or None. It is a Page
        method and may not be bound on a PooledTab; older VoidCrawl builds may
        lack it entirely. Either way we return None rather than failing the
        fetch — None is a valid attribution value (soft block with no named
        captcha), distinct from the html-marker heuristic.
        """
        probe = getattr(tab, 'detect_captcha', None)
        if probe is None:
            return None
        try:
            result = await probe()
        except Exception as exc:  # noqa: BLE001 — attribution is best-effort
            logger.debug('detect_captcha probe failed: %s', exc)
            return None
        return result if isinstance(result, str) else None

    async def _run_downloads(
        self,
        tab: Any,
        download_specs: dict[str, DownloadSpec] | None,
        domain: str,
    ) -> dict[str, DownloadResult] | None:
        """Execute ys.File() download specs on the live tab (defense-in-depth gate)."""
        if not download_specs:
            return None
        if not self._allow_downloads:
            raise DownloadError(
                next(iter(download_specs)),
                'downloads are disabled; pass allow_downloads=True to enable ys.File() fields',
            )
        return await execute_downloads(tab, download_specs, domain, base_dir=self._download_dir)

    @staticmethod
    def _compose_action_scripts(scripts: dict[str, str]) -> str:
        """Compose multiple JS scripts into one dict-returning expression.

        Each sub-script is wrapped in try/catch so a single failure does not
        discard all outputs — the failed field gets ``null`` instead.
        Field names are JSON-encoded so quotes and special characters are safe.
        """
        import json

        entries = '; '.join(
            f'try {{ out[{json.dumps(k)}] = (()=>{{ return ({v}); }})(); }} catch(e) {{ out[{json.dumps(k)}] = null; }}'
            for k, v in scripts.items()
        )
        return f'(()=>{{ const out={{}}; {entries}; return out; }})()'

    async def _eval_with_settle(
        self,
        tab: Any,
        scripts: dict[str, str],
    ) -> tuple[JsOutputs, int]:
        """Evaluate action scripts, polling until all fields return non-null.

        The assert pattern: run JS → if any field is null, wait
        ``_JS_POLL_INTERVAL_S`` and retry, up to ``_JS_MAX_SETTLE_CYCLES`` times.
        Returns the outputs and the number of extra cycles waited (0 = first
        eval succeeded, no settle needed).
        """
        for cycle in range(_JS_MAX_SETTLE_CYCLES):
            outputs = await self._eval_action_scripts(tab, scripts)
            if all(v is not None for v in outputs.values()):
                return outputs, cycle
            if cycle < _JS_MAX_SETTLE_CYCLES - 1:
                await asyncio.sleep(_JS_POLL_INTERVAL_S)
        # Final attempt — accept whatever the DOM has now
        outputs = await self._eval_action_scripts(tab, scripts)
        return outputs, _JS_MAX_SETTLE_CYCLES

    async def _amend_a3node_settle(self, scope: A3NodeScope | str, wait_cycles: int) -> None:
        """Append or update the wait_for_js act in the scoped A3Node recipe."""
        if self._a3node_storage is None:
            return
        cache_key = scope.scope_key if isinstance(scope, A3NodeScope) else scope
        display = scope.domain if isinstance(scope, A3NodeScope) else scope
        node = self._a3node_cache.get(cache_key)
        existing = list(node.acts) if node else []
        # Replace any previous wait_for_js with the fresh measurement
        domloader_only = [a for a in existing if a.kind != _WAIT_FOR_JS_ACT]
        amended = [*domloader_only, ActRecord(kind=_WAIT_FOR_JS_ACT, cycles=wait_cycles)]
        await self._a3node_storage.save(scope, amended)
        loaded = await self._a3node_storage.load(scope)
        if loaded is not None:
            self._a3node_cache[cache_key] = loaded
        settle_s = wait_cycles * _JS_POLL_INTERVAL_S
        self._console.print(
            f'[success]  ✓ A3Node settle recorded for {display}: '
            f'{wait_cycles} cycle(s) × {_JS_POLL_INTERVAL_S:.1f}s = {settle_s:.1f}s[/success]'
        )

    async def _eval_action_scripts(self, tab: Any, scripts: dict[str, str]) -> JsOutputs:
        composite = self._compose_action_scripts(scripts)
        try:
            result = await tab.eval_js(composite)
            if isinstance(result, dict):
                return result
            logger.warning('action_scripts eval returned non-dict: %r', result)
            return {}
        except Exception as exc:  # noqa: BLE001
            logger.warning('action_scripts eval failed: %s', exc)
            return {}

    async def _fetch_with_replay(self, tab: Any, scope: A3NodeScope | str, node: A3Node) -> str | None:
        """Replay a stored A3Node recipe, falling back to a full probe on failure.

        Empty recipe → the page needed no actions, so just capture the current
        HTML. Non-empty recipe → re-execute the stored acts directly via
        ``DOMLoader.replay`` (no behavior-tree search, no LLM). Either way, a
        successful replay records the replay so ``replay_count``/``battle_tested``
        advance; an insufficient result re-probes and re-saves the fresh recipe.
        """
        display = scope.domain if isinstance(scope, A3NodeScope) else scope
        if self._a3node_storage is None:
            obs.annotate_a3node(obs.current_span(), mode=obs.A3_MODE_DISABLED)
            return await self._fetch_with_probe(tab, scope)

        settle_s = node.settle_seconds
        dl_acts = node.domloader_acts
        span = obs.current_span()
        # Shared replay-mode metadata; success/fallback exits add replayed/fell_back.
        replay_attrs: obs.A3ReplayAttrs = {
            'mode': obs.A3_MODE_REPLAY,
            'acts': len(dl_acts),
            'replay_count': node.replay_count,
            'settle_seconds': settle_s,
        }

        if node.is_empty:
            settle_label = f', settle={settle_s:.1f}s' if settle_s else ''
            self._console.print(f'[dim]  ↻ A3Node replay: {display} needs no DOMLoader actions{settle_label}[/dim]')
            try:
                if settle_s > 0:
                    await asyncio.sleep(settle_s)
                html: str = await tab.content()
                if html and len(html) >= self.min_content_length:
                    await self._a3node_storage.record_replay(scope)
                    obs.annotate_a3node(span, replayed=True, **replay_attrs)
                    return html
            except (RuntimeError, OSError, ValueError) as exc:
                logger.debug('A3Node empty-recipe content capture failed: %s', exc)
        else:
            self._console.print(
                f'[dim]  ↻ A3Node replay: {display} ({len(dl_acts)} act(s), replayed {node.replay_count}×)[/dim]'
            )
            result = await DOMLoader(console=self._console).replay(tab, dl_acts)
            if result.success:
                if settle_s > 0:
                    await asyncio.sleep(settle_s)
                    # Re-capture after settle — DOMLoader html may predate the async load
                    try:
                        settled: str = await tab.content()
                        html_candidate = settled if settled and len(settled) >= self.min_content_length else result.html
                    except (RuntimeError, OSError, ValueError):
                        html_candidate = result.html
                else:
                    html_candidate = result.html
                if html_candidate and len(html_candidate) >= self.min_content_length:
                    await self._a3node_storage.record_replay(scope)
                    obs.annotate_a3node(span, replayed=True, **replay_attrs)
                    return html_candidate

        self._console.print(f'[warning]  ✗ A3Node replay fell short for {display} — re-probing[/warning]')
        obs.annotate_a3node(span, fell_back=True, **replay_attrs)
        return await self._fetch_with_probe(tab, scope)

    async def _fetch_with_probe(self, tab: object, scope: A3NodeScope | str) -> str | None:
        """Run fragment-bank replay, then full DOMLoader probe, and persist the scoped recipe."""
        loader = DOMLoader(console=self._console)
        fragments = await self._load_a3_fragments(limit=8)
        fragment_acts: list[ActRecord] = []
        if fragments:
            fragment_result = await loader.replay_fragments(tab, fragments)
            fragment_acts = fragment_result.acts
            await self._record_fragment_replays(fragments, fragment_acts)

        probe_result = await loader.run(tab)
        html = probe_result.html
        acts = [*fragment_acts, *probe_result.acts]

        # Persist the acts regardless of content length — even "no action needed"
        # is a valid and useful recipe to store. Also mint domain-free fragments from
        # concrete targets so later scopes can try the same A3 action with the LLM off.
        if self._a3node_storage is not None and probe_result.success:
            await self._a3node_storage.save(scope, acts)
            await self._save_a3_fragments_from_acts(scope, acts)
            # Update in-memory cache
            node = await self._a3node_storage.load(scope)
            if node is not None:
                cache_key = scope.scope_key if isinstance(scope, A3NodeScope) else scope
                display = scope.domain if isinstance(scope, A3NodeScope) else scope
                self._a3node_cache[cache_key] = node
                verb = 'stored (no actions needed)' if node.is_empty else f'stored ({len(node.acts)} acts)'
                self._console.print(f'[success]  ✓ A3Node {verb} for {display}[/success]')

        return html

    async def _load_a3_fragments(self, *, limit: int) -> list[A3Fragment]:
        """Load reusable A3 fragments, tolerating older/mocked storage objects."""
        import inspect

        if self._a3node_storage is None:
            return []
        load_fragments = getattr(self._a3node_storage, 'load_fragments', None)
        if not callable(load_fragments):
            return []
        maybe_fragments = load_fragments(kinds=set(A3_FRAGMENT_BANK_KINDS), limit=limit)
        loaded = await maybe_fragments if inspect.isawaitable(maybe_fragments) else maybe_fragments
        return loaded if isinstance(loaded, list) else []

    async def _record_fragment_replays(self, fragments: list[A3Fragment], acts: list[ActRecord]) -> None:
        """Update fragment replay stats for successfully applied acts."""
        import inspect

        if self._a3node_storage is None:
            return
        record_fragment_replay = getattr(self._a3node_storage, 'record_fragment_replay', None)
        if not callable(record_fragment_replay):
            return
        for act in acts:
            for fragment in fragments:
                if fragment.kind == act.kind and fragment.target == act.target:
                    maybe_recorded = record_fragment_replay(fragment.fragment_key)
                    if inspect.isawaitable(maybe_recorded):
                        await maybe_recorded
                    break

    async def _save_a3_fragments_from_acts(self, scope: A3NodeScope | str, acts: list[ActRecord]) -> None:
        """Mint reusable fragments when storage supports the fragment bank."""
        import inspect

        if self._a3node_storage is None:
            return
        save_fragments = getattr(self._a3node_storage, 'save_fragments_from_acts', None)
        if not callable(save_fragments):
            return
        maybe_saved = save_fragments(scope, acts)
        if inspect.isawaitable(maybe_saved):
            await maybe_saved


class HeadlessFetcher(_VoidCrawlFetcher):
    """Chrome fetcher running in headless mode (no visible window)."""

    _headless = True


class HeadfulFetcher(_VoidCrawlFetcher):
    """Chrome fetcher running in headful mode (visible window, best bot evasion)."""

    _headless = False
