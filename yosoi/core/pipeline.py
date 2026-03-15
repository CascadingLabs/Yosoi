"""Main pipeline for selector discovery.

Centralized retry logic for bot detection and AI failures.
"""

import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import httpx
import logfire
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from tenacity import RetryCallState, RetryError

from yosoi.core.cleaning import HTMLCleaner
from yosoi.core.configs import YosoiConfig
from yosoi.core.discovery import DiscoveryOrchestrator, LLMConfig
from yosoi.core.extraction import ContentExtractor
from yosoi.core.fetcher import HTMLFetcher, create_fetcher
from yosoi.core.verification import SelectorVerifier
from yosoi.models import FetchResult
from yosoi.models.contract import Contract
from yosoi.models.results import VerificationResult
from yosoi.models.selectors import SelectorLevel
from yosoi.storage import DebugManager, LLMTracker, SelectorStorage
from yosoi.storage.tracking import DomainStats
from yosoi.utils.exceptions import BotDetectionError
from yosoi.utils.retry import get_async_retryer

# Selector dict: field name → {primary, fallback, tertiary} selectors
# Values may be plain strings, SelectorEntry dicts, or None depending on source
SelectorMap = dict[str, dict[str, Any]]
# Extracted content: field name → extracted value(s)
ContentMap = dict[str, str | list[str | dict[str, str]]]
# Multi-item extraction: list of ContentMap dicts
ContentItems = list[ContentMap]


class Pipeline:
    """Main pipeline for discovering and saving CSS selectors with retry logic.

    The main pipeline of YOSOi that goes through all the other python files to
    fetch the HTML, parse the HTML, have an LLM discover the selectors, and
    verify and store the selectors.

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

        """
        self.selector_level = selector_level

        # Auto-resolve model strings → LLMConfig
        if isinstance(llm_config, str):
            from yosoi.core.discovery.config import provider

            llm_config = provider(llm_config)

        if isinstance(llm_config, YosoiConfig):
            yosoi_cfg = llm_config
            llm_config = yosoi_cfg.llm
            debug_mode = yosoi_cfg.debug.save_html
            force = yosoi_cfg.force
            if yosoi_cfg.telemetry.logfire_token:
                import logfire as _logfire

                _logfire.configure(token=yosoi_cfg.telemetry.logfire_token)
                _logfire.instrument_pydantic()

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
        self.console = Console(theme=self.custom_theme, quiet=quiet)
        self.cleaner = HTMLCleaner(console=self.console)
        self.storage = SelectorStorage()
        self.discovery = DiscoveryOrchestrator(
            contract=self.contract,
            llm_config=llm_config,
            storage=self.storage,
            console=self.console,
            target_level=self.selector_level,
        )
        self.verifier = SelectorVerifier(console=self.console)
        self.extractor = ContentExtractor(console=self.console, contract=self.contract)
        self.tracker = LLMTracker()
        self.debug_mode = debug_mode
        self.debug = DebugManager(console=self.console, enabled=debug_mode)
        self.output_formats: list[str] = [output_format] if isinstance(output_format, str) else list(output_format)
        self.force = force
        self.logger = logging.getLogger(__name__)

        # Auto-initialize .yosoi dir and file logging when used outside the CLI
        has_file_handler = any(isinstance(h, logging.FileHandler) for h in logging.getLogger().handlers)
        if not has_file_handler:
            from yosoi.utils.files import init_yosoi, is_initialized
            from yosoi.utils.logging import setup_local_logging

            if not is_initialized():
                init_yosoi()
            log_file = setup_local_logging()
            self.console.print(f'ℹ Log file: [link=file://{log_file}]file://{log_file}[/link]')

    async def process_url(
        self,
        url: str,
        force: bool | None = None,
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
        skip_verification: bool = False,
        fetcher_type: str = 'simple',
        output_format: str | list[str] | None = None,
    ) -> None:
        """Process a single URL: discover, verify, and save selectors.

        Thin wrapper around :meth:`scrape` that drains the generator.
        Raises on failure — callers are responsible for error handling.

        Args:
            url: URL to process
            force: Force re-discovery even if selectors exist. Defaults to False.
            skip_verification: Skip verification step. Defaults to False.
            fetcher_type: Type of fetcher ('simple'). Defaults to 'simple'.
            max_fetch_retries: Maximum fetch retry attempts. Defaults to 2.
            max_discovery_retries: Maximum AI discovery retry attempts. Defaults to 3.
            output_format: Format(s) for extracted content. Defaults to None (uses pipeline default).

        """
        async for _ in self.scrape(
            url,
            force=force,
            max_fetch_retries=max_fetch_retries,
            max_discovery_retries=max_discovery_retries,
            skip_verification=skip_verification,
            fetcher_type=fetcher_type,
            output_format=output_format,
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
    ) -> dict[str, list[str]]:
        """Process multiple URLs and collect results.

        Args:
            urls: List of URLs to process.
            force: Force re-discovery even if selectors exist. Defaults to False.
            skip_verification: Skip verification step. Defaults to False.
            fetcher_type: Type of fetcher ('simple'). Defaults to 'simple'.
            max_fetch_retries: Maximum fetch retry attempts. Defaults to 2.
            max_discovery_retries: Maximum AI discovery retry attempts. Defaults to 3.
            output_format: Format(s) for extracted content. Defaults to None (uses pipeline default).

        Returns:
            Dictionary with two keys:
                - 'successful': List of successfully processed URLs
                - 'failed': List of URLs that failed processing

        """
        # Normalise to list, fall back to pipeline default
        _raw = output_format if output_format is not None else self.output_formats
        format_to_use: list[str] = [_raw] if isinstance(_raw, str) else list(_raw)
        force_flag = self.force if force is None else force

        results: dict[str, list[str]] = {'successful': [], 'failed': []}

        run_start = time.monotonic()
        with logfire.span('process_urls', total_urls=len(urls)):
            for idx, url in enumerate(urls, 1):
                self.console.print(f'\n[bold blue]Processing URL {idx}/{len(urls)}[/bold blue]')
                self.logger.info('--- Processing URL %d/%d: %s ---', idx, len(urls), url)

                try:
                    await self.process_url(
                        url,
                        force_flag,
                        max_fetch_retries=max_fetch_retries,
                        max_discovery_retries=max_discovery_retries,
                        skip_verification=skip_verification,
                        fetcher_type=fetcher_type,
                        output_format=format_to_use,
                    )
                    results['successful'].append(url)
                except Exception as e:
                    logfire.error('Error processing URL', url=url, error=str(e))
                    self.logger.exception('Critical error processing %s', url)
                    self.console.print(f'[danger]Error processing {url}: {e}[/danger]')
                    results['failed'].append(url)

                self.console.print()

            total_elapsed = time.monotonic() - run_start
            self.console.print(
                f'[bold]Done:[/bold] {len(results["successful"])} succeeded, '
                f'{len(results["failed"])} failed '
                f'[dim]({total_elapsed:.1f}s total)[/dim]'
            )

            logfire.info(
                'Processing complete',
                total=len(urls),
                successful=len(results['successful']),
                failed=len(results['failed']),
            )

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
            fetcher_type: Type of fetcher ('simple'). Defaults to 'simple'.
            output_format: Format(s) for saving extracted content.

        Yields:
            ContentMap dicts — one per extracted item.

        """
        self._url_start = time.monotonic()

        _raw = output_format if output_format is not None else self.output_formats
        format_to_use: list[str] = [_raw] if isinstance(_raw, str) else list(_raw)
        force_flag = self.force if force is None else force

        url = await self.normalize_url(url)

        with logfire.span('scrape', url=url, force=force_flag, fetcher_type=fetcher_type):
            self.logger.info('Processing URL: %s (force=%s, fetcher=%s)', url, force_flag, fetcher_type)
            domain = self._extract_domain(url)
            fetcher = self._create_fetcher(fetcher_type)
            if not fetcher:
                raise RuntimeError(f'Invalid fetcher type: {fetcher_type}')

            async with fetcher:
                # Try using cached selectors if available
                if not force_flag:
                    cache_gen = await self._try_cached(url, domain, fetcher, skip_verification, format_to_use)
                    if cache_gen is not None:
                        async for item in cache_gen:
                            yield item
                        return

                # Fresh discovery path
                result = await self._fetch(url, fetcher, max_retries=max_fetch_retries)
                if not result:
                    raise RuntimeError(f'Failed to fetch {url}')
                assert result.html is not None, 'result.html should not be None after successful fetch'

                cleaned_html = self._clean(url, result)
                if not cleaned_html:
                    raise RuntimeError(f'HTML cleaning failed for {url}')

                selectors, used_llm = await self._discover_with_escalation(
                    url, cleaned_html, max_retries=max_discovery_retries
                )
                if not selectors:
                    raise RuntimeError(f'Selector discovery failed for {url}')

                container_selector = self._resolve_container(selectors)

                verified = self._verify(url, cleaned_html, selectors, skip_verification)
                if not verified:
                    raise RuntimeError(f'Selector verification failed for {url}')

                extracted = self._extract(url, cleaned_html, verified, container_selector)
                selectors_to_save = self._selectors_with_container(verified, container_selector)

                if not extracted:
                    self.console.print('[warning]⚠ Extraction failed, but selectors are valid[/warning]')
                    self._finish(url, domain, selectors_to_save, None, used_llm, format_to_use)
                    return

                # Validate, yield, and save
                validated_items = self._validate_items(extracted, url)
                for vi in validated_items:
                    yield vi
                save_all: ContentMap | ContentItems = (
                    validated_items if len(validated_items) > 1 else validated_items[0]
                )
                self._finish(url, domain, selectors_to_save, save_all, used_llm, format_to_use)

    # ============================================================================
    # scrape() helpers
    # ============================================================================

    async def _try_cached(
        self,
        url: str,
        domain: str,
        fetcher: HTMLFetcher,
        skip_verification: bool,
        format_to_use: list[str],
    ) -> AsyncIterator[ContentMap] | None:
        """Attempt cached-selector path. Returns an async generator if cache hit, None otherwise."""
        existing = self.storage.load_selectors(domain)
        if not existing:
            return None

        self.console.print(f'[success]✓ Found cached selectors for {domain}[/success]')
        logfire.info('Using cached selectors', domain=domain, url=url)

        items, cache_valid = await self._extract_with_cached(url, fetcher, existing, skip_verification)
        if not cache_valid:
            return None  # fall through to fresh discovery

        async def _yield_cached() -> AsyncIterator[ContentMap]:
            if items:
                validated = self._validate_items(items, url)
                for v in validated:
                    yield v
                save_content: ContentMap | ContentItems = validated if len(validated) > 1 else validated[0]
                for fmt in format_to_use:
                    self.storage.save_content(url, save_content, fmt)
            self._track_cached_success(url, domain)
            self.last_elapsed = time.monotonic() - self._url_start
            self.console.print(f'[dim]  ⏱ {self.last_elapsed:.1f}s elapsed[/dim]')

        return _yield_cached()

    def _validate_items(self, extracted: ContentMap | ContentItems, url: str) -> ContentItems:
        """Normalise extraction result to list and validate each item."""
        items_list: ContentItems = extracted if isinstance(extracted, list) else [extracted]
        return [self._validate_single_item(item, url) for item in items_list]

    @staticmethod
    def _selectors_with_container(verified: SelectorMap, container_selector: str | None) -> SelectorMap:
        """Re-attach container selector for persistence."""
        selectors_to_save = dict(verified)
        if container_selector:
            selectors_to_save['yosoi_container'] = {'primary': container_selector}
        return selectors_to_save

    def _finish(
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
        self._save_and_track(url, domain, selectors_to_save, content, used_llm, format_to_use, elapsed)
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
            # Try HTTPS first
            try:
                test_url = 'https://' + url
                async with httpx.AsyncClient() as client:
                    await client.head(test_url, timeout=3, follow_redirects=True)
                return test_url
            except httpx.HTTPError:
                # Fall back to HTTP
                return 'http://' + url
        return url

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL.

        Args:
            url: The URL that is being fetched

        Returns:
            The domain of the URL

        """
        return urlparse(url).netloc.replace('www.', '')

    def _create_fetcher(self, fetcher_type: str) -> HTMLFetcher | None:
        """Create HTML fetcher instance.

        Args:
            fetcher_type: The type of fetcher to be used to fetch HTMLs

        Returns:
            The fetcher to be used to fetch HTMLs

        """
        try:
            return create_fetcher(fetcher_type)
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
                logfire.warn('Retrying fetch', url=url, attempt=attempt)

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
                            # Raise exception to trigger retry
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
                        # Don't re-log if we just raised it ourselves above
                        if str(e) not in [
                            'No HTML content received',
                            f'Fetch failed: {getattr(result, "block_reason", "Unknown")}',
                        ]:
                            self.console.print(f'[danger]Unexpected error: {e}[/danger]')
                            self.logger.exception('Fetch error for %s', url)
                            logfire.error(
                                'Fetch error', url=url, error=str(e), attempt=attempt.retry_state.attempt_number
                            )
                        raise

        except RetryError:
            self.console.print(f'[danger]All {max_retries} attempts failed[/danger]')
            return None
        except (httpx.HTTPError, OSError, ValueError, RuntimeError):
            return None

        return None

    def _clean(self, url: str, result: FetchResult) -> str | None:
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

        # Save debug HTML if enabled
        self.debug.save_debug_html(url, cleaned_html)

        self.console.print(f'[success]Cleaned HTML ready ({len(cleaned_html):,} chars)[/success]')
        return cleaned_html

    async def _discover(self, url: str, cleaned_html: str, max_retries: int = 3) -> tuple[SelectorMap | None, bool]:
        """Discover CSS selectors with AI, using fallback heuristics if needed.

        Attempts AI-powered selector discovery with automatic retries. Falls
        back to heuristic selectors for RSS feeds or JavaScript-heavy sites.

        Args:
            url: URL being processed (for logging).
            cleaned_html: Pre-cleaned HTML content to analyze.
            max_retries: Maximum AI retry attempts. Defaults to 3.

        Returns:
            Tuple of (selectors, used_llm) where:
            - selectors: Dict mapping field names to selector configs,
              or None if discovery completely failed
            - used_llm: True if AI was used, False if using fallback heuristics

        """
        # Collect any manual selector overrides defined on the contract fields
        overrides = self.contract.get_selector_overrides()
        if overrides:
            override_fields = ', '.join(f'`{f}`' for f in overrides)
            self.console.print(f'[info]  ↳ Using selector overrides for: {override_fields}[/info]')

        # If every field has an override, skip AI entirely
        if not self.contract.field_descriptions():
            self.console.print('[step]Step 2: All fields have selector overrides — skipping AI discovery[/step]')
            logfire.info('Skipping AI discovery — all fields overridden', url=url)
            self.debug.save_debug_selectors(url, overrides)
            return overrides, False

        # Use AI discovery with retries
        def before_ai_sleep_log(retry_state: RetryCallState) -> None:
            attempt = retry_state.attempt_number
            if attempt >= 1:
                self.console.print(f'[warning]AI retry attempt {attempt}/{max_retries}...[/warning]')
                logfire.warn('Retrying AI discovery', url=url, attempt=attempt)

        # Use AI discovery with retries
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

                    # discover_selectors takes cleaned HTML and returns just selectors
                    selectors = await self.discovery.discover_selectors(cleaned_html, url)

                    if selectors:
                        # Merge manual overrides (overrides take precedence)
                        selectors.update(overrides)

                        self.console.print(f'[success]Discovered selectors for {len(selectors)} fields[/success]')

                        # Save debug selectors if enabled
                        self.debug.save_debug_selectors(url, selectors)

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

        # All attempts failed
        self.console.print(f'[danger]All {max_retries} AI attempts failed[/danger]')
        logfire.error('All AI attempts failed', url=url)
        return None, False

    async def _discover_with_escalation(
        self, url: str, cleaned_html: str, max_retries: int = 3
    ) -> tuple[SelectorMap | None, bool]:
        """Delegate to _discover — per-field escalation is handled by DiscoveryOrchestrator.

        Args:
            url: URL being processed (for logging).
            cleaned_html: Pre-cleaned HTML content to analyze.
            max_retries: Maximum AI retry attempts per field per level. Defaults to 3.

        Returns:
            Tuple of (selectors, used_llm) — same as _discover.

        """
        return await self._discover(url, cleaned_html, max_retries)

    @staticmethod
    def _pop_container(selectors: SelectorMap) -> str | None:
        """Remove and return the ``yosoi_container`` selector from a selector map.

        Args:
            selectors: Mutable selector dict (modified in-place).

        Returns:
            The primary container CSS selector string, or None.

        """
        container_entry = selectors.pop('yosoi_container', None)
        if isinstance(container_entry, dict):
            primary = container_entry.get('primary')
            if isinstance(primary, str) and primary:
                return primary
            # Handle SelectorEntry-style dicts
            if isinstance(primary, dict):
                value = primary.get('value')
                return value if isinstance(value, str) else None
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

    def _resolve_container(self, selectors: SelectorMap) -> str | None:
        """Determine the container selector from contract override or AI discovery.

        Pops ``yosoi_container`` from *selectors* as a side-effect so it is not passed
        to the verifier/extractor as a content field.

        Args:
            selectors: Mutable selector dict (modified in-place).

        Returns:
            Container CSS selector string, or None for single-item pages.

        """
        # Contract-level override takes precedence
        contract_container = self.contract.get_container_selector()
        if contract_container:
            self._pop_container(selectors)  # discard AI's _container if present
            return contract_container
        # Otherwise use AI-discovered _container
        return self._pop_container(selectors)

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
                return None, True  # fail-open

            self.console.print('[step]Cleaning HTML...[/step]')
            cleaned_html = self.cleaner.clean_html(result.html)
            self.debug.save_debug_html(url, cleaned_html)

            # Resolve container selector from cached selectors
            container_selector = self._resolve_container(existing_selectors)

            # Verify container selector before proceeding — a stale container means
            # all content extractions will silently fail, so force re-discovery.
            if container_selector and not skip_verification:
                from parsel import Selector as _PS

                from yosoi.models.selectors import coerce_selector_entry

                _entry = coerce_selector_entry(container_selector)
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
                    return None, False  # fall through to fresh discovery
                selectors_to_use = {
                    name: existing_selectors[name]
                    for name in verification.results
                    if verification.results[name].status == 'verified'
                }
                self.console.print(
                    f'[success]✓ Verified {len(selectors_to_use)}/{len(self.contract.model_fields)} cached selectors[/success]'
                )
                # If any contract fields (excluding overrides) have no cached selector,
                # fall through to fresh discovery so the new fields get discovered.
                overridden = set(self.contract.get_selector_overrides())
                required_fields = set(self.contract.model_fields) - overridden
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
                # Normalise to list
                if isinstance(extracted, list):
                    return extracted, True
                return [extracted], True

            self.console.print('[warning]⚠ Extraction failed with cached selectors[/warning]')
            return None, True  # extraction failed but cache was valid

        except BotDetectionError:
            raise
        except Exception as e:
            self.logger.exception('Cached selector handling failed for %s', url)
            self.console.print(f'[warning]⚠ Error: {e}, skipping extraction[/warning]')
            return None, True  # fail-open

    def _track_cached_success(self, url: str, domain: str) -> None:
        """Track successful use of cached selectors.

        Args:
            url: The URL that is being fetched
            domain: The domain from which the URL is grabbed

        """
        elapsed = time.monotonic() - self._url_start if hasattr(self, '_url_start') else None
        stats = self.tracker.record_url(url, used_llm=False, level_distribution=None, elapsed=elapsed)
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
        logfire.warn(
            'Bot detection triggered',
            url=error.url,
            status_code=error.status_code,
            indicators=error.indicators,
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

    def _save_and_track(
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

        Saves selectors to storage, optionally saves extracted content,
        records usage statistics, and displays tracking information to console.

        Args:
            url: URL that was processed.
            domain: Domain name.
            verified: Verified selector dictionary to save.
            extracted: Extracted content dictionary to save, or None if extraction failed.
            used_llm: Whether LLM was called for this URL.
            output_format: Format for output files ('json' or 'markdown').
            elapsed: Time in seconds spent processing this URL. Defaults to None.

        """
        # Save selectors (always JSON) and content (user's choice of format)
        self.storage.save_selectors(url, verified)

        if extracted:
            for fmt in output_format:
                self.storage.save_content(url, extracted, fmt)

        level_dist = getattr(self, '_last_level_distribution', None)
        stats = self.tracker.record_url(url, used_llm=used_llm, level_distribution=level_dist or None, elapsed=elapsed)
        self._print_tracking_stats(domain, stats)

    def _print_tracking_stats(self, domain: str, stats: 'DomainStats') -> None:
        """Print LLM tracking statistics for domain.

        Displays LLM call count, URL count, elapsed time, and efficiency metrics.

        Args:
            domain: Domain name being tracked.
            stats: DomainStats with tracking data for the domain.

        """
        self.console.print(f'\n[dim]  - Tracking Stats for {domain}:[/dim]')
        self.console.print(f'[dim]    -- LLM Calls: {stats["llm_calls"]}[/dim]')
        self.console.print(f'[dim]    -- URLs Processed: {stats["url_count"]}[/dim]')
        total_elapsed = stats.get('total_elapsed', 0.0)
        if total_elapsed:
            self.console.print(f'[dim]    -- Total Elapsed: {total_elapsed:.1f}s[/dim]')
        if stats['llm_calls'] > 0:
            efficiency = stats['url_count'] / stats['llm_calls']
            self.console.print(f'[dim]     • Efficiency: {efficiency:.1f} URLs per LLM call[/dim]')
        self.console.print()

    # ============================================================================
    # Display methods
    # ============================================================================

    def show_summary(self) -> None:
        """Show summary of all saved selectors."""
        domains = self.storage.list_domains()

        if not domains:
            self.console.print('[warning]No selectors found in storage[/warning]')
            return

        table = Table(title='Saved Selectors Summary')
        table.add_column('Domain', style='cyan')
        table.add_column('Fields', style='green')

        for domain in domains:
            selectors = self.storage.load_selectors(domain)
            if selectors:
                table.add_row(domain, str(len(selectors)))

        self.console.print(table)
        self.console.print(f'\n[success]Total domains: {len(domains)}[/success]')

    def show_llm_stats(self) -> None:
        """Show LLM usage statistics."""
        stats = self.tracker.get_all_stats()

        # Aggregate stats across all domains
        total_llm_calls = sum(domain_stats.get('llm_calls', 0) for domain_stats in stats.values())
        total_urls = sum(domain_stats.get('url_count', 0) for domain_stats in stats.values())

        self.console.print('\n[bold cyan]═══ LLM Usage Statistics ═══[/bold cyan]')
        self.console.print(f'[info]Total URLs processed: {total_urls}[/info]')
        self.console.print(f'[info]LLM calls made: {total_llm_calls}[/info]')

        if total_llm_calls > 0:
            efficiency = total_urls / total_llm_calls
            self.console.print(f'[success]Efficiency: {efficiency:.1f} URLs per LLM call[/success]')

        self.console.print()
