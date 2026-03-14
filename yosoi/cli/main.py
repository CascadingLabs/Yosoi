"""Main CLI command definition."""

from __future__ import annotations

import asyncio
import os

import rich_click as click

from yosoi.cli.args import SchemaParamType
from yosoi.cli.progress import run_concurrent
from yosoi.cli.setup import build_yosoi_config, print_fetcher_info
from yosoi.cli.utils import console, load_urls_from_file
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.selectors import SelectorLevel

_LEVEL_MAP: dict[str, SelectorLevel] = {
    **{m.name.lower(): m for m in SelectorLevel},
    'all': max(SelectorLevel),  # alias → most inclusive level
}

_VALID_FORMATS = {'json', 'md', 'markdown', 'jsonl', 'ndjson', 'csv', 'xlsx', 'parquet'}


def _resolve_output_formats(flag_values: tuple[str, ...]) -> list[str]:
    """Parse -o flag values into a normalised, deduplicated format list."""
    raw = [tok.strip().lower() for item in flag_values for tok in item.split(',') if tok.strip()]
    invalid = [f for f in raw if f not in _VALID_FORMATS]
    if invalid:
        raise click.BadParameter(
            f'Unknown format(s): {", ".join(invalid)}. Choose from: {", ".join(sorted(_VALID_FORMATS))}'
        )
    normalised = ['markdown' if f in ('md', 'markdown') else f for f in raw]
    return list(dict.fromkeys(normalised)) or ['json']


@click.command()
@click.pass_context
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
    multiple=True,
    default=('json',),
    metavar='FORMAT',
    help='Output format(s): json, md, jsonl, ndjson, csv, xlsx, parquet. Repeat or comma-separate for multiple.',
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
@click.option(
    '-x',
    '--selector-level',
    type=click.Choice(list(_LEVEL_MAP), case_sensitive=False),
    default='css',
    help='Maximum selector strategy level (default: css)',
)
def main(
    ctx: click.Context,
    model: str | None,
    url: str | None,
    file_path: str | None,
    limit: int | None,
    force: bool,
    summary: bool,
    debug: bool,
    skip_verification: bool,
    output: tuple[str, ...],
    fetcher: str,
    log_level: str,
    contract: type[Contract] | None,
    workers: int,
    selector_level: str,
) -> None:
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
    from yosoi.utils.files import init_yosoi, is_initialized
    from yosoi.utils.logging import setup_local_logging

    if not is_initialized():
        init_yosoi()

    yosoi_config = build_yosoi_config(model, debug)

    log_file = setup_local_logging(level=log_level)
    output_formats = _resolve_output_formats(output)
    resolved_contract = contract if contract else NewsArticle
    resolved_level = _LEVEL_MAP[selector_level.lower()]

    console.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')

    if selector_level != 'css':
        console.print(f'[cyan]ℹ Selector level:[/cyan] [bold]{selector_level}[/bold]')

    if summary:
        pipeline = Pipeline(yosoi_config, contract=resolved_contract, output_format=output_formats)
        pipeline.show_summary()
        return

    urls: list[str] = []

    if url:
        urls.append(url)

    if file_path:
        urls.extend(load_urls_from_file(file_path))

    if not urls:
        raise click.UsageError('No URLs provided. Use --url <url> or --file <file>')

    if limit:
        urls = urls[:limit]
        console.print(f'[cyan]ℹ Limiting to first {limit} URLs[/cyan]')

    if debug:
        console.print('[cyan]ℹ Debug mode enabled[/cyan] [dim]- extracted HTML will be saved to .yosoi/debug/[/dim]')

    console.print(f'[cyan]ℹ Output format(s):[/cyan] [bold]{", ".join(output_formats)}[/bold]')

    print_fetcher_info(fetcher)

    effective_workers = min(workers, len(urls))

    if workers > 1 and len(urls) == 1:
        console.print(f'[cyan]ℹ --workers {workers} has no effect with a single URL, running sequentially[/cyan]')
    elif workers > len(urls):
        console.print(f'[cyan]ℹ --workers {workers} capped to {len(urls)} (one per URL)[/cyan]')

    if effective_workers > 1:
        console.print(f'[cyan]ℹ Using {effective_workers} concurrent workers via taskiq[/cyan]')
        asyncio.run(
            run_concurrent(
                yosoi_config,
                resolved_contract,
                urls,
                output_format=output_formats,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=fetcher,
                max_workers=effective_workers,
                selector_level=resolved_level,
            )
        )
    else:
        pipeline = Pipeline(
            yosoi_config,
            contract=resolved_contract,
            output_format=output_formats,
            selector_level=resolved_level,
        )
        asyncio.run(
            pipeline.process_urls(
                urls,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=fetcher,
            )
        )
