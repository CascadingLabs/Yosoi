"""Command-line interface for Yosoi.

Handles argument parsing via Click and delegates to pipeline.
"""

import asyncio
import difflib
import importlib.util
import json
import os

import rich_click as click
from dotenv import load_dotenv
from rich.console import Console

from yosoi.models.contract import Contract
from yosoi.models.defaults import BUILTIN_SCHEMAS, NewsArticle

# Load .env early so env vars are available for option defaults (e.g. YOSOI_LOG_LEVEL)
load_dotenv()

console = Console()
console_err = Console(stderr=True)

# ── rich-click styling ──────────────────────────────────────────────
click.rich_click.TEXT_MARKUP = 'rich'
_option_groups = [
    {
        'name': 'Input',
        'options': ['--url', '--file', '--contract', '--limit'],
    },
    {
        'name': 'Model & Fetcher',
        'options': ['--model', '--fetcher'],
    },
    {
        'name': 'Output',
        'options': ['--output', '--summary'],
    },
    {
        'name': 'Concurrency',
        'options': ['--workers'],
    },
    {
        'name': 'Advanced',
        'options': ['--force', '--debug', '--skip-verification', '--log-level'],
    },
]
# Register for both the function name ('main') and the entry-point name ('yosoi')
click.rich_click.OPTION_GROUPS = {
    'main': _option_groups,
    'yosoi': _option_groups,
}


# ── SchemaParamType ─────────────────────────────────────────────────
class SchemaParamType(click.ParamType):
    """Click parameter type that resolves schema names with fuzzy matching."""

    name = 'schema'

    def get_metavar(self, param: click.Parameter, ctx: click.Context | None = None) -> str:
        """Return metavar for help text."""
        return 'NAME|path:Class'

    def shell_complete(self, ctx: click.Context, param: click.Parameter, incomplete: str) -> list:
        """Provide shell completion for built-in schema names."""
        return [
            click.shell_completion.CompletionItem(name)
            for name in BUILTIN_SCHEMAS
            if name.lower().startswith(incomplete.lower())
        ]

    def convert(self, value: str, param: click.Parameter | None, ctx: click.Context | None) -> type[Contract]:
        """Convert a string value to a Contract class.

        Resolution order:
        1. Exact match in BUILTIN_SCHEMAS
        2. Case-insensitive match
        3. Fuzzy match (with warning)
        4. Dynamic import via ``path:ClassName``
        """
        # 1. Exact match
        if value in BUILTIN_SCHEMAS:
            return BUILTIN_SCHEMAS[value]

        # 2. Case-insensitive match
        lower_map = {k.lower(): k for k in BUILTIN_SCHEMAS}
        if value.lower() in lower_map:
            return BUILTIN_SCHEMAS[lower_map[value.lower()]]

        # 3. Fuzzy match
        close = difflib.get_close_matches(value, BUILTIN_SCHEMAS.keys(), n=1, cutoff=0.4)
        if close:
            matched = close[0]
            console_err.print(f'[yellow]Warning: fuzzy-matched schema {value!r} → {matched!r}[/yellow]')
            return BUILTIN_SCHEMAS[matched]

        # 4. Dynamic import (path:ClassName)
        if ':' in value:
            return load_schema(value)

        available_str = ', '.join(BUILTIN_SCHEMAS.keys())
        self.fail(f'Unknown schema {value!r}. Available: {available_str}', param, ctx)
        raise AssertionError('unreachable')  # self.fail always raises


# ── Helper functions ────────────────────────────────────────────────
def setup_llm_config(model_arg: str | None = None):
    """Set up LLM configuration from -m/--model flag or environment variables.

    Args:
        model_arg: Model string in ``provider/model-name`` format.

    Returns:
        LLMConfig instance.

    Raises:
        click.ClickException: If the provider format is invalid.

    """
    from yosoi.core.discovery.config import LLMConfig

    if model_arg:
        if '/' not in model_arg:
            raise click.ClickException(
                '--model must be in provider/model-name format (e.g. groq/llama-3.3-70b-versatile)'
            )
        provider, model_name = model_arg.split('/', 1)
        return LLMConfig(provider=provider, model_name=model_name, api_key='')

    # Legacy auto-detect fallback (defaults)
    if os.getenv('GROQ_KEY'):
        return LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='')

    if os.getenv('GEMINI_KEY'):
        return LLMConfig(provider='gemini', model_name='gemini-2.0-flash', api_key='')

    return LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='')


def _suggest_file(file_path: str, class_name: str) -> list[str]:
    """Return suggested ``file:class`` strings for a missing file path."""
    suggestions: list[str] = []

    if not file_path.endswith('.py'):
        py_path = file_path + '.py'
        if os.path.exists(py_path):
            suggestions.append(f'{py_path}:{class_name}')

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


def _find_contract_classes(module: object) -> list[str]:
    """Return names of all Contract subclasses in a module."""
    return [
        name
        for name in dir(module)
        if not name.startswith('_')
        and isinstance(getattr(module, name), type)
        and issubclass(getattr(module, name), Contract)
    ]


def _raise_class_not_found(class_name: str, file_path: str, module: object, contract_classes: list[str]) -> None:
    """Raise a ClickException with helpful hints when a class is not found."""
    available = [name for name in dir(module) if not name.startswith('_') and isinstance(getattr(module, name), type)]
    msg = f'Class {class_name!r} not found in {file_path}'
    matches = difflib.get_close_matches(class_name, available, n=3, cutoff=0.5)
    if matches:
        msg += f'\nDid you mean: {matches[0]}'
        if len(matches) > 1:
            msg += f'\n  Other options: {", ".join(matches[1:])}'
    elif contract_classes:
        msg += f'\nAvailable Contract subclasses: {", ".join(contract_classes)}'
    elif available:
        msg += f'\nAvailable classes: {", ".join(available)}'
    raise click.ClickException(msg)


def load_schema(schema_str: str) -> type[Contract]:
    # TODO make a global registry of Contracts so that in the CLI we can suggset on custom COntracts too!
    """Load a Contract class from a ``path/to/file.py:ClassName`` string.

    Args:
        schema_str: Dynamic import path in ``file:ClassName`` format.

    Returns:
        The Contract subclass.

    Raises:
        click.ClickException: If the schema cannot be found or loaded.

    """
    if ':' not in schema_str:
        raise click.ClickException(f'Dynamic schema must use path:ClassName format, got {schema_str!r}')

    file_path, class_name = schema_str.rsplit(':', 1)
    if not os.path.exists(file_path):
        msg = f'Schema file not found: {file_path}'
        suggestions = _suggest_file(file_path, class_name)
        if suggestions:
            msg += f'\nDid you mean: {suggestions[0]}'
            if len(suggestions) > 1:
                msg += f'\n  Other options: {", ".join(suggestions[1:])}'
        raise click.ClickException(msg)

    spec = importlib.util.spec_from_file_location('_yosoi_schema', file_path)
    if spec is None or spec.loader is None:
        raise click.ClickException(f'Could not load schema from {file_path}')

    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    try:
        loader.exec_module(module)
    except Exception as e:
        raise click.ClickException(f'Failed to load {file_path}: {e}') from e

    cls = getattr(module, class_name, None)
    contract_classes = _find_contract_classes(module)

    if cls is None:
        _raise_class_not_found(class_name, file_path, module, contract_classes)

    if not (isinstance(cls, type) and issubclass(cls, Contract)):
        msg = f'Found {class_name!r} in {file_path}, but it is not a Contract subclass'
        if contract_classes:
            msg += f'\nAvailable Contract subclasses: {", ".join(contract_classes)}'
        raise click.ClickException(msg)

    return cls


def load_urls_from_file(filepath: str) -> list[str]:
    # TODO upgrade this to be more extensible w/ more file types (pdf, xlsx, csv, etc.)
    """Load URLs from a file (JSON or plain text).

    Args:
        filepath: Path to file containing URLs.

    Returns:
        List of URL strings.

    Raises:
        click.ClickException: If file is not found.

    """
    if not os.path.exists(filepath):
        raise click.ClickException(f'File not found: {filepath}')

    if filepath.endswith('.json'):
        with open(filepath) as f:
            data = json.load(f)

        if isinstance(data, list):
            urls: list[str] = []
            for item in data:
                if isinstance(item, str) and item:
                    urls.append(item)
                elif isinstance(item, dict):
                    url = item.get('url')
                    if url:
                        urls.append(url)
            return urls
        if isinstance(data, dict):
            urls = []
            for key in data:
                value = data.get(key, {})
                if isinstance(value, str) and value:
                    urls.append(value)
                elif isinstance(value, dict) and 'url' in value:
                    urls.append(value['url'])
            return urls
        return []

    with open(filepath) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]


def print_fetcher_info(fetcher_type: str):
    """Print information about the selected fetcher.

    Args:
        fetcher_type: Type of fetcher ('simple').

    """
    console.print('[cyan]ℹ Using Simple fetcher[/cyan] [dim](fast, works for most sites)[/dim]')


_STATUS_STYLES: dict[str, tuple[str, bool]] = {
    'Queued': ('dim', False),
    'Running': ('bold yellow', True),
    'Done': ('bold green', False),
    'Skipped': ('dim', False),
    'Failed': ('bold red', False),
}


def _build_progress_table(url_status: dict[str, tuple[str, float]]):
    """Build a rich Table showing per-URL progress.

    Args:
        url_status: Mapping of URL to (status, value) where value is
            a monotonic start time for Running, or elapsed seconds for Done/Failed.

    Returns:
        A Rich Table renderable.

    """
    import time

    from rich.table import Table

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


async def _run_concurrent(
    yosoi_config,
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
    import time
    from urllib.parse import urlparse as _urlparse

    from rich.live import Live

    from yosoi.tasks import configure_broker, enqueue_urls, shutdown_broker

    await configure_broker(yosoi_config, contract=contract, output_format=output_format, max_workers=max_workers)
    start_time = time.monotonic()

    # Track per-URL status: (status_label, monotonic_start | elapsed_seconds)
    url_status: dict[str, tuple[str, float]] = dict.fromkeys(urls, ('Queued', 0.0))

    # Pre-mark deduped URLs so the table shows them correctly from the start
    _seen_domains: set[str] = set()
    now = time.monotonic()
    for u in urls:
        parse_u = u if u.startswith(('http://', 'https://')) else f'https://{u}'
        domain = _urlparse(parse_u).netloc.replace('www.', '')
        if domain in _seen_domains:
            url_status[u] = ('Skipped', 0.0)
        else:
            _seen_domains.add(domain)
            url_status[u] = ('Running', now)

    live = Live(_build_progress_table(url_status), console=console, refresh_per_second=4)

    async def _on_complete(url: str, success: bool, elapsed: float):
        url_status[url] = ('Done' if success else 'Failed', elapsed)
        live.update(_build_progress_table(url_status))

    try:
        with live:
            results = await enqueue_urls(
                urls,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=fetcher_type,
                on_complete=_on_complete,
            )
    finally:
        await shutdown_broker()

    # Print summary after live display ends
    total_elapsed = time.monotonic() - start_time
    console.print(
        f'\n[bold]Results:[/bold] [green]{len(results["successful"])} succeeded[/green], '
        f'[red]{len(results["failed"])} failed[/red] '
        f'[dim]({total_elapsed:.1f}s total)[/dim]'
    )
    if results.get('skipped'):
        console.print(f'  [dim]{len(results["skipped"])} skipped (duplicate domains)[/dim]')
    if results['failed']:
        console.print('[bold red]Failed URLs:[/bold red]')
        for url in results['failed']:
            console.print(f'  [red]- {url}[/red]')


# ── Main CLI command ────────────────────────────────────────────────
@click.command()
@click.option(
    '-m', '--model', default=None, metavar='PROVIDER/MODEL', help='LLM model (e.g. groq/llama-3.3-70b-versatile)'
)
@click.option('-u', '--url', default=None, help='Single URL to process')
@click.option('-f', '--file', 'file_path', default=None, help='File containing URLs (one per line, or JSON)')
@click.option('-l', '--limit', type=int, default=None, help='Limit number of URLs to process from file')
@click.option('-F', '--force', is_flag=True, help='Force re-discovery even if selectors exist')
@click.option('-s', '--summary', is_flag=True, help='Show summary of saved selectors')
@click.option('-d', '--debug', is_flag=True, help='Enable debug mode (saves extracted HTML to debug/)')
@click.option('-S', '--skip-verification', is_flag=True, help='Skip verification for faster processing')
@click.option(
    '-o',
    '--output',
    type=click.Choice(['json', 'markdown', 'md'], case_sensitive=False),
    default='json',
    help='Output format for extracted content',
)
@click.option(
    '-t',
    '--fetcher',
    type=click.Choice(['simple'], case_sensitive=False),
    default='simple',
    help='HTML fetcher to use',
)
@click.option(
    '-L',
    '--log-level',
    type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'ALL'], case_sensitive=False),
    default=os.getenv('YOSOI_LOG_LEVEL', 'DEBUG'),
    help='Logging level for the local log file',
)
@click.option(
    '-C', '--contract', type=SchemaParamType(), default=None, help='Contract schema (built-in name or path:Class)'
)
@click.option(
    '-w',
    '--workers',
    type=int,
    default=1,
    metavar='N',
    help='Number of concurrent workers for batch processing (default: 1, sequential)',
)
def main(
    model: str | None,
    url: str | None,
    file_path: str | None,
    limit: int | None,
    force: bool,
    summary: bool,
    debug: bool,
    skip_verification: bool,
    output: str,
    fetcher: str,
    log_level: str,
    contract: type[Contract] | None,
    workers: int,
):
    """Discover selectors from web pages using AI.

    [bold]Examples:[/bold]

    yosoi -u https://example.com

    yosoi -m groq/llama-3.3-70b-versatile -u https://example.com

    yosoi -m gemini/gemini-2.0-flash -f urls.txt -l 10

    yosoi -C Product -u https://example.com

    yosoi -u https://example.com -F -d

    yosoi -w 3 -f urls.txt

    yosoi -s
    """
    from yosoi import Pipeline
    from yosoi.config import DebugConfig, TelemetryConfig, YosoiConfig
    from yosoi.utils.files import init_yosoi, is_initialized
    from yosoi.utils.logging import setup_local_logging

    if not is_initialized():
        init_yosoi()

    llm_config = setup_llm_config(model)

    try:
        yosoi_config = YosoiConfig(
            llm=llm_config,
            debug=DebugConfig(save_html=debug),
            telemetry=TelemetryConfig(logfire_token=os.getenv('LOGFIRE_TOKEN')),
        )
    except Exception as e:
        raise click.ClickException(f'Configuration Error: {e}') from e

    console.print(
        f'[bold]Using[/bold] [green]{yosoi_config.llm.provider}[/green] / [cyan]{yosoi_config.llm.model_name}[/cyan]'
    )

    log_file = setup_local_logging(level=log_level)
    output_format = 'markdown' if output in ['markdown', 'md'] else 'json'
    resolved_contract = contract if contract else NewsArticle

    console.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')

    # Handle summary request (quick exit — needs pipeline for storage access)
    if summary:
        pipeline = Pipeline(yosoi_config, contract=resolved_contract, output_format=output_format)
        pipeline.show_summary()
        return

    # Gather URLs
    urls: list[str] = []

    if url:
        urls.append(url)

    if file_path:
        file_urls = load_urls_from_file(file_path)
        urls.extend(file_urls)

    if not urls:
        raise click.UsageError('No URLs provided. Use --url <url> or --file <file>')

    if limit:
        urls = urls[:limit]
        console.print(f'[cyan]ℹ Limiting to first {limit} URLs[/cyan]')

    if debug:
        console.print('[cyan]ℹ Debug mode enabled[/cyan] [dim]- extracted HTML will be saved to .yosoi/debug/[/dim]')

    console.print(f'[cyan]ℹ Output format:[/cyan] [bold]{output_format}[/bold]')

    print_fetcher_info(fetcher)

    # Determine effective concurrency
    effective_workers = min(workers, len(urls))

    if workers > 1 and len(urls) == 1:
        console.print(f'[cyan]ℹ --workers {workers} has no effect with a single URL, running sequentially[/cyan]')
    elif workers > len(urls):
        console.print(f'[cyan]ℹ --workers {workers} capped to {len(urls)} (one per URL)[/cyan]')

    # Process URLs
    if effective_workers > 1:
        console.print(f'[cyan]ℹ Using {effective_workers} concurrent workers via taskiq[/cyan]')
        asyncio.run(
            _run_concurrent(
                yosoi_config,
                resolved_contract,
                urls,
                output_format=output_format,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=fetcher,
                max_workers=effective_workers,
            )
        )
    else:
        pipeline = Pipeline(yosoi_config, contract=resolved_contract, output_format=output_format)
        asyncio.run(
            pipeline.process_urls(
                urls,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=fetcher,
            )
        )


if __name__ == '__main__':
    main()
