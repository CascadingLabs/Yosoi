"""Main pipeline for selector discovery.

Centralized retry logic for bot detection and AI failures.
"""

import logging
from urllib.parse import urlparse

import logfire
import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from tenacity import RetryError

from yosoi.core.cleaning import HTMLCleaner
from yosoi.core.discovery import LLMConfig, SelectorDiscovery
from yosoi.core.extraction import ContentExtractor
from yosoi.core.fetcher import HTMLFetcher, create_fetcher
from yosoi.core.verification import SelectorVerifier
from yosoi.models import FetchResult
from yosoi.storage import DebugManager, LLMTracker, SelectorStorage
from yosoi.utils.exceptions import BotDetectionError
from yosoi.utils.retry import get_retryer


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

    def __init__(self, llm_config: LLMConfig, debug_mode: bool = False, output_format: str = 'json'):
        """Initialize the pipeline with LLM configuration.

        Args:
            llm_config: Configuration of LLM
            debug_mode: If enabled will output the HTML from the URL
            output_format: Format for extracted content ('json' or 'markdown'). Defaults to 'json'.

        """
        self.custom_theme = Theme(
            {
                'info': 'dim cyan',
                'warning': 'magenta',
                'danger': 'bold red',
                'success': 'bold green',
                'step': 'bold blue',
            }
        )
        self.console = Console(theme=self.custom_theme)
        self.cleaner = HTMLCleaner(console=self.console)
        self.discovery = SelectorDiscovery(llm_config=llm_config, console=self.console)
        self.verifier = SelectorVerifier(console=self.console)
        self.extractor = ContentExtractor(console=self.console)
        self.storage = SelectorStorage()
        self.tracker = LLMTracker()
        self.debug_mode = debug_mode
        self.debug = DebugManager(console=self.console, enabled=debug_mode)
        self.output_format = output_format
        self.logger = logging.getLogger(__name__)

    def process_url(
        self,
        url: str,
        force: bool = False,
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
        skip_verification: bool = False,
        fetcher_type: str = 'simple',
        output_format: str | None = None,
    ) -> bool:
        """Process a single URL: discover, verify, and save selectors.

        Args:
            url: URL to process
            force: Force re-discovery even if selectors exist. Defaults to False.
            skip_verification: Skip verification step. Defaults to False.
            fetcher_type: Type of fetcher ('simple', 'playwright', 'smart'). Defaults to 'simple'.
            max_fetch_retries: Maximum fetch retry attempts. Defaults to 2.
            max_discovery_retries: Maximum AI discovery retry attempts. Defaults to 3.
            output_format: Format for extracted content ('json' or 'markdown').
                          Defaults to None (uses pipeline default).

        Returns:
            True if operation succeeded, False otherwise.

        """
        # Use provided format or fall back to pipeline default
        format_to_use = output_format or self.output_format

        url = self.normalize_url(url)

        with logfire.span('process_url', url=url, force=force, fetcher_type=fetcher_type):
            self.logger.info(f'Processing URL: {url} (force={force}, fetcher={fetcher_type})')
            domain = self._extract_domain(url)
            fetcher = self._create_fetcher(fetcher_type)
            if not fetcher:
                return False

            # Try using cached selectors if available
            if not force and self._cached_selectors(url, domain, fetcher, skip_verification, format_to_use):
                return True

            # Fetch HTML with retry logic for bot detection
            result = self._fetch(url, fetcher, max_retries=max_fetch_retries)
            if not result:
                return False

            # At this point, result.html should never be None (checked in _fetch)
            assert result.html is not None, 'result.html should not be None after successful fetch'

            # Clean HTML (Step 1.5)
            cleaned_html = self._clean(url, result)
            if not cleaned_html:
                return False

            # Discover selectors with retry logic for AI failures (Step 2)
            # Returns: (selectors, used_llm)
            selectors, used_llm = self._discover(url, cleaned_html, max_retries=max_discovery_retries)
            if not selectors:
                return False

            # Verify selectors using cleaned HTML (Step 3)
            verified = self._verify(url, cleaned_html, selectors, skip_verification)
            if not verified:
                return False

            # Extract content using verified selectors and cleaned HTML (Step 4)
            extracted = self._extract(url, cleaned_html, verified)
            # Note: extraction can fail but we still save the selectors
            if not extracted:
                self.console.print('[warning]⚠ Extraction failed, but selectors are valid[/warning]')

            # Save and track (save selectors + content if extracted)
            self._save_and_track(url, domain, verified, extracted, used_llm, format_to_use)
            return True

    def process_urls(
        self,
        urls: list[str],
        force: bool = False,
        skip_verification: bool = False,
        fetcher_type: str = 'simple',
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
        output_format: str | None = None,
    ) -> dict[str, list[str]]:
        """Process multiple URLs and collect results.

        Args:
            urls: List of URLs to process.
            force: Force re-discovery even if selectors exist. Defaults to False.
            skip_verification: Skip verification step. Defaults to False.
            fetcher_type: Type of fetcher ('simple', 'playwright', 'smart'). Defaults to 'simple'.
            max_fetch_retries: Maximum fetch retry attempts. Defaults to 2.
            max_discovery_retries: Maximum AI discovery retry attempts. Defaults to 3.
            output_format: Format for extracted content ('json' or 'markdown').
                          Defaults to None (uses pipeline default).

        Returns:
            Dictionary with two keys:
                - 'successful': List of successfully processed URLs
                - 'failed': List of URLs that failed processing

        """
        # Use provided format or fall back to pipeline default
        format_to_use = output_format or self.output_format

        results: dict[str, list[str]] = {'successful': [], 'failed': []}

        with logfire.span('process_urls', total_urls=len(urls)):
            for idx, url in enumerate(urls, 1):
                self.console.print(f'\n[bold blue]Processing URL {idx}/{len(urls)}[/bold blue]')
                self.logger.info(f'--- Processing URL {idx}/{len(urls)}: {url} ---')

                try:
                    success = self.process_url(
                        url,
                        force,
                        max_fetch_retries=max_fetch_retries,
                        max_discovery_retries=max_discovery_retries,
                        skip_verification=skip_verification,
                        fetcher_type=fetcher_type,
                        output_format=format_to_use,
                    )
                    results['successful' if success else 'failed'].append(url)
                except Exception as e:
                    logfire.error('Error processing URL', url=url, error=str(e))
                    self.logger.exception(f'Critical error processing {url}')
                    self.console.print(f'[danger]Error processing {url}: {e}[/danger]')
                    results['failed'].append(url)

                self.console.print()

            logfire.info(
                'Processing complete',
                total=len(urls),
                successful=len(results['successful']),
                failed=len(results['failed']),
            )

        return results

    # ============================================================================
    # Private helper methods
    # ============================================================================

    def normalize_url(self, url: str) -> str:
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
                requests.head(test_url, timeout=3)
                return test_url
            except requests.exceptions.RequestException:
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

    def _fetch(self, url: str, fetcher: HTMLFetcher, max_retries: int = 2) -> FetchResult | None:
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

        def before_sleep_log(retry_state):
            attempt = retry_state.attempt_number
            if attempt >= 1:
                self.console.print(f'[warning]Fetch retry attempt {attempt}/{max_retries}...[/warning]')
                logfire.warn('Retrying fetch', url=url, attempt=attempt)

        try:
            retryer = get_retryer(
                max_attempts=max_retries,
                wait_min=1,
                wait_max=10,
                exceptions=(BotDetectionError, Exception),
                log_callback=before_sleep_log,
            )

            for attempt in retryer:
                with attempt:
                    try:
                        result = fetcher.fetch(url)

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

                    except Exception as e:
                        # Don't re-log if we just raised it ourselves above
                        if str(e) not in [
                            'No HTML content received',
                            f'Fetch failed: {getattr(result, "block_reason", "Unknown")}',
                        ]:
                            self.console.print(f'[danger]Unexpected error: {e}[/danger]')
                            self.logger.exception(f'Fetch error for {url}')
                            logfire.error(
                                'Fetch error', url=url, error=str(e), attempt=attempt.retry_state.attempt_number
                            )
                        raise

        except RetryError:
            self.console.print(f'[danger]All {max_retries} attempts failed[/danger]')
            return None
        except Exception:
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

    def _discover(self, url: str, cleaned_html: str, max_retries: int = 3) -> tuple[dict | None, bool]:
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

        # Use AI discovery with retries
        def before_ai_sleep_log(retry_state):
            attempt = retry_state.attempt_number
            if attempt >= 1:
                self.console.print(f'[warning]AI retry attempt {attempt}/{max_retries}...[/warning]')
                logfire.warn('Retrying AI discovery', url=url, attempt=attempt)

        # Use AI discovery with retries
        try:
            retryer = get_retryer(
                max_attempts=max_retries,
                wait_min=1,
                wait_max=10,
                exceptions=(Exception,),
                log_callback=before_ai_sleep_log,
            )

            for attempt in retryer:
                with attempt:
                    self.console.print(
                        f'[step]Step 2: AI analyzing HTML (attempt {attempt.retry_state.attempt_number}/{max_retries})...[/step]'
                    )

                    # discover_selectors takes cleaned HTML and returns just selectors
                    selectors = self.discovery.discover_selectors(cleaned_html, url)

                    if selectors:
                        self.console.print(f'[success]Discovered selectors for {len(selectors)} fields[/success]')

                        # Save debug selectors if enabled
                        self.debug.save_debug_selectors(url, selectors)

                        if attempt.retry_state.attempt_number > 1:
                            self.console.print(
                                f'[success]AI retry successful on attempt {attempt.retry_state.attempt_number}[/success]'
                            )
                        return selectors, True

                    self.console.print('[danger]AI discovery failed[/danger]')
                    self.logger.warning(f'AI discovery failed for {url}')
                    raise Exception('AI discovery failed')

        except RetryError:
            pass
        except Exception:
            pass

        # All attempts failed - use fallback
        # All attempts failed
        self.console.print(f'[danger]All {max_retries} AI attempts failed[/danger]')
        logfire.error('All AI attempts failed', url=url)
        return None, False

    def _verify(self, _url: str, html: str, selectors: dict, skip_verification: bool) -> dict | None:
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

        result = self.verifier.verify(html, selectors)

        if not result.success:
            self._print_verification_failure(result)
            return None

        verified = {name: selectors[name] for name in result.results if result.results[name].status == 'verified'}

        failed_count = len(selectors) - len(verified)
        self.console.print(f'[success]Verified {len(verified)}/{result.total_fields} fields successfully[/success]')

        if failed_count >= 1:
            self._print_partial_failure(result)

        return verified

    def _print_verification_failure(self, result) -> None:
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

    def _print_partial_failure(self, result) -> None:
        """Print summary of partial failures."""
        failed_fields = [name for name in result.results if result.results[name].status == 'failed']
        self.console.print(f'[warning]  ⚠ {len(failed_fields)} field(s) failed verification:[/warning]')
        for field_name in failed_fields:
            field_result = result.results[field_name]
            reasons = [f.reason for f in field_result.failed_selectors if f.reason != 'na_selector']
            primary_reason = reasons[0] if reasons else 'all_na'
            self.console.print(f'      [dim]• {field_name}:[/dim] {primary_reason}')

    def _extract(self, url: str, html: str, verified_selectors: dict) -> dict | None:
        """Extract content from HTML using verified selectors.

        Args:
            url: URL being processed (for logging).
            html: Cleaned HTML content to extract from.
            verified_selectors: Verified selectors to use for extraction.

        Returns:
            Dictionary of extracted content by field name, or None if extraction failed.

        """
        self.console.print('[step]Step 4: Extracting content using verified selectors...[/step]')

        extracted = self.extractor.extract_content_with_html(url, html, verified_selectors)

        if not extracted:
            self.console.print('[danger]Content extraction failed - no content extracted[/danger]')
            return None

        self.console.print(f'[success]Extracted content from {len(extracted)} fields successfully[/success]')
        return extracted

    def _cached_selectors(
        self, url: str, domain: str, fetcher: HTMLFetcher, skip_verification: bool, output_format: str
    ) -> bool:
        """Try to use cached selectors if available.

        Checks if selectors exist for the domain, verifies them against
        the current URL, extracts content, and tracks usage.

        Args:
            url: URL being processed.
            domain: Domain name extracted from URL.
            fetcher: HTML fetcher instance for verification.
            skip_verification: Skip verification of cached selectors. Defaults to False.
            output_format: Format for extracted content ('json' or 'markdown').

        Returns:
            True if cached selectors found and used successfully,
            False if no cached selectors exist or verification failed.

        """
        existing_selectors = self.storage.load_selectors(domain)
        if not existing_selectors:
            return False

        self.console.print(f'[success]✓ Found cached selectors for {domain}[/success]')
        logfire.info('Using cached selectors', domain=domain, url=url)

        if skip_verification:
            # Still need to fetch and extract even if skipping verification
            self._extract_with_cached_selectors(url, domain, fetcher, existing_selectors, output_format)
            return True

        # Verify and extract with cached selectors
        return self._verify_and_extract_cached(url, domain, fetcher, existing_selectors, output_format)

    def _verify_and_extract_cached(
        self, url: str, domain: str, fetcher: HTMLFetcher, existing_selectors: dict, output_format: str
    ) -> bool:
        """Verify cached selectors and extract content from current URL.

        Fetches HTML, verifies cached selectors, and extracts content.
        Falls back to using cached selectors as-is if fetch or verification fails.

        Args:
            url: URL to fetch and verify against.
            domain: Domain name (for logging and tracking).
            fetcher: HTML fetcher instance.
            existing_selectors: Previously discovered selectors to verify.
            output_format: Format for extracted content ('json' or 'markdown').

        Returns:
            True if selectors verified successfully or fetch failed (uses cached
            selectors as-is). False if verification explicitly failed (triggers
            re-discovery).

        Raises:
            BotDetectionError: Passes through bot detection from fetcher.

        """
        self.console.print('[step]Fetching HTML to verify cached selectors...[/step]')

        try:
            result = fetcher.fetch(url)

            if not result.success or result.html is None:
                self.console.print('[warning]⚠ Could not fetch HTML, skipping extraction[/warning]')
                self._track_cached_success(url, domain)
                return True

            # Clean HTML
            self.console.print('[step]Cleaning HTML...[/step]')
            cleaned_html = self.cleaner.clean_html(result.html)

            # Save debug HTML if enabled
            self.debug.save_debug_html(url, cleaned_html)

            # Verify selectors
            verified = self.verifier.verify_selectors_with_html(url, cleaned_html, existing_selectors)

            if verified:
                self.console.print(f'[success]✓ Verified {len(verified)}/5 cached selectors[/success]')

                # Extract content using verified cached selectors
                extracted = self._extract(url, cleaned_html, verified)

                # Save extracted content
                if extracted:
                    self.storage.save_content(url, extracted, output_format)
                else:
                    self.console.print('[warning]⚠ Extraction failed with cached selectors[/warning]')

                self._track_cached_success(url, domain)
                return True

            self.console.print('[warning]⚠ Cached selectors failed verification - forcing re-discovery[/warning]')
            return False

        except BotDetectionError:
            raise
        except Exception as e:
            self.logger.exception(f'Cached selector verification failed for {url}')
            self.console.print(f'[warning]⚠ Verification error: {e}, skipping extraction[/warning]')
            self._track_cached_success(url, domain)
            return True

    def _extract_with_cached_selectors(
        self, url: str, domain: str, fetcher: HTMLFetcher, existing_selectors: dict, output_format: str
    ):
        """Extract content using cached selectors without verification.

        Args:
            url: URL to fetch and extract from.
            domain: Domain name (for logging and tracking).
            fetcher: HTML fetcher instance.
            existing_selectors: Previously discovered selectors to use.
            output_format: Format for extracted content ('json' or 'markdown').

        """
        self.console.print('[step]Fetching HTML for extraction with cached selectors...[/step]')

        try:
            result = fetcher.fetch(url)

            if not result.success or result.html is None:
                self.console.print('[warning]⚠ Could not fetch HTML, skipping extraction[/warning]')
                self._track_cached_success(url, domain)
                return

            # Clean HTML
            self.console.print('[step]Cleaning HTML...[/step]')
            cleaned_html = self.cleaner.clean_html(result.html)

            # Save debug HTML if enabled
            self.debug.save_debug_html(url, cleaned_html)

            # Extract content (no verification)
            extracted = self._extract(url, cleaned_html, existing_selectors)

            # Save extracted content
            if extracted:
                self.storage.save_content(url, extracted, output_format)
            else:
                self.console.print('[warning]⚠ Extraction failed with cached selectors[/warning]')

            self._track_cached_success(url, domain)

        except Exception as e:
            self.console.print(f'[warning]⚠ Extraction error: {e}[/warning]')
            self._track_cached_success(url, domain)

    def _track_cached_success(self, url: str, domain: str):
        """Track successful use of cached selectors.

        Args:
            url: The URL that is being fetched
            domain: The domain from which the URL is grabbed

        """
        stats = self.tracker.record_url(url, used_llm=False)
        self._print_tracking_stats(domain, stats)

    def _handle_bot_detection(self, error: BotDetectionError, attempt: int, max_retries: int):
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

        if attempt >= max_retries:
            self.console.print('[danger]ABORTING - All fetch attempts exhausted[/danger]')
            self.console.print('[info]Try: --fetcher smart (or) --fetcher playwright[/info]')

    def _save_and_track(
        self, url: str, domain: str, verified: dict, extracted: dict | None, used_llm: bool, output_format: str
    ):
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

        """
        # Save selectors (always JSON) and content (user's choice of format)
        self.storage.save_selectors(url, verified)

        if extracted:
            self.storage.save_content(url, extracted, output_format)

        stats = self.tracker.record_url(url, used_llm=used_llm)
        self._print_tracking_stats(domain, stats)

    def _print_tracking_stats(self, domain: str, stats: dict):
        """Print LLM tracking statistics for domain.

        Displays LLM call count, URL count, and efficiency metrics.

        Args:
            domain: Domain name being tracked.
            stats: Statistics dictionary with 'llm_calls' and 'url_count' keys.

        """
        self.console.print(f'\n[dim]  - Tracking Stats for {domain}:[/dim]')
        self.console.print(f'[dim]    -- LLM Calls: {stats["llm_calls"]}[/dim]')
        self.console.print(f'[dim]    -- URLs Processed: {stats["url_count"]}[/dim]')
        if stats['llm_calls'] > 0:
            efficiency = stats['url_count'] / stats['llm_calls']
            self.console.print(f'[dim]     • Efficiency: {efficiency:.1f} URLs per LLM call[/dim]')
        self.console.print()

    # ============================================================================
    # Display methods
    # ============================================================================

    def show_summary(self):
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

    def show_llm_stats(self):
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
