"""Command-line interface for Yosoi.

Handles argument parsing and delegates to pipeline.
"""

import argparse
import asyncio
import difflib
import importlib.util
import json
import os
import sys

import logfire
from dotenv import load_dotenv

from yosoi import Pipeline
from yosoi.config import DebugConfig, TelemetryConfig, YosoiConfig
from yosoi.core.discovery.config import LLMConfig
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.utils.files import init_yosoi, is_initialized
from yosoi.utils.logging import setup_local_logging


def setup_llm_config(model_arg: str | None = None) -> LLMConfig:
    """Set up LLM configuration from -m/--model flag or environment variables.

    Args:
        model_arg: Model string in ``provider/model-name`` format (e.g. ``groq/llama-3.3-70b-versatile``).
                   If None, falls back to auto-detecting from GROQ_KEY or GEMINI_KEY.

    Returns:
        LLMConfig instance configured with the selected provider and model.

    Raises:
        SystemExit: If the provider is unknown, the API key is missing, or no config can be determined.

    """
    if model_arg:
        if '/' not in model_arg:
            print('Error: --model must be in provider/model-name format (e.g. groq/llama-3.3-70b-versatile)')
            sys.exit(1)
        provider, model_name = model_arg.split('/', 1)
        # We don't fetch the API key here; YosoiConfig will handle it during validation
        return LLMConfig(provider=provider, model_name=model_name, api_key='')

    # Legacy auto-detect fallback (defaults)
    if os.getenv('GROQ_KEY'):
        return LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='')

    if os.getenv('GEMINI_KEY'):
        return LLMConfig(provider='gemini', model_name='gemini-2.0-flash', api_key='')

    # Return a partially filled config; validation in YosoiConfig will catch missing keys
    return LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='')


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


def _suggest_file(file_path: str, class_name: str) -> list[str]:
    """Return suggested ``file:class`` strings for a missing file path.

    Tries adding a ``.py`` extension first, then fuzzy-matches against files
    in the same directory.

    Args:
        file_path: The path that was not found.
        class_name: The class name from the original argument.

    Returns:
        List of suggestion strings in ``path:ClassName`` format.

    """
    suggestions: list[str] = []

    # Try adding .py extension
    if not file_path.endswith('.py'):
        py_path = file_path + '.py'
        if os.path.exists(py_path):
            suggestions.append(f'{py_path}:{class_name}')

    # Fuzzy-match filenames in the same directory
    dir_part = os.path.dirname(file_path) or '.'
    base_name = os.path.basename(file_path)
    try:
        candidates = [f for f in os.listdir(dir_part) if f.endswith('.py')]
        matches = difflib.get_close_matches(base_name, candidates, n=3, cutoff=0.4)
        for m in matches:
            candidate = f'{os.path.join(dir_part, m)}:{class_name}'
            if candidate not in suggestions:
                suggestions.append(candidate)
    except OSError:
        pass

    return suggestions


def load_schema(schema_str: str) -> type[Contract]:
    """Load a Contract class by path or built-in name.

    Args:
        schema_str: Either ``path/to/file.py:ClassName`` for dynamic import
                    or a bare name like ``NewsArticle`` for built-in schemas.

    Returns:
        The Contract subclass.

    Raises:
        SystemExit: If the schema cannot be found or loaded.

    """
    if ':' in schema_str:
        file_path, class_name = schema_str.rsplit(':', 1)
        if not os.path.exists(file_path):
            print(f'Error: Schema file not found: {file_path}')
            suggestions = _suggest_file(file_path, class_name)
            if suggestions:
                print(f'Did you mean: {suggestions[0]}')
                if len(suggestions) > 1:
                    print(f'  Other options: {", ".join(suggestions[1:])}')
            sys.exit(1)
        spec = importlib.util.spec_from_file_location('_yosoi_schema', file_path)
        if spec is None or spec.loader is None:
            print(f'Error: Could not load schema from {file_path}')
            sys.exit(1)
        module = importlib.util.module_from_spec(spec)
        loader = spec.loader
        assert loader is not None
        loader.exec_module(module)
        cls = getattr(module, class_name, None)
        if cls is None:
            available = [
                name for name in dir(module) if not name.startswith('_') and isinstance(getattr(module, name), type)
            ]
            print(f'Error: Class {class_name!r} not found in {file_path}')
            matches = difflib.get_close_matches(class_name, available, n=3, cutoff=0.5)
            if matches:
                print(f'Did you mean: {matches[0]}')
                if len(matches) > 1:
                    print(f'  Other options: {", ".join(matches[1:])}')
            elif available:
                print(f'Available classes: {", ".join(available)}')
            sys.exit(1)
        return cls  # type: ignore[no-any-return]
    from yosoi.models.defaults import BUILTIN_SCHEMAS

    schema = BUILTIN_SCHEMAS.get(schema_str)
    if schema is None:
        available_str = ', '.join(BUILTIN_SCHEMAS.keys())
        print(f'Error: Unknown built-in schema {schema_str!r}. Available: {available_str}')
        sys.exit(1)
    return schema


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
        description='Discover selectors from web pages using AI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -u https://example.com
  %(prog)s -m groq/llama-3.3-70b-versatile -u https://example.com
  %(prog)s -m gemini/gemini-2.0-flash -f urls.txt -l 10
  %(prog)s --url https://example.com --force
  %(prog)s -s
  %(prog)s -u https://example.com -d -F
        """,
    )

    parser.add_argument(
        '-m',
        '--model',
        type=str,
        default=None,
        metavar='PROVIDER/MODEL',
        help='LLM model in provider/model format (e.g. groq/llama-3.3-70b-versatile, gemini/gemini-2.0-flash)',
    )
    parser.add_argument('-u', '--url', type=str, help='Single URL to process')
    parser.add_argument('-f', '--file', type=str, help='File containing URLs (one per line, or JSON)')
    parser.add_argument('-l', '--limit', type=int, help='Limit number of URLs to process from file')
    parser.add_argument('-F', '--force', action='store_true', help='Force re-discovery even if selectors exist')
    parser.add_argument('-s', '--summary', action='store_true', help='Show summary of saved selectors')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode (saves extracted HTML to debug/)')
    parser.add_argument(
        '-sv', '--skip-verification', action='store_true', help='Skip verification for faster processing'
    )
    parser.add_argument(
        '-o',
        '--output',
        choices=['json', 'markdown', 'md'],
        default='json',
        help='Output format for extracted content (default: json)',
    )
    parser.add_argument(
        '-t',
        '--fetcher',
        choices=['simple'],
        default='simple',
        help='HTML fetcher to use (default: simple)',
    )
    parser.add_argument(
        '-L',
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'ALL'],
        default=os.getenv('YOSOI_LOG_LEVEL', 'DEBUG'),
        help='Logging level for the local log file (default: DEBUG or YOSOI_LOG_LEVEL env)',
    )
    parser.add_argument(
        '-sc',
        '--schema',
        type=str,
        default=None,
        help=(
            'Contract schema to use. '
            'Built-in: NewsArticle, Video, Product, JobPosting. '
            'Dynamic: /path/to/file.py:ClassName'
        ),
    )
    parser.add_argument(
        '-w',
        '--workers',
        type=int,
        default=1,
        metavar='N',
        help='Number of concurrent workers for batch processing (default: 1, sequential)',
    )

    return parser.parse_args()


def print_fetcher_info(fetcher_type: str):
    """Print information about the selected fetcher.

    Args:
        fetcher_type: Type of fetcher ('simple')

    Returns:
        None

    """
    print('ℹ Using Simple fetcher (fast, works for most sites)')


async def _run_concurrent(
    yosoi_config: YosoiConfig,
    contract: type[Contract],
    urls: list[str],
    output_format: str = 'json',
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'simple',
    max_workers: int = 5,
):
    """Run URL processing concurrently via taskiq broker.

    Args:
        yosoi_config: Validated YosoiConfig.
        contract: Contract subclass.
        urls: URLs to process.
        output_format: Output format.
        force: Force re-discovery.
        skip_verification: Skip verification step.
        fetcher_type: Fetcher type.
        max_workers: Max concurrent workers.

    """
    from yosoi.tasks import configure_broker, enqueue_urls, shutdown_broker

    await configure_broker(yosoi_config, contract=contract, output_format=output_format, max_workers=max_workers)
    try:
        results = await enqueue_urls(
            urls,
            force=force,
            skip_verification=skip_verification,
            fetcher_type=fetcher_type,
        )

        # Print summary
        print(f'\nResults: {len(results["successful"])} succeeded, {len(results["failed"])} failed')
        if results.get('skipped'):
            print(f'  {len(results["skipped"])} skipped (duplicate domains)')
        if results['failed']:
            print('Failed URLs:')
            for url in results['failed']:
                print(f'  - {url}')
    finally:
        await shutdown_broker()


def main():
    """Run the CLI entry point."""
    # Load environment variables
    load_dotenv()

    # Parse arguments
    args = parse_arguments()

    if not is_initialized():
        init_yosoi()

    # Set up LLM configuration
    llm_config = setup_llm_config(args.model)

    # Create YosoiConfig for validation
    try:
        yosoi_config = YosoiConfig(
            llm=llm_config,
            debug=DebugConfig(save_html=args.debug),
            telemetry=TelemetryConfig(logfire_token=os.getenv('LOGFIRE_TOKEN')),
        )
    except Exception as e:
        print(f'Configuration Error: {e}')
        sys.exit(1)

    print(f'Using {yosoi_config.llm.provider} / {yosoi_config.llm.model_name}')

    # Initialize logging
    log_file = setup_local_logging(level=args.log_level)

    # Normalize output format
    output_format = 'markdown' if args.output in ['markdown', 'md'] else 'json'

    # Resolve contract schema
    contract = load_schema(args.schema) if args.schema else NewsArticle

    from rich import print as rprint

    # Show log file link
    rprint(f'ℹ Log file: [link=file://{log_file}]file://{log_file}[/link]')

    # Handle summary request (quick exit — needs pipeline for storage access)
    if args.summary:
        pipeline = Pipeline(yosoi_config, contract=contract, output_format=output_format)
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
        print('ℹ Debug mode enabled - extracted HTML will be saved to debug/')

    # Show output format info
    print(f'ℹ Output format: {output_format}')

    # Show fetcher info
    print_fetcher_info(args.fetcher)

    # Determine effective concurrency
    effective_workers = min(args.workers, len(urls))

    if args.workers > 1 and len(urls) == 1:
        print(f'ℹ --workers {args.workers} has no effect with a single URL, running sequentially')
    elif args.workers > len(urls):
        print(f'ℹ --workers {args.workers} capped to {len(urls)} (one per URL)')

    # Process URLs
    if effective_workers > 1:
        print(f'ℹ Using {effective_workers} concurrent workers via taskiq')
        asyncio.run(
            _run_concurrent(
                yosoi_config,
                contract,
                urls,
                output_format=output_format,
                force=args.force,
                skip_verification=args.skip_verification,
                fetcher_type=args.fetcher,
                max_workers=effective_workers,
            )
        )
    else:
        pipeline = Pipeline(yosoi_config, contract=contract, output_format=output_format)
        asyncio.run(
            pipeline.process_urls(
                urls,
                force=args.force,
                skip_verification=args.skip_verification,
                fetcher_type=args.fetcher,
            )
        )


if __name__ == '__main__':
    main()
