"""Main pipeline for selector discovery.

Centralized retry logic for bot detection and AI failures.
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
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from tenacity import RetryCallState, RetryError

from yosoi.core.cleaning import HTMLCleaner
from yosoi.core.configs import YosoiConfig
from yosoi.core.discovery import DiscoveryOrchestrator, LLMConfig
from yosoi.core.discovery.bus import DiscoveryBus
from yosoi.core.extraction import ContentExtractor
from yosoi.core.fetcher import HTMLFetcher, create_fetcher
from yosoi.core.fetcher.waterfall import JSFetcher
from yosoi.core.verification import (
    FieldSemanticIssue,
    SelectorVerifier,
    SemanticValidator,
    field_rules_for_contract,
)
from yosoi.models import FetchResult
from yosoi.models.contract import Contract
from yosoi.models.results import VerificationResult
from yosoi.models.selectors import SelectorLevel
from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot, snapshot_to_selector_dict
from yosoi.prompts.discovery import FieldFeedback
from yosoi.storage import DebugManager, LLMTracker, SelectorStorage
from yosoi.storage.tracking import DomainStats
from yosoi.utils import observability
from yosoi.utils.exceptions import BotDetectionError
from yosoi.utils.retry import get_async_retryer
from yosoi.utils.signatures import contract_signature

# Selector dict: field name → {primary, fallback, tertiary} selectors
# Values may be plain strings, SelectorEntry dicts, or None depending on source
SelectorMap = dict[str, dict[str, Any]]
# Extracted content: field name → extracted value(s)
ContentMap = dict[str, str | list[str | dict[str, str]]]
# Multi-item extraction: list of ContentMap dicts
ContentItems = list[ContentMap]

_STATUS_STYLES: dict[str, tuple[str, bool]] = {
    'Queued': ('dim', False),
    'Running': ('bold yellow', True),
    'Done': ('bold green', False),
    'Skipped': ('dim', False),
    'Failed': ('bold red', False),
}


def _build_concurrent_table(url_status: dict[str, tuple[str, float]]) -> Table:
    """Build a Rich Table showing per-URL concurrent progress."""
    table = Table(title='Concurrent Processing', expand=True)
    table.add_column('#', style='dim', width=4)
    table.add_column('URL', style='cyan', ratio=3)
    table.add_column('Status', width=12)
    table.add_column('Elapsed', style='dim', width=10)
    for idx, (u, (status, value)) in enumerate(url_status.items(), 1):
        style, is_running = _STATUS_STYLES.get(status, ('bold red', False))
        elapsed_str = f'{time.monotonic() - value:.1f}s' if is_running else (f'{value:.1f}s' if value else '—')
        table.add_row(str(idx), u, f'[{style}]{status}[/{style}]', elapsed_str)
    return table


class Pipeline:
    """Main pipeline for discovering and saving CSS selectors with retry logic.

    Fetches HTML, cleans it, runs LLM-based selector discovery, then verifies
    and stores the selectors.

    Attributes:
        custom_theme: Rich theme for console output
        console: Rich console instance for formatted output
        cleaner: Python class to clean and extract main content from HTML
        discovery: Python class to use LLM to find selectors from cleaned HTML
        verifier: Python class to check the selectors if they are real
        extractor: Python class to extract content using verified selectors
        storage: Store the found selectors as a JSON file
        tracker: Used to track how much an LLM is used in comparison to amount of urls used
        debug_mode: If enabled will output the HTML from the URL
        logger: Logger instance for detailed run tracking

    """

    def __init__(
        self,
        llm_config: LLMConfig | YosoiConfig | str,
        contract: type[Contract],
        debug_mode: bool = False,
        output_format: str | list[str] = 'json',
        force: bool = False,
        quiet: bool = False,
        selector_level: SelectorLevel = SelectorLevel.CSS,
        discovery_mode: Literal['static', 'mcp'] | None = None,
        bus: DiscoveryBus | None = None,
        write_lock: asyncio.Lock | None = None,
    ):
        """Initialize the pipeline with LLM configuration.

        Args:
            llm_config: LLMConfig, YosoiConfig, or a model string
                (e.g. ``'groq:llama-3.3-70b-versatile'``). Strings are
                auto-resolved via :func:`yosoi.core.discovery.config.provider`.
            debug_mode: If enabled will output the HTML from the URL.
                        Overridden by YosoiConfig.debug.save_html when YosoiConfig is passed.
            output_format: Format for extracted content ('json' or 'markdown'). Defaults to 'json'.
            contract: Contract subclass defining the fields to scrape.
            force: Force re-discovery even if selectors are cached. Overridden by
                   YosoiConfig.force when YosoiConfig is passed. Defaults to False.
            quiet: Suppress console output. Used in concurrent mode where a
                   progress display replaces per-task output. Defaults to False.
            selector_level: Maximum selector strategy level for discovery and extraction.
                            Defaults to CSS.
            discovery_mode: Selector discovery path. ``'static'`` uses the
                            existing cleaned-HTML fan-out. ``'mcp'`` is reserved
                            for the MCP lesson path and currently fails fast.
            bus: Optional shared discovery bus for cross-pipeline field deduplication.
            write_lock: Optional asyncio.Lock to serialize selector writes for the domain.

        """
        self.selector_level = selector_level
        resolved_discovery_mode = discovery_mode or os.getenv('YOSOI_DISCOVERY_MODE') or 'static'

        # Auto-resolve model strings → LLMConfig
        if isinstance(llm_config, str):
            from yosoi.core.discovery.config import provider

            llm_config = provider(llm_config)

        # Keep the original config for concurrent mode (taskiq broker needs it)
        self._llm_config: LLMConfig | YosoiConfig = llm_config

        # Default discovery fan-out — overridden below when YosoiConfig is passed.
        max_concurrent_discovery: int = 5

        if isinstance(llm_config, YosoiConfig):
            yosoi_cfg = llm_config
            llm_config = yosoi_cfg.llm
            debug_mode = yosoi_cfg.debug.save_html
            force = yosoi_cfg.force
            max_concurrent_discovery = yosoi_cfg.discovery.max_concurrent
            resolved_discovery_mode = discovery_mode or os.getenv('YOSOI_DISCOVERY_MODE') or yosoi_cfg.discovery.mode
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
        if resolved_discovery_mode not in {'static', 'mcp'}:
            raise ValueError("discovery_mode must be 'static' or 'mcp'")
        self.discovery_mode: Literal['static', 'mcp'] = resolved_discovery_mode  # type: ignore[assignment]
        if self.discovery_mode == 'mcp':
            raise NotImplementedError(
                'MCP discovery mode is configured but not wired yet. '
                "Use discovery_mode='static' while the CAS-79 MCP lesson path is being implemented."
            )
        self.console = Console(theme=self.custom_theme, quiet=quiet)
        self.cleaner = HTMLCleaner(console=self.console)
        self.storage = SelectorStorage()
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
        self.verifier = SelectorVerifier(console=self.console)
        self.semantic_validator = SemanticValidator()
        self._field_rules = field_rules_for_contract(self.contract)
        self.extractor = ContentExtractor(console=self.console, contract=self.contract)
        self.tracker = LLMTracker()
        self.debug_mode = debug_mode
        self.debug = DebugManager(console=self.console, enabled=debug_mode)
        self.output_formats: list[str] = [output_format] if isinstance(output_format, str) else list(output_format)
        self.force = force
        self.logger = logging.getLogger(__name__)
        self._url_start: float = 0.0
        self.last_elapsed: float = 0.0
        self._client: httpx.AsyncClient = httpx.AsyncClient()

        # Process-scoped Langfuse session — every Pipeline in this CLI/script
        # invocation shares the same id, so each pipeline call shows up as a
        # separate trace under one session.
        self.session_id: str = observability.process_session_id()

        # Auto-initialize .yosoi dir and file logging when used outside the CLI
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
        """Exit the async context manager, closing the HTTP client."""
        await self._client.aclose()

    async def process_url(
        self,
        url: str,
        force: bool | None = None,
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
        skip_verification: bool = False,
        fetcher_type: str = 'simple',
        output_format: str | list[str] | None = None,
        fetcher: HTMLFetcher | None = None,
    ) -> None:
        """Process a single URL: discover, verify, and save selectors.

        Thin wrapper around :meth:`scrape` that drains the generator.
        Raises on failure — callers are responsible for error handling.

        Args:
            url: URL to process
            force: Force re-discovery even if selectors exist. Defaults to False.
            skip_verification: Skip verification step. Defaults to False.
            fetcher_type: Type of fetcher ('simple', 'waterfall', etc.). Defaults to 'simple'.
            max_fetch_retries: Maximum fetch retry attempts. Defaults to 2.
            max_discovery_retries: Maximum AI discovery retry attempts. Defaults to 3.
            output_format: Format(s) for extracted content. Defaults to None (uses pipeline default).
            fetcher: Optional pre-existing fetcher instance. When provided the fetcher
                is not closed after this call — the caller owns its lifecycle.

        """
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
        """Process multiple URLs and collect results.

        When ``workers`` > 1 and there are multiple URLs, processing runs
        concurrently via the taskiq broker.  Otherwise URLs are processed
        sequentially.

        Args:
            urls: List of URLs to process.
            force: Force re-discovery even if selectors exist. Defaults to False.
            skip_verification: Skip verification step. Defaults to False.
            fetcher_type: Type of fetcher ('simple', 'waterfall', etc.). Defaults to 'simple'.
            max_fetch_retries: Maximum fetch retry attempts. Defaults to 2.
            max_discovery_retries: Maximum AI discovery retry attempts. Defaults to 3.
            output_format: Format(s) for extracted content. Defaults to None (uses pipeline default).
            workers: Number of concurrent workers. Defaults to 1 (sequential).
            on_complete: Optional async callback ``(url, success, elapsed)`` called
                after each URL finishes. Used by the CLI for live progress display.
            on_start: Optional async callback ``(url)`` called just before each
                URL begins processing.
            origin: ``'cli'`` when invoked from the ``yosoi`` CLI, ``'script'`` for
                Python-API callers (the default). Used as a Langfuse session tag so
                the UI can split CLI runs from scripted pipelines.

        Returns:
            Dictionary with keys:
                - 'successful': List of successfully processed URLs
                - 'failed': List of URLs that failed processing
                - 'skipped': List of URLs skipped (concurrent only)

        """
        # Normalise to list, fall back to pipeline default
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
        """Run concurrent processing wrapped in a Rich Live progress table.

        Called automatically from process_urls() when workers > 1,
        the pipeline is not quiet, and no external callbacks are provided.
        """
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
        """Process URLs concurrently via the taskiq broker.

        Both the CLI and scripted paths use this method. The optional
        ``on_complete`` and ``on_start`` callbacks let callers (e.g.
        CLI Live display) react to task lifecycle events.

        """
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

    def _print_summary(self, results: dict[str, list[str]], total_elapsed: float) -> None:
        """Print a standardised summary of processing results."""
        self.console.print(
            f'\n[bold]Results:[/bold] [green]{len(results["successful"])} succeeded[/green], '
            f'[red]{len(results["failed"])} failed[/red] '
            f'[dim]({total_elapsed:.1f}s total)[/dim]'
        )
        if results.get('skipped'):
            self.console.print(f'  [dim]{len(results["skipped"])} skipped[/dim]')
        if results['failed']:
            self.console.print('[bold red]Failed URLs:[/bold red]')
            for url in results['failed']:
                self.console.print(f'  [red]- {url}[/red]')

    async def scrape(
        self,
        url: str,
        force: bool | None = None,
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
        skip_verification: bool = False,
        fetcher_type: str = 'simple',
        output_format: str | list[str] | None = None,
        fetcher: HTMLFetcher | None = None,
    ) -> AsyncIterator[ContentMap]:
        """Async generator yielding individual content items from a URL.

        Canonical entry point — handles both cached-selector replay and fresh
        AI discovery.  For multi-item pages (catalogs, listings), yields one
        ``ContentMap`` per matched container element.  For single-item pages,
        yields exactly one ``ContentMap``.

        Args:
            url: URL to process
            force: Force re-discovery even if selectors exist. Defaults to
                the pipeline-level ``force`` flag.
            max_fetch_retries: Maximum fetch retry attempts. Defaults to 2.
            max_discovery_retries: Maximum AI discovery retry attempts. Defaults to 3.
            skip_verification: Skip verification step. Defaults to False.
            fetcher_type: Type of fetcher ('simple', 'waterfall', etc.). Defaults to 'simple'.
            output_format: Format(s) for saving extracted content.
            fetcher: Optional pre-existing fetcher. When provided it is used directly
                and not closed after the call — the caller owns its lifecycle.

        Yields:
            ContentMap dicts — one per extracted item.

        """
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
                # Try using cached selectors if available
                if not force_flag:
                    cache_gen = await self._try_cached(
                        url, domain, fetcher, skip_verification, format_to_use, root_span=root_span
                    )
                    if cache_gen is not None:
                        async for item in cache_gen:
                            yield item
                        return

                # Fresh discovery path
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
        fetcher: HTMLFetcher,
        force_flag: bool,
        max_fetch_retries: int,
        max_discovery_retries: int,
        skip_verification: bool,
        format_to_use: list[str],
        root_span: Any | None,
    ) -> AsyncIterator[ContentMap]:
        """Fresh discovery path — fetch, clean, discover, verify, extract, save.

        Separated from scrape() to keep complexity under the C901 limit.
        Uses raw HTML for extraction so the cleaner's deduplication does not
        truncate content; cleaned HTML is used only for LLM discovery and
        selector verification where token reduction matters.

        Args:
            url: Normalised URL to process.
            domain: Extracted domain string.
            fetcher: Active HTML fetcher instance.
            force_flag: Whether to force re-discovery.
            max_fetch_retries: Maximum fetch retry attempts.
            max_discovery_retries: Maximum AI discovery retry attempts.
            skip_verification: Skip verification step.
            format_to_use: Output format list.
            root_span: Active observability span, or None.

        Yields:
            ContentMap dicts — one per extracted item.

        """
        with observability.span('fetch', url=url, max_retries=max_fetch_retries):
            result = await self._fetch(url, fetcher, max_retries=max_fetch_retries)
            if not result:
                raise RuntimeError(f'Failed to fetch {url}')
            assert result.html is not None, 'result.html should not be None after successful fetch'

        with observability.span('clean', url=url, raw_chars=len(result.html)):
            cleaned_html = await self._clean(url, result)
            if not cleaned_html:
                raise RuntimeError(f'HTML cleaning failed for {url}')

        with observability.span('discover', url=url, cleaned_chars=len(cleaned_html)):
            selectors, used_llm = await self._discover(
                url, cleaned_html, max_retries=max_discovery_retries, force=force_flag
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

    # ============================================================================
    # scrape() helpers
    # ============================================================================

    async def _fetch_and_clean_for_cache(self, url: str, fetcher: HTMLFetcher) -> tuple[str, str] | None:
        """Fetch HTML for cache verification. Returns (raw_html, cleaned_html) or None on failure (fail-open)."""
        with observability.span('fetch', url=url, mode='cache_verify'):
            try:
                result = await self._fetch(url, fetcher)
                if result is None or result.html is None:
                    self.console.print('[warning]⚠ Could not fetch HTML, skipping extraction[/warning]')
                    return None
            except BotDetectionError:
                raise
            except Exception as e:
                self.logger.exception('Fetch failed during cache verification for %s', url)
                self.console.print(f'[warning]⚠ Error: {e}, skipping extraction[/warning]')
                return None

        self.console.print('[step]Cleaning HTML...[/step]')
        with observability.span('clean', url=url, raw_chars=len(result.html), mode='cache_verify'):
            cleaned_html: str = self.cleaner.clean_html(result.html)

        # Too short to be a real page — likely a loading stub or redirect gate.
        # Fail-open so cached selectors are used without triggering re-discovery.
        if len(cleaned_html) < 1000:
            self.console.print(
                '[warning]⚠ Fetched HTML too short for verification — using cached selectors as-is[/warning]'
            )
            return None

        await self.debug.save_debug_html(url, cleaned_html)
        return result.html, cleaned_html  # raw for extraction, cleaned for verification

    async def _try_cached(
        self,
        url: str,
        domain: str,
        fetcher: HTMLFetcher,
        skip_verification: bool,
        format_to_use: list[str],
        *,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap] | None:
        """Attempt cached-selector path with per-field granularity."""
        snapshots = await self.storage.load_snapshots(domain)
        if not snapshots:
            return None

        self.console.print(f'[success]✓ Found cached selectors for {domain}[/success]')
        self.logger.info('Using cached selectors domain=%s url=%s', domain, url)

        if skip_verification:
            existing = {name: data for name, snap in snapshots.items() if (data := snapshot_to_selector_dict(snap))}
            items, cache_valid = await self._extract_with_cached(url, fetcher, existing, skip_verification)
            if not cache_valid:
                return None
            return self._yield_cached_items(
                items,
                url,
                domain,
                format_to_use,
                root_span=root_span,
                selectors_payload=existing,
            )

        fetch_result = await self._fetch_and_clean_for_cache(url, fetcher)
        if fetch_result is None:
            existing_for_payload = {
                name: data for name, snap in snapshots.items() if (data := snapshot_to_selector_dict(snap))
            }
            return self._yield_cached_items(
                None,
                url,
                domain,
                format_to_use,
                root_span=root_span,
                selectors_payload=existing_for_payload,
            )

        raw_html, cleaned_html = fetch_result
        return await self._evaluate_cached_verdicts(
            url,
            domain,
            fetcher,
            raw_html,
            cleaned_html,
            snapshots,
            format_to_use,
            root_span=root_span,
        )

    async def _evaluate_cached_verdicts(
        self,
        url: str,
        domain: str,
        fetcher: HTMLFetcher,
        raw_html: str,
        cleaned_html: str,
        snapshots: dict[str, SelectorSnapshot],
        format_to_use: list[str],
        *,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap] | None:
        """Verify cached fields, branch on fresh/stale/partial."""
        with observability.span('verify', url=url, mode='per_field_cache', fields=len(snapshots)):
            verdicts = self._verify_per_field(cleaned_html, snapshots)

        for field_name, verdict in verdicts.items():
            await self.storage.record_verdict(domain, field_name, verdict)

        stale_fields = {f for f, v in verdicts.items() if v != CacheVerdict.FRESH}
        fresh_fields = {f for f, v in verdicts.items() if v == CacheVerdict.FRESH}

        # Check for new contract fields not in cache
        overridden = set(self.contract.get_selector_overrides())
        missing = (self.contract.discovery_field_names() - overridden) - set(snapshots)
        if missing:
            self.console.print(
                f'[warning]⚠ New contract fields not in cache: {", ".join(sorted(missing))} — re-discovering[/warning]'
            )
            stale_fields |= missing

        if not stale_fields:
            return self._extract_all_fresh(
                url, domain, fetcher, raw_html, snapshots, fresh_fields, format_to_use, root_span=root_span
            )

        if not fresh_fields:
            self.console.print(
                f'[warning]⚠ All {len(stale_fields)} cached selectors stale — forcing re-discovery[/warning]'
            )
            return None

        return await self._partial_rediscovery(
            url,
            domain,
            raw_html,
            cleaned_html,
            fetcher,
            snapshots,
            fresh_fields,
            stale_fields,
            format_to_use,
            root_span=root_span,
        )

    def _extract_all_fresh(
        self,
        url: str,
        domain: str,
        fetcher: HTMLFetcher,
        raw_html: str,
        snapshots: dict[str, SelectorSnapshot],
        fresh_fields: set[str],
        format_to_use: list[str],
        *,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap]:
        """All cached selectors verified — extract content."""
        self.console.print(f'[success]✓ All {len(fresh_fields)} cached selectors verified[/success]')
        existing = {name: data for name, snap in snapshots.items() if (data := snapshot_to_selector_dict(snap))}
        root_entry = self._resolve_root(existing)
        container_selector = self._root_value(root_entry)
        with observability.span('extract', url=url, mode='cache', container=container_selector or 'single'):
            extracted = self._extract(url, raw_html, existing, container_selector)
        if extracted:
            items_list: ContentItems = extracted if isinstance(extracted, list) else [extracted]
            return self._yield_cached_items(
                items_list,
                url,
                domain,
                format_to_use,
                fetcher=fetcher,
                root_span=root_span,
                selectors_payload=existing,
            )
        self.console.print('[warning]⚠ Extraction failed with cached selectors[/warning]')
        return self._yield_cached_items(
            None, url, domain, format_to_use, fetcher=fetcher, root_span=root_span, selectors_payload=existing
        )

    async def _partial_rediscovery(
        self,
        url: str,
        domain: str,
        raw_html: str,
        cleaned_html: str,
        fetcher: HTMLFetcher,
        snapshots: dict[str, SelectorSnapshot],
        fresh_fields: set[str],
        stale_fields: set[str],
        format_to_use: list[str],
        *,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap] | None:
        """Rediscover only stale fields, merge with fresh cache, extract and yield."""
        self.console.print(
            f'[info]  ↳ {len(fresh_fields)} fresh, {len(stale_fields)} stale '
            f'— partial rediscovery for: {", ".join(sorted(stale_fields))}[/info]'
        )

        new_selectors = await self.discovery.discover_selectors(cleaned_html, url, stale_fields=stale_fields)
        merged = await self._merge_and_save_snapshots(url, snapshots, fresh_fields, new_selectors, cleaned_html)

        root_entry = self._resolve_root(merged)
        container_selector = self._root_value(root_entry)
        extracted = self._extract(url, raw_html, merged, container_selector)

        if not extracted:
            self.console.print('[warning]⚠ Extraction failed after partial rediscovery[/warning]')
            return None

        items_list: ContentItems = extracted if isinstance(extracted, list) else [extracted]
        validated = self._validate_items(items_list, url)

        async def _yield_partial() -> AsyncIterator[ContentMap]:
            for v in validated:
                yield v
            save_content: ContentMap | ContentItems = validated if len(validated) > 1 else validated[0]
            for fmt in format_to_use:
                await self.storage.save_content(url, save_content, fmt, contract_sig=self._contract_sig)
            await self._record_fetch_strategy_selector_level(fetcher, domain)
            elapsed = time.monotonic() - self._url_start
            self.last_elapsed = elapsed
            stats = await self.tracker.record_url(
                url, used_llm=True, level_distribution=None, elapsed=elapsed, partial_discovery=True
            )
            self._print_tracking_stats(domain, stats)
            self.console.print(f'[dim]  ⏱ {self.last_elapsed:.1f}s elapsed[/dim]')
            observability.set_trace_output(
                root_span,
                {
                    'path': 'cache-partial',
                    'selectors': merged,
                    'extracted_count': len(validated),
                    'extracted_sample': validated[0] if validated else None,
                },
            )

        return _yield_partial()

    def _verify_per_field(self, html: str, snapshots: dict[str, SelectorSnapshot]) -> dict[str, CacheVerdict]:
        """Verify each cached field independently and apply root cascade.

        Args:
            html: Cleaned HTML to verify against
            snapshots: Per-field snapshots to verify

        Returns:
            Dict mapping field names to CacheVerdict.

        """
        from parsel import Selector as _PS

        sel = _PS(text=html)
        verdicts: dict[str, CacheVerdict] = {}
        field_levels: dict[str, str] = {}

        for field_name, snap in snapshots.items():
            if not snap.is_active:
                verdicts[field_name] = CacheVerdict.FRESH
                continue
            sel_dict = snapshot_to_selector_dict(snap)
            field_result = self.verifier._verify_field(sel, field_name, sel_dict, self.selector_level)
            verdicts[field_name] = CacheVerdict.FRESH if field_result.status == 'verified' else CacheVerdict.STALE
            if field_result.status == 'verified' and field_result.selector_level:
                field_levels[field_name] = field_result.selector_level

        # Root cascade: if root is stale, mark all non-root fields stale
        if verdicts.get('root') == CacheVerdict.STALE:
            for name in verdicts:
                if name != 'root':
                    verdicts[name] = CacheVerdict.STALE

        level_distribution: dict[str, int] = {}
        for field_name, level in field_levels.items():
            if verdicts[field_name] == CacheVerdict.FRESH:
                level_distribution[level] = level_distribution.get(level, 0) + 1

        self._last_level_distribution = level_distribution
        return verdicts

    def _yield_cached_items(
        self,
        items: ContentItems | None,
        url: str,
        domain: str,
        format_to_use: list[str],
        *,
        fetcher: HTMLFetcher | None = None,
        root_span: Any | None = None,
        selectors_payload: SelectorMap | None = None,
    ) -> AsyncIterator[ContentMap]:
        """Wrap cached items into an async generator that tracks and saves."""

        async def _gen() -> AsyncIterator[ContentMap]:
            validated_for_output: ContentItems | None = None
            if items:
                validated = self._validate_items(items, url)
                validated_for_output = validated
                for v in validated:
                    yield v
                save_content: ContentMap | ContentItems = validated if len(validated) > 1 else validated[0]
                for fmt in format_to_use:
                    await self.storage.save_content(url, save_content, fmt, contract_sig=self._contract_sig)
            if fetcher is not None:
                await self._record_fetch_strategy_selector_level(fetcher, domain)
            await self._track_cached_success(url, domain)
            self.last_elapsed = time.monotonic() - self._url_start
            self.console.print(f'[dim]  ⏱ {self.last_elapsed:.1f}s elapsed[/dim]')
            observability.set_trace_output(
                root_span,
                {
                    'path': 'cache-fresh',
                    'selectors': selectors_payload or {},
                    'extracted_count': len(validated_for_output) if validated_for_output else 0,
                    'extracted_sample': validated_for_output[0] if validated_for_output else None,
                },
            )

        return _gen()

    async def _merge_and_save_snapshots(
        self,
        url: str,
        snapshots: dict[str, SelectorSnapshot],
        fresh_fields: set[str],
        new_selectors: SelectorMap | None,
        cleaned_html: str,
    ) -> SelectorMap:
        """Merge fresh cached selectors with newly discovered, verify new ones, and save."""
        from datetime import datetime
        from datetime import timezone as _tz

        from yosoi.models.snapshot import selector_dict_to_snapshot as _to_snap

        merged: SelectorMap = {
            name: data
            for name, snap in snapshots.items()
            if name in fresh_fields and (data := snapshot_to_selector_dict(snap))
        }
        if new_selectors:
            merged.update(new_selectors)
            verification = self.verifier.verify(cleaned_html, new_selectors, max_level=self.selector_level)
            level_distribution = getattr(self, '_last_level_distribution', {}).copy()
            for level, count in verification.level_distribution.items():
                level_distribution[level] = level_distribution.get(level, 0) + count
            self._last_level_distribution = level_distribution
            for name, field_result in verification.results.items():
                if field_result.status != 'verified':
                    self.console.print(f'[warning]⚠ Rediscovered selector for {name} failed verification[/warning]')
                    merged.pop(name, None)

        now = datetime.now(_tz.utc)
        merged_snapshots: dict[str, SelectorSnapshot] = {}
        for name, sel_dict in merged.items():
            if name in fresh_fields and name in snapshots:
                merged_snapshots[name] = snapshots[name]
            else:
                merged_snapshots[name] = _to_snap(sel_dict, discovered_at=now, last_verified_at=now)
        await self.storage.save_snapshots(url, merged_snapshots)
        return merged

    def _validate_items(self, extracted: ContentMap | ContentItems, url: str) -> ContentItems:
        """Normalise extraction result to list and validate each item."""
        items_list: ContentItems = extracted if isinstance(extracted, list) else [extracted]
        return [self._validate_single_item(item, url) for item in items_list]

    @staticmethod
    def _selectors_with_root(verified: SelectorMap, root_entry: dict[str, Any] | None) -> SelectorMap:
        """Re-attach root selector for persistence, preserving the original type."""
        selectors_to_save = dict(verified)
        if root_entry:
            selectors_to_save['root'] = root_entry
        return selectors_to_save

    async def _finish(
        self,
        url: str,
        domain: str,
        selectors_to_save: SelectorMap,
        content: ContentMap | ContentItems | None,
        used_llm: bool,
        format_to_use: list[str],
    ) -> None:
        """Set elapsed time, save, track, and print timing."""
        elapsed = time.monotonic() - self._url_start
        self.last_elapsed = elapsed
        await self._save_and_track(url, domain, selectors_to_save, content, used_llm, format_to_use, elapsed)
        self.console.print(f'[dim]  ⏱ {self.last_elapsed:.1f}s elapsed[/dim]')

    # ============================================================================
    # Private helper methods
    # ============================================================================

    async def normalize_url(self, url: str) -> str:
        """Add protocol to URL, preferring https.

        Args:
            url: The URL that is being fetched

        Returns:
            The complete URL

        """
        if not url.startswith(('http://', 'https://')):
            try:
                test_url = 'https://' + url
                await self._client.head(test_url, timeout=3, follow_redirects=True)
                return test_url
            except httpx.HTTPError:
                return 'http://' + url
        return url

    def _extract_domain(self, url: str) -> str:
        """Extract the (sub)domain from URL.

        Thin delegator over :func:`yosoi.utils.observability.normalize_user_id`
        so storage and observability never split: the value used as the
        Langfuse ``user_id`` is the same value used as the storage domain.

        Args:
            url: The URL that is being fetched.

        Returns:
            Normalized host (lowercased, single leading ``www.`` stripped,
            port and userinfo removed), or empty string for URLs without a host.

        """
        return observability.normalize_user_id(url) or ''

    def _create_fetcher(self, fetcher_type: str, console: Console | None = None) -> HTMLFetcher | None:
        """Create HTML fetcher instance.

        Args:
            fetcher_type: The type of fetcher to be used to fetch HTMLs
            console: Optional Rich console passed to fetchers that support it

        Returns:
            The fetcher to be used to fetch HTMLs

        """
        try:
            kwargs: dict[str, Any] = {'console': console} if fetcher_type == 'waterfall' and console is not None else {}
            return create_fetcher(fetcher_type, **kwargs)
        except ValueError:
            self.console.print(f'[danger]Invalid fetcher type: {fetcher_type}[/danger]')
            return None

    async def _fetch(self, url: str, fetcher: HTMLFetcher, max_retries: int = 2) -> FetchResult | None:
        """Fetch HTML with automatic retry logic for bot detection.

        Attempts to fetch HTML with automatic retries when bot detection is
        encountered. Logs and displays progress for each retry attempt.

        Args:
            url: The URL that is being fetched.
            fetcher: HTML fetcher instance to use.
            max_retries: Maximum retry attempts. Defaults to 2.

        Returns:
            FetchResult if fetch succeeds within retry limit, None if all
            attempts fail or other errors occur.

        Note:
            Bot detection errors are caught and retried. Other exceptions
            are caught and logged, returning None rather than raising.

        """
        self.console.print(Panel(f'Processing: {url}', style='bold blue'))
        self.console.print('[step]Step 1: Fetching HTML...[/step]')

        def before_sleep_log(retry_state: RetryCallState) -> None:
            attempt = retry_state.attempt_number
            if attempt >= 1:
                self.console.print(f'[warning]Fetch retry attempt {attempt}/{max_retries}...[/warning]')
                observability.warning('Retrying fetch', url=url, attempt=attempt)

        try:
            retryer = get_async_retryer(
                max_attempts=max_retries,
                wait_min=1,
                wait_max=10,
                exceptions=(BotDetectionError, Exception),
                log_callback=before_sleep_log,
                reraise=False,
            )

            async for attempt in retryer:
                with attempt:
                    result = None
                    try:
                        result = await fetcher.fetch(url)

                        if not result.success:
                            self.console.print(
                                f'[danger]Fetch failed: {result.block_reason or "Unknown error"}[/danger]'
                            )
                            raise Exception(f'Fetch failed: {result.block_reason}')

                        if result.html is None:
                            self.console.print('[danger]No HTML content received[/danger]')
                            raise Exception('No HTML content received')

                        self.console.print(
                            f'[success]Fetched {len(result.html):,} characters of HTML ({result.fetch_time:.2f}s)[/success]'
                        )
                        return result

                    except BotDetectionError as e:
                        self._handle_bot_detection(e, attempt.retry_state.attempt_number, max_retries)
                        raise

                    except (httpx.HTTPError, OSError, ValueError, RuntimeError) as e:
                        if str(e) not in [
                            'No HTML content received',
                            f'Fetch failed: {getattr(result, "block_reason", "Unknown")}',
                        ]:
                            self.console.print(f'[danger]Unexpected error: {e}[/danger]')
                            self.logger.exception('Fetch error for %s', url)
                            observability.warning(
                                'Fetch error', url=url, error=str(e), attempt=attempt.retry_state.attempt_number
                            )
                        raise

        except RetryError:
            self.console.print(f'[danger]All {max_retries} attempts failed[/danger]')
            return None
        except (httpx.HTTPError, OSError, ValueError, RuntimeError):
            return None

        return None

    async def _clean(self, url: str, result: FetchResult) -> str | None:
        """Clean HTML by removing noise and extracting main content.

        Args:
            url: URL being processed (for logging and debug output).
            result: FetchResult containing raw HTML.

        Returns:
            Cleaned HTML string, or None if result contains no HTML.

        """
        assert result.html is not None, 'result.html should not be None in _clean'

        self.console.print('[step]Step 1.5: Cleaning HTML...[/step]')
        cleaned_html = self.cleaner.clean_html(result.html)

        if not cleaned_html:
            self.console.print('[danger]HTML cleaning produced empty result[/danger]')
            return None

        await self.debug.save_debug_html(url, cleaned_html)
        self.console.print(f'[success]Cleaned HTML ready ({len(cleaned_html):,} chars)[/success]')
        return cleaned_html

    async def _discover(
        self, url: str, cleaned_html: str, max_retries: int = 3, force: bool = False
    ) -> tuple[SelectorMap | None, bool]:
        """Discover CSS selectors with AI, using fallback heuristics if needed.

        Attempts AI-powered selector discovery with automatic retries.

        Args:
            url: URL being processed (for logging).
            cleaned_html: Pre-cleaned HTML content to analyze.
            max_retries: Maximum AI retry attempts. Defaults to 3.
            force: Force re-discovery even if selectors exist. Defaults to False.

        Returns:
            Tuple of (selectors, used_llm) where:
            - selectors: Dict mapping field names to selector configs,
              or None if discovery completely failed
            - used_llm: True if AI was used, False if using fallback heuristics

        """
        overrides = self.contract.get_selector_overrides()
        if overrides:
            override_fields = ', '.join(f'`{f}`' for f in overrides)
            self.console.print(f'[info]  ↳ Using selector overrides for: {override_fields}[/info]')

        if not self.contract.field_descriptions():
            self.console.print('[step]Step 2: All fields have selector overrides — skipping AI discovery[/step]')
            self.logger.info('Skipping AI discovery — all fields overridden url=%s', url)
            await self.debug.save_debug_selectors(url, overrides)
            return overrides, False

        def before_ai_sleep_log(retry_state: RetryCallState) -> None:
            attempt = retry_state.attempt_number
            if attempt >= 1:
                self.console.print(f'[warning]AI retry attempt {attempt}/{max_retries}...[/warning]')
                observability.warning('Retrying AI discovery', url=url, attempt=attempt)

        try:
            retryer = get_async_retryer(
                max_attempts=max_retries,
                wait_min=1,
                wait_max=10,
                exceptions=(Exception,),
                log_callback=before_ai_sleep_log,
                reraise=False,
            )

            async for attempt in retryer:
                with attempt:
                    self.console.print(
                        f'[step]Step 2: AI analyzing HTML (attempt {attempt.retry_state.attempt_number}/{max_retries})...[/step]'
                    )

                    selectors = await self.discovery.discover_selectors(cleaned_html, url, force=force)

                    if selectors:
                        selectors.update(overrides)
                        self.console.print(f'[success]Discovered selectors for {len(selectors)} fields[/success]')
                        await self.debug.save_debug_selectors(url, selectors)

                        if attempt.retry_state.attempt_number > 1:
                            self.console.print(
                                f'[success]AI retry successful on attempt {attempt.retry_state.attempt_number}[/success]'
                            )
                        return selectors, True

                    self.console.print('[danger]AI discovery failed[/danger]')
                    self.logger.warning('AI discovery failed for %s', url)
                    raise Exception('AI discovery failed')

        except RetryError:
            pass
        except (httpx.HTTPError, OSError, ValueError, RuntimeError):
            pass

        self.console.print(f'[danger]All {max_retries} AI attempts failed[/danger]')
        observability.warning('All AI attempts failed', url=url)
        return None, False

    @staticmethod
    def _pop_root(selectors: SelectorMap) -> dict[str, Any] | None:
        """Remove and return the full ``root`` selector entry from a selector map.

        Args:
            selectors: Mutable selector dict (modified in-place).

        Returns:
            The full root entry dict, or None.

        """
        root_entry = selectors.pop('root', None)
        if isinstance(root_entry, dict):
            primary = root_entry.get('primary')
            if isinstance(primary, str) and primary:
                return root_entry
            if isinstance(primary, dict):
                value = primary.get('value')
                return root_entry if isinstance(value, str) and value else None
        return None

    @staticmethod
    def _root_value(root_entry: dict[str, Any] | None) -> str | None:
        """Extract the selector value string from a full root entry.

        Args:
            root_entry: Full root entry dict, or None.

        Returns:
            The root selector string, or None.

        """
        if root_entry is None:
            return None
        primary = root_entry.get('primary')
        if isinstance(primary, str) and primary:
            return primary
        if isinstance(primary, dict):
            value = primary.get('value')
            return value if isinstance(value, str) and value else None
        return None

    def _verify(self, _url: str, html: str, selectors: SelectorMap, skip_verification: bool) -> SelectorMap | None:
        """Verify discovered selectors against HTML.

        Args:
            _url: URL being processed (for logging only, unused).
            html: HTML content to verify selectors against.
            selectors: Discovered selectors to verify.
            skip_verification: Skip verification and return selectors as-is. Defaults to False.

        Returns:
            Dictionary of verified selectors (same structure as input) if verification
            succeeds. Returns input selectors unchanged if skip_verification is True.
            Returns None if all selectors fail verification.

        """
        if skip_verification:
            self.console.print('[warning]Skipping verification (--skip-verification enabled)[/warning]')
            return selectors

        self.console.print('[step]Step 3: Verifying selectors against actual HTML...[/step]')

        result = self.verifier.verify(html, selectors, max_level=self.selector_level)
        self._last_level_distribution = result.level_distribution

        if not result.success:
            self._print_verification_failure(result)
            return None

        verified = {name: selectors[name] for name in result.results if result.results[name].status == 'verified'}

        failed_count = len(selectors) - len(verified)
        self.console.print(f'[success]Verified {len(verified)}/{result.total_fields} fields successfully[/success]')

        if failed_count >= 1:
            self._print_partial_failure(result)

        return verified

    async def _record_fetch_strategy_selector_level(self, fetcher: HTMLFetcher, domain: str) -> None:
        """Cache the highest selector level that worked with the domain loading strategy."""
        if not isinstance(fetcher, JSFetcher):
            return
        level_dist = getattr(self, '_last_level_distribution', None)
        if not level_dist:
            return
        order = ['css', 'xpath', 'regex', 'jsonld']
        highest = next((level for level in reversed(order) if level_dist.get(level)), None)
        if highest is not None:
            await fetcher.update_selector_level(domain, highest)

    def _print_verification_failure(self, result: VerificationResult) -> None:
        """Print detailed failure summary when all selectors fail."""
        self.console.print('[danger]Verification failed - no selectors matched![/danger]')
        self.console.print('')

        for field_name, field_result in result.results.items():
            self.console.print(f'  [danger]✗ {field_name}[/danger]')
            for failure in field_result.failed_selectors:
                self.console.print(
                    f'      [dim]→ {failure.level}:[/dim] "{failure.selector}" [warning]→ {failure.reason}[/warning]'
                )

        self.console.print('')

    def _print_partial_failure(self, result: VerificationResult) -> None:
        """Print summary of partial failures."""
        failed_fields = [name for name in result.results if result.results[name].status == 'failed']
        self.console.print(f'[warning]  ⚠ {len(failed_fields)} field(s) failed verification:[/warning]')
        for field_name in failed_fields:
            field_result = result.results[field_name]
            reasons = [f.reason for f in field_result.failed_selectors if f.reason != 'na_selector']
            primary_reason = reasons[0] if reasons else 'all_na'
            self.console.print(f'      [dim]• {field_name}:[/dim] {primary_reason}')

    def _resolve_root(self, selectors: SelectorMap) -> dict[str, Any] | None:
        """Determine the root selector from contract override or AI discovery.

        Pops ``root`` from *selectors* as a side-effect so it is not passed
        to the verifier/extractor as a content field.

        Args:
            selectors: Mutable selector dict (modified in-place).

        Returns:
            Full root entry dict, or None for single-item pages.

        """
        contract_root = self.contract.get_root()
        if contract_root:
            self._pop_root(selectors)
            return {'primary': contract_root.model_dump()}
        return self._pop_root(selectors)

    def _extract(
        self,
        url: str,
        html: str,
        verified_selectors: SelectorMap,
        container_selector: str | None = None,
    ) -> ContentMap | ContentItems | None:
        """Extract content from HTML using verified selectors.

        Args:
            url: URL being processed (for logging).
            html: Cleaned HTML content to extract from.
            verified_selectors: Verified selectors to use for extraction.
            container_selector: Optional CSS selector for multi-item containers.

        Returns:
            Single ContentMap, list of ContentMaps for multi-item, or None.

        """
        self.console.print('[step]Step 4: Extracting content using verified selectors...[/step]')

        if container_selector:
            items = self.extractor.extract_items(
                url, html, verified_selectors, container_selector, max_level=self.selector_level
            )
            if not items:
                self.console.print('[danger]Content extraction failed - no items extracted[/danger]')
                return None
            self.console.print(f'[success]Extracted {len(items)} items successfully[/success]')
            return items

        extracted = self.extractor.extract_content_with_html(
            url, html, verified_selectors, max_level=self.selector_level
        )

        if not extracted:
            self.console.print('[danger]Content extraction failed - no content extracted[/danger]')
            return None

        self.console.print(f'[success]Extracted content from {len(extracted)} fields successfully[/success]')
        return extracted

    @staticmethod
    def _selector_values(entry: dict[str, Any] | None) -> tuple[str, ...]:
        """Collect the non-empty primary/fallback/tertiary selector strings from an entry.

        These are the selectors already tried (and found semantically wrong) for a
        field; they are forbidden on the corrective re-discovery so the LLM cannot
        return one of them again.
        """
        if not isinstance(entry, dict):
            return ()
        values: list[str] = []
        for key in ('primary', 'fallback', 'tertiary'):
            candidate = entry.get(key)
            if isinstance(candidate, str) and candidate:
                values.append(candidate)
            elif isinstance(candidate, dict):
                value = candidate.get('value')
                if isinstance(value, str) and value:
                    values.append(value)
        return tuple(dict.fromkeys(values))  # dedupe, preserve order

    def _semantic_issues(self, extracted: ContentMap | ContentItems) -> list[FieldSemanticIssue]:
        """Run the type-aware semantic validator on a representative extracted item.

        For multi-item pages every item shares the same selectors, so the first
        non-empty item is representative of a systematically wrong selector.
        """
        if isinstance(extracted, list):
            item = next((i for i in extracted if i), None)
            if item is None:
                return []
        else:
            item = extracted
        return self.semantic_validator.validate(item, self._field_rules)

    async def _semantic_refine(
        self,
        url: str,
        cleaned_html: str,
        raw_html: str,
        verified: SelectorMap,
        container_selector: str | None,
        extracted: ContentMap | ContentItems,
        max_retries: int,
    ) -> tuple[ContentMap | ContentItems, SelectorMap]:
        """Re-discover fields whose extracted values fail type-aware semantic checks.

        Structural verification only proves a selector matches *something*; this
        loop catches values of the wrong shape (e.g. a numeric ``score`` that came
        back as whole-card text), feeds the failure back to the LLM as a hint, and
        re-discovers only the offending fields. Bounded by ``max_retries``. Passing
        fields keep their selectors. See CAS-78.

        Returns:
            The (possibly improved) extraction result and verified selector map.

        """
        for attempt in range(max_retries):
            issues = self._semantic_issues(extracted)
            if not issues:
                return extracted, verified

            feedback = {
                issue.field: FieldFeedback(
                    message=issue.as_feedback(),
                    failed_selectors=self._selector_values(verified.get(issue.field)),
                )
                for issue in issues
            }
            failing = set(feedback)
            self.console.print(
                f'[warning]⚠ Semantic check flagged {", ".join(sorted(failing))} — '
                f're-discovering (attempt {attempt + 1}/{max_retries})[/warning]'
            )

            fresh = await self.discovery.discover_selectors(
                cleaned_html, url, stale_fields=failing, feedback=feedback, force=True
            )
            if not fresh:
                break

            reverified = self._verify(url, cleaned_html, fresh, skip_verification=False)
            improved = {k: v for k, v in (reverified or {}).items() if k != 'root'}
            if not improved:
                break

            verified.update(improved)
            re_extracted = self._extract(url, raw_html, verified, container_selector)
            if not re_extracted:
                break
            extracted = re_extracted

        remaining = self._semantic_issues(extracted)
        if remaining:
            fields = ', '.join(sorted({issue.field for issue in remaining}))
            self.console.print(f'[warning]⚠ Semantic issues remain after {max_retries} retries: {fields}[/warning]')
        return extracted, verified

    async def _extract_with_cached(
        self,
        url: str,
        fetcher: HTMLFetcher,
        existing_selectors: SelectorMap,
        skip_verification: bool,
    ) -> tuple[ContentItems | None, bool]:
        """Fetch, optionally verify, and extract content using cached selectors.

        Args:
            url: URL to fetch and extract from.
            fetcher: HTML fetcher instance.
            existing_selectors: Previously discovered selectors to use.
            skip_verification: Skip selector verification if True.

        Returns:
            Tuple of (items_or_none, cache_valid).
            - cache_valid=False means fall through to fresh discovery.
            - cache_valid=True + items=None means fail-open (fetch failed, treat as success).
            - cache_valid=True + items=list means extracted successfully.

        Raises:
            BotDetectionError: Passes through bot detection from fetcher.

        """
        step = (
            'Fetching HTML for extraction with cached selectors...'
            if skip_verification
            else 'Fetching HTML to verify cached selectors...'
        )
        self.console.print(f'[step]{step}[/step]')

        try:
            result = await fetcher.fetch(url)

            if not result.success or result.html is None:
                self.console.print('[warning]⚠ Could not fetch HTML, skipping extraction[/warning]')
                return None, True

            self.console.print('[step]Cleaning HTML...[/step]')
            cleaned_html = self.cleaner.clean_html(result.html)
            await self.debug.save_debug_html(url, cleaned_html)

            root_entry = self._resolve_root(existing_selectors)
            container_selector = self._root_value(root_entry)

            if root_entry and not skip_verification:
                from parsel import Selector as _PS

                from yosoi.models.selectors import coerce_selector_entry

                primary = root_entry.get('primary')
                _entry = coerce_selector_entry(primary) if primary else None
                if _entry is not None:
                    _ok, _ = self.verifier._test_selector(_PS(text=cleaned_html), _entry)
                    if not _ok:
                        self.console.print(
                            '[warning]⚠ Cached container selector failed — forcing re-discovery[/warning]'
                        )
                        return None, False

            if not skip_verification:
                verification = self.verifier.verify(cleaned_html, existing_selectors, max_level=self.selector_level)
                if not verification.success:
                    self.console.print(
                        '[warning]⚠ Cached selectors failed verification - forcing re-discovery[/warning]'
                    )
                    return None, False
                selectors_to_use = {
                    name: existing_selectors[name]
                    for name in verification.results
                    if verification.results[name].status == 'verified'
                }
                self.console.print(
                    f'[success]✓ Verified {len(selectors_to_use)}/{len(self.contract.discovery_field_names())} cached selectors[/success]'
                )
                overridden = set(self.contract.get_selector_overrides())
                required_fields = self.contract.discovery_field_names() - overridden
                missing = required_fields - set(selectors_to_use)
                if missing:
                    self.console.print(
                        f'[warning]⚠ New contract fields not in cache: {", ".join(sorted(missing))} — re-discovering[/warning]'
                    )
                    return None, False
            else:
                selectors_to_use = existing_selectors

            extracted = self._extract(url, cleaned_html, selectors_to_use, container_selector)
            if extracted:
                if isinstance(extracted, list):
                    return extracted, True
                return [extracted], True

            self.console.print('[warning]⚠ Extraction failed with cached selectors[/warning]')
            return None, True

        except BotDetectionError:
            raise
        except Exception as e:
            self.logger.exception('Cached selector handling failed for %s', url)
            self.console.print(f'[warning]⚠ Error: {e}, skipping extraction[/warning]')
            return None, True

    async def _track_cached_success(self, url: str, domain: str) -> None:
        """Track successful use of cached selectors.

        Args:
            url: The URL that is being fetched
            domain: The domain from which the URL is grabbed

        """
        elapsed = time.monotonic() - self._url_start
        stats = await self.tracker.record_url(url, used_llm=False, level_distribution=None, elapsed=elapsed)
        self._print_tracking_stats(domain, stats)

    def _handle_bot_detection(self, error: BotDetectionError, attempt: int, max_retries: int) -> None:
        """Handle bot detection error.

        Args:
            error: The error being handled
            attempt: The amount of times it has been handled
            max_retries: The maximum amount of times it can be handled

        """
        self.console.print(f'[danger]BOT DETECTION (Attempt {attempt}/{max_retries})[/danger]')
        self.console.print(f'[danger]URL: {error.url}[/danger]')
        self.console.print(f'[danger]Status Code: {error.status_code}[/danger]')
        self.console.print(f'[danger]Indicators: {", ".join(error.indicators)}[/danger]')

        self.logger.warning(
            'Bot detection (attempt %d/%d) for %s (status=%d): %s',
            attempt,
            max_retries,
            error.url,
            error.status_code,
            ', '.join(error.indicators),
        )
        observability.warning(
            'Bot detection triggered',
            url=error.url,
            status_code=error.status_code,
            indicators=','.join(error.indicators),
            attempt=attempt,
            max_retries=max_retries,
        )

        if attempt >= max_retries:
            self.console.print('[danger]ABORTING - All fetch attempts exhausted[/danger]')
            self.console.print('[info]All fetch attempts exhausted for this URL[/info]')

    def _validate_with_contract(self, extracted: ContentMap | ContentItems, url: str = '') -> ContentMap | ContentItems:
        """Instantiate Contract with extracted data to run validators and type coercion.

        Args:
            extracted: Raw extracted data (single dict or list of dicts).
            url: Source URL injected into validation context for relative URL resolution.

        Returns:
            Validated and transformed data, or the original if validation fails.

        """
        if isinstance(extracted, list):
            validated_items: ContentItems = [self._validate_single_item(item, url) for item in extracted]
            self.console.print(f'[success]✓ Contract validation applied to {len(validated_items)} items[/success]')
            return validated_items

        validated = self._validate_single_item(extracted, url)
        if validated is not extracted:
            self.console.print('[success]✓ Contract validation applied[/success]')
        return validated

    def _validate_single_item(self, item: ContentMap, url: str) -> ContentMap:
        """Validate a single content dict through the Contract.

        Args:
            item: Raw extracted data dictionary.
            url: Source URL for validation context.

        Returns:
            Validated dict, or original if validation fails.

        """
        try:
            instance = self.contract.model_validate(item, context={'source_url': url})
            return instance.model_dump()
        except (ValueError, TypeError) as e:
            self.logger.warning('Contract validation failed, using raw data: %s', e)
            self.console.print(f'[warning]⚠ Validation skipped: {e}[/warning]')
            return item

    async def _save_and_track(
        self,
        url: str,
        domain: str,
        verified: SelectorMap,
        extracted: ContentMap | ContentItems | None,
        used_llm: bool,
        output_format: list[str],
        elapsed: float | None = None,
    ) -> None:
        """Save verified selectors, extracted content, and track LLM usage.

        Args:
            url: URL that was processed.
            domain: Domain name.
            verified: Verified selector dictionary to save.
            extracted: Extracted content dictionary to save, or None if extraction failed.
            used_llm: Whether LLM was called for this URL.
            output_format: Format for output files ('json' or 'markdown').
            elapsed: Time in seconds spent processing this URL. Defaults to None.

        """
        await self.storage.save_selectors(url, verified, verified=True)

        if extracted:
            for fmt in output_format:
                await self.storage.save_content(url, extracted, fmt, contract_sig=self._contract_sig)

        level_dist = getattr(self, '_last_level_distribution', None)
        stats = await self.tracker.record_url(
            url, used_llm=used_llm, level_distribution=level_dist or None, elapsed=elapsed
        )
        self._print_tracking_stats(domain, stats)

    def _print_tracking_stats(self, domain: str, stats: 'DomainStats') -> None:
        """Print LLM tracking statistics for domain.

        Args:
            domain: Domain name being tracked.
            stats: DomainStats with tracking data for the domain.

        """
        self.console.print(f'\n[dim]  - Tracking Stats for {domain}:[/dim]')
        self.console.print(f'[dim]    -- LLM Calls: {stats.llm_calls}[/dim]')
        self.console.print(f'[dim]    -- URLs Processed: {stats.url_count}[/dim]')
        if stats.total_elapsed:
            self.console.print(f'[dim]    -- Total Elapsed: {stats.total_elapsed:.1f}s[/dim]')
        if stats.llm_calls > 0:
            efficiency = stats.url_count / stats.llm_calls
            self.console.print(f'[dim]     • Efficiency: {efficiency:.1f} URLs per LLM call[/dim]')
        self.console.print()

    # ============================================================================
    # Display methods
    # ============================================================================

    async def show_summary(self) -> None:
        """Show summary of all saved selectors."""
        domains = await self.storage.list_domains()

        if not domains:
            self.console.print('[warning]No selectors found in storage[/warning]')
            return

        table = Table(title='Saved Selectors Summary')
        table.add_column('Domain', style='cyan')
        table.add_column('Fields', style='green')

        for domain in domains:
            selectors = await self.storage.load_selectors(domain)
            if selectors:
                table.add_row(domain, str(len(selectors)))

        self.console.print(table)
        self.console.print(f'\n[success]Total domains: {len(domains)}[/success]')

    async def show_llm_stats(self) -> None:
        """Show LLM usage statistics."""
        stats = await self.tracker.get_all_stats()

        total_llm_calls = sum(domain_stats.llm_calls for domain_stats in stats.values())
        total_urls = sum(domain_stats.url_count for domain_stats in stats.values())

        self.console.print('\n[bold cyan]═══ LLM Usage Statistics ═══[/bold cyan]')
        self.console.print(f'[info]Total URLs processed: {total_urls}[/info]')
        self.console.print(f'[info]LLM calls made: {total_llm_calls}[/info]')

        if total_llm_calls > 0:
            efficiency = total_urls / total_llm_calls
            self.console.print(f'[success]Efficiency: {efficiency:.1f} URLs per LLM call[/success]')

        self.console.print()
