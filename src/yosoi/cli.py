"""
cli.py
=======
Main entry point for CSS selector discovery system.
"""

import argparse
import os
import sys
from urllib.parse import urlparse

import logfire
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

from yosoi.discovery import SelectorDiscovery
from yosoi.fetcher import BotDetectionError, create_fetcher
from yosoi.storage import SelectorStorage
from yosoi.tracker import LLMTracker
from yosoi.validator import SelectorValidator


class SelectorDiscoveryPipeline:
    """Main pipeline for discovering and saving CSS selectors."""

    def __init__(self, ai_api_key: str, model_name: str, provider: str = 'groq', debug_mode: bool = False):
        """Initialize the pipeline with API key."""

        # Initialize Rich Console
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

        # Initialize components
        self.discovery = SelectorDiscovery(
            model_name=model_name, api_key=ai_api_key, provider=provider, console=self.console, debug_mode=debug_mode
        )
        self.validator = SelectorValidator(console=self.console)
        self.storage = SelectorStorage()
        self.tracker = LLMTracker()
        self.debug_mode = debug_mode

    def process_url(  # noqa: C901
        self,
        url: str,
        force: bool = False,
        max_discovery_attempts: int = 2,
        skip_validation: bool = False,
        fetcher_type: str = 'simple',  # 'simple', 'playwright', or 'smart'
    ) -> bool:
        """
        Process a single URL: discover, validate, and save selectors.

        Args:
            url: URL to process
            force: If True, re-discover even if selectors exist
            max_discovery_attempts: Maximum retry attempts for discovery
            skip_validation: Skip validation step
            fetcher_type: Type of HTML fetcher to use

        Returns:
            True if successful, False otherwise
        """
        with logfire.span('process_url', url=url, force=force, fetcher_type=fetcher_type):
            # Extract domain
            domain = urlparse(url).netloc.replace('www.', '')

            # Initialize fetcher early (needed for both cache validation and discovery)
            try:
                fetcher = create_fetcher(fetcher_type)
            except ValueError:
                self.console.print(f'[danger]Invalid fetcher type: {fetcher_type}[/danger]')
                return False

            # Step 0: Check if selectors already exist (unless force=True)
            if not force:
                existing_selectors = self.storage.load_selectors(domain)
                if existing_selectors:
                    self.console.print(f'[success]✓ Found cached selectors for {domain}[/success]')
                    logfire.info('Using cached selectors', domain=domain, url=url)

                    # NEW: Validate cached selectors unless skip_validation is set
                    if not skip_validation:
                        # Fetch HTML for validation
                        self.console.print('[step]Fetching HTML to validate cached selectors...[/step]')
                        try:
                            result = fetcher.fetch(url)

                            if not result.success:
                                self.console.print(
                                    '[warning]⚠ Could not fetch HTML for validation, using cached selectors as-is[/warning]'
                                )
                                # Use cached selectors anyway if fetch failed
                                stats = self.tracker.record_url(url, used_llm=False)
                                self._print_tracking_stats(domain, stats)
                                return True
                            # Validate cached selectors
                            self.console.print('[step]Validating cached selectors...[/step]')
                            validated = self.validator.validate_selectors_with_html(
                                url, result.html, existing_selectors
                            )

                            if not validated:
                                self.console.print(
                                    '[warning]⚠ Cached selectors failed validation - forcing re-discovery[/warning]'
                                )
                                logfire.warn('Cached selectors failed validation', domain=domain, url=url)
                                # Don't return - fall through to re-discovery
                            else:
                                self.console.print(
                                    f'[success]✓ Validated {len(validated)}/{len(existing_selectors)} cached selectors[/success]'
                                )
                                logfire.info('Cached selectors validated', domain=domain, fields=len(validated))
                                stats = self.tracker.record_url(url, used_llm=False)
                                self._print_tracking_stats(domain, stats)
                                return True
                        except BotDetectionError:
                            raise  # Re-raise bot detection
                        except Exception as e:
                            self.console.print(
                                f'[warning]⚠ Validation error: {e}, using cached selectors as-is[/warning]'
                            )
                            logfire.error('Cached selector validation error', url=url, error=str(e))
                            # Use cached selectors anyway if validation error
                            stats = self.tracker.record_url(url, used_llm=False)
                            self._print_tracking_stats(domain, stats)
                            return True
                    else:
                        # Skip validation was requested
                        self.console.print('[info]Using cached selectors (validation skipped)[/info]')
                        stats = self.tracker.record_url(url, used_llm=False)
                        self._print_tracking_stats(domain, stats)
                        return True

            self.console.print(Panel(f'Processing: {url}', style='bold blue'))

            # Step 1: Fetch HTML ONCE
            with logfire.span('fetch_html', url=url, fetcher_type=fetcher_type):
                self.console.print('[step]Step 1: Fetching HTML...[/step]')

                try:
                    result = fetcher.fetch(url)

                    if not result.success:
                        if result.block_reason:
                            self.console.print(f'[danger]Fetch failed: {result.block_reason}[/danger]')
                        else:
                            self.console.print('[danger]Fetch failed[/danger]')
                        return False

                    html = result.html
                    self.console.print(
                        f'[success]Fetched {len(html):,} characters of HTML ({result.fetch_time:.2f}s)[/success]'
                    )

                except BotDetectionError as e:
                    # BOT DETECTION - ABORT IMMEDIATELY
                    self.console.print('[danger]BOT DETECTION TRIGGERED[/danger]')
                    self.console.print(f'[danger]URL: {e.url}[/danger]')
                    self.console.print(f'[danger]Status Code: {e.status_code}[/danger]')
                    self.console.print(f'[danger]Indicators: {", ".join(e.indicators)}[/danger]')
                    self.console.print(
                        '[danger]ABORTING - Use a different fetcher or implement anti-bot measures[/danger]'
                    )
                    logfire.error(
                        'Bot detection triggered', url=url, status_code=e.status_code, indicators=e.indicators
                    )

                    # Stop processing - raise to stop batch if desired
                    raise

                except Exception as e:
                    self.console.print(f'[danger]Unexpected error: {e}[/danger]')
                    logfire.error('Fetch error', url=url, error=str(e))
                    return False

            # NEW: Check content metadata and decide whether to use AI or heuristics
            use_heuristics = False
            heuristic_reason = None

            if result.is_rss:
                use_heuristics = True
                heuristic_reason = 'RSS feed detected'
                self.console.print('[info]RSS feed detected - using heuristics[/info]')
                logfire.info('RSS feed detected, skipping AI', url=url)

            elif result.is_tailwind_heavy:
                use_heuristics = True
                heuristic_reason = f'Heavy Tailwind usage ({result.metadata.tailwind_class_count} utility classes)'
                self.console.print(
                    f'[info]Heavy Tailwind CSS detected ({result.metadata.tailwind_class_count} classes) - using heuristics[/info]'
                )
                logfire.info(
                    'Tailwind-heavy site, skipping AI', url=url, tailwind_count=result.metadata.tailwind_class_count
                )

            elif result.requires_js:
                use_heuristics = True
                framework = result.metadata.js_framework or 'unknown'
                heuristic_reason = f'JavaScript-heavy site ({framework})'
                self.console.print(f'[info]JavaScript-heavy site detected ({framework}) - using heuristics[/info]')
                logfire.info('JS-heavy site, skipping AI', url=url, framework=framework)

                # Suggest Playwright if using SimpleFetcher
                if fetcher_type == 'simple':
                    self.console.print('[warning]Tip: Try --fetcher playwright for better JS rendering[/warning]')

            # Use heuristics if special content detected
            if use_heuristics:
                self.console.print('[step]Step 2: Using heuristic selectors (AI skipped)[/step]')
                selectors = self.discovery.fallback_selectors
                used_llm = False

                logfire.info('Skipped AI, used heuristics', url=url, reason=heuristic_reason)
            else:
                # Normal AI discovery flow
                for attempt in range(1, max_discovery_attempts + 1):
                    logfire.info('Discovery attempt', url=url, attempt=attempt, max_attempts=max_discovery_attempts)

                    # Step 2: Discover selectors with LLM (using the HTML we already fetched)
                    with logfire.span('discovery_selectors', url=url, attempt=attempt):
                        self.console.print('[step]Step 2: AI analyzing HTML...[/step]')

                        selectors = self.discovery.discover_from_html(url, html)

                        if not selectors:
                            logfire.error('Discovery failed', url=url, attempt=attempt)
                            self.console.print('[danger]AI could not find selectors[/danger]')
                            if attempt < max_discovery_attempts:
                                self.console.print('[warning]Retrying...[/warning]')
                                continue
                            return False

                        self.console.print(f'[success]Discovered selectors for {len(selectors)} fields[/success]')
                        used_llm = True
                        break  # Success, exit retry loop

            # Step 3: Validate selectors (using the SAME HTML - no re-fetch!)
            if skip_validation:
                self.console.print('[warning]Skipping validation (--skip-validation enabled)[/warning]')
                validated = selectors
                logfire.info('Validation skipped', url=url, skip_validation=True)
            else:
                with logfire.span('validate_selectors', url=url):
                    self.console.print('[step]Step 3: Validating selectors against actual HTML...[/step]')

                    # Validate using the HTML we already have (no re-fetch!)
                    validated = self.validator.validate_selectors_with_html(url, html, selectors)

                    if not validated:
                        logfire.error('No selectors validated', url=url)
                        self.console.print(
                            '[danger]No selectors validated successfully - all selectors failed![/danger]'
                        )
                        return False

                    # Show validation results
                    failed_count = len(selectors) - len(validated)
                    self.console.print(
                        f'[success]Validated {len(validated)}/{len(selectors)} fields successfully[/success]'
                    )

                    # Check if too many failed
                    if failed_count >= 2:
                        logfire.warn('Too many validations failed', url=url, failed_count=failed_count)
                        self.console.print(f'[warning]Warning: {failed_count} fields failed validation[/warning]')

            # Success! Save selectors
            with logfire.span('save_selectors', url=url, domain=domain):
                self.storage.save_selectors(url, validated)

            logfire.info('Processing complete', url=url, domain=domain, fields_saved=len(validated))

            stats = self.tracker.record_url(url, used_llm=used_llm)
            self._print_tracking_stats(domain, stats)

            return True

    def _print_tracking_stats(self, domain: str, stats: dict):
        """Print LLM tracking statistics for this domain."""
        self.console.print(f'\n[dim]  - Tracking Stats for {domain}:[/dim]')
        self.console.print(f'[dim]    -- LLM Calls: {stats["llm_calls"]}[/dim]')
        self.console.print(f'[dim]    -- URLs Processed: {stats["url_count"]}[/dim]')
        if stats['llm_calls'] > 0:
            efficiency = stats['url_count'] / stats['llm_calls']
            self.console.print(f'[dim]     • Efficiency: {efficiency:.1f} URLs per LLM call[/dim]')
        self.console.print()

    def process_urls(  # noqa: C901
        self, urls: list, force: bool = False, skip_validation: bool = False, fetcher_type: str = 'simple'
    ):
        """Process multiple URLs."""
        results: dict[str, list] = {'successful': [], 'failed': [], 'skipped': []}

        with logfire.span('process_urls', total_urls=len(urls)):
            for idx, url in enumerate(urls, 1):
                self.console.print(f'\n[bold blue]Processing URL {idx}/{len(urls)}[/bold blue]')

                with logfire.span('Processing URL', url=url):
                    logfire.info('Processing URL', url=url)
                    try:
                        success = self.process_url(
                            url, force=force, skip_validation=skip_validation, fetcher_type=fetcher_type
                        )
                        if success:
                            results['successful'].append(url)
                        else:
                            results['failed'].append(url)
                    except Exception as e:
                        logfire.error('Error processing URL', url=url, error=str(e))
                        self.console.print(f'[danger]Error processing {url}: {e}[/danger]')
                        results['failed'].append(url)

                    self.console.print()  # Blank line between URLs

            logfire.info(
                'Processing complete',
                total=len(urls),
                successful=len(results['successful']),
                failed=len(results['failed']),
            )

    def show_summary(self):
        """Show summary of all saved selectors."""
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
        stats = self.tracker.get_stats()

        self.console.print('\n[bold cyan]═══ LLM Usage Statistics ═══[/bold cyan]')
        self.console.print(f'[info]Total URLs processed: {stats.get("total_urls", 0)}[/info]')
        self.console.print(f'[info]LLM calls made: {stats.get("llm_calls", 0)}[/info]')
        self.console.print(f'[info]Cache hits: {stats.get("cache_hits", 0)}[/info]')

        if stats.get('llm_calls', 0) > 0:
            efficiency = stats.get('total_urls', 0) / stats.get('llm_calls', 1)
            self.console.print(f'[success]Efficiency: {efficiency:.1f} URLs per LLM call[/success]')

        self.console.print()


def main():  # noqa: C901
    """Main entry point."""
    # Load environment variables
    load_dotenv()

    gemini_api_key = os.getenv('GEMINI_KEY')
    groq_api_key = os.getenv('GROQ_KEY')

    if not gemini_api_key:
        print('Warning: GEMINI_KEY not found in environment variables')
        if not groq_api_key:
            print('Error: GROQ_KEY not found in environment variables')
            sys.exit(1)

    # USE_GROQ = False
    USE_GROQ = bool(groq_api_key)
    print(f'Using {"GROQ" if USE_GROQ else "Gemini"} as AI provider')

    if USE_GROQ:
        if not groq_api_key:
            raise ValueError('GROQ_API_KEY not found in environment')
        pipeline = SelectorDiscoveryPipeline(groq_api_key, 'llama-3.3-70b-versatile', provider='groq')
    else:
        if not gemini_api_key:
            raise ValueError('GEMINI_API_KEY not found in environment')
        pipeline = SelectorDiscoveryPipeline(gemini_api_key, 'gemini-2.0-flash-exp', provider='gemini')

    logfire_token = os.getenv('LOGFIRE_TOKEN')
    if logfire_token:
        logfire.configure(token=logfire_token)
        print('Logfire setup complete')
    else:
        print('LOGFIRE_TOKEN not set - skipping logfire setup')

    # Parse arguments
    parser = argparse.ArgumentParser(description='Discover CSS selectors from web pages using AI')
    parser.add_argument('--url', type=str, help='Single URL to process')
    parser.add_argument('--file', type=str, help='File containing URLs (one per line)')
    parser.add_argument('--limit', type=int, help='Limit number of URLs to process from file')
    parser.add_argument('--force', action='store_true', help='Force re-discovery even if selectors exist')
    parser.add_argument('--summary', action='store_true', help='Show summary of saved selectors')
    parser.add_argument('--debug', action='store_true', help='Enable debug more (saves extracted HTML to debug_html/')
    parser.add_argument('--skip-validation', action='store_true', help='Skip validation for faster processing')
    parser.add_argument(
        '--fetcher',
        choices=['simple', 'playwright', 'smart'],
        default='simple',
        help='HTML fetcher to use (default: simple)',
    )

    args = parser.parse_args()

    if args.debug:
        print(' Debug mode enabled - extracted HTML will be saved to debug_html/')

    # Handle summary request
    if args.summary:
        pipeline.show_summary()
        return

    # Gather URLs
    urls = []

    if args.url:
        urls.append(args.url)

    if args.file:
        if not os.path.exists(args.file):
            print(f'Error: File not found: {args.file}')
            sys.exit(1)

        # Check if it's a JSON file
        if args.file.endswith('.json'):
            import json

            with open(args.file) as f:
                data = json.load(f)

            # Extract URLs based on structure
            if isinstance(data, list):
                file_urls = [item.get('url', item) for item in data if item]
            else:
                file_urls = [data[key]['url'] for key in data if 'url' in data.get(key, {})]
        else:
            # Plain text file
            with open(args.file) as f:
                file_urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        urls.extend(file_urls)

    if not urls:
        print('Error: No URLs provided')
        sys.exit(1)

    # Apply limit if specified
    if args.limit:
        urls = urls[: args.limit]
        print(f' Limiting to first {args.limit} URLs')

    # Show fetcher info
    if args.fetcher == 'playwright':
        print(' Using Playwright fetcher (slower but more reliable)')
        print('   Make sure Playwright is installed: uv pip install playwright && playwright install chromium')
    elif args.fetcher == 'smart':
        print(' Using Smart fetcher (tries simple first, falls back to Playwright)')
        print('   Make sure Playwright is installed: uv pip install playwright && playwright install chromium')
    else:
        print(' Using Simple fetcher (fast, works for most sites)')

    # Process URLs
    pipeline.process_urls(urls, force=args.force, skip_validation=args.skip_validation, fetcher_type=args.fetcher)


if __name__ == '__main__':
    main()
