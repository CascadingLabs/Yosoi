"""Main pipeline for selector discovery.

Spine only: ``__init__``, ``scrape``, ``process_url``, ``process_urls``, and the
concurrent processing methods. Behavior is delegated to focused mixin modules:

* ``pipeline_cache.py``      — cached selector replay
* ``pipeline_extraction.py`` — fetch / clean / extract / downloads
* ``pipeline_discovery.py``  — AI selector discovery, MCP escalation, JS actions
* ``pipeline_crawler.py``    — frontier / crawl helpers (CAS-52)
* ``pipeline_utils.py``      — stateless helpers, display methods
"""

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import ExitStack, nullcontext
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from rich.console import Console
from rich.live import Live
from rich.theme import Theme

# Re-export for backwards-compat (imported by cli/progress.py and tests)
from yosoi.core._pipeline_table import _build_concurrent_table
from yosoi.core.configs import YosoiConfig
from yosoi.core.discovery import DiscoveryOrchestrator, LLMConfig, MCPDiscoveryOrchestrator
from yosoi.core.discovery.bus import DiscoveryBus
from yosoi.core.fetcher import create_fetcher  # re-exported: tests patch yosoi.core.pipeline.create_fetcher
from yosoi.core.pipeline_cache import PipelineCacheMixin
from yosoi.core.pipeline_crawler import PipelineCrawlerMixin
from yosoi.core.pipeline_discovery import PipelineDiscoveryMixin
from yosoi.core.pipeline_extraction import PipelineExtractionMixin
from yosoi.core.pipeline_utils import PipelineUtilsMixin
from yosoi.core.verification import SelectorVerifier, SemanticValidator, field_rules_for_contract
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.storage import DebugManager, LLMTracker, SelectorStorage
from yosoi.storage.discovery_strategy import DiscoveryStrategyStorage
from yosoi.storage.js_scripts import JsScriptStorage
from yosoi.types.filetypes import normalize_allowed_types
from yosoi.utils import observability
from yosoi.utils.signatures import contract_signature

# Type aliases
SelectorMap = dict[str, dict[str, Any]]
ContentMap = dict[str, str | list[str | dict[str, str]]]
ContentItems = list[ContentMap]

logger = logging.getLogger(__name__)


class Pipeline(
    PipelineCacheMixin,
    PipelineExtractionMixin,
    PipelineDiscoveryMixin,
    PipelineCrawlerMixin,
    PipelineUtilsMixin,
):
    """Main pipeline for discovering and saving CSS selectors with retry logic.

    Fetches HTML, cleans it, runs LLM-based selector discovery, then verifies
    and stores the selectors. Behavior is split across focused mixin modules; the
    public API (``scrape``, ``process_url``, ``process_urls``) lives here.
    """

    _allow_downloads: bool = False
    _allowed_download_types: tuple[str, ...] = ()
    _download_dir: str | None = None
    _max_download_bytes: int | None = None
    _keep_downloads: bool = True

    def __init__(
        self,
        llm_config: LLMConfig | YosoiConfig | str,
        contract: type[Contract],
        debug_mode: bool = False,
        output_format: str | list[str] = 'json',
        force: bool = False,
        quiet: bool = False,
        selector_level: SelectorLevel = SelectorLevel.CSS,
        bus: DiscoveryBus | None = None,
        write_lock: asyncio.Lock | None = None,
        experimental_a3node: bool = False,
        allow_downloads: bool = False,
        allowed_download_types: tuple[str, ...] = (),
        download_dir: str | None = None,
        max_download_bytes: int | None = None,
        keep_downloads: bool = True,
    ):
        """Initialize the pipeline with LLM configuration.

        See full parameter documentation in the original pipeline.py docstring.
        """
        self.selector_level = selector_level
        self._experimental_a3node = experimental_a3node
        self._allow_downloads = allow_downloads
        self._allowed_download_types = normalize_allowed_types(allowed_download_types)
        self._download_dir = download_dir
        self._max_download_bytes = max_download_bytes
        self._keep_downloads = keep_downloads
        self._download_log: list[Any] = []

        if isinstance(llm_config, str):
            from yosoi.core.discovery.config import provider

            llm_config = provider(llm_config)

        self._llm_config: LLMConfig | YosoiConfig = llm_config

        max_concurrent_discovery: int = 5
        replay_verify_threshold: float = 1.0

        if isinstance(llm_config, YosoiConfig):
            yosoi_cfg = llm_config
            llm_config = yosoi_cfg.llm
            debug_mode = yosoi_cfg.debug.save_html
            force = yosoi_cfg.force
            max_concurrent_discovery = yosoi_cfg.discovery.max_concurrent
            replay_verify_threshold = yosoi_cfg.discovery.replay_verify_threshold
            observability.configure(yosoi_cfg.telemetry)
        else:
            from yosoi.core.configs import TelemetryConfig

            observability.configure(
                TelemetryConfig(
                    langfuse_public_key=os.getenv('LANGFUSE_PUBLIC_KEY'),
                    langfuse_secret_key=os.getenv('LANGFUSE_SECRET_KEY'),
                    langfuse_host=os.getenv('LANGFUSE_BASE_URL') or os.getenv('LANGFUSE_HOST'),
                )
            )

        self.custom_theme = Theme(
            {
                'info': 'dim cyan',
                'warning': 'magenta',
                'danger': 'bold red',
                'success': 'bold green',
                'step': 'bold blue',
            }
        )
        self.contract = contract
        self._contract_sig = contract_signature(contract)
        self.console = Console(theme=self.custom_theme, quiet=quiet)
        from yosoi.core.cleaning import HTMLCleaner

        self.cleaner = HTMLCleaner(console=self.console)
        self.storage = SelectorStorage()
        self.js_storage = JsScriptStorage()

        self.discovery = DiscoveryOrchestrator(
            contract=self.contract,
            llm_config=llm_config,
            storage=self.storage,
            console=self.console,
            target_level=self.selector_level,
            max_concurrent=max_concurrent_discovery,
            bus=bus,
            write_lock=write_lock,
        )
        self._mcp_discovery: MCPDiscoveryOrchestrator | None = None
        self._mcp_llm_config: LLMConfig = llm_config
        self._replay_verify_threshold: float = replay_verify_threshold
        self._force_mcp: bool = os.getenv('YOSOI_DISCOVERY_MODE') == 'mcp'
        self._discovery_strategy = DiscoveryStrategyStorage()
        self._js_discovery_orchestrator: Any = None
        self.verifier = SelectorVerifier(console=self.console)
        self.semantic_validator = SemanticValidator()
        self._field_rules = field_rules_for_contract(self.contract)
        from yosoi.core.extraction import ContentExtractor

        self.extractor = ContentExtractor(console=self.console, contract=self.contract)
        self.tracker = LLMTracker()
        self.debug_mode = debug_mode
        self.debug = DebugManager(console=self.console, enabled=debug_mode)
        self.output_formats: list[str] = [output_format] if isinstance(output_format, str) else list(output_format)
        self.force = force
        self.logger = logging.getLogger(__name__)
        self._url_start: float = 0.0
        self.last_elapsed: float = 0.0
        self._last_level_distribution: dict[str, int] = {}
        self._client: httpx.AsyncClient = httpx.AsyncClient()

        self.session_id: str = observability.process_session_id()

        has_file_handler = any(isinstance(h, logging.FileHandler) for h in logging.getLogger().handlers)
        if not has_file_handler:
            from yosoi.utils.files import init_yosoi, is_initialized
            from yosoi.utils.logging import setup_local_logging

            if not is_initialized():
                init_yosoi()
            log_file = setup_local_logging()
            self.console.print(f'ℹ Log file: [link=file://{log_file}]file://{log_file}[/link]')

    async def __aenter__(self) -> 'Pipeline':
        """Enter the async context manager, returning self."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Exit the async context manager, closing the HTTP client + finalizing downloads."""
        await self._client.aclose()
        self._finalize_downloads()

    def _create_fetcher(self, fetcher_type: str, console: Console | None = None) -> Any | None:
        """Create HTML fetcher instance.

        Defined on Pipeline (not the utils mixin) so that
        ``mocker.patch('yosoi.core.pipeline.create_fetcher')`` intercepts calls here.
        """
        try:
            kwargs: dict[str, Any] = {}
            if fetcher_type in ('waterfall', 'headless', 'headful'):
                if console is not None:
                    kwargs['console'] = console
                kwargs['experimental_a3node'] = self._experimental_a3node
                kwargs['allow_downloads'] = self._allow_downloads
                kwargs['download_dir'] = self._download_dir
            return create_fetcher(fetcher_type, **kwargs)
        except ValueError:
            self.console.print(f'[danger]Invalid fetcher type: {fetcher_type}[/danger]')
            return None

    async def process_url(
        self,
        url: str,
        force: bool | None = None,
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
        skip_verification: bool = False,
        fetcher_type: str = 'simple',
        output_format: str | list[str] | None = None,
        fetcher: Any | None = None,
    ) -> None:
        """Process a single URL: discover, verify, and save selectors."""
        async for _ in self.scrape(
            url,
            force=force,
            max_fetch_retries=max_fetch_retries,
            max_discovery_retries=max_discovery_retries,
            skip_verification=skip_verification,
            fetcher_type=fetcher_type,
            output_format=output_format,
            fetcher=fetcher,
        ):
            pass

    async def process_urls(
        self,
        urls: list[str],
        force: bool | None = None,
        skip_verification: bool = False,
        fetcher_type: str = 'simple',
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
        output_format: str | list[str] | None = None,
        workers: int = 1,
        on_complete: Callable[[str, bool, float], Awaitable[None]] | None = None,
        on_start: Callable[[str], Awaitable[None]] | None = None,
        origin: Literal['cli', 'script'] = 'script',
    ) -> dict[str, list[str]]:
        """Process multiple URLs and collect results."""
        _raw = output_format if output_format is not None else self.output_formats
        format_to_use: list[str] = [_raw] if isinstance(_raw, str) else list(_raw)
        force_flag = self.force if force is None else force
        sess_id = observability.process_session_id()
        effective_workers = min(workers, len(urls))

        with observability.session(sess_id, tags=['yosoi', origin]):
            if effective_workers > 1:
                if not self.console.quiet and on_start is None and on_complete is None:
                    return await self._process_urls_with_live(
                        urls,
                        force=force_flag,
                        skip_verification=skip_verification,
                        fetcher_type=fetcher_type,
                        max_fetch_retries=max_fetch_retries,
                        max_discovery_retries=max_discovery_retries,
                        output_format=format_to_use,
                        effective_workers=effective_workers,
                        sess_id=sess_id,
                        origin=origin,
                    )
                return await self._process_urls_concurrent(
                    urls,
                    force=force_flag,
                    skip_verification=skip_verification,
                    fetcher_type=fetcher_type,
                    max_fetch_retries=max_fetch_retries,
                    max_discovery_retries=max_discovery_retries,
                    output_format=format_to_use,
                    max_workers=effective_workers,
                    on_complete=on_complete,
                    on_start=on_start,
                    sess_id=sess_id,
                    origin=origin,
                )

            results: dict[str, list[str]] = {'successful': [], 'failed': []}
            run_start = time.monotonic()
            shared_fetcher = self._create_fetcher(fetcher_type, console=self.console)
            if not shared_fetcher:
                raise RuntimeError(f'Invalid fetcher type: {fetcher_type}')

            async with shared_fetcher:
                for idx, url in enumerate(urls, 1):
                    self.console.print(f'\n[bold blue]Processing URL {idx}/{len(urls)}[/bold blue]')
                    self.logger.info('--- Processing URL %d/%d: %s ---', idx, len(urls), url)
                    url_start = time.monotonic()
                    try:
                        await self.process_url(
                            url,
                            force_flag,
                            max_fetch_retries=max_fetch_retries,
                            max_discovery_retries=max_discovery_retries,
                            skip_verification=skip_verification,
                            fetcher_type=fetcher_type,
                            output_format=format_to_use,
                            fetcher=shared_fetcher,
                        )
                        results['successful'].append(url)
                        if on_complete is not None:
                            await on_complete(url, True, time.monotonic() - url_start)
                    except Exception as e:
                        observability.warning('Error processing URL', url=url, error=str(e))
                        self.logger.exception('Critical error processing %s', url)
                        self.console.print(f'[danger]Error processing {url}: {e}[/danger]')
                        results['failed'].append(url)
                        if on_complete is not None:
                            await on_complete(url, False, time.monotonic() - url_start)
                    self.console.print()

            total_elapsed = time.monotonic() - run_start
            self._print_summary(results, total_elapsed)
            self.logger.info(
                'Processing complete total=%d successful=%d failed=%d',
                len(urls),
                len(results['successful']),
                len(results['failed']),
            )

        observability.flush()
        return results

    async def scrape(
        self,
        url: str,
        force: bool | None = None,
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
        skip_verification: bool = False,
        fetcher_type: str = 'simple',
        output_format: str | list[str] | None = None,
        fetcher: Any | None = None,
    ) -> AsyncIterator[ContentMap]:
        """Async generator yielding individual content items from a URL."""
        self._url_start = time.monotonic()
        _raw = output_format if output_format is not None else self.output_formats
        format_to_use: list[str] = [_raw] if isinstance(_raw, str) else list(_raw)
        force_flag = self.force if force is None else force
        url = await self.normalize_url(url)
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
                        'name': self.contract.__name__,
                        'fields': self.contract.field_descriptions(),
                        'overrides': self.contract.get_selector_overrides(),
                        'discovery_field_names': sorted(self.contract.discovery_field_names()),
                    },
                },
            )
            self.logger.info('Processing URL: %s (force=%s, fetcher=%s)', url, force_flag, fetcher_type)
            domain = self._extract_domain(url)

            _owns_fetcher = fetcher is None
            if _owns_fetcher:
                fetcher = self._create_fetcher(fetcher_type, console=self.console)
                if not fetcher:
                    raise RuntimeError(f'Invalid fetcher type: {fetcher_type}')

            if fetcher is None:
                raise RuntimeError('No fetcher available')
            ctx = fetcher if _owns_fetcher else nullcontext(fetcher)

            async with ctx:
                if not force_flag:
                    cache_gen = await self._try_cached(
                        url, domain, fetcher, skip_verification, format_to_use, root_span=root_span
                    )
                    if cache_gen is not None:
                        async for item in cache_gen:
                            yield item
                        return

                async for item in self._scrape_fresh(
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

    async def _scrape_fresh(
        self,
        url: str,
        domain: str,
        fetcher: Any,
        force_flag: bool,
        max_fetch_retries: int,
        max_discovery_retries: int,
        skip_verification: bool,
        format_to_use: list[str],
        root_span: Any | None,
    ) -> AsyncIterator[ContentMap]:
        """Fresh discovery path — fetch, clean, discover, verify, extract, save."""
        observability.annotate_cache(root_span, path=observability.CACHE_FRESH)

        await self._discover_js_actions(url, domain, fetcher)
        js_scripts = await self._resolve_js_scripts(domain)
        download_specs = self._resolve_download_specs(fetcher)

        with observability.span('fetch', url=url, max_retries=max_fetch_retries):
            result = await self._fetch(
                url,
                fetcher,
                max_retries=max_fetch_retries,
                action_scripts=js_scripts or None,
                download_specs=download_specs,
            )
            if not result:
                raise RuntimeError(f'Failed to fetch {url}')
            assert result.html is not None

        with observability.span('clean', url=url, raw_chars=len(result.html)):
            cleaned_html = await self._clean(url, result)
            if not cleaned_html:
                raise RuntimeError(f'HTML cleaning failed for {url}')

        cached_mode = None if force_flag else await self._discovery_strategy.load(domain, self._contract_sig)
        escalate_first = self._force_mcp or cached_mode == 'mcp'

        with observability.span(
            'discover', url=url, cleaned_chars=len(cleaned_html), mode='mcp' if escalate_first else 'static'
        ):
            if escalate_first:
                selectors, used_llm = await self._discover_via_mcp(url, cleaned_html, force=force_flag)
            else:
                selectors, used_llm = await self._discover(
                    url,
                    cleaned_html,
                    max_retries=max_discovery_retries,
                    force=force_flag,
                    ax_snapshot=result.ax_snapshot,
                )
            if not selectors:
                raise RuntimeError(f'Selector discovery failed for {url}')

        root_entry = self._resolve_root(selectors)
        container_selector = self._root_value(root_entry)

        with observability.span('verify', url=url, skip=skip_verification, fields=len(selectors)):
            verified = self._verify(url, cleaned_html, selectors, skip_verification)
            if not verified:
                raise RuntimeError(f'Selector verification failed for {url}')

        with observability.span('extract', url=url, container=container_selector or 'single'):
            extracted = self._extract(url, result.html, verified, container_selector)
            extracted = self._merge_fetch_outputs(extracted, result)
            self._record_downloads(result.downloads)

        if extracted:
            with observability.span('semantic_refine', url=url):
                extracted, verified = await self._semantic_refine(
                    url,
                    cleaned_html,
                    result.html,
                    verified,
                    container_selector,
                    extracted,
                    max_discovery_retries,
                )

        if not escalate_first:
            extracted, verified, root_entry, container_selector, escalated = await self._maybe_escalate(
                url, domain, cleaned_html, result.html, verified, container_selector, root_entry, extracted
            )
            used_llm = used_llm or escalated

        selectors_to_save = self._selectors_with_root(verified, root_entry)

        if not extracted:
            self.console.print('[warning]⚠ Extraction failed, but selectors are valid[/warning]')
            await self._finish(url, domain, selectors_to_save, None, used_llm, format_to_use)
            observability.set_trace_output(
                root_span,
                {
                    'path': 'fresh-no-extract',
                    'selectors': selectors_to_save,
                    'extracted_count': 0,
                    'extracted_sample': None,
                },
            )
            return

        with observability.span('validate', url=url, items=len(extracted) if isinstance(extracted, list) else 1):
            validated_items = self._validate_items(extracted, url)

        for vi in validated_items:
            yield vi

        save_all: ContentMap | ContentItems = validated_items if len(validated_items) > 1 else validated_items[0]
        with observability.span('save', url=url, items=len(validated_items)):
            await self._finish(url, domain, selectors_to_save, save_all, used_llm, format_to_use)
        await self._record_fetch_strategy_selector_level(fetcher, domain)

        observability.set_trace_output(
            root_span,
            {
                'path': 'fresh',
                'selectors': selectors_to_save,
                'extracted_count': len(validated_items),
                'extracted_sample': validated_items[0] if validated_items else None,
            },
        )

    # ── Concurrent processing ────────────────────────────────────────────────

    async def _process_urls_with_live(
        self,
        urls: list[str],
        force: bool,
        skip_verification: bool,
        fetcher_type: str,
        max_fetch_retries: int,
        max_discovery_retries: int,
        output_format: list[str],
        effective_workers: int,
        sess_id: str | None = None,
        origin: Literal['cli', 'script'] = 'script',
    ) -> dict[str, list[str]]:
        """Run concurrent processing wrapped in a Rich Live progress table."""
        url_status: dict[str, tuple[str, float]] = dict.fromkeys(urls, ('Queued', 0.0))
        live = Live(_build_concurrent_table(url_status), console=self.console, refresh_per_second=4)

        async def _on_start(url: str) -> None:
            url_status[url] = ('Running', time.monotonic())
            live.update(_build_concurrent_table(url_status))

        async def _on_complete(url: str, success: bool, elapsed: float) -> None:
            url_status[url] = ('Done' if success else 'Failed', elapsed)
            live.update(_build_concurrent_table(url_status))

        with live:
            return await self._process_urls_concurrent(
                urls,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=fetcher_type,
                max_fetch_retries=max_fetch_retries,
                max_discovery_retries=max_discovery_retries,
                output_format=output_format,
                max_workers=effective_workers,
                on_complete=_on_complete,
                on_start=_on_start,
                sess_id=sess_id,
                origin=origin,
            )

    async def _process_urls_concurrent(
        self,
        urls: list[str],
        force: bool,
        skip_verification: bool,
        fetcher_type: str,
        max_fetch_retries: int,
        max_discovery_retries: int,
        output_format: list[str],
        max_workers: int,
        sess_id: str | None = None,
        origin: Literal['cli', 'script'] = 'script',
        on_complete: Callable[[str, bool, float], Awaitable[None]] | None = None,
        on_start: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, list[str]]:
        """Process URLs concurrently via the taskiq broker."""
        from yosoi.core.tasks import configure_broker, enqueue_urls, shutdown_broker

        if isinstance(sess_id, str):
            os.environ['YOSOI_SESSION_ID'] = sess_id

        with observability.detached_span('enqueue', count=len(urls), workers=max_workers, origin=origin):
            await configure_broker(
                self._llm_config,
                contract=self.contract,
                output_format=output_format,
                max_workers=max_workers,
                selector_level=self.selector_level,
                experimental_a3node=getattr(self, '_experimental_a3node', False),
            )

            run_start = time.monotonic()
            try:
                enqueue_result = await enqueue_urls(
                    urls,
                    force=force,
                    skip_verification=skip_verification,
                    fetcher_type=fetcher_type,
                    max_fetch_retries=max_fetch_retries,
                    max_discovery_retries=max_discovery_retries,
                    on_complete=on_complete,
                    on_start=on_start,
                    sess_id=sess_id,
                    origin=origin,
                )
            finally:
                await shutdown_broker()

        total_elapsed = time.monotonic() - run_start
        results: dict[str, list[str]] = {
            'successful': enqueue_result.successful,
            'failed': enqueue_result.failed,
            'skipped': enqueue_result.skipped,
        }
        self._print_summary(results, total_elapsed)
        self.logger.info(
            'Concurrent processing complete total=%d successful=%d failed=%d skipped=%d workers=%d',
            len(urls),
            len(results['successful']),
            len(results['failed']),
            len(results['skipped']),
            max_workers,
        )
        observability.flush()
        return results
