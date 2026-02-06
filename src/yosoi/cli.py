"""
cli.py
======
Command-line interface for Yosoi.
Handles argument parsing and delegates to pipeline.
"""

import argparse
import json
import os
import sys

import logfire
from dotenv import load_dotenv

from yosoi import gemini, groq
from yosoi.pipeline import SelectorDiscoveryPipeline


def setup_llm_config():
    """Set up LLM configuration from environment variables.

    Checks for GROQ_KEY first, then GEMINI_KEY.

    Returns:
        LLMConfig instance configured with available API key.

    Raises:
        SystemExit: If no API keys are found in environment.
    """
    groq_api_key = os.getenv('GROQ_KEY')
    gemini_api_key = os.getenv('GEMINI_KEY')

    if groq_api_key:
        print('Using GROQ as AI provider')
        return groq('llama-3.3-70b-versatile', groq_api_key)

    if gemini_api_key:
        print('Using Gemini as AI provider')
        return gemini('gemini-2.0-flash-exp', gemini_api_key)

    print('Error: No API keys found')
    print('Please set GROQ_KEY or GEMINI_KEY in your .env file')
    sys.exit(1)


def setup_logfire():
    """Set up Logfire observability if token is available.

    Configures Logfire and instruments Pydantic if LOGFIRE_TOKEN is set.

    Returns:
        None
    """
    logfire_token = os.getenv('LOGFIRE_TOKEN')
    if logfire_token:
        logfire.configure(token=logfire_token)
        logfire.instrument_pydantic()
        print('Logfire setup complete')
    else:
        print('LOGFIRE_TOKEN not set - skipping logfire setup')


def load_urls_from_file(filepath: str) -> list[str]:
    """Load URLs from a file (JSON or plain text).

    Args:
        filepath: Path to file containing URLs

    Returns:
        List of URL strings.

    Raises:
        SystemExit: If file is not found.
    """
    if not os.path.exists(filepath):
        print(f'Error: File not found: {filepath}')
        sys.exit(1)

    if filepath.endswith('.json'):
        with open(filepath) as f:
            data = json.load(f)

        # Extract URLs based on structure
        if isinstance(data, list):
            return [item.get('url', item) for item in data if item]
        return [data[key]['url'] for key in data if 'url' in data.get(key, {})]
    # Plain text file
    with open(filepath) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]


def parse_arguments():
    """Parse command-line arguments.

    Returns:
        argparse.Namespace object with parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description='Discover CSS selectors from web pages using AI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --url https://example.com
  %(prog)s --file urls.txt --limit 10
  %(prog)s --url https://example.com --force
  %(prog)s --summary
        """,
    )

    parser.add_argument('--url', type=str, help='Single URL to process')
    parser.add_argument('--file', type=str, help='File containing URLs (one per line, or JSON)')
    parser.add_argument('--limit', type=int, help='Limit number of URLs to process from file')
    parser.add_argument('--force', action='store_true', help='Force re-discovery even if selectors exist')
    parser.add_argument('--summary', action='store_true', help='Show summary of saved selectors')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode (saves extracted HTML to debug_html/)')
    parser.add_argument('--skip-validation', action='store_true', help='Skip validation for faster processing')
    parser.add_argument(
        '--fetcher',
        choices=['simple', 'playwright', 'smart'],
        default='simple',
        help='HTML fetcher to use (default: simple)',
    )

    return parser.parse_args()


def print_fetcher_info(fetcher_type: str):
    """Print information about the selected fetcher.

    Args:
        fetcher_type: Type of fetcher ('simple', 'playwright', or 'smart')

    Returns:
        None
    """
    if fetcher_type == 'playwright':
        print('ℹ Using Playwright fetcher (slower but more reliable)')
    elif fetcher_type == 'smart':
        print('ℹ Using Smart fetcher (tries simple first, falls back to Playwright)')
    else:
        print('ℹ Using Simple fetcher (fast, works for most sites)')


def main():
    """Main entry point for CLI."""
    # Load environment variables
    load_dotenv()

    # Parse arguments
    args = parse_arguments()

    # Set up LLM configuration
    llm_config = setup_llm_config()

    # Initialize pipeline
    pipeline = SelectorDiscoveryPipeline(llm_config, debug_mode=args.debug)

    # Set up Logfire
    setup_logfire()

    # Handle summary request (quick exit)
    if args.summary:
        pipeline.show_summary()
        return

    # Gather URLs
    urls = []

    if args.url:
        urls.append(args.url)

    if args.file:
        file_urls = load_urls_from_file(args.file)
        urls.extend(file_urls)

    if not urls:
        print('Error: No URLs provided')
        print('Use --url <url> or --file <file>')
        sys.exit(1)

    # Apply limit if specified
    if args.limit:
        urls = urls[: args.limit]
        print(f'ℹ Limiting to first {args.limit} URLs')

    # Show debug info
    if args.debug:
        print('ℹ Debug mode enabled - extracted HTML will be saved to debug_html/')

    # Show fetcher info
    print_fetcher_info(args.fetcher)

    # Process URLs
    pipeline.process_urls(urls, force=args.force, skip_validation=args.skip_validation, fetcher_type=args.fetcher)


if __name__ == '__main__':
    main()
