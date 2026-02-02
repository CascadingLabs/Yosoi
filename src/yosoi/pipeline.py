"""
pipeline.py
===========
Main pipeline for CSS selector discovery.
Centralized retry logic for bot detection and AI failures.
"""

from urllib.parse import urlparse

import logfire
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

from yosoi import LLMConfig, SelectorDiscovery
from yosoi.fetcher import BotDetectionError, FetchResult, HTMLFetcher, create_fetcher
from yosoi.storage import SelectorStorage
from yosoi.tracker import LLMTracker
from yosoi.validator import SelectorValidator


class SelectorDiscoveryPipeline:
    """Main pipeline for discovering and saving CSS selectors with retry logic."""

    def __init__(self, llm_config: LLMConfig, debug_mode: bool = False):
        """Initialize the pipeline with LLM configuration."""
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
        self.discovery = SelectorDiscovery(llm_config=llm_config, console=self.console, debug_mode=debug_mode)
        self.validator = SelectorValidator(console=self.console)
        self.storage = SelectorStorage()
        self.tracker = LLMTracker()
        self.debug_mode = debug_mode

    def process_url(
        self,
        url: str,
        force: bool = False,
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
        skip_validation: bool = False,
        fetcher_type: str = 'simple',
    ) -> bool:
        """
        Process a single URL: discover, validate, and save selectors.

        Args:
            url: URL to process
            force: If True, re-discover even if selectors exist
            max_fetch_retries: Maximum retry attempts for fetching (bot detection)
            max_discovery_retries: Maximum retry attempts for AI discovery
            skip_validation: Skip validation step
            fetcher_type: Type of HTML fetcher to use

        Returns:
            True if successful, False otherwise
        """
        with logfire.span('process_url', url=url, force=force, fetcher_type=fetcher_type):
            domain = self._extract_domain(url)
            fetcher = self._create_fetcher(fetcher_type)
            if not fetcher:
                return False

            # Try using cached selectors if available
            if not force and self._cached_selectors(url, domain, fetcher, skip_validation):
                return True

            # Fetch HTML with retry logic for bot detection
            result = self._fetch(url, fetcher, max_retries=max_fetch_retries)
            if not result:
                return False

            # Discover selectors with retry logic for AI failures
            selectors, used_llm = self._discover(url, result, max_retries=max_discovery_retries)
            if not selectors:
                return False

            # Validate selectors
            validated = self._validate(url, result.html, selectors, skip_validation)
            if not validated:
                return False

            # Save and track
            self._save_and_track(url, domain, validated, used_llm)
            return True

    def process_urls(
        self,
        urls: list[str],
        force: bool = False,
        skip_validation: bool = False,
        fetcher_type: str = 'simple',
        max_fetch_retries: int = 2,
        max_discovery_retries: int = 3,
    ) -> dict[str, list[str]]:
        """Process multiple URLs and return results."""
        results: dict[str, list[str]] = {'successful': [], 'failed': []}

        with logfire.span('process_urls', total_urls=len(urls)):
            for idx, url in enumerate(urls, 1):
                self.console.print(f'\n[bold blue]Processing URL {idx}/{len(urls)}[/bold blue]')

                try:
                    success = self.process_url(
                        url,
                        force,
                        max_fetch_retries=max_fetch_retries,
                        max_discovery_retries=max_discovery_retries,
                        skip_validation=skip_validation,
                        fetcher_type=fetcher_type,
                    )
                    results['successful' if success else 'failed'].append(url)
                except Exception as e:
                    logfire.error('Error processing URL', url=url, error=str(e))
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

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        return urlparse(url).netloc.replace('www.', '')

    def _create_fetcher(self, fetcher_type: str) -> HTMLFetcher | None:
        """Create HTML fetcher instance."""
        try:
            return create_fetcher(fetcher_type)
        except ValueError:
            self.console.print(f'[danger]Invalid fetcher type: {fetcher_type}[/danger]')
            return None

    def _fetch(self, url: str, fetcher: HTMLFetcher, max_retries: int = 2) -> FetchResult | None:
        """
        Fetch HTML with retry logic for bot detection.

        Args:
            url: URL to fetch
            fetcher: HTML fetcher instance
            max_retries: Maximum number of retry attempts

        Returns:
            FetchResult if successful, None otherwise
        """
        self.console.print(Panel(f'Processing: {url}', style='bold blue'))
        self.console.print('[step]Step 1: Fetching HTML...[/step]')

        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    self.console.print(f'[warning]Fetch retry attempt {attempt}/{max_retries}...[/warning]')
                    logfire.warn('Retrying fetch', url=url, attempt=attempt)

                result = fetcher.fetch(url)

                if not result.success:
                    self.console.print(f'[danger]Fetch failed: {result.block_reason or "Unknown error"}[/danger]')

                    # If not the last attempt, continue to retry
                    if attempt < max_retries:
                        continue
                    return None

                if result.html is None:
                    self.console.print('[danger]No HTML content received[/danger]')
                    if attempt < max_retries:
                        continue
                    return None

                self.console.print(
                    f'[success]Fetched {len(result.html):,} characters of HTML ({result.fetch_time:.2f}s)[/success]'
                )
                return result

            except BotDetectionError as e:
                self._handle_bot_detection(e, attempt, max_retries)

                # If not the last attempt, continue to retry
                if attempt < max_retries:
                    continue

                # Last attempt also failed
                raise

            except Exception as e:
                self.console.print(f'[danger]Unexpected error: {e}[/danger]')
                logfire.error('Fetch error', url=url, error=str(e), attempt=attempt)

                if attempt < max_retries:
                    continue
                return None

        return None

    def _discover(self, url: str, result: FetchResult, max_retries: int = 3) -> tuple[dict | None, bool]:
        """
        Discover selectors with retry logic for AI failures.

        Args:
            url: URL being processed
            result: Fetch result with HTML
            max_retries: Maximum number of retry attempts

        Returns:
            Tuple of (selectors, used_llm)
        """
        # Check if we should use heuristics instead of AI
        should_use_heuristics, reason = self._should_use_heuristics(result)

        if should_use_heuristics:
            self.console.print(f'[step]Step 2: Using heuristic selectors ({reason})[/step]')
            return self.discovery.fallback_selectors, False

        # Use AI discovery with retries
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                self.console.print(f'[warning]AI retry attempt {attempt}/{max_retries}...[/warning]')
                logfire.warn('Retrying AI discovery', url=url, attempt=attempt)

            self.console.print(f'[step]Step 2: AI analyzing HTML (attempt {attempt}/{max_retries})...[/step]')

            selectors = self.discovery.discover_from_html(url, result.html)

            if selectors:
                self.console.print(f'[success]Discovered selectors for {len(selectors)} fields[/success]')
                if attempt > 1:
                    self.console.print(f'[success]AI retry successful on attempt {attempt}[/success]')
                return selectors, True

            self.console.print('[danger]AI discovery failed[/danger]')

            # If not last attempt, continue
            if attempt < max_retries:
                self.console.print('[warning]Retrying AI discovery...[/warning]')
                continue

        # All attempts failed - use fallback
        self.console.print(f'[warning]All {max_retries} AI attempts failed, using fallback heuristics[/warning]')
        logfire.error('All AI attempts failed, using fallback', url=url)
        return self.discovery.fallback_selectors, False

    def _validate(self, url: str, html: str, selectors: dict, skip_validation: bool) -> dict | None:
        """Validate discovered selectors."""
        if skip_validation:
            self.console.print('[warning]Skipping validation (--skip-validation enabled)[/warning]')
            return selectors

        self.console.print('[step]Step 3: Validating selectors against actual HTML...[/step]')

        validated = self.validator.validate_selectors_with_html(url, html, selectors)

        if not validated:
            self.console.print('[danger]No selectors validated successfully - all selectors failed![/danger]')
            return None

        failed_count = len(selectors) - len(validated)
        self.console.print(f'[success]Validated {len(validated)}/5 fields successfully[/success]')

        if failed_count >= 2:
            self.console.print(f'[warning]Warning: {failed_count} fields failed validation[/warning]')

        return validated

    def _cached_selectors(self, url: str, domain: str, fetcher: HTMLFetcher, skip_validation: bool) -> bool:
        """Try to use cached selectors if available."""
        existing_selectors = self.storage.load_selectors(domain)
        if not existing_selectors:
            return False

        self.console.print(f'[success]✓ Found cached selectors for {domain}[/success]')
        logfire.info('Using cached selectors', domain=domain, url=url)

        if skip_validation:
            self._track_cached_success(url, domain)
            return True

        # Validate cached selectors
        return self._validate_cached_selectors(url, domain, fetcher, existing_selectors)

    def _validate_cached_selectors(self, url: str, domain: str, fetcher: HTMLFetcher, existing_selectors: dict) -> bool:
        """Validate cached selectors against current HTML."""
        self.console.print('[step]Fetching HTML to validate cached selectors...[/step]')

        try:
            result = fetcher.fetch(url)

            if not result.success or result.html is None:
                self.console.print('[warning]⚠ Could not fetch HTML, using cached selectors as-is[/warning]')
                self._track_cached_success(url, domain)
                return True

            validated = self.validator.validate_selectors_with_html(url, result.html, existing_selectors)

            if validated:
                self.console.print(f'[success]✓ Validated {len(validated)}/5 cached selectors[/success]')
                self._track_cached_success(url, domain)
                return True

            self.console.print('[warning]⚠ Cached selectors failed validation - forcing re-discovery[/warning]')
            return False

        except BotDetectionError:
            raise
        except Exception as e:
            self.console.print(f'[warning]⚠ Validation error: {e}, using cached selectors as-is[/warning]')
            self._track_cached_success(url, domain)
            return True

    def _track_cached_success(self, url: str, domain: str):
        """Track successful use of cached selectors."""
        stats = self.tracker.record_url(url, used_llm=False)
        self._print_tracking_stats(domain, stats)

    def _handle_bot_detection(self, error: BotDetectionError, attempt: int, max_retries: int):
        """Handle bot detection error."""
        self.console.print(f'[danger]BOT DETECTION (Attempt {attempt}/{max_retries})[/danger]')
        self.console.print(f'[danger]URL: {error.url}[/danger]')
        self.console.print(f'[danger]Status Code: {error.status_code}[/danger]')
        self.console.print(f'[danger]Indicators: {", ".join(error.indicators)}[/danger]')

        if attempt >= max_retries:
            self.console.print('[danger]ABORTING - All fetch attempts exhausted[/danger]')
            self.console.print('[info]Try: --fetcher smart (or) --fetcher playwright[/info]')

    def _should_use_heuristics(self, result: FetchResult) -> tuple[bool, str]:
        """Determine if we should use heuristics instead of AI."""
        if result.is_rss:
            self.console.print('[info]RSS feed detected - using heuristics[/info]')
            return True, 'RSS feed'

        if result.requires_js:
            framework = result.metadata.js_framework or 'unknown'
            self.console.print(f'[info]JavaScript-heavy site ({framework}) - using heuristics[/info]')
            return True, f'JS-heavy ({framework})'

        return False, ''

    def _save_and_track(self, url: str, domain: str, validated: dict, used_llm: bool):
        """Save selectors and track usage."""
        self.storage.save_selectors(url, validated)
        stats = self.tracker.record_url(url, used_llm=used_llm)
        self._print_tracking_stats(domain, stats)

    def _print_tracking_stats(self, domain: str, stats: dict):
        """Print LLM tracking statistics for this domain."""
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
        import os

        selectors_dir = 'selectors'

        if not os.path.exists(selectors_dir):
            self.console.print('[warning]No selectors directory found[/warning]')
            return

        files = [f for f in os.listdir(selectors_dir) if f.endswith('.json')]

        if not files:
            self.console.print('[warning]No selector files found[/warning]')
            return

        table = Table(title='Saved Selectors Summary')
        table.add_column('Domain', style='cyan')
        table.add_column('Fields', style='green')

        for file in sorted(files):
            domain = file.replace('selectors_', '').replace('.json', '').replace('_', '.')
            try:
                selectors = self.storage.load_selectors(domain)
                if selectors:
                    table.add_row(domain, str(len(selectors)))
            except Exception:
                continue

        self.console.print(table)
        self.console.print(f'\n[success]Total domains: {len(files)}[/success]')

    def show_llm_stats(self):
        """Show LLM usage statistics."""
        stats = self.tracker.get_all_stats()

        self.console.print('\n[bold cyan]═══ LLM Usage Statistics ═══[/bold cyan]')
        self.console.print(f'[info]Total URLs processed: {stats.get("total_urls", 0)}[/info]')
        self.console.print(f'[info]LLM calls made: {stats.get("llm_calls", 0)}[/info]')
        self.console.print(f'[info]Cache hits: {stats.get("cache_hits", 0)}[/info]')

        if stats.get('llm_calls', 0) > 0:
            efficiency = stats.get('total_urls', 0) / stats.get('llm_calls', 1)
            self.console.print(f'[success]Efficiency: {efficiency:.1f} URLs per LLM call[/success]')

        self.console.print()
