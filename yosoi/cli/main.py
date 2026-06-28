"""Main CLI command definition — verb group (CAS-121) with backward compat."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlparse

import rich_click as click
from click.core import ParameterSource
from rich.console import Console
from rich.table import Table
from rich.theme import Theme

from yosoi.cli.contract_param import ContractParamType
from yosoi.cli.machine import MachineReadableGroup, echo_json
from yosoi.cli.setup import build_policy, print_fetcher_info
from yosoi.cli.utils import console, load_urls_from_file
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.selectors import SelectorLevel

if TYPE_CHECKING:
    from yosoi.policy import Policy

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


def _new_crawl_run_id() -> str:
    return f'crawl-{datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:8]}'


def _run_crawl_json_safe(run_crawl: Any, request: Any, *, json_output: bool) -> Any:
    if not json_output:
        return asyncio.run(run_crawl(request))
    with redirect_stdout(sys.stderr):
        return asyncio.run(run_crawl(request))


def _has_command_line_root_options(ctx: click.Context) -> bool:
    """Return whether the root command received explicit CLI options."""
    return any(
        param.name is not None and ctx.get_parameter_source(param.name) is ParameterSource.COMMANDLINE
        for param in ctx.command.params
    )


def _apply_crawl_cli_overrides(
    policy: Policy,
    *,
    run_id: str | None,
    max_pages: int | None,
    max_depth: int | None,
    max_attempts: int | None,
    max_pages_per_host: int | None,
    workers: int | None,
    per_host_concurrency: int | None,
    politeness: float | None,
    timeout: float | None,
    retries: int | None,
    respect_robots: bool | None,
    allow_redirects: bool | None,
) -> Policy:
    """Layer crawl stress flags over an existing policy object."""
    from yosoi.policy import CrawlPolicy, Policy

    crawl = policy.require_crawl()
    payload = crawl.model_dump()

    budget = dict(payload.get('budget') or {})
    scheduler = dict(payload.get('scheduler') or {})
    safety = dict(payload.get('safety') or {})

    if max_pages is not None:
        budget['max_pages'] = max_pages
    if max_depth is not None:
        budget['max_depth'] = max_depth
    if max_attempts is not None:
        budget['max_attempts'] = max_attempts
    if max_pages_per_host is not None:
        budget['max_pages_per_host'] = max_pages_per_host
    if run_id is not None and not budget.get('crawl_session_id'):
        budget['crawl_session_id'] = run_id

    if workers is not None:
        scheduler['max_workers'] = workers
    if per_host_concurrency is not None:
        scheduler['per_host_concurrency'] = per_host_concurrency
    if politeness is not None:
        scheduler['politeness_delay'] = politeness
    if timeout is not None:
        scheduler['fetch_timeout_seconds'] = timeout
    if retries is not None:
        scheduler['max_fetch_retries'] = retries

    if respect_robots is not None:
        safety['respect_robots'] = respect_robots
    if allow_redirects is not None:
        safety['allow_redirects'] = allow_redirects

    payload['budget'] = budget
    payload['scheduler'] = scheduler
    payload['safety'] = safety
    return Policy.cascade(policy, Policy(crawl=CrawlPolicy.model_validate(payload)))


def _apply_profile_cli_overrides(
    policy: Policy,
    *,
    profile: str | None,
    profile_pool: str | None,
    max_live_profiles: int,
) -> Policy:
    """Layer scrape browser-profile flags over an existing policy."""
    if profile is None and profile_pool is None:
        return policy
    if profile is not None and profile_pool is not None:
        raise click.UsageError('--profile and --profile-pool are mutually exclusive')
    if max_live_profiles < 1:
        raise click.BadParameter('--max-live-profiles must be >= 1')

    from yosoi.policy import BrowserProfilePolicy, PagePolicy, Policy

    browser_profile = BrowserProfilePolicy(
        profile=profile,
        pool=profile_pool,
        headful=True,
        max_live=max_live_profiles,
    )
    return Policy.cascade(policy, Policy(page=PagePolicy(profile=browser_profile)))


def _render_compact_crawl(summary: dict[str, Any]) -> None:
    rows = list(summary.get('results', []))
    wall_time = float(summary.get('wall_time') or 0.0)
    console.print(
        f'Crawl stress {summary.get("status")}: '
        f'{summary.get("pages_fetched", 0)}/{summary.get("attempted_urls", 0)} fetched, '
        f'{summary.get("failures", 0)} failed, {wall_time:.2f}s',
        markup=False,
    )
    has_errors = any(row.get('error') for row in rows)
    header = f'{"#":>3}  {"status":<12} {"http":>4} {"d":>2} {"l":>3} {"bytes":>7} {"time":>7}  url'
    if has_errors:
        header = f'{header}  error'
    console.print(header, markup=False)
    if has_errors:
        console.print('-' * min(140, len(header)), markup=False)
    for row in rows:
        status_text = str(row.get('status') or '')
        status_code_text = str(row.get('status_code') or '')
        line = (
            f'{int(row.get("index") or 0):>3}  '
            f'{status_text:<12.12} '
            f'{status_code_text:>4.4} '
            f'{int(row.get("depth") or 0):>2} '
            f'{int(row.get("links") or 0):>3} '
            f'{int(row.get("html_chars") or 0):>7} '
            f'{float(row.get("fetch_time") or 0.0):>6.2f}s  '
            f'{row.get("url") or ""}'
        )
        if has_errors:
            line = f'{line}  {row.get("error") or ""}'
        console.print(line, markup=False)
    if not rows:
        console.print('  -  error           -  -   -       -      -  (no attempted URLs)', markup=False)
    if summary.get('run_id'):
        console.print(f'run_id={summary["run_id"]}', markup=False)


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


def _print_atom_reads_info(ui: Console, policy: object) -> None:
    if not getattr(policy, 'atom_reads', False):
        return
    trust_tier = getattr(policy, 'trust_tier', 'strict')
    if trust_tier == 'yellow':
        ui.print(
            '[cyan]⚛ Field atoms:[/cyan] [bold yellow]armed, yellow trust[/bold yellow] '
            '[dim](includes fingerprint-generalized atoms; legacy selector cache still wins)[/dim]'
        )
    else:
        ui.print(
            '[cyan]⚛ Field atoms:[/cyan] [bold green]armed, strict trust[/bold green] '
            '[dim](verified/manual/LLM atoms on selector-cache miss)[/dim]'
        )


def _print_map_result(result: object) -> None:
    from yosoi.core.site_map import MapResult

    typed = cast(MapResult, result)
    if typed.mode == 'subdomains':
        console.print(
            f'[cyan]Subdomains:[/cyan] [bold]{typed.root_host}[/bold] [dim]({len(typed.subdomains)} hosts)[/dim]'
        )
    else:
        console.print(
            f'[cyan]Map:[/cyan] [bold]{typed.root_host}[/bold] '
            f'[dim]({len(typed.urls)} URLs, {len(typed.sitemaps)} sitemap probes, {len(typed.hosts)} hosts)[/dim]'
        )
    if typed.robots_url:
        status = 'found' if typed.robots_found else 'missing'
        console.print(f'[cyan]Robots:[/cyan] {typed.robots_url} [dim]{status}[/dim]')

    if typed.hosts:
        host_table = Table(
            title='Subdomains' if typed.mode == 'subdomains' else 'Hosts',
            show_header=True,
            header_style='bold cyan',
        )
        host_table.add_column('Host')
        if typed.mode != 'subdomains':
            host_table.add_column('URLs', justify='right')
        host_table.add_column('Subdomain')
        for host in typed.hosts:
            if typed.mode == 'subdomains':
                host_table.add_row(host.host, host.subdomain or '')
            else:
                host_table.add_row(host.host, str(host.url_count), host.subdomain or '')
        console.print(host_table)

    if typed.sitemaps:
        sitemap_table = Table(title='Sitemaps', show_header=True, header_style='bold cyan')
        sitemap_table.add_column('Status')
        sitemap_table.add_column('Source')
        sitemap_table.add_column('URLs', justify='right')
        sitemap_table.add_column('URL')
        for sitemap in typed.sitemaps[:20]:
            sitemap_table.add_row(sitemap.status, sitemap.source, str(sitemap.url_count), sitemap.url)
        console.print(sitemap_table)

    if typed.urls:
        url_table = Table(title='Discovered URLs', show_header=True, header_style='bold cyan')
        url_table.add_column('Host')
        url_table.add_column('Path')
        url_table.add_column('Subdomain')
        for map_url in typed.urls[:30]:
            url_table.add_row(map_url.host, map_url.path, map_url.subdomain or '')
        console.print(url_table)

    for error in typed.errors:
        label = 'Map error' if typed.status == 'error' else 'Map warning'
        console.print(f'[warning]{label}:[/warning] {error}')


def _render_fetch_result(result: object) -> None:
    from yosoi.operations import FetchResult

    typed = cast(FetchResult, result)
    rendered = False
    for unit in typed.results:
        if unit.status != 'ok':
            console.print(f'[warning]Fetch error:[/warning] {unit.url} {unit.error or "failed"}', markup=False)
            continue
        if rendered:
            click.echo('\n---\n')
        click.echo(unit.content or '')
        rendered = True


def _render_content_result(result: object, output_format: str) -> None:
    from yosoi.operations import ContentResult

    typed = cast(ContentResult, result)
    rendered = False
    for unit in typed.results:
        if unit.status != 'ok':
            console.print(f'[warning]Content error:[/warning] {unit.url} {unit.error or "failed"}', markup=False)
            continue
        if rendered:
            click.echo('\n---\n')
        if output_format == 'text':
            click.echo(unit.text or '')
        else:
            click.echo(unit.markdown or '')
        rendered = True


def _write_fetch_output(path: Path, result: object) -> None:
    from yosoi.operations import FetchResult

    typed = cast(FetchResult, result)
    ok_units = [unit for unit in typed.results if unit.status == 'ok']
    if len(ok_units) == 1 and (path.suffix or not path.exists()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ok_units[0].content or '', encoding='utf-8')
        return
    path.mkdir(parents=True, exist_ok=True)
    for index, unit in enumerate(ok_units, start=1):
        parsed = urlparse(unit.final_url or unit.url)
        stem = (parsed.hostname or f'page-{index}').removeprefix('www.') + (parsed.path or '/').replace('/', '-')
        stem = re.sub(r'[^A-Za-z0-9_.-]+', '-', stem).strip('-') or f'page-{index}'
        (path / f'{index:03d}-{stem}.txt').write_text(unit.content or '', encoding='utf-8')


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
@click.option('--flat-files', is_flag=True, help='Also write extracted content to .yosoi/content flat files.')
@click.option(
    '--policy',
    'policy_source',
    multiple=True,
    metavar='FILE|YAML|JSON',
    help='Policy file or inline YAML/JSON. Repeat to layer.',
)
@click.option('--atom-reads', is_flag=True, help='Allow policy-gated reads from the field-atom index before discovery.')
@click.option('--no-llm', is_flag=True, help='Cache-only guard: fail instead of discovering or repairing selectors.')
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
    help='Emit records as NDJSON on stdout; logs/progress on stderr. Exit 0=records, 1=error.',
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
    flat_files: bool,
    policy_source: tuple[str, ...],
    atom_reads: bool,
    no_llm: bool,
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

    yosoi fetch https://example.com

    yosoi scrape -u https://example.com --contract @Product

    yosoi discover -u https://example.com --contract @Product

    yosoi cache status example.com
    """
    if ctx.invoked_subcommand is not None:
        # Sub-command (scrape / discover / cache) will handle everything.
        return

    if not _has_command_line_root_options(ctx):
        click.echo(ctx.get_help())
        return

    # ── Legacy root options (backward-compatible scrape path) ─────────────────
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
        flat_files=flat_files,
        atom_reads=atom_reads,
        policy_sources=policy_source,
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
            allow_llm=not no_llm,
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
        _print_atom_reads_info(ui, policy)
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
        allow_llm=not no_llm,
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


# ── fetch command — URL to clean document surface ────────────────────────────


@main.command('fetch')
@click.argument('urls', nargs=-1)
@click.option('-u', '--url', multiple=True, help='URL to fetch. Repeat for multiple URLs.')
@click.option('-f', '--file', 'file_path', default=None, help='File containing URLs.')
@click.option('-l', '--limit', type=int, default=None, help='Limit number of URLs.')
@click.option(
    '--policy',
    'policy_source',
    multiple=True,
    metavar='FILE|YAML|JSON',
    help='Policy file or inline YAML/JSON. Repeat to layer.',
)
@click.option(
    '-t',
    '--fetcher',
    type=click.Choice(_FETCHER_CHOICES, case_sensitive=False),
    default=None,
    help='Fetch strategy override. Defaults to policy page.fetcher_type.',
)
@click.option(
    '--view',
    type=click.Choice(
        ['text', 'markdown', 'html', 'clean-html', 'raw-html', 'rendered-html', 'ax', 'links', 'metadata', 'bundle'],
        case_sensitive=False,
    ),
    default='text',
    show_default=True,
    help='Content view to emit. markdown is deterministic/lossy; text is the safe default.',
)
@click.option('--page', 'content_page', type=int, default=1, show_default=True, help='1-indexed content page.')
@click.option('--page-size', '--chars', type=int, default=12_000, show_default=True, help='Max chars per page.')
@click.option(
    '--include',
    multiple=True,
    metavar='ITEMS',
    help='Comma-separated metadata to include: headers,network/endpoints,fingerprint,links,ax.',
)
@click.option(
    '-C',
    '--contract',
    type=ContractParamType(),
    multiple=True,
    help='Advisory contract probe. Repeat for multiple contracts; does not scrape or call the LLM.',
)
@click.option('-o', '--output', 'output_path', default=None, metavar='FILE|DIR', help='Write selected view or bundle.')
@click.option('--a3node', is_flag=True, help='Enable experimental A3Node acquisition recipe replay/minting.')
@click.option('--dump-request', is_flag=True, help='Print the resolved fetch request JSON and exit.')
@click.option('--json', 'json_output', is_flag=True, default=False, help='Emit machine JSON envelope on stdout.')
def fetch(
    urls: tuple[str, ...],
    url: tuple[str, ...],
    file_path: str | None,
    limit: int | None,
    policy_source: tuple[str, ...],
    fetcher: str | None,
    view: str,
    content_page: int,
    page_size: int,
    include: tuple[str, ...],
    contract: tuple[type[Contract], ...],
    output_path: str | None,
    a3node: bool,
    dump_request: bool,
    json_output: bool,
) -> None:
    """Fetch URL(s) as bounded page acquisition content without scraping."""
    from yosoi.cli import exit_codes
    from yosoi.operations import FetchRequest, run_fetch
    from yosoi.policy import PagePolicy, Policy
    from yosoi.policy.files import load_policy_layers

    if content_page < 1:
        raise click.BadParameter('--page must be >= 1')
    if page_size < 1:
        raise click.BadParameter('--page-size/--chars must be >= 1')

    ui: Console = Console(theme=_THEME, stderr=True) if json_output else console
    all_urls = _collect_urls(tuple(list(urls) + list(url)), file_path, limit, ui)
    policy = Policy.cascade(Policy.from_env(), load_policy_layers(policy_source))
    if fetcher is not None:
        policy = Policy.cascade(policy, Policy(page=PagePolicy(fetcher_type=cast(Any, fetcher))))
    include_items = [item for raw in include for item in raw.split(',') if item.strip()]
    normalised_view = view.lower().replace('-', '_')
    request = FetchRequest.from_axes(
        all_urls,
        list(contract) or None,
        view=normalised_view,
        policy=policy,
        fetcher_type=fetcher,
        page=content_page,
        page_size=page_size,
        include=include_items,
        output_dir=output_path if normalised_view == 'bundle' else None,
        experimental_a3node=a3node,
    )
    if dump_request:
        click.echo(request.model_dump_json(indent=2))
        return

    try:
        with redirect_stdout(sys.stderr):
            result = asyncio.run(run_fetch(request))
    except Exception as exc:
        if json_output:
            sys.stdout.write(json.dumps({'type': 'error', 'message': str(exc)}) + '\n')
            sys.stdout.flush()
            sys.exit(exit_codes.ERROR)
        raise click.ClickException(str(exc)) from exc

    if output_path and normalised_view != 'bundle':
        _write_fetch_output(Path(output_path), result)

    if json_output:
        sys.stdout.write(result.model_dump_json() + '\n')
        sys.stdout.flush()
    elif not output_path or normalised_view == 'bundle':
        _render_fetch_result(result)
    sys.exit(exit_codes.RECORDS if result.status == 'ok' else exit_codes.ERROR)


# ── search command — local web discovery surface ─────────────────────────────


@main.command('search')
@click.argument('query', nargs=-1)
@click.option('--limit', type=click.IntRange(1), default=None, help='Maximum number of search results.')
@click.option('--backend', default=None, help='DDGS backend string.')
@click.option('--region', default=None, help='Search region, such as us-en.')
@click.option(
    '--safesearch',
    type=click.Choice(['on', 'moderate', 'off'], case_sensitive=False),
    default=None,
    help='Safe search setting.',
)
@click.option('--timelimit', default=None, help='DDGS time limit, such as d, w, m, y, or a date range.')
@click.option('--page', type=click.IntRange(1), default=None, help='Search result page.')
@click.option(
    '--policy',
    'policy_source',
    multiple=True,
    metavar='FILE|YAML|JSON',
    help='Policy file or inline YAML/JSON. Repeat to layer.',
)
@click.option('--json', 'json_output', is_flag=True, default=False, help='Machine JSON to stdout.')
@click.option('--dump-request', is_flag=True, help='Print the resolved SearchRequest JSON and exit.')
def search(
    query: tuple[str, ...],
    limit: int | None,
    backend: str | None,
    region: str | None,
    safesearch: str | None,
    timelimit: str | None,
    page: int | None,
    policy_source: tuple[str, ...],
    json_output: bool,
    dump_request: bool,
) -> None:
    """Search the web and return normalized source URLs."""
    from rich import box
    from rich.table import Table

    from yosoi.cli import exit_codes
    from yosoi.operations import SearchRequest, run_search
    from yosoi.policy import Policy
    from yosoi.policy.files import discover_policy_files, load_policy_layers

    query_text = ' '.join(part for part in query if part).strip()
    if not query_text:
        raise click.UsageError('No search query provided.')

    safe_search = cast(Literal['on', 'moderate', 'off'], safesearch.lower()) if safesearch is not None else None
    try:
        file_policy = load_policy_layers(policy_source) if policy_source or discover_policy_files() else None
        policy = Policy.cascade(Policy.from_env(), file_policy)
        request = SearchRequest.from_policy(
            query_text,
            policy=policy,
            backend=backend,
            region=region,
            safesearch=safe_search,
            timelimit=timelimit,
            max_results=limit,
            page=page,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if dump_request:
        click.echo(request.model_dump_json(indent=2))
        return

    try:
        result = asyncio.run(run_search(request))
    except Exception as exc:
        if json_output:
            sys.stdout.write(json.dumps({'type': 'error', 'message': str(exc)}) + '\n')
            sys.stdout.flush()
            sys.exit(exit_codes.ERROR)
        raise click.ClickException(str(exc)) from exc

    if json_output:
        sys.stdout.write(result.model_dump_json() + '\n')
        sys.stdout.flush()
        sys.exit(exit_codes.RECORDS)

    table = Table(box=box.SIMPLE_HEAVY, show_lines=False)
    table.add_column('#', justify='right', style='cyan', no_wrap=True)
    table.add_column('Title', style='bold', overflow='fold')
    table.add_column('URL', style='blue', overflow='fold')
    table.add_column('Snippet', style='dim', overflow='fold')
    for hit in result.hits:
        table.add_row(str(hit.rank), hit.title, hit.url, hit.snippet)
    console.print(table)


@main.group('research')
def research() -> None:
    """Create and inspect local research-frontier packets."""


@research.command('init')
@click.argument('topic', nargs=-1, required=True)
@click.option('--packet-dir', type=click.Path(path_type=Path), default=None)
@click.option('--llm-budget-usd', type=float, default=0.0)
@click.option('--api-budget-usd', type=float, default=0.0)
@click.option('--json', 'json_output', is_flag=True, default=False)
def research_init(
    topic: tuple[str, ...],
    packet_dir: Path | None,
    llm_budget_usd: float,
    api_budget_usd: float,
    json_output: bool,
) -> None:
    """Create a research packet skeleton under .yosoi/research."""
    from yosoi.research import create_packet

    topic_text = ' '.join(topic).strip()
    packet = create_packet(
        topic_text,
        packet_dir=packet_dir,
        llm_budget_usd=llm_budget_usd,
        api_budget_usd=api_budget_usd,
    )
    if json_output:
        echo_json({'packet': str(packet), 'topic': topic_text})
        return
    console.print(str(packet), markup=False)


@research.command('observe')
@click.argument('packet', type=click.Path(path_type=Path))
@click.option('--from-scrape', 'scrape_artifact', type=click.Path(exists=True, path_type=Path), default=None)
@click.option('--from-search', 'search_artifact', type=click.Path(exists=True, path_type=Path), default=None)
@click.option('--from-crawl', 'crawl_artifact', type=click.Path(exists=True, path_type=Path), default=None)
@click.option('--note', default=None)
@click.option(
    '--contract-status',
    type=click.Choice(['candidate', 'validated', 'provisional', 'rejected', 'production']),
    default=None,
)
@click.option('--json', 'json_output', is_flag=True, default=False)
def research_observe(
    packet: Path,
    scrape_artifact: Path | None,
    search_artifact: Path | None,
    crawl_artifact: Path | None,
    note: str | None,
    contract_status: str | None,
    json_output: bool,
) -> None:
    """Append structured observations from search, crawl, scrape, or notes."""
    from yosoi.research import (
        ContractStatus,
        append_observations,
        observation_from_artifact,
        observation_from_note,
        observations_from_scrape,
    )

    sources = [value is not None for value in (scrape_artifact, search_artifact, crawl_artifact, note)]
    if sum(sources) != 1:
        raise click.UsageError('Pass exactly one of --from-scrape, --from-search, --from-crawl, or --note')

    observations = []
    if scrape_artifact is not None:
        scrape_status = cast('ContractStatus | None', contract_status)
        observations = observations_from_scrape(scrape_artifact, contract_status=scrape_status)
    elif search_artifact is not None:
        resolved_status = cast('ContractStatus', contract_status or 'candidate')
        observations = [observation_from_artifact('search', search_artifact, contract_status=resolved_status)]
    elif crawl_artifact is not None:
        resolved_status = cast('ContractStatus', contract_status or 'candidate')
        observations = [observation_from_artifact('crawl', crawl_artifact, contract_status=resolved_status)]
    elif note is not None:
        resolved_status = cast('ContractStatus', contract_status or 'candidate')
        observations = [observation_from_note(note, contract_status=resolved_status)]

    path = append_observations(packet, observations)
    payload = {'observations': len(observations), 'path': str(path)}
    if json_output:
        echo_json(payload)
        return
    console.print(f'Appended {len(observations)} observation(s) to {path}', markup=False)


@research.command('status')
@click.argument('packet', type=click.Path(exists=True, path_type=Path))
@click.option('--json', 'json_output', is_flag=True, default=False)
def research_status(packet: Path, json_output: bool) -> None:
    """Summarize contract promotion states and open quality gaps."""
    from rich import box

    from yosoi.research import summarize_packet

    summary = summarize_packet(packet)
    if json_output:
        echo_json(summary)
        return

    console.print(f'Research packet: {summary["topic"]}', markup=False)
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style='bold cyan')
    table.add_column('Contract')
    table.add_column('Status')
    table.add_column('Obs', justify='right')
    table.add_column('Quality')
    table.add_column('Records', justify='right')
    table.add_column('Latest Artifact', overflow='fold')
    for contract_name, row in summary['contracts'].items():
        table.add_row(
            contract_name,
            str(row.get('status') or ''),
            str(row.get('observations') or 0),
            str(row.get('latest_quality_status') or ''),
            str(row.get('latest_record_count') or ''),
            str(row.get('latest_artifact') or ''),
        )
    console.print(table)
    gaps = summary.get('open_quality_gaps') or []
    if gaps:
        console.print('[warning]Open replay/quality gaps:[/warning]')
        for gap in gaps:
            console.print(f'- {gap}', markup=False)


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
@click.option('--flat-files', is_flag=True, help='Also write extracted content to .yosoi/content flat files.')
@click.option(
    '--policy',
    'policy_source',
    multiple=True,
    metavar='FILE|YAML|JSON',
    help='Policy file or inline YAML/JSON. Repeat to layer.',
)
@click.option('--atom-reads', is_flag=True, help='Allow policy-gated reads from the field-atom index before discovery.')
@click.option('--no-llm', is_flag=True, help='Cache-only guard: fail instead of discovering or repairing selectors.')
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
@click.option('--a3node', is_flag=True, help='Enable experimental A3Node acquisition recipe replay/minting.')
@click.option('--profile-pool', default=None, metavar='NAME', help='VoidCrawl managed profile pool.')
@click.option('--profile', default=None, metavar='ID', help='VoidCrawl managed profile id.')
@click.option('--max-live-profiles', type=int, default=3, show_default=True, help='Active profile cap.')
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
    flat_files: bool,
    policy_source: tuple[str, ...],
    atom_reads: bool,
    no_llm: bool,
    fetcher: str,
    log_level: str,
    selector_level: str,
    json_output: bool,
    workers: int,
    a3node: bool,
    profile_pool: str | None,
    profile: str | None,
    max_live_profiles: int,
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
        flat_files=flat_files,
        atom_reads=atom_reads,
        policy_sources=policy_source,
    )
    policy = _apply_profile_cli_overrides(
        policy,
        profile=profile,
        profile_pool=profile_pool,
        max_live_profiles=max_live_profiles,
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
        updates: dict[str, object] = {}
        if no_llm:
            updates['allow_llm'] = False
        if a3node:
            updates['experimental_a3node'] = True
        if updates:
            request = request.model_copy(update=updates)
        if profile is not None or profile_pool is not None:
            request = request.model_copy(update={'policy': policy})
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
            allow_llm=not no_llm,
            experimental_a3node=a3node,
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
        sys.exit(exit_codes.RECORDS if result.status == 'ok' else exit_codes.ERROR)

    if len(request.contracts) != 1:
        raise click.UsageError('Multiple contracts currently require --json or --dump-request')

    _print_atom_reads_info(ui, policy)
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
        experimental_a3node=a3node,
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
@click.option('--flat-files', is_flag=True, help='Also write extracted content to .yosoi/content flat files.')
@click.option(
    '--policy',
    'policy_source',
    multiple=True,
    metavar='FILE|YAML|JSON',
    help='Policy file or inline YAML/JSON. Repeat to layer.',
)
@click.option('--atom-reads', is_flag=True, help='Allow policy-gated reads from the field-atom index before discovery.')
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
    flat_files: bool,
    policy_source: tuple[str, ...],
    atom_reads: bool,
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
        flat_files=flat_files,
        atom_reads=atom_reads,
        policy_sources=policy_source,
    )

    ui: Console = Console(theme=_THEME, stderr=True) if json_output else console
    ui.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')
    if not json_output:
        _print_atom_reads_info(ui, policy)
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
@click.option(
    '--policy',
    'policy_source',
    multiple=True,
    metavar='FILE|YAML|JSON',
    help='Policy file or inline YAML/JSON. Repeat to layer.',
)
@click.option('--request', 'request_file', default=None, metavar='FILE', help='CrawlRequest JSON file.')
@click.option('--dump-request', is_flag=True, help='Print the resolved CrawlRequest JSON and exit.')
@click.option('-t', '--fetcher', type=click.Choice(_FETCHER_CHOICES, case_sensitive=False), default=None)
@click.option('--persist', is_flag=True, help='Persist crawl frontier/checkpoint state.')
@click.option('--progress/--no-progress', default=None)
@click.option('--stress', is_flag=True, help='Store crawl run metrics and use stress-friendly compact output.')
@click.option('--run-id', default=None, metavar='ID', help='Stable crawl run/checkpoint id.')
@click.option('--compact/--full', 'compact_output', default=None, help='Choose compact or full machine crawl output.')
@click.option('--include-html', is_flag=True, help='Include page HTML in compact crawl JSON.')
@click.option('--include-fingerprints', is_flag=True, help='Include fingerprints/observations in compact crawl JSON.')
@click.option('--failure-threshold', type=int, default=0, help='Failures allowed before crawl status becomes partial.')
@click.option('--max-pages', type=int, default=None, help='Crawl page budget.')
@click.option('--max-depth', type=int, default=None, help='Maximum crawl depth.')
@click.option('--max-attempts', type=int, default=None, help='Attempt budget including failed pages.')
@click.option('--max-pages-per-host', type=int, default=None, help='Per-host page budget.')
@click.option('--workers', type=int, default=None, help='Maximum crawl workers.')
@click.option('--per-host-concurrency', type=int, default=None, help='Maximum concurrent fetches per host.')
@click.option('--politeness', type=float, default=None, help='Per-host politeness delay in seconds.')
@click.option('--timeout', 'timeout_seconds', type=float, default=None, help='Fetch timeout in seconds.')
@click.option('--deadline', 'deadline_seconds', type=float, default=None, help='Wall-clock crawl deadline in seconds.')
@click.option('--retries', type=int, default=None, help='Maximum fetch retries.')
@click.option('--respect-robots/--no-respect-robots', default=None, help='Honor robots.txt during crawl.')
@click.option('--allow-redirects/--no-allow-redirects', default=None, help='Allow fetch redirects during crawl.')
@click.option('--json', 'json_output', is_flag=True, default=False)
def crawl(
    seeds: tuple[str, ...],
    url: tuple[str, ...],
    file_path: str | None,
    limit: int | None,
    contract: tuple[type[Contract], ...],
    policy_source: tuple[str, ...],
    request_file: str | None,
    dump_request: bool,
    fetcher: str | None,
    persist: bool,
    progress: bool | None,
    stress: bool,
    run_id: str | None,
    compact_output: bool | None,
    include_html: bool,
    include_fingerprints: bool,
    failure_threshold: int,
    max_pages: int | None,
    max_depth: int | None,
    max_attempts: int | None,
    max_pages_per_host: int | None,
    workers: int | None,
    per_host_concurrency: int | None,
    politeness: float | None,
    timeout_seconds: float | None,
    deadline_seconds: float | None,
    retries: int | None,
    respect_robots: bool | None,
    allow_redirects: bool | None,
    json_output: bool,
) -> None:
    """Crawl seed URL(s) through the public ys.crawl operation surface."""
    from yosoi.cli import exit_codes
    from yosoi.operations import CrawlRequest, run_crawl
    from yosoi.policy import Policy
    from yosoi.policy.files import load_policy_layers

    if failure_threshold < 0:
        raise click.BadParameter('--failure-threshold must be >= 0')

    if request_file:
        try:
            with open(request_file, encoding='utf-8') as handle:
                request = CrawlRequest.model_validate_json(handle.read())
        except Exception as exc:
            raise click.ClickException(f'Cannot parse CrawlRequest {request_file!r}: {exc}') from exc
        if stress and request.run_id is None:
            request.run_id = run_id or _new_crawl_run_id()
            request.store_crawl = True
            request.stress = True
            request.compact = compact_output if compact_output is not None else True
        elif run_id is not None:
            request.run_id = run_id
        if compact_output is not None:
            request.compact = compact_output
        request.include_html = request.include_html or include_html
        request.include_fingerprints = request.include_fingerprints or include_fingerprints
        request.failure_threshold = failure_threshold
        if deadline_seconds is not None:
            request.deadline_seconds = deadline_seconds
    else:
        all_seeds: list[str] = list(seeds) + list(url) + (load_urls_from_file(file_path) if file_path else [])
        if not all_seeds:
            raise click.UsageError('No seeds provided. Pass seed(s) as arguments or use --url / --file')
        resolved_run_id = run_id or (_new_crawl_run_id() if stress or persist else None)
        policy = Policy.cascade(
            Policy.for_crawl('crawl.conservative'), Policy.from_env(), load_policy_layers(policy_source)
        )
        policy = _apply_crawl_cli_overrides(
            policy,
            run_id=resolved_run_id,
            max_pages=max_pages,
            max_depth=max_depth,
            max_attempts=max_attempts,
            max_pages_per_host=max_pages_per_host,
            workers=workers,
            per_host_concurrency=per_host_concurrency,
            politeness=politeness,
            timeout=timeout_seconds,
            retries=retries,
            respect_robots=respect_robots,
            allow_redirects=allow_redirects,
        )
        request = CrawlRequest.from_axes(
            all_seeds,
            list(contract) or None,
            limit=limit,
            policy=policy,
            fetcher_type=fetcher,
            persist=persist,
            progress=progress if progress is not None else (False if json_output else None),
            run_id=resolved_run_id,
            compact=compact_output if compact_output is not None else stress,
            include_html=include_html,
            include_fingerprints=include_fingerprints,
            store_crawl=stress,
            stress=stress,
            failure_threshold=failure_threshold,
            deadline_seconds=deadline_seconds,
        )

    if dump_request:
        click.echo(request.model_dump_json(indent=2))
        return

    try:
        if json_output or request.compact or request.store_crawl:
            result = _run_crawl_json_safe(run_crawl, request, json_output=json_output)
        else:
            from yosoi.operations import execute_crawl
            from yosoi.reporting import show

            summary = asyncio.run(execute_crawl(request))
            show(summary)
            return
    except (RuntimeError, ValueError, OSError, TypeError) as exc:
        message = str(exc)
        if isinstance(exc, TimeoutError):
            message = f'Crawl deadline exceeded after {request.deadline_seconds}s'
        sys.stdout.write(json.dumps({'type': 'error', 'message': message}) + '\n')
        sys.stdout.flush()
        sys.exit(exit_codes.ERROR)

    if json_output:
        sys.stdout.write(result.model_dump_json() + '\n')
        sys.stdout.flush()
        sys.exit(exit_codes.RECORDS)

    _render_compact_crawl(result.summary)


# ── map command — ys.map operation surface ───────────────────────────────────


@main.command('map')
@click.argument('site', required=False)
@click.option('-u', '--url', 'url_option', default=None, help='Site URL or hostname.')
@click.option('--request', 'request_file', default=None, metavar='FILE', help='MapRequest JSON file.')
@click.option('--dump-request', is_flag=True, help='Print the resolved MapRequest JSON and exit.')
@click.option('--max-sitemaps', type=int, default=20)
@click.option('--max-urls', type=int, default=500)
@click.option('--max-subdomains', type=int, default=500)
@click.option('--subfinder-bin', default='subfinder', help='subfinder executable to run for --subdomains.')
@click.option('--subfinder-timeout', type=int, default=60, help='Seconds before aborting subfinder.')
@click.option('--robots/--no-robots', 'include_robots', default=True)
@click.option('--default-sitemaps/--no-default-sitemaps', 'include_default_sitemaps', default=True)
@click.option(
    '--subdomains',
    'discover_subdomains',
    is_flag=True,
    default=False,
    help='Enumerate subdomains with subfinder instead of sitemap URLs.',
)
@click.option('--json', 'json_output', is_flag=True, default=False)
def map_command(
    site: str | None,
    url_option: str | None,
    request_file: str | None,
    dump_request: bool,
    max_sitemaps: int,
    max_urls: int,
    max_subdomains: int,
    subfinder_bin: str,
    subfinder_timeout: int,
    include_robots: bool,
    include_default_sitemaps: bool,
    discover_subdomains: bool,
    json_output: bool,
) -> None:
    """Map a site's sitemap URLs, or enumerate subdomains with --subdomains."""
    from yosoi.cli import exit_codes
    from yosoi.operations import MapRequest, run_map

    if request_file:
        try:
            with open(request_file, encoding='utf-8') as handle:
                request = MapRequest.model_validate_json(handle.read())
        except Exception as exc:
            raise click.ClickException(f'Cannot parse MapRequest {request_file!r}: {exc}') from exc
    else:
        target = url_option or site
        if target is None:
            raise click.UsageError('No site provided. Pass a positional site or --url')
        request = MapRequest(
            url=target,
            max_sitemaps=max_sitemaps,
            max_urls=max_urls,
            max_subdomains=max_subdomains,
            subfinder_bin=subfinder_bin,
            subfinder_timeout=subfinder_timeout,
            include_robots=include_robots,
            include_default_sitemaps=include_default_sitemaps,
            discover_subdomains=discover_subdomains,
        )

    if dump_request:
        click.echo(request.model_dump_json(indent=2))
        return

    try:
        result = asyncio.run(run_map(request))
    except Exception as exc:
        if json_output:
            sys.stdout.write(json.dumps({'type': 'error', 'message': str(exc)}) + '\n')
            sys.stdout.flush()
            sys.exit(exit_codes.ERROR)
        raise click.ClickException(str(exc)) from exc

    if json_output:
        sys.stdout.write(result.model_dump_json() + '\n')
        sys.stdout.flush()
        sys.exit(exit_codes.RECORDS if result.status != 'error' else exit_codes.ERROR)

    _print_map_result(result)
    sys.exit(exit_codes.RECORDS if result.status != 'error' else exit_codes.ERROR)


# ── policy command group ──────────────────────────────────────────────────────


@main.group('policy')
def policy_group() -> None:
    """Inspect, validate, and resolve policy JSON/YAML."""


@policy_group.command('init')
@click.option('--global', 'global_config', is_flag=True, help='Create ~/.config/yosoi/policy.yaml.')
@click.option('--local', 'local_config', is_flag=True, help='Create .yosoi/policy.yaml.')
@click.option('--force', is_flag=True, help='Overwrite an existing policy file.')
def policy_init(global_config: bool, local_config: bool, force: bool) -> None:
    """Create starter policy YAML with a language-server schema directive."""
    from yosoi.policy.files import init_policy_files

    try:
        paths = init_policy_files(global_config=global_config, local_config=local_config, force=force)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    for path in paths:
        console.print(f'[success]✓ Wrote {path}[/success]')


@policy_group.command('schema')
def policy_schema() -> None:
    """Print the policy JSON Schema for YAML/JSON language servers."""
    from yosoi.policy.files import dump_policy_schema

    click.echo(dump_policy_schema().rstrip())


@policy_group.command('list')
@click.option(
    '--all', 'include_missing', is_flag=True, default=False, help='Include candidate paths that do not exist yet.'
)
@click.option('--json', 'json_output', is_flag=True, default=False, help='Print machine-readable policy paths.')
def policy_list(include_missing: bool, json_output: bool) -> None:
    """List discovered policy files in precedence order."""
    from yosoi.policy.files import default_global_policy_paths, default_project_policy_paths

    records = [
        {'scope': scope, 'path': str(path), 'exists': path.is_file()}
        for scope, paths in (
            ('global', default_global_policy_paths()),
            ('project', default_project_policy_paths()),
        )
        for path in paths
    ]
    if not include_missing:
        records = [record for record in records if record['exists']]
    if json_output:
        echo_json({'type': 'policy.list', 'files': records})
        return
    if not records:
        console.print('[info]No policy files found. Use `yosoi policy list --all` to show candidate paths.[/info]')
        return

    from rich.markup import escape

    for record in records:
        marker = '✓' if record['exists'] else '·'
        style = 'success' if record['exists'] else 'info'
        path = Path(cast('str', record['path'])).expanduser()
        uri = path.resolve(strict=False).as_uri()
        scope = escape(cast('str', record['scope']))
        label = escape(cast('str', record['path']))
        console.print(f'[{style}]{marker} {scope}: [link={uri}]{label}[/link][/{style}]')


@policy_group.command('defaults')
@click.option('--crawl', 'crawl_defaults', is_flag=True, help='Show crawl.conservative defaults.')
@click.option('--format', 'output_format', type=click.Choice(['json', 'yaml']), default='yaml')
def policy_defaults(crawl_defaults: bool, output_format: str) -> None:
    """Print default policy as human-readable YAML by default; use --format json for JSON."""
    from yosoi.policy import Policy
    from yosoi.policy.files import PolicyFormat, dump_policy

    policy = Policy.for_crawl('crawl.conservative') if crawl_defaults else Policy()
    click.echo(dump_policy(policy, fmt=cast('PolicyFormat', output_format)).rstrip())


@policy_group.command('validate')
@click.argument('policy_source')
@click.option('--json', 'json_output', is_flag=True, default=False)
def policy_validate(policy_source: str, json_output: bool) -> None:
    """Validate a policy JSON/YAML file or inline document."""
    from yosoi.policy.files import load_policy_source

    try:
        load_policy_source(policy_source)
    except Exception as exc:
        if json_output:
            echo_json(
                {'type': 'error', 'command': 'policy.validate', 'policy_source': policy_source, 'message': str(exc)}
            )
            sys.exit(1)
        raise click.ClickException(f'Invalid policy {policy_source!r}: {exc}') from exc
    if json_output:
        echo_json({'type': 'policy.validate', 'status': 'ok', 'policy_source': policy_source})
        return
    console.print('[success]✓ Policy valid[/success]')


@policy_group.command('inspect')
@click.argument('policy_source')
@click.option('--format', 'output_format', type=click.Choice(['json', 'yaml']), default='yaml')
def policy_inspect(policy_source: str, output_format: str) -> None:
    """Print normalized human-readable YAML by default; use --format json for JSON."""
    from yosoi.policy.files import PolicyFormat, dump_policy, load_policy_source

    try:
        policy = load_policy_source(policy_source)
    except Exception as exc:
        raise click.ClickException(f'Invalid policy {policy_source!r}: {exc}') from exc
    click.echo(dump_policy(policy, fmt=cast('PolicyFormat', output_format)).rstrip())


@policy_group.command('effective')
@click.option(
    '--policy',
    'policy_source',
    multiple=True,
    metavar='FILE|YAML|JSON',
    help='Additional policy file or inline document. Repeat to layer.',
)
@click.option('--no-discover', is_flag=True, help='Do not load global/project policy files.')
@click.option(
    '--crawl', 'crawl_defaults', is_flag=True, help='Seed the effective policy with crawl.conservative defaults.'
)
@click.option('--format', 'output_format', type=click.Choice(['json', 'yaml']), default='yaml')
def policy_effective(
    policy_source: tuple[str, ...], no_discover: bool, crawl_defaults: bool, output_format: str
) -> None:
    """Print the effective env + global + project + inline policy as YAML by default."""
    from yosoi.policy import Policy
    from yosoi.policy.files import PolicyFormat, dump_policy, load_policy_layers

    base = Policy.for_crawl('crawl.conservative') if crawl_defaults else None
    policy = Policy.cascade(
        base, Policy.from_env(), load_policy_layers(policy_source, include_discovered=not no_discover)
    )
    click.echo(dump_policy(policy, fmt=cast('PolicyFormat', output_format)).rstrip())


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
            'status': 'cache_metrics_libsql_unavailable',
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

    def _print_field_metrics_table(rows: list[object]) -> None:
        if not rows:
            return
        from rich.table import Table

        table = Table(title='Cache field metrics')
        table.add_column('Domain')
        table.add_column('Route')
        table.add_column('URL')
        table.add_column('Field')
        table.add_column('Status')
        table.add_column('Failures', justify='right')
        table.add_column('Last verified')
        for row in rows:
            table.add_row(
                str(getattr(row, 'domain', '')),
                str(getattr(row, 'route_signature', '')),
                str(getattr(row, 'source_url', None) or '—'),
                str(getattr(row, 'field_name', '')),
                str(getattr(row, 'status', '')),
                str(getattr(row, 'failure_count', 0)),
                str(getattr(row, 'last_verified_at', None) or '—'),
            )
        console.print(table)

    if domain is None:
        if resolved_contract is not None:
            fp = contract_signature(resolved_contract)
            try:
                from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore

                async def _summarize_contract_metrics() -> Any:
                    async with LibSQLCacheMetricsStore() as metrics_store:
                        return await metrics_store.summarize_contract(fp)

                summary = asyncio.run(_summarize_contract_metrics())
                field_metrics = [row.__dict__ for row in summary.field_metrics]
                counts = {
                    'runs': summary.run_count,
                    'urls': summary.url_count,
                    'domains': len(summary.domains),
                    'top_level_domains': len(summary.top_level_domains),
                    'routes': len(summary.routes),
                    'fields': len(summary.fields),
                    'events': summary.event_counts,
                }
                doc: dict[str, object] = {
                    'type': 'cache.status',
                    'target': target_value,
                    'target_kind': routed_kind,
                    'contract': resolved_contract.__name__,
                    'contract_fingerprint': fp,
                    'cached': bool(field_metrics),
                    'counts': counts,
                    'domains': summary.domains,
                    'top_level_domains': summary.top_level_domains,
                    'routes': summary.routes,
                    'urls': summary.urls,
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
                console.print(f'  Runs: [bold]{summary.run_count}[/bold]')
                console.print(f'  URLs: [bold]{summary.url_count}[/bold]')
                console.print(f'  Domains: {", ".join(summary.domains)}')
                console.print(f'  Routes: {", ".join(summary.routes)}')
                console.print(f'  URL list: {", ".join(summary.urls)}')
                console.print(f'  Fields: {", ".join(summary.fields)}')
                if summary.event_counts:
                    events = ', '.join(f'{name}={count}' for name, count in sorted(summary.event_counts.items()))
                    console.print(f'  Events: {events}')
                _print_field_metrics_table(summary.field_metrics)
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
        try:
            from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore

            async with LibSQLCacheMetricsStore() as metrics_store:
                domain_summary = await metrics_store.summarize_domain(domain, contract_sig)
                try:
                    health = await metrics_store.scrape_health(
                        contract_fingerprint=contract_sig,
                        domain=domain,
                        url=routed_target.value if routed_target is not None and routed_target.kind == 'url' else None,
                        route_signature=routed_target.route if routed_target is not None else None,
                    )
                except (AttributeError, TypeError):
                    health = None
            field_metrics = health.field_metrics if health is not None else domain_summary.field_metrics
            if field_metrics or domain_summary.event_counts:
                doc['field_metrics'] = [row.__dict__ for row in field_metrics]
                if health is not None:
                    top_level_domains = sorted(
                        {row.top_level_domain for row in field_metrics if row.top_level_domain is not None}
                    )
                    routes = sorted({row.route_signature for row in field_metrics if row.route_signature is not None})
                    metric_urls = sorted({row.source_url for row in field_metrics if row.source_url is not None})
                    contracts = sorted(
                        {row.contract_fingerprint for row in field_metrics if row.contract_fingerprint is not None}
                    )
                    fields = sorted({row.field_name for row in field_metrics if row.field_name is not None})
                else:
                    top_level_domains = domain_summary.top_level_domains
                    routes = domain_summary.routes
                    metric_urls = domain_summary.urls
                    contracts = domain_summary.contract_fingerprints
                    fields = domain_summary.fields
                doc['top_level_domains'] = top_level_domains
                doc['routes'] = routes
                doc['urls'] = metric_urls
                doc['contracts'] = contracts
                doc['counts'] = {
                    'runs': domain_summary.run_count,
                    'urls': len(metric_urls) if health is not None else domain_summary.url_count,
                    'contracts': len(contracts),
                    'top_level_domains': len(top_level_domains),
                    'routes': len(routes),
                    'fields': len(fields),
                    'events': domain_summary.event_counts,
                }
            if health is not None:
                doc['health'] = health.health
            if health is not None and health.latest_run is not None:
                doc['latest_run'] = health.latest_run.__dict__
        except Exception as exc:  # noqa: BLE001
            doc['metrics_error'] = str(exc)

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
            if 'counts' in doc:
                counts = doc['counts']
                if isinstance(counts, dict):
                    console.print(f'  Runs: [bold]{counts.get("runs", 0)}[/bold]')
                    console.print(f'  URLs: [bold]{counts.get("urls", 0)}[/bold]')
                    rendered_urls = doc.get('urls')
                    if isinstance(rendered_urls, list) and rendered_urls:
                        console.print(f'  URL list: {", ".join(str(url) for url in rendered_urls)}')
                    events = counts.get('events')
                    if isinstance(events, dict) and events:
                        rendered = ', '.join(f'{name}={count}' for name, count in sorted(events.items()))
                        console.print(f'  Events: {rendered}')
                metric_rows = doc.get('field_metrics')
                if isinstance(metric_rows, list):
                    from types import SimpleNamespace

                    _print_field_metrics_table([SimpleNamespace(**row) for row in metric_rows])

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


@main.command('status')
@click.argument('target', required=False)
@click.option('-C', '--contract', type=ContractParamType(), default=None, help='Contract to check fingerprint for')
@click.option('--domain', 'domain_target', default=None, metavar='DOMAIN', help='Explicit domain target.')
@click.option('--url', 'url_target', default=None, metavar='URL', help='Explicit URL target.')
@click.option('--route', 'route_target', default=None, metavar='PATH', help='Explicit route/path target.')
@click.option('-j', '--json', 'json_output', is_flag=True, default=False)
def status(
    target: str | None,
    contract: type[Contract] | None,
    domain_target: str | None,
    url_target: str | None,
    route_target: str | None,
    json_output: bool,
) -> None:
    """Show scrape/cache health for a contract, domain, URL, or route."""
    callback = cache_status.callback
    if callback is None:
        raise click.ClickException('cache status command is unavailable')
    callback(
        target=target,
        contract=contract,
        domain_target=domain_target,
        url_target=url_target,
        route_target=route_target,
        json_output=json_output,
    )


@cache_group.group('metrics')
def cache_metrics_group() -> None:
    """Manage cache metrics storage."""


@cache_metrics_group.command('backfill')
@click.option('-C', '--contract', type=ContractParamType(), multiple=True, help='Contract(s) to backfill.')
@click.option('--domain', 'domain_target', default=None, metavar='DOMAIN', help='Domain to backfill.')
@click.option('--all', 'all_targets', is_flag=True, help='Backfill all selector cache files.')
@click.option('-j', '--json', 'json_output', is_flag=True, default=False)
def cache_metrics_backfill(
    contract: tuple[type[Contract], ...], domain_target: str | None, all_targets: bool, json_output: bool
) -> None:
    """Import existing selector JSON files into the metrics DB as backfill events."""
    from dataclasses import asdict

    from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore
    from yosoi.utils.files import init_yosoi, is_initialized
    from yosoi.utils.signatures import contract_signature

    if not all_targets and not contract and domain_target is None:
        raise click.UsageError('Pass --all, --contract, or --domain to choose what to backfill.')
    if not is_initialized():
        init_yosoi()

    contract_fps: list[str | None] = [contract_signature(cls) for cls in contract] or [None]

    async def _backfill() -> dict[str, object]:
        results = []
        async with LibSQLCacheMetricsStore() as metrics_store:
            for fp in contract_fps:
                result = await metrics_store.backfill_existing(
                    contract_fingerprint=None if all_targets else fp,
                    domain=domain_target,
                )
                results.append(asdict(result) | {'contract_fingerprint': None if all_targets else fp})
                if all_targets:
                    break
        totals = {
            'scanned_files': sum(int(item['scanned_files']) for item in results),
            'imported_files': sum(int(item['imported_files']) for item in results),
            'skipped_files': sum(int(item['skipped_files']) for item in results),
            'imported_fields': sum(int(item['imported_fields']) for item in results),
        }
        return {'type': 'cache.metrics.backfill', 'results': results, 'totals': totals}

    doc = asyncio.run(_backfill())
    if json_output:
        echo_json(doc)
        return

    totals = doc['totals']
    if isinstance(totals, dict):
        console.print('[success]✓ Cache metrics backfill complete[/success]')
        console.print(f'  Scanned files: [bold]{totals["scanned_files"]}[/bold]')
        console.print(f'  Imported files: [bold]{totals["imported_files"]}[/bold]')
        console.print(f'  Skipped files: [bold]{totals["skipped_files"]}[/bold]')
        console.print(f'  Imported fields: [bold]{totals["imported_fields"]}[/bold]')


# ── recipe command group (CAS-152) ───────────────────────────────────────────


@main.group('recipe')
def recipe_group() -> None:
    """Mint, install, inspect, and publish flat Yosoi recipe JSON artifacts."""


@recipe_group.command('mint')
@click.option(
    '--contract',
    'contract_source',
    required=True,
    metavar='FILE|@NAME|PATH:CLASS',
    help='Contract source to canonicalize.',
)
@click.option('--selectors', 'selectors_source', required=True, metavar='FILE', help='Selector SnapshotMap JSON file.')
@click.option('--a3nodes', 'a3nodes_source', default=None, metavar='FILE', help='Optional A3Node/action JSON file.')
@click.option(
    '--validation', 'validation_source', default=None, metavar='FILE', help='Optional validation evidence JSON file.'
)
@click.option('--out', 'out_path', required=True, metavar='FILE', help='Output recipe JSON path.')
@click.option('--name', default=None, metavar='NAME', help='Human-readable recipe name.')
@click.option(
    '--domain', 'domains', multiple=True, metavar='DOMAIN', help='Domain scope. Defaults to selector domains.'
)
@click.option(
    '--url-pattern', 'url_patterns', multiple=True, metavar='PATTERN', help='URL pattern covered by this recipe.'
)
@click.option('--notes', default=None, metavar='TEXT', help='Optional recipe notes.')
@click.option('--json', 'json_output', is_flag=True, default=False)
def recipe_mint(
    contract_source: str,
    selectors_source: str,
    a3nodes_source: str | None,
    validation_source: str | None,
    out_path: str,
    name: str | None,
    domains: tuple[str, ...],
    url_patterns: tuple[str, ...],
    notes: str | None,
    json_output: bool,
) -> None:
    """Create a deterministic flat recipe JSON from contract and selectors."""
    from yosoi.models.recipe import Recipe, RecipeMetadata, RecipeValidation
    from yosoi.storage.recipe_store import parse_contract_file, parse_json_file, parse_selectors_file
    from yosoi.utils.contracts import resolve_contract
    from yosoi.utils.files import atomic_write_text

    try:
        if contract_source.endswith('.json') and Path(contract_source).is_file():
            contract_spec = parse_contract_file(contract_source)
        else:
            contract_spec = resolve_contract(contract_source.removeprefix('@')).to_spec()
        selectors = parse_selectors_file(selectors_source)
        a3nodes_raw = parse_json_file(a3nodes_source) if a3nodes_source else []
        validation_raw = parse_json_file(validation_source) if validation_source else {}
        if not isinstance(a3nodes_raw, list):
            raise click.ClickException('--a3nodes must be a JSON array')
        if not isinstance(validation_raw, dict):
            raise click.ClickException('--validation must be a JSON object')
        recipe = Recipe(
            contract=contract_spec,
            selectors=selectors,
            a3nodes=a3nodes_raw,
            validation=RecipeValidation.model_validate(validation_raw),
            metadata=RecipeMetadata(
                name=name or contract_spec.name,
                domain_scope=list(domains) or sorted(selectors),
                url_patterns=list(url_patterns),
                notes=notes,
            ),
        )
        recipe.verify_integrity()
        atomic_write_text(out_path, recipe.canonical_json())
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    doc = {'type': 'recipe.mint', 'status': 'ok', 'recipe_id': recipe.recipe_id, 'path': out_path}
    if json_output:
        echo_json(doc)
        return
    console.print(f'[success]✓ Minted recipe[/success] {recipe.recipe_id} → {out_path}')


@recipe_group.command('install')
@click.argument('source')
@click.option('--recipe-id', default=None, metavar='sha256:...', help='Expected pinned recipe id.')
@click.option('--cache-dir', default=None, metavar='DIR', help='Override install cache directory.')
@click.option('--json', 'json_output', is_flag=True, default=False)
def recipe_install(source: str, recipe_id: str | None, cache_dir: str | None, json_output: bool) -> None:
    """Fetch, verify, and cache a local/HTTPS/gh: flat recipe JSON."""
    from yosoi.storage.recipe_store import install_recipe

    if source.startswith(('http://', 'https://', 'gh:')) and recipe_id is None:
        raise click.UsageError(
            'Remote recipe installs require --recipe-id sha256:... until CLI RecipePolicy flags land.'
        )

    try:
        result = install_recipe(source, expected_recipe_id=recipe_id, cache_dir=cache_dir)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    doc = {'type': 'recipe.install', 'status': 'ok', 'recipe_id': result.recipe.recipe_id, 'path': str(result.path)}
    if json_output:
        echo_json(doc)
        return
    console.print(f'[success]✓ Installed recipe[/success] {result.recipe.recipe_id} → {result.path}')


@recipe_group.command('inspect')
@click.argument('source')
@click.option('--json', 'json_output', is_flag=True, default=False)
def recipe_inspect(source: str, json_output: bool) -> None:
    """Load and summarize a flat recipe JSON artifact."""
    from yosoi.storage.recipe_store import load_recipe

    try:
        recipe = load_recipe(source)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    domain_names = sorted(recipe.selectors)
    field_names = sorted(recipe.contract.fields)
    doc = {
        'type': 'recipe.inspect',
        'recipe_id': recipe.recipe_id,
        'schema_version': recipe.schema_version,
        'contract': recipe.contract.name,
        'domains': domain_names,
        'fields': field_names,
        'a3nodes': len(recipe.a3nodes),
        'validation_urls': len(recipe.validation.fixture_urls),
    }
    if json_output:
        echo_json(doc)
        return
    console.print(f'[bold]Recipe[/bold] {doc["recipe_id"]}')
    console.print(f'  contract: {doc["contract"]}')
    console.print(f'  domains: {", ".join(domain_names) or "(none)"}')
    console.print(f'  fields: {", ".join(field_names) or "(none)"}')
    console.print(f'  a3nodes: {doc["a3nodes"]}')
    console.print(f'  validation fixture urls: {doc["validation_urls"]}')


@recipe_group.command('check')
@click.argument('source')
@click.option('--recipe-id', default=None, metavar='sha256:...', help='Expected pinned recipe id.')
@click.option('--json', 'json_output', is_flag=True, default=False)
def recipe_check(source: str, recipe_id: str | None, json_output: bool) -> None:
    """Verify recipe schema and deterministic identity."""
    from yosoi.storage.recipe_store import load_recipe

    try:
        recipe = load_recipe(source, expected_recipe_id=recipe_id)
    except Exception as exc:
        if json_output:
            echo_json({'type': 'recipe.check', 'status': 'error', 'source': source, 'error': str(exc)})
        raise click.ClickException(str(exc)) from exc
    if json_output:
        echo_json({'type': 'recipe.check', 'status': 'ok', 'source': source, 'recipe_id': recipe.recipe_id})
        return
    console.print(f'[success]✓ Recipe OK[/success] {recipe.recipe_id}')


@recipe_group.command('publish')
@click.argument('recipe_file')
@click.option('--repo', required=True, metavar='OWNER/REPO', help='GitHub repository to publish to.')
@click.option('--path', 'remote_path', required=True, metavar='PATH', help='Repository path for recipe JSON.')
@click.option('--branch', default='main', show_default=True, metavar='REF', help='Target branch.')
@click.option('--message', default=None, metavar='TEXT', help='Commit message.')
@click.option('--json', 'json_output', is_flag=True, default=False)
def recipe_publish(
    recipe_file: str,
    repo: str,
    remote_path: str,
    branch: str,
    message: str | None,
    json_output: bool,
) -> None:
    """Publish a flat recipe JSON to GitHub via the Contents API."""
    from yosoi.storage.recipe_store import load_recipe, publish_recipe_github

    try:
        recipe = load_recipe(recipe_file)
        url = publish_recipe_github(recipe, repo=repo, path=remote_path, branch=branch, message=message)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    doc = {'type': 'recipe.publish', 'status': 'ok', 'recipe_id': recipe.recipe_id, 'url': url}
    if json_output:
        echo_json(doc)
        return
    console.print(f'[success]✓ Published recipe[/success] {recipe.recipe_id}')
    console.print(url)


@recipe_group.command('gist')
@click.argument('recipe_file')
@click.option('--filename', default=None, metavar='NAME.json', help='Gist filename. Defaults to recipe hash.')
@click.option('--description', default=None, metavar='TEXT', help='Gist description.')
@click.option(
    '--public',
    'public_gist',
    is_flag=True,
    default=False,
    help='Create a public gist. Default is secret/unlisted (not access-controlled private).',
)
@click.option('--json', 'json_output', is_flag=True, default=False)
def recipe_gist(
    recipe_file: str,
    filename: str | None,
    description: str | None,
    public_gist: bool,
    json_output: bool,
) -> None:
    """Publish a flat recipe JSON to a GitHub Gist. Secret/unlisted by default."""
    from yosoi.storage.recipe_store import load_recipe, publish_recipe_gist

    try:
        recipe = load_recipe(recipe_file)
        result = publish_recipe_gist(recipe, filename=filename, description=description, public=public_gist)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    doc = {
        'type': 'recipe.gist',
        'status': 'ok',
        'recipe_id': recipe.recipe_id,
        'url': result.raw_url,
        'raw_url': result.raw_url,
        'html_url': result.html_url,
        'filename': result.filename,
        'visibility': 'public' if public_gist else 'secret',
        'public': public_gist,
    }
    if json_output:
        echo_json(doc)
        return
    visibility = 'public' if public_gist else 'secret/unlisted'
    console.print(f'[success]✓ Published {visibility} recipe gist[/success] {recipe.recipe_id}')
    console.print(result.raw_url)
    console.print(f'[dim]HTML: {result.html_url}[/dim]')


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
