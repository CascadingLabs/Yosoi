"""Main CLI command definition — verb group (CAS-121) with backward compat."""

from __future__ import annotations

import asyncio
import json
import os
import sys

import rich_click as click
from rich.console import Console
from rich.theme import Theme

from yosoi.cli.contract_param import ContractParamType
from yosoi.cli.machine import MachineReadableGroup, echo_json
from yosoi.cli.setup import build_policy, print_fetcher_info
from yosoi.cli.utils import console, load_urls_from_file
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.selectors import SelectorLevel

_DEFAULT_SELECTOR_LEVEL = 'all'
_DEFAULT_AUTO_WORKERS = 4

_LEVEL_MAP: dict[str, SelectorLevel] = {
    **{m.name.lower(): m for m in SelectorLevel},
    'all': max(SelectorLevel),
}

_VALID_FORMATS = {'json', 'md', 'markdown', 'jsonl', 'ndjson', 'csv', 'xlsx', 'parquet'}
_FETCHER_CHOICES = ['auto', 'simple', 'headless', 'headful', 'waterfall']  # waterfall aliases auto

_CONTEXT_SETTINGS = {'help_option_names': ['-h', '--help'], 'show_default': True}

_THEME = Theme(
    {
        'info': 'dim cyan',
        'warning': 'magenta',
        'danger': 'bold red',
        'success': 'bold green',
        'step': 'bold blue',
    }
)


def _resolve_output_formats(flag_values: tuple[str, ...]) -> list[str]:
    raw = [tok.strip().lower() for item in flag_values for tok in item.split(',') if tok.strip()]
    invalid = [f for f in raw if f not in _VALID_FORMATS]
    if invalid:
        raise click.BadParameter(
            f'Unknown format(s): {", ".join(invalid)}. Choose from: {", ".join(sorted(_VALID_FORMATS))}'
        )
    normalised = ['markdown' if f in ('md', 'markdown') else f for f in raw]
    return list(dict.fromkeys(normalised)) or ['json']


def _effective_workers(requested: int, total: int) -> int:
    """Resolve CLI worker count; 0 means auto bounded by URL count."""
    if requested < 0:
        raise click.BadParameter('--workers must be >= 0')
    if total < 1:
        return 1
    if requested == 0:
        return min(total, _DEFAULT_AUTO_WORKERS)
    return min(requested, total)


def _collect_urls(url: tuple[str, ...], file_path: str | None, limit: int | None, ui: Console) -> list[str]:
    urls: list[str] = list(url)
    if file_path:
        urls.extend(load_urls_from_file(file_path))
    if not urls:
        raise click.UsageError('No URLs provided. Use --url <url> or --file <file>')
    if limit is not None:
        if limit < 1:
            raise click.BadParameter('--limit must be >= 1')
        urls = urls[:limit]
        ui.print(f'[cyan]ℹ Limiting to first {limit} URLs[/cyan]')
    return urls


async def _run_json(
    pipeline_ctx: object,
    urls: list[str],
    force: bool,
    skip_verification: bool,
    fetcher: str,
    output_formats: list[str],
) -> int:
    from yosoi import Pipeline
    from yosoi.cli import exit_codes

    pipeline_obj: Pipeline = pipeline_ctx  # type: ignore[assignment]
    async with pipeline_obj as pipeline:
        for url in urls:
            async for item in pipeline.scrape(
                url,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=fetcher,
                output_format=output_formats,
            ):
                sys.stdout.write(json.dumps(item, default=str) + '\n')
                sys.stdout.flush()

    return exit_codes.RECORDS


# ── shared option decorators ──────────────────────────────────────────────────


# ── main group ────────────────────────────────────────────────────────────────


@click.group(cls=MachineReadableGroup, invoke_without_command=True, context_settings=_CONTEXT_SETTINGS)
@click.pass_context
@click.option(
    '-m',
    '--model',
    default=None,
    metavar='PROVIDER:MODEL',
    help='LLM model (e.g. groq:llama-3.3-70b-versatile). Defaults to $YOSOI_MODEL env var if set.',
)
@click.option('-u', '--url', multiple=True, help='URL to process. Repeat for multiple URLs.')
@click.option('-f', '--file', 'file_path', default=None, help='File containing URLs (one per line, or JSON)')
@click.option('-l', '--limit', type=int, default=None, help='Limit number of URLs to process from file')
@click.option('-F', '--force', is_flag=True, help='Force re-discovery even if selectors exist')
@click.option('-s', '--summary', is_flag=True, help='Show run/page/contract/domain tracking summary after scraping')
@click.option('-d', '--debug', is_flag=True, help='Enable debug mode (saves extracted HTML to debug/)')
@click.option('-S', '--skip-verification', is_flag=True, help='Skip verification for faster processing')
@click.option(
    '-o',
    '--output',
    multiple=True,
    default=('json',),
    metavar='FORMAT',
    help='Output format(s): json, md, jsonl, ndjson, csv, xlsx, parquet.',
)
@click.option(
    '-t',
    '--fetcher',
    type=click.Choice(_FETCHER_CHOICES, case_sensitive=False),
    default='auto',
    help='HTML fetcher to use',
)
@click.option(
    '-L',
    '--log-level',
    type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'ALL'], case_sensitive=False),
    default=os.getenv('YOSOI_LOG_LEVEL', 'INFO'),
    help='Logging level for the local log file',
)
@click.option(
    '-C',
    '--contract',
    type=ContractParamType(),
    default=None,
    help='Contract: @name, path/to/file.json, inline JSON, or path:Class',
)
@click.option(
    '-w',
    '--workers',
    type=int,
    default=0,
    metavar='N',
    help='Concurrent URL workers. 0=auto, capped at 4; use 1 for sequential.',
)
@click.option(
    '-x',
    '--selector-level',
    type=click.Choice(list(_LEVEL_MAP), case_sensitive=False),
    default=_DEFAULT_SELECTOR_LEVEL,
    help='Maximum selector strategy level (default: all)',
)
@click.option(
    '--session-id', 'session_id', default=None, metavar='ID', help='Override the Langfuse session id for this run.'
)
@click.option(
    '-j',
    '--json',
    'json_output',
    is_flag=True,
    default=False,
    help='Emit records as NDJSON on stdout; logs/progress on stderr. Exit 0=records, 2=needs_discovery, 1=error.',
)
def main(
    ctx: click.Context,
    model: str | None,
    url: tuple[str, ...],
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
    session_id: str | None,
    json_output: bool,
) -> None:
    """Discover selectors from web pages using AI.

    [bold]Examples:[/bold]

    yosoi -u https://example.com

    yosoi scrape -u https://example.com --contract @Product

    yosoi discover -u https://example.com --contract @Product

    yosoi cache status example.com
    """
    if ctx.invoked_subcommand is not None:
        # Sub-command (scrape / discover / cache) will handle everything.
        return

    # ── Legacy / bare invocation ──────────────────────────────────────────────
    if session_id is not None:
        os.environ['YOSOI_SESSION_ID'] = session_id

    from yosoi import Pipeline
    from yosoi.utils.files import init_yosoi, is_initialized
    from yosoi.utils.logging import setup_local_logging

    if not is_initialized():
        init_yosoi()

    log_file = setup_local_logging(level=log_level)
    output_formats = _resolve_output_formats(output)
    resolved_contract = contract if contract else NewsArticle
    resolved_level = _LEVEL_MAP[selector_level.lower()]
    policy = build_policy(
        model,
        debug,
        force=force,
        skip_verification=skip_verification,
        fetcher_type=fetcher,
        selector_level=resolved_level,
        output_formats=output_formats,
        quiet=json_output,
        json_output=json_output,
        max_concurrency=workers or None,
    )

    ui: Console = Console(theme=_THEME, stderr=True) if json_output else console

    ui.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')

    if selector_level.lower() != _DEFAULT_SELECTOR_LEVEL:
        ui.print(f'[cyan]ℹ Selector level:[/cyan] [bold]{selector_level}[/bold]')

    if summary and not (url or file_path):
        pipeline = Pipeline(policy=policy, contract=resolved_contract, output_format=list(output_formats))
        asyncio.run(pipeline.show_summary())
        return

    urls = _collect_urls(url, file_path, limit, ui)

    if debug:
        ui.print('[cyan]ℹ Debug mode enabled[/cyan] [dim]- extracted HTML will be saved to .yosoi/debug/[/dim]')

    if json_output:
        from yosoi.cli import exit_codes

        stderr_con = Console(theme=_THEME, stderr=True)
        pipeline = Pipeline(
            None,
            contract=resolved_contract,
            output_format=output_formats,
            selector_level=resolved_level,
            console=stderr_con,
            policy=policy,
            show_tracking_summary=summary,
        )
        try:
            exit_code = asyncio.run(_run_json(pipeline, urls, force, skip_verification, fetcher, list(output_formats)))
        except Exception as exc:  # noqa: BLE001
            err_doc = json.dumps({'type': 'error', 'message': str(exc)})
            sys.stdout.write(err_doc + '\n')
            sys.stdout.flush()
            sys.exit(exit_codes.ERROR)
        sys.exit(exit_code)

    if not json_output:
        ui.print(f'[cyan]ℹ Output format(s):[/cyan] [bold]{", ".join(output_formats)}[/bold]')
        print_fetcher_info(fetcher)

    effective_workers = _effective_workers(workers, len(urls))
    if workers == 0 and effective_workers > 1:
        ui.print(f'[cyan]ℹ Auto workers:[/cyan] [bold]{effective_workers}[/bold] concurrent URL tasks')
    elif workers > 1 and len(urls) == 1:
        ui.print(f'[cyan]ℹ --workers {workers} has no effect with a single URL, running sequentially[/cyan]')
    elif workers > len(urls):
        ui.print(f'[cyan]ℹ --workers {workers} capped to {len(urls)} (one per URL)[/cyan]')
    elif effective_workers > 1:
        ui.print(f'[cyan]ℹ Using {effective_workers} concurrent workers via taskiq[/cyan]')

    pipeline = Pipeline(
        None,
        contract=resolved_contract,
        output_format=output_formats,
        selector_level=resolved_level,
        policy=policy,
        show_tracking_summary=summary,
    )
    asyncio.run(
        pipeline.process_urls(
            urls,
            workers=effective_workers,
            force=force,
            skip_verification=skip_verification,
            fetcher_type=fetcher,
            origin='cli',
        )
    )


# ── scrape command — replay-only ──────────────────────────────────────────────


@main.command('scrape')
@click.argument('urls', nargs=-1)
@click.option(
    '-u', '--url', multiple=True, help='URL to scrape (alternative to positional URL). Repeat for multiple URLs.'
)
@click.option('-f', '--file', 'file_path', default=None, help='File containing URLs.')
@click.option('-l', '--limit', type=int, default=None, help='Limit number of URLs from --file.')
@click.option(
    '-m',
    '--model',
    default=None,
    metavar='PROVIDER:MODEL',
    help='LLM model override; default resolves from policy/env.',
)
@click.option(
    '-C',
    '--contract',
    type=ContractParamType(),
    multiple=True,
    help='Contract: @name, path/to/file.json, inline JSON, or path:Class. Repeat for multiple contracts.',
)
@click.option('--request', 'request_file', default=None, metavar='FILE', help='ScrapeRequest JSON file.')
@click.option('--dump-request', is_flag=True, help='Print the resolved ScrapeRequest JSON and exit.')
@click.option('-s', '--summary', is_flag=True, help='Show run/page/contract/domain tracking summary.')
@click.option('-S', '--skip-verification', is_flag=True, help='Skip selector verification after extraction.')
@click.option(
    '-o',
    '--output',
    multiple=True,
    default=('json',),
    metavar='FORMAT',
    help='Output format(s); repeat or comma-separate.',
)
@click.option(
    '-t',
    '--fetcher',
    type=click.Choice(_FETCHER_CHOICES, case_sensitive=False),
    default='auto',
    help='Fetch strategy: auto tries cheap HTTP first, then browser tiers as needed.',
)
@click.option(
    '-L',
    '--log-level',
    type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'ALL'], case_sensitive=False),
    default=os.getenv('YOSOI_LOG_LEVEL', 'INFO'),
    help='Local file log level; defaults to $YOSOI_LOG_LEVEL or INFO.',
)
@click.option(
    '-x',
    '--selector-level',
    type=click.Choice(list(_LEVEL_MAP), case_sensitive=False),
    default=_DEFAULT_SELECTOR_LEVEL,
    help='Selector strategy level used for discovery/cache replay.',
)
@click.option(
    '--json',
    'json_output',
    is_flag=True,
    default=False,
    help='Machine JSON to stdout; exit 0=records, 1=error.',
)
@click.option(
    '-w',
    '--workers',
    type=int,
    default=0,
    metavar='N',
    help='Concurrent URL workers. 0=auto, capped at 4; use 1 for sequential.',
)
@click.option('--session-id', default=None)
def scrape(
    urls: tuple[str, ...],
    url: tuple[str, ...],
    file_path: str | None,
    limit: int | None,
    model: str | None,
    contract: tuple[type[Contract], ...],
    request_file: str | None,
    dump_request: bool,
    summary: bool,
    skip_verification: bool,
    output: tuple[str, ...],
    fetcher: str,
    log_level: str,
    selector_level: str,
    json_output: bool,
    workers: int,
    session_id: str | None,
) -> None:
    """Scrape URL(s) through the public ys.scrape operation surface.

    ``--request`` accepts ScrapeRequest JSON. Repeating ``--contract`` runs the
    URL axis against multiple contracts, matching ``ys.scrape`` grid semantics.
    """
    if session_id is not None:
        os.environ['YOSOI_SESSION_ID'] = session_id

    from yosoi import Pipeline
    from yosoi.operations import ScrapeRequest, run_scrape
    from yosoi.utils.files import init_yosoi, is_initialized
    from yosoi.utils.logging import setup_local_logging

    if not is_initialized():
        init_yosoi()

    log_file = setup_local_logging(level=log_level)
    output_formats = _resolve_output_formats(output)
    resolved_contracts = list(contract) or [NewsArticle]
    resolved_contract = resolved_contracts[0]
    resolved_level = _LEVEL_MAP[selector_level.lower()]
    policy = build_policy(
        model,
        False,
        force=False,
        skip_verification=skip_verification,
        fetcher_type=fetcher,
        selector_level=resolved_level,
        output_formats=output_formats,
        quiet=json_output or dump_request,
        json_output=json_output,
    )

    ui: Console = Console(theme=_THEME, stderr=True) if json_output else console
    if not dump_request:
        ui.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')

    all_urls: list[str] = list(urls) + list(url) + (load_urls_from_file(file_path) if file_path else [])
    if limit is not None:
        all_urls = all_urls[: max(1, limit)]

    if request_file:
        try:
            with open(request_file, encoding='utf-8') as handle:
                request = ScrapeRequest.model_validate_json(handle.read())
        except Exception as exc:
            raise click.ClickException(f'Cannot parse ScrapeRequest {request_file!r}: {exc}') from exc
    else:
        if not all_urls:
            raise click.UsageError('No URLs provided. Pass URL(s) as arguments or use --url / --file')
        request = ScrapeRequest.from_axes(
            all_urls,
            resolved_contracts,
            model=model,
            policy=policy,
            force=False,
            skip_verification=skip_verification,
            fetcher_type=fetcher,
            selector_level=selector_level,
            save_formats=list(output_formats),
        )

    if dump_request:
        click.echo(request.model_dump_json(indent=2))
        return

    if json_output:
        from yosoi.cli import exit_codes

        try:
            result = asyncio.run(run_scrape(request))
        except Exception as exc:  # noqa: BLE001
            sys.stdout.write(json.dumps({'type': 'error', 'message': str(exc)}) + '\n')
            sys.stdout.flush()
            sys.exit(exit_codes.ERROR)
        sys.stdout.write(result.model_dump_json() + '\n')
        sys.stdout.flush()
        sys.exit(exit_codes.RECORDS)

    if len(request.contracts) != 1:
        raise click.UsageError('Multiple contracts currently require --json or --dump-request')

    effective_workers = _effective_workers(workers, len(request.urls))
    if workers == 0 and effective_workers > 1:
        ui.print(f'[cyan]ℹ Auto workers:[/cyan] [bold]{effective_workers}[/bold] concurrent URL tasks')

    # Human mode keeps the existing rich pipeline display.
    pipeline = Pipeline(
        None,
        contract=resolved_contract,
        output_format=output_formats,
        selector_level=resolved_level,
        policy=policy,
        show_tracking_summary=summary,
    )
    asyncio.run(
        pipeline.process_urls(
            request.urls,
            workers=effective_workers,
            force=False,
            skip_verification=skip_verification,
            fetcher_type=fetcher,
            origin='cli',
        )
    )


# ── discover command — expensive LLM path ─────────────────────────────────────


@main.command('discover')
@click.argument('urls', nargs=-1)
@click.option('-u', '--url', multiple=True)
@click.option('-f', '--file', 'file_path', default=None)
@click.option('-l', '--limit', type=int, default=None)
@click.option('-m', '--model', default=None, metavar='PROVIDER:MODEL')
@click.option(
    '-C',
    '--contract',
    type=ContractParamType(),
    default=None,
    help='Contract: @name, path/to/file.json, inline JSON, or path:Class',
)
@click.option('-d', '--debug', is_flag=True)
@click.option('-S', '--skip-verification', is_flag=True)
@click.option('-o', '--output', multiple=True, default=('json',), metavar='FORMAT')
@click.option(
    '-t',
    '--fetcher',
    type=click.Choice(_FETCHER_CHOICES, case_sensitive=False),
    default='auto',
)
@click.option(
    '-L',
    '--log-level',
    type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'ALL'], case_sensitive=False),
    default=os.getenv('YOSOI_LOG_LEVEL', 'INFO'),
)
@click.option(
    '-x', '--selector-level', type=click.Choice(list(_LEVEL_MAP), case_sensitive=False), default=_DEFAULT_SELECTOR_LEVEL
)
@click.option('-w', '--workers', type=int, default=1, metavar='N')
@click.option('--session-id', default=None)
@click.option('--json', 'json_output', is_flag=True, default=False)
def discover(
    urls: tuple[str, ...],
    url: tuple[str, ...],
    file_path: str | None,
    limit: int | None,
    model: str | None,
    contract: type[Contract] | None,
    debug: bool,
    skip_verification: bool,
    output: tuple[str, ...],
    fetcher: str,
    log_level: str,
    selector_level: str,
    workers: int,
    session_id: str | None,
    json_output: bool,
) -> None:
    """Run LLM-powered selector discovery and populate the cache.

    This is the expensive path that calls the LLM. Run this once per domain;
    subsequent scrapes replay the cached selectors without LLM cost.
    """
    if session_id is not None:
        os.environ['YOSOI_SESSION_ID'] = session_id

    from yosoi import Pipeline
    from yosoi.utils.files import init_yosoi, is_initialized
    from yosoi.utils.logging import setup_local_logging

    if not is_initialized():
        init_yosoi()

    log_file = setup_local_logging(level=log_level)
    output_formats = _resolve_output_formats(output)
    resolved_contract = contract if contract else NewsArticle
    resolved_level = _LEVEL_MAP[selector_level.lower()]
    policy = build_policy(
        model,
        debug,
        force=True,
        skip_verification=skip_verification,
        fetcher_type=fetcher,
        selector_level=resolved_level,
        output_formats=output_formats,
        quiet=json_output,
        json_output=json_output,
        max_concurrency=workers or None,
    )

    ui: Console = Console(theme=_THEME, stderr=True) if json_output else console
    ui.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')
    ui.print('[cyan]ℹ Running LLM discovery (expensive path)...[/cyan]')

    all_urls: list[str] = list(urls) + list(url) + (load_urls_from_file(file_path) if file_path else [])
    if not all_urls:
        raise click.UsageError('No URLs provided.')
    if limit is not None:
        all_urls = all_urls[: max(1, limit)]

    effective_workers = min(workers, len(all_urls))

    if json_output:
        from yosoi.cli import exit_codes

        stderr_con = Console(theme=_THEME, stderr=True)
        pipeline = Pipeline(
            None,
            contract=resolved_contract,
            output_format=output_formats,
            selector_level=resolved_level,
            console=stderr_con,
            policy=policy,
        )
        try:
            exit_code = asyncio.run(
                _run_json(pipeline, all_urls, True, skip_verification, fetcher, list(output_formats))
            )
        except Exception as exc:  # noqa: BLE001
            sys.stdout.write(json.dumps({'type': 'error', 'message': str(exc)}) + '\n')
            sys.stdout.flush()
            sys.exit(exit_codes.ERROR)
        sys.exit(exit_code)

    pipeline = Pipeline(
        None,
        contract=resolved_contract,
        output_format=output_formats,
        selector_level=resolved_level,
        policy=policy,
    )
    asyncio.run(
        pipeline.process_urls(
            all_urls,
            workers=effective_workers,
            force=True,  # always re-discover
            skip_verification=skip_verification,
            fetcher_type=fetcher,
            origin='cli',
        )
    )


# ── crawl command — ys.crawl operation surface ────────────────────────────────


@main.command('crawl')
@click.argument('seeds', nargs=-1)
@click.option(
    '-u', '--url', multiple=True, help='Seed URL (alternative to positional seed). Repeat for multiple seeds.'
)
@click.option('-f', '--file', 'file_path', default=None, help='File containing seed URLs')
@click.option('-l', '--limit', type=int, default=None)
@click.option('-C', '--contract', type=ContractParamType(), multiple=True, help='Target contract. Repeat for multiple.')
@click.option('--policy', 'policy_file', default=None, metavar='FILE', help='Policy JSON file.')
@click.option('--request', 'request_file', default=None, metavar='FILE', help='CrawlRequest JSON file.')
@click.option('--dump-request', is_flag=True, help='Print the resolved CrawlRequest JSON and exit.')
@click.option('-t', '--fetcher', type=click.Choice(_FETCHER_CHOICES, case_sensitive=False), default=None)
@click.option('--persist', is_flag=True, help='Persist crawl frontier/checkpoint state.')
@click.option('--progress/--no-progress', default=None)
@click.option('--json', 'json_output', is_flag=True, default=False)
def crawl(
    seeds: tuple[str, ...],
    url: tuple[str, ...],
    file_path: str | None,
    limit: int | None,
    contract: tuple[type[Contract], ...],
    policy_file: str | None,
    request_file: str | None,
    dump_request: bool,
    fetcher: str | None,
    persist: bool,
    progress: bool | None,
    json_output: bool,
) -> None:
    """Crawl seed URL(s) through the public ys.crawl operation surface."""
    from dataclasses import asdict

    from yosoi.cli import exit_codes
    from yosoi.operations import CrawlRequest, run_crawl
    from yosoi.policy import Policy

    if request_file:
        try:
            with open(request_file, encoding='utf-8') as handle:
                request = CrawlRequest.model_validate_json(handle.read())
        except Exception as exc:
            raise click.ClickException(f'Cannot parse CrawlRequest {request_file!r}: {exc}') from exc
    else:
        all_seeds: list[str] = list(seeds) + list(url) + (load_urls_from_file(file_path) if file_path else [])
        if not all_seeds:
            raise click.UsageError('No seeds provided. Pass seed(s) as arguments or use --url / --file')
        policy = None
        if policy_file:
            try:
                with open(policy_file, encoding='utf-8') as handle:
                    policy = Policy.model_validate_json(handle.read())
            except Exception as exc:
                raise click.ClickException(f'Cannot parse Policy {policy_file!r}: {exc}') from exc
        request = CrawlRequest.from_axes(
            all_seeds,
            list(contract) or None,
            limit=limit,
            policy=policy,
            fetcher_type=fetcher,
            persist=persist,
            progress=progress if progress is not None else (False if json_output else None),
        )

    if dump_request:
        click.echo(request.model_dump_json(indent=2))
        return

    if json_output:
        try:
            result = asyncio.run(run_crawl(request))
        except Exception as exc:  # noqa: BLE001
            sys.stdout.write(json.dumps({'type': 'error', 'message': str(exc)}) + '\n')
            sys.stdout.flush()
            sys.exit(exit_codes.ERROR)
        sys.stdout.write(result.model_dump_json() + '\n')
        sys.stdout.flush()
        sys.exit(exit_codes.RECORDS)

    from yosoi.operations import execute_crawl

    summary = asyncio.run(execute_crawl(request))
    console.print(json.dumps(asdict(summary), default=str, indent=2))


# ── policy command group ──────────────────────────────────────────────────────


@main.group('policy')
def policy_group() -> None:
    """Inspect and validate policy JSON."""


@policy_group.command('defaults')
@click.option('--crawl', 'crawl_defaults', is_flag=True, help='Show crawl.conservative defaults.')
@click.option('--json', 'json_output', is_flag=True, default=False)
def policy_defaults(crawl_defaults: bool, json_output: bool) -> None:
    """Print default policy JSON."""
    from yosoi.policy import Policy

    _ = json_output
    policy = Policy.for_crawl('crawl.conservative') if crawl_defaults else Policy()
    click.echo(policy.model_dump_json(indent=2))


@policy_group.command('validate')
@click.argument('policy_file')
@click.option('--json', 'json_output', is_flag=True, default=False)
def policy_validate(policy_file: str, json_output: bool) -> None:
    """Validate a policy JSON file."""
    from yosoi.policy import Policy

    try:
        with open(policy_file, encoding='utf-8') as handle:
            Policy.model_validate_json(handle.read())
    except Exception as exc:
        if json_output:
            echo_json({'type': 'error', 'command': 'policy.validate', 'policy_file': policy_file, 'message': str(exc)})
            sys.exit(1)
        raise click.ClickException(f'Invalid policy {policy_file!r}: {exc}') from exc
    if json_output:
        echo_json({'type': 'policy.validate', 'status': 'ok', 'policy_file': policy_file})
        return
    console.print('[success]✓ Policy valid[/success]')


@policy_group.command('inspect')
@click.argument('policy_file')
@click.option('--json', 'json_output', is_flag=True, default=False)
def policy_inspect(policy_file: str, json_output: bool) -> None:
    """Print a normalized policy JSON file."""
    from yosoi.policy import Policy

    _ = json_output
    try:
        with open(policy_file, encoding='utf-8') as handle:
            policy = Policy.model_validate_json(handle.read())
    except Exception as exc:
        raise click.ClickException(f'Invalid policy {policy_file!r}: {exc}') from exc
    click.echo(policy.model_dump_json(indent=2))


# ── cache command group ────────────────────────────────────────────────────────


@main.group('cache')
def cache_group() -> None:
    """Cache management commands."""


@cache_group.command('status')
@click.argument('target', required=False)
@click.option('-C', '--contract', type=ContractParamType(), default=None, help='Contract to check fingerprint for')
@click.option('--domain', 'domain_target', default=None, metavar='DOMAIN', help='Explicit domain target.')
@click.option('--url', 'url_target', default=None, metavar='URL', help='Explicit URL target.')
@click.option('--route', 'route_target', default=None, metavar='PATH', help='Explicit route/path target.')
@click.option('-j', '--json', 'json_output', is_flag=True, default=False)
def cache_status(
    target: str | None,
    contract: type[Contract] | None,
    domain_target: str | None,
    url_target: str | None,
    route_target: str | None,
    json_output: bool,
) -> None:
    """Show cache status for a contract, domain, URL, or route.

    TARGET may be @Contract, example.com, https://example.com/page, or /route/path.
    Use explicit --contract/--domain/--url/--route when smart routing is ambiguous.
    """
    from yosoi.cli.cache_target import classify_cache_status_target, explicit_cache_status_target
    from yosoi.storage import SelectorStorage
    from yosoi.utils.files import init_yosoi, is_initialized
    from yosoi.utils.signatures import contract_signature

    try:
        explicit_target = explicit_cache_status_target(domain_target, url_target, route_target)
        if target and explicit_target is not None:
            raise click.UsageError('Use either positional TARGET or explicit --domain/--url/--route, not both.')
        routed_target = classify_cache_status_target(target) if target else explicit_target
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    resolved_contract = contract
    if routed_target is not None and routed_target.kind == 'contract':
        target_contract = ContractParamType().convert(routed_target.value, None, None)
        if resolved_contract is not None and contract_signature(resolved_contract) != contract_signature(
            target_contract
        ):
            raise click.UsageError('Contract TARGET conflicts with --contract. Use only one contract selector.')
        resolved_contract = target_contract

    if routed_target is None:
        if resolved_contract is None:
            raise click.UsageError('Missing target. Pass TARGET or --contract/--domain/--url/--route.')
        routed_kind = 'contract'
        target_value = f'@{resolved_contract.__name__}'
        domain = None
    else:
        routed_kind = routed_target.kind
        target_value = routed_target.raw
        domain = routed_target.domain

    if not is_initialized():
        init_yosoi()

    def _metrics_status_doc(message: str) -> dict[str, object]:
        doc: dict[str, object] = {
            'type': 'cache.status',
            'target': target_value,
            'target_kind': routed_kind,
            'status': 'cache_metrics_sqlite_unavailable',
            'cached': False,
            'fields': [],
            'message': message,
        }
        if resolved_contract is not None:
            doc['contract'] = resolved_contract.__name__
            doc['contract_fingerprint'] = contract_signature(resolved_contract)
        if routed_target is not None and routed_target.route is not None:
            doc['route'] = routed_target.route
        return doc

    if domain is None:
        if resolved_contract is not None:
            fp = contract_signature(resolved_contract)
            try:
                from yosoi.storage.cache_metrics_sqlite import SQLiteCacheMetricsStore

                summary = asyncio.run(SQLiteCacheMetricsStore().summarize_contract(fp))
                field_metrics = [row.__dict__ for row in summary.field_metrics]
                doc: dict[str, object] = {
                    'type': 'cache.status',
                    'target': target_value,
                    'target_kind': routed_kind,
                    'contract': resolved_contract.__name__,
                    'contract_fingerprint': fp,
                    'cached': bool(field_metrics),
                    'domains': summary.domains,
                    'routes': summary.routes,
                    'fields': summary.fields,
                    'field_metrics': field_metrics,
                }
                if json_output:
                    echo_json(doc)
                    return
                console.print(f'[info]Contract:[/info] {resolved_contract.__name__}')
                console.print(f'  Fingerprint: [bold]{fp}[/bold]')
                if not field_metrics:
                    console.print('[warning]✗ No cache metrics for this contract[/warning]')
                    return
                console.print(f'  Domains: {", ".join(summary.domains)}')
                console.print(f'  Routes: {", ".join(summary.routes)}')
                console.print(f'  Fields: {", ".join(summary.fields)}')
                return
            except Exception as exc:  # noqa: BLE001
                doc = _metrics_status_doc(f'Could not read cache metrics DB: {exc}')
                if json_output:
                    echo_json(doc)
                    return
                console.print(f'[warning]{doc["message"]}[/warning]')
                return

        doc = _metrics_status_doc('Route usage status requires a domain or URL until route-wide metrics queries land.')
        if json_output:
            echo_json(doc)
            return
        if routed_target is not None and routed_target.route is not None:
            console.print(f'[info]Route:[/info] {routed_target.route}')
        console.print(f'[warning]{doc["message"]}[/warning]')
        return

    storage = SelectorStorage()

    async def _check() -> dict[str, object]:
        contract_sig = contract_signature(resolved_contract) if resolved_contract is not None else None
        snapshots = await storage.load_snapshots(domain, contract_sig=contract_sig)
        doc: dict[str, object] = {
            'type': 'cache.status',
            'target': target_value,
            'target_kind': routed_kind,
            'domain': domain,
            'cached': bool(snapshots),
            'fields': sorted(snapshots) if snapshots else [],
        }
        if routed_target is not None and routed_target.route is not None:
            doc['route'] = routed_target.route
        if contract_sig is not None:
            doc['contract'] = resolved_contract.__name__ if resolved_contract is not None else None
            doc['contract_fingerprint'] = contract_sig

        if not snapshots:
            if not json_output:
                console.print(f'[warning]✗ No cached selectors for {domain!r}[/warning]')
            return doc

        if not json_output:
            console.print(f'[success]✓ Cached selectors for {domain!r}[/success]')
            console.print(f'  Fields: {", ".join(sorted(snapshots))}')

        if resolved_contract is not None:
            spec = resolved_contract.to_spec()
            fp = spec.fingerprint
            cached_fields = set(snapshots)
            contract_fields = resolved_contract.discovery_field_names()
            missing = sorted(contract_fields - cached_fields)
            doc['missing_fields'] = missing
            if not json_output:
                console.print(f'  Contract fingerprint: [bold]{fp}[/bold]')
                if missing:
                    console.print(f'  [warning]Missing fields: {", ".join(missing)}[/warning]')
                else:
                    console.print('  [success]All contract fields cached[/success]')
        return doc

    doc = asyncio.run(_check())
    if json_output:
        echo_json(doc)


# ── contracts command group (CAS-122) ─────────────────────────────────────────


@main.group('contracts')
def contracts_group() -> None:
    """Manage the local content-addressed contracts store."""


@contracts_group.command('list')
@click.option('--store', default=None, metavar='DIR', help='Contracts store directory (default: .yosoi/contracts)')
@click.option('--json', 'json_output', is_flag=True, default=False)
def contracts_list(store: str | None, json_output: bool) -> None:
    """List built-in/registered contracts and local store aliases."""
    from yosoi.models.contract import _CONTRACT_REGISTRY
    from yosoi.models.defaults import BUILTIN_SCHEMAS
    from yosoi.storage.contracts_store import ContractStore

    seen: set[str] = set()
    builtins = []
    for name, cls in sorted({**BUILTIN_SCHEMAS, **_CONTRACT_REGISTRY}.items()):
        seen.add(name)
        builtins.append({'name': name, 'fingerprint': cls.to_spec().fingerprint})

    cs = ContractStore(store)
    aliases = [{'name': name, 'fingerprint': fp} for name, fp in cs.list_aliases() if name not in seen]
    if json_output:
        echo_json({'type': 'contracts.list', 'builtins': builtins, 'aliases': aliases})
        return

    console.print('[bold]Available contracts[/bold] [dim](fingerprint = stable structural contract id)[/dim]')
    for item in builtins:
        console.print(f'  [bold]{item["name"]}[/bold]  [dim]{item["fingerprint"]}[/dim]')

    if aliases:
        console.print('\n[bold]Local aliases[/bold] [dim](name → fingerprint)[/dim]')
        for item in aliases:
            console.print(f'  [bold]{item["name"]}[/bold]  [dim]{item["fingerprint"]}[/dim]')


@contracts_group.command('show')
@click.argument('name_or_fp')
@click.option('--store', default=None, metavar='DIR')
@click.option('--json', 'json_output', is_flag=True, default=False)
def contracts_show(name_or_fp: str, store: str | None, json_output: bool) -> None:
    """Show a ContractSpec by store alias/fingerprint or registered contract name."""
    from yosoi.storage.contracts_store import ContractStore
    from yosoi.utils.contracts import resolve_contract

    cs = ContractStore(store)
    try:
        spec = cs.get(name_or_fp)
    except KeyError:
        try:
            spec = resolve_contract(name_or_fp.removeprefix('@')).to_spec()
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    _ = json_output
    click.echo(spec.model_dump_json(indent=2))


@contracts_group.command('add')
@click.argument('spec_file')
@click.option('--name', default=None, metavar='ALIAS', help='Alias name (defaults to spec name)')
@click.option('--store', default=None, metavar='DIR')
@click.option('--json', 'json_output', is_flag=True, default=False)
def contracts_add(spec_file: str, name: str | None, store: str | None, json_output: bool) -> None:
    """Add a ContractSpec JSON file to the local store.

    SPEC_FILE is the path to a JSON file containing a ContractSpec.
    """
    import json

    from yosoi.models.spec import ContractSpec
    from yosoi.storage.contracts_store import ContractCollisionError, ContractStore

    try:
        with open(spec_file, encoding='utf-8') as f:
            data = json.load(f)
        spec = ContractSpec.model_validate(data)
    except (OSError, json.JSONDecodeError, Exception) as exc:
        raise click.ClickException(f'Cannot parse {spec_file!r}: {exc}') from exc

    # Lint before adding
    cs = ContractStore(store)
    errors = cs.lint(spec)
    if errors:
        for err in errors:
            console.print(f'[warning]lint: {err}[/warning]')
        raise click.ClickException('Spec failed lint checks. Fix errors before adding.')

    try:
        fp = cs.add(spec, name=name)
    except ContractCollisionError as exc:
        raise click.ClickException(str(exc)) from exc

    alias = name or spec.name
    if json_output:
        echo_json({'type': 'contracts.add', 'status': 'ok', 'alias': alias, 'fingerprint': fp})
        return
    console.print(f'[success]✓ Added {alias!r} → {fp}[/success]')


@contracts_group.command('lint')
@click.argument('spec_file')
@click.option('--json', 'json_output', is_flag=True, default=False)
def contracts_lint(spec_file: str, json_output: bool) -> None:
    """Validate a ContractSpec JSON file for governance issues."""
    import json

    from yosoi.models.spec import ContractSpec
    from yosoi.storage.contracts_store import ContractStore

    try:
        with open(spec_file, encoding='utf-8') as f:
            data = json.load(f)
        spec = ContractSpec.model_validate(data)
    except (OSError, json.JSONDecodeError, Exception) as exc:
        raise click.ClickException(f'Cannot parse {spec_file!r}: {exc}') from exc

    cs = ContractStore()
    errors = cs.lint(spec)
    if errors:
        if json_output:
            echo_json({'type': 'contracts.lint', 'status': 'error', 'spec_file': spec_file, 'errors': errors})
        else:
            for err in errors:
                console.print(f'[warning]✗ {err}[/warning]')
        sys.exit(1)
    if json_output:
        echo_json({'type': 'contracts.lint', 'status': 'ok', 'spec_file': spec_file})
        return
    console.print('[success]✓ Spec is valid[/success]')


@contracts_group.command('migrate')
@click.argument('spec_file')
@click.option('--in-place', is_flag=True, help='Write migrated spec back to the same file')
@click.option('--json', 'json_output', is_flag=True, default=False)
def contracts_migrate(spec_file: str, in_place: bool, json_output: bool) -> None:
    """Migrate a ContractSpec to the current schema version."""
    import json

    from yosoi.models.spec import ContractSpec
    from yosoi.storage.contracts_store import ContractStore

    try:
        with open(spec_file, encoding='utf-8') as f:
            data = json.load(f)
        spec = ContractSpec.model_validate(data)
    except (OSError, json.JSONDecodeError, Exception) as exc:
        raise click.ClickException(f'Cannot parse {spec_file!r}: {exc}') from exc

    cs = ContractStore()
    migrated = cs.migrate(spec)
    output = migrated.model_dump_json(indent=2)

    if in_place:
        with open(spec_file, 'w', encoding='utf-8') as f:
            f.write(output + '\n')
        if json_output:
            echo_json(
                {
                    'type': 'contracts.migrate',
                    'status': 'ok',
                    'spec_file': spec_file,
                    'schema_version': migrated.schema_version,
                    'in_place': True,
                }
            )
            return
        console.print(f'[success]✓ Migrated {spec_file!r} to schema_version {migrated.schema_version}[/success]')
    elif json_output:
        click.echo(output)
    else:
        console.print(output)


contract_alias_group = MachineReadableGroup(
    name='contract',
    help=contracts_group.help,
    short_help=contracts_group.short_help,
    commands=contracts_group.commands,
    hidden=True,
)
main.add_command(contract_alias_group)
