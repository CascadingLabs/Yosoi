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

from selector_discovery import SelectorDiscovery
from selector_storage import SelectorStorage
from selector_validator import SelectorValidator


class SelectorDiscoveryPipeline:
    """Main pipeline for discovering and saving CSS selectors."""

    def __init__(self, gemini_api_key: str):
        """Initialize the pipeline with API key."""
        # Initialize LLM
        self.llm = ChatGoogleGenerativeAI(
            model='gemini-2.5-flash',
            google_api_key=gemini_api_key,
            temperature=0,
        )

        # Initialize components
        self.discovery = SelectorDiscovery(self.llm)
        self.validator = SelectorValidator()
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
        print(f'\n{"=" * 80}')
        print(f'Processing: {url}')
        print(f'{"=" * 80}')

        # Check if selectors already exist
        domain = self.storage._extract_domain(url)
        if not force and self.storage.selector_exists(domain):
            print(f'✓ Selectors already exist for {domain} (use --force to re-discover)')
            return True

        # Step 1: Fetch HTML
        print('\nStep 1: Fetching HTML...')
        html = self._fetch_html(url)
        if not html:
            return False

        # Step 2: Discover selectors with AI
        print('\nStep 2: AI analyzing HTML...')
        selectors = self.discovery.discover_from_html(url, html)

        if not selectors:
            print('✗ Failed to discover selectors')
            return False

        print(f'✓ Discovered selectors for {len(selectors)} fields')

        # Step 3: Validate selectors
        print('\nStep 3: Validating selectors...')
        validated = self.validator.validate_selectors(url, selectors)

        if not validated:
            print('✗ No selectors validated successfully')
            return False

        print(f'\n✓ Validated {len(validated)}/{len(selectors)} fields')

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
                print(f'\n✗ Error processing {url}: {e}')
                results['failed'].append(url)

            print()  # Blank line between URLs

        # Print summary
        self._print_summary(results)

    def show_summary(self):
        """Show summary of all saved selectors."""
        summary = self.storage.get_summary()

        print(f'\n{"=" * 80}')
        print('Selector Discovery Summary')
        print(f'{"=" * 80}')
        print(f'\nTotal domains: {summary["total_domains"]}')

        if summary['domains']:
            print('\nDomains with selectors:')
            for domain_info in summary['domains']:
                print(f'\n  {domain_info["domain"]}')
                print(f'    Discovered: {domain_info["discovered_at"]}')
                print(f'    Fields: {", ".join(domain_info["fields"])}')
        else:
            print('\nNo selectors discovered yet.')

        print(f'\n{"=" * 80}')

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML from URL."""
        try:
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            response.raise_for_status()
            print(f'✓ Fetched {len(response.text):,} characters of HTML')
            return response.text
        except Exception as e:
            print(f'✗ Failed to fetch HTML: {e}')
            return None

    def _print_summary(self, results: dict):
        """Print processing summary."""
        print(f'{"=" * 80}')
        print('Processing Summary')
        print(f'{"=" * 80}')
        print(f'Successful: {len(results["successful"])}')
        print(f'Failed: {len(results["failed"])}')

        if results['failed']:
            print('\nFailed URLs:')
            for url in results['failed']:
                print(f'  - {url}')

        print(f'{"=" * 80}')


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
