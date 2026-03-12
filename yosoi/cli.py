"""Command-line interface for Yosoi.

Handles argument parsing via Click and delegates to pipeline.
"""

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


def load_schema(schema_str: str) -> type[Contract]:
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
    loader.exec_module(module)

    cls = getattr(module, class_name, None)
    if cls is None:
        available = [
            name for name in dir(module) if not name.startswith('_') and isinstance(getattr(module, name), type)
        ]
        msg = f'Class {class_name!r} not found in {file_path}'
        matches = difflib.get_close_matches(class_name, available, n=3, cutoff=0.5)
        if matches:
            msg += f'\nDid you mean: {matches[0]}'
            if len(matches) > 1:
                msg += f'\n  Other options: {", ".join(matches[1:])}'
        elif available:
            msg += f'\nAvailable classes: {", ".join(available)}'
        raise click.ClickException(msg)
    return cls  # type: ignore[no-any-return]


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
            return [item.get('url', item) for item in data if item]
        return [data[key]['url'] for key in data if 'url' in data.get(key, {})]

    with open(filepath) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]


def print_fetcher_info(fetcher_type: str):
    """Print information about the selected fetcher.

    Args:
        fetcher_type: Type of fetcher ('simple', 'playwright', or 'smart').

    """
    if fetcher_type == 'playwright':
        console.print('[cyan]ℹ Using Playwright fetcher[/cyan] [dim](slower but more reliable)[/dim]')
    elif fetcher_type == 'smart':
        console.print('[cyan]ℹ Using Smart fetcher[/cyan] [dim](tries simple first, falls back to Playwright)[/dim]')
    else:
        console.print('[cyan]ℹ Using Simple fetcher[/cyan] [dim](fast, works for most sites)[/dim]')


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
    type=click.Choice(['simple', 'playwright', 'smart'], case_sensitive=False),
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
):
    """Discover selectors from web pages using AI.

    [bold]Examples:[/bold]

    yosoi -u https://example.com

    yosoi -m groq/llama-3.3-70b-versatile -u https://example.com

    yosoi -m gemini/gemini-2.0-flash -f urls.txt -l 10

    yosoi -C Product -u https://example.com

    yosoi -u https://example.com -F -d

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

    pipeline = Pipeline(yosoi_config, contract=resolved_contract, output_format=output_format)

    console.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')

    if summary:
        pipeline.show_summary()
        return

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
        console.print('[cyan]ℹ Debug mode enabled[/cyan] [dim]- extracted HTML will be saved to debug/[/dim]')

    console.print(f'[cyan]ℹ Output format:[/cyan] [bold]{output_format}[/bold]')

    print_fetcher_info(fetcher)

    pipeline.process_urls(
        urls,
        force=force,
        skip_verification=skip_verification,
        fetcher_type=fetcher,
    )


if __name__ == '__main__':
    main()
