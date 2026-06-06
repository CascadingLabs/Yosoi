"""Chrome-based fetchers using a persistent browser instance via voidcrawl.

A3Node replay
-------------
On each fetch the caller (_VoidCrawlFetcher) checks A3NodeStorage for a
stored stability recipe. If one exists, the acts are replayed in order
before capturing HTML — skipping the full probe phase entirely.

If replay produces less content than the stored recipe previously achieved
(or the recipe is empty / no acts needed), the result is accepted as-is.

After any full probe run (no stored node, or replay failed), the new acts
are saved via A3NodeStorage so the next visit skips the probe.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

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
from yosoi.storage.a3node import A3Node, A3NodeStorage, ActRecord
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


def _import_voidcrawl() -> tuple[Any, Any, Any]:
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
        config = PoolConfig(
            browsers=1,
            tabs_per_browser=self.max_concurrent,
            tab_max_idle_secs=300,
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

        ident = self._identity
        if ident is not None:
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
            if ident.profile_dir is not None and 'extra_args' in fields:
                extra = list(kwargs.get('extra_args', []))
                extra.extend([f'--user-data-dir={ident.profile_dir}', '--profile-directory=Default'])
                kwargs['extra_args'] = extra
        return kwargs

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

    async def fetch(
        self,
        url: str,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult:
        start = time.time()
        return await self._do_fetch(url, start, 'fetch', action_scripts=action_scripts, download_specs=download_specs)

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

    async def _do_fetch(
        self,
        url: str,
        start_time: float,
        _tier: str,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult:
        domain = extract_domain(url)
        stored_node = self._a3node_cache.get(domain) if self._experimental_a3node else None

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
            page_resp = await self._goto_capture(tab, url)
            resp_headers = getattr(page_resp, 'headers', None) or None
            resp_endpoints = getattr(page_resp, 'endpoints', None) or None

            if stored_node is not None:
                html = await self._fetch_with_replay(tab, domain, stored_node)
            else:
                if not self._experimental_a3node:
                    obs.annotate_a3node(obs.current_span(), mode=obs.A3_MODE_DISABLED)
                else:
                    obs.annotate_a3node(obs.current_span(), mode=obs.A3_MODE_PROBE)
                html = await self._fetch_with_probe(tab, domain)

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
                        await self._amend_a3node_settle(domain, wait_cycles)

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

    async def _amend_a3node_settle(self, domain: str, wait_cycles: int) -> None:
        """Append or update the wait_for_js act in the domain's A3Node recipe."""
        if self._a3node_storage is None:
            return
        node = self._a3node_cache.get(domain)
        existing = list(node.acts) if node else []
        # Replace any previous wait_for_js with the fresh measurement
        domloader_only = [a for a in existing if a.kind != _WAIT_FOR_JS_ACT]
        amended = [*domloader_only, ActRecord(kind=_WAIT_FOR_JS_ACT, cycles=wait_cycles)]
        await self._a3node_storage.save(domain, amended)
        loaded = await self._a3node_storage.load(domain)
        if loaded is not None:
            self._a3node_cache[domain] = loaded
        settle_s = wait_cycles * _JS_POLL_INTERVAL_S
        self._console.print(
            f'[success]  ✓ A3Node settle recorded for {domain}: '
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

    async def _fetch_with_replay(self, tab: Any, domain: str, node: A3Node) -> str | None:
        """Replay a stored A3Node recipe, falling back to a full probe on failure.

        Empty recipe → the page needed no actions, so just capture the current
        HTML. Non-empty recipe → re-execute the stored acts directly via
        ``DOMLoader.replay`` (no behavior-tree search, no LLM). Either way, a
        successful replay records the replay so ``replay_count``/``battle_tested``
        advance; an insufficient result re-probes and re-saves the fresh recipe.
        """
        if self._a3node_storage is None:
            obs.annotate_a3node(obs.current_span(), mode=obs.A3_MODE_DISABLED)
            return await self._fetch_with_probe(tab, domain)

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
            self._console.print(f'[dim]  ↻ A3Node replay: {domain} needs no DOMLoader actions{settle_label}[/dim]')
            try:
                if settle_s > 0:
                    await asyncio.sleep(settle_s)
                html: str = await tab.content()
                if html and len(html) >= self.min_content_length:
                    await self._a3node_storage.record_replay(domain)
                    obs.annotate_a3node(span, replayed=True, **replay_attrs)
                    return html
            except (RuntimeError, OSError, ValueError) as exc:
                logger.debug('A3Node empty-recipe content capture failed: %s', exc)
        else:
            self._console.print(
                f'[dim]  ↻ A3Node replay: {domain} ({len(dl_acts)} act(s), replayed {node.replay_count}×)[/dim]'
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
                    await self._a3node_storage.record_replay(domain)
                    obs.annotate_a3node(span, replayed=True, **replay_attrs)
                    return html_candidate

        self._console.print(f'[warning]  ✗ A3Node replay fell short for {domain} — re-probing[/warning]')
        obs.annotate_a3node(span, fell_back=True, **replay_attrs)
        return await self._fetch_with_probe(tab, domain)

    async def _fetch_with_probe(self, tab: object, domain: str) -> str | None:
        """Run the full DOMLoader probe and persist the resulting recipe."""
        probe_result = await DOMLoader(console=self._console).run(tab)
        html = probe_result.html

        # Persist the acts regardless of content length — even "no action needed"
        # is a valid and useful recipe to store
        if self._a3node_storage is not None and probe_result.success:
            await self._a3node_storage.save(domain, probe_result.acts)
            # Update in-memory cache
            node = await self._a3node_storage.load(domain)
            if node is not None:
                self._a3node_cache[domain] = node
                verb = 'stored (no actions needed)' if node.is_empty else f'stored ({len(node.acts)} acts)'
                self._console.print(f'[success]  ✓ A3Node {verb} for {domain}[/success]')

        return html


class HeadlessFetcher(_VoidCrawlFetcher):
    """Chrome fetcher running in headless mode (no visible window)."""

    _headless = True


class HeadfulFetcher(_VoidCrawlFetcher):
    """Chrome fetcher running in headful mode (visible window, best bot evasion)."""

    _headless = False
