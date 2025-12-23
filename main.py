"""
main.py
=======
Main entry point for CSS selector discovery system.

Usage:
    python main.py                          # Process default URLs
    python main.py --url <url>              # Process single URL
    python main.py --file <urls.txt>        # Process URLs from file
    python main.py --summary                # Show summary of saved selectors
"""

import argparse
import os
import sys

import requests
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from rich.console import Console
from rich.table import Table
from rich.theme import Theme
from rich.panel import Panel

from selector_discovery import SelectorDiscovery
from selector_storage import SelectorStorage
from selector_validator import SelectorValidator


class SelectorDiscoveryPipeline:
    """Main pipeline for discovering and saving CSS selectors."""

    def __init__(self, gemini_api_key: str):
        """Initialize the pipeline with API key."""
        # Initialize Rich Console
        self.custom_theme = Theme({
            "info": "dim cyan",
            "warning": "magenta",
            "danger": "bold red",
            "success": "bold green",
            "step": "bold blue"
        })
        self.console = Console(theme=self.custom_theme)

        # Initialize LLM
        self.llm = ChatGoogleGenerativeAI(
            model='gemini-2.5-flash',
            google_api_key=gemini_api_key,
            temperature=0,
        )

        # Initialize components
        self.discovery = SelectorDiscovery(self.llm, console=self.console)
        self.validator = SelectorValidator(console=self.console)
        self.storage = SelectorStorage()

    def process_url(self, url: str, force: bool = False) -> bool:
        """
        Process a single URL: discover, validate, and save selectors.

        Args:
            url: URL to process
            force: If True, re-discover even if selectors exist

        Returns:
            True if successful, False otherwise
        """
        self.console.print(Panel(f"[bold]Processing:[/bold] [underline]{url}[/underline]", border_style="blue"))

        # Check if selectors already exist
        domain = self.storage._extract_domain(url)
        if not force and self.storage.selector_exists(domain):
            self.console.print(f'[success]✓ Selectors already exist for {domain}[/success] [dim](use --force to re-discover)[/dim]')
            return True

        # Step 1: Fetch HTML
        html = None
        with self.console.status("[step]Step 1: Fetching HTML...[/step]", spinner="dots"):
            html = self._fetch_html(url)
        
        if not html:
            return False

        # Step 2: Discover selectors with AI
        selectors = None
        with self.console.status("[step]Step 2: AI analyzing HTML...[/step]", spinner="earth"):
            selectors = self.discovery.discover_from_html(url, html)

        if not selectors:
            self.console.print('[danger]✗ Failed to discover selectors[/danger]')
            return False

        self.console.print(f'[success]✓ Discovered selectors for {len(selectors)} fields[/success]')

        # Step 3: Validate selectors
        validated = None
        with self.console.status("[step]Step 3: Validating selectors...[/step]", spinner="bouncingBall"):
             validated = self.validator.validate_selectors(url, selectors)

        if not validated:
            self.console.print('[danger]✗ No selectors validated successfully[/danger]')
            return False

        self.console.print(f'[success]✓ Validated {len(validated)}/{len(selectors)} fields[/success]')

        # Step 4: Save selectors
        self.storage.save_selectors(url, validated)

        return True

    def process_urls(self, urls: list, force: bool = False):
        """Process multiple URLs."""
        results = {'successful': [], 'failed': []}

        for url in urls:
            try:
                success = self.process_url(url, force=force)
                if success:
                    results['successful'].append(url)
                else:
                    results['failed'].append(url)
            except Exception as e:
                self.console.print(f'[danger]✗ Error processing {url}: {e}[/danger]')
                results['failed'].append(url)

            self.console.print()  # Blank line between URLs

        # Print summary
        self._print_summary(results)

    def show_summary(self):
        """Show summary of all saved selectors."""
        summary = self.storage.get_summary()

        self.console.print(Panel("[bold]Selector Discovery Summary[/bold]", style="bold blue"))
        self.console.print(f'Total domains: [bold]{summary["total_domains"]}[/bold]')

        if summary['domains']:
            table = Table(title="Domains with Selectors")
            table.add_column("Domain", style="cyan", no_wrap=True)
            table.add_column("Discovered At", style="magenta")
            table.add_column("Fields", style="green")

            for domain_info in summary['domains']:
                table.add_row(
                    domain_info["domain"],
                    domain_info["discovered_at"],
                    ", ".join(domain_info["fields"])
                )
            self.console.print(table)
        else:
            self.console.print('[warning]No selectors discovered yet.[/warning]')

        self.console.print()

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML from URL."""
        try:
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            response.raise_for_status()
            self.console.print(f'[success]✓ Fetched {len(response.text):,} characters of HTML[/success]')
            return response.text
        except Exception as e:
            self.console.print(f'[danger]✗ Failed to fetch HTML: {e}[/danger]')
            return None

    def _print_summary(self, results: dict):
        """Print processing summary."""
        self.console.print()
        table = Table(title="Processing Summary", show_header=False)
        table.add_row("[green]Successful[/green]", str(len(results["successful"])))
        table.add_row("[red]Failed[/red]", str(len(results["failed"])))
        self.console.print(table)

        if results['failed']:
            self.console.print('\n[bold red]Failed URLs:[/bold red]')
            for url in results['failed']:
                self.console.print(f'  - {url}', style="red")

        self.console.print()


def load_urls_from_file(filepath: str) -> list:
    """Load URLs from a text file (one per line)."""
    try:
        with open(filepath) as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        return urls
    except Exception as e:
        print(f'Error loading URLs from file: {e}')
        return []


def main():
    """Main entry point."""
    # Load environment variables
    load_dotenv()

    gemini_api_key = os.getenv('GEMINI_KEY')
    if not gemini_api_key:
        print('Error: GEMINI_KEY not found in environment variables.')
        print('Please create a .env file with your GEMINI_KEY.')
        sys.exit(1)

    # Parse arguments
    parser = argparse.ArgumentParser(description='Discover CSS selectors from web pages using AI')
    parser.add_argument('--url', type=str, help='Single URL to process')
    parser.add_argument('--file', type=str, help='File containing URLs (one per line)')
    parser.add_argument('--force', action='store_true', help='Force re-discovery even if selectors exist')
    parser.add_argument('--summary', action='store_true', help='Show summary of saved selectors')

    args = parser.parse_args()

    # Initialize pipeline
    pipeline = SelectorDiscoveryPipeline(gemini_api_key)

    # Handle summary request
    if args.summary:
        pipeline.show_summary()
        return

    # Determine URLs to process
    urls = []

    if args.url:
        # Single URL from command line
        urls = [args.url]
    elif args.file:
        # URLs from file
        urls = load_urls_from_file(args.file)
        if not urls:
            print(f'No valid URLs found in {args.file}')
            sys.exit(1)
    else:
        # Default test URLs
        urls = [
            'https://virginiabusiness.com/new-documents-reveal-scope-of-googles-chesterfield-data-center-campus/',
            'https://finance.yahoo.com/video/three-big-questions-left-musk-125600891.html',
        ]
        print('No URLs specified, using default test URLs')

    # Process URLs
    print(f'\nStarting selector discovery for {len(urls)} URL(s)...')
    pipeline.process_urls(urls, force=args.force)


if __name__ == '__main__':
    main()
