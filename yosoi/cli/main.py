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
from yosoi.cli.setup import build_policy, print_fetcher_info
from yosoi.cli.utils import console, load_urls_from_file
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.selectors import SelectorLevel

_LEVEL_MAP: dict[str, SelectorLevel] = {
    **{m.name.lower(): m for m in SelectorLevel},
    'all': max(SelectorLevel),
}

_VALID_FORMATS = {'json', 'md', 'markdown', 'jsonl', 'ndjson', 'csv', 'xlsx', 'parquet'}
_FETCHER_CHOICES = ['auto', 'simple', 'headless', 'headful', 'waterfall']  # waterfall aliases auto

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


def _collect_urls(url: str | None, file_path: str | None, limit: int | None, ui: Console) -> list[str]:
    urls: list[str] = []
    if url:
        urls.append(url)
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


@click.group(invoke_without_command=True)
@click.pass_context
@click.option(
    '-m',
    '--model',
    default=None,
    metavar='PROVIDER:MODEL',
    help='LLM model (e.g. groq:llama-3.3-70b-versatile). Defaults to $YOSOI_MODEL env var if set.',
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
    default=os.getenv('YOSOI_LOG_LEVEL', 'DEBUG'),
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
    '-w', '--workers', type=int, default=1, metavar='N', help='Number of concurrent workers (default: 1, sequential)'
)
@click.option(
    '-x',
    '--selector-level',
    type=click.Choice(list(_LEVEL_MAP), case_sensitive=False),
    default='css',
    help='Maximum selector strategy level (default: css)',
)
@click.option(
    '--session-id', 'session_id', default=None, metavar='ID', help='Override the Langfuse session id for this run.'
)
@click.option(
    '--json',
    'json_output',
    is_flag=True,
    default=False,
    help='Emit records as NDJSON on stdout; logs/progress on stderr. Exit 0=records, 2=needs_discovery, 1=error.',
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
        max_concurrency=workers,
    )

    ui: Console = Console(theme=_THEME, stderr=True) if json_output else console

    ui.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')

    if selector_level != 'css':
        ui.print(f'[cyan]ℹ Selector level:[/cyan] [bold]{selector_level}[/bold]')

    if summary:
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

    effective_workers = min(workers, len(urls))
    if workers > 1 and len(urls) == 1:
        ui.print(f'[cyan]ℹ --workers {workers} has no effect with a single URL, running sequentially[/cyan]')
    elif workers > len(urls):
        ui.print(f'[cyan]ℹ --workers {workers} capped to {len(urls)} (one per URL)[/cyan]')
    if effective_workers > 1:
        ui.print(f'[cyan]ℹ Using {effective_workers} concurrent workers via taskiq[/cyan]')

    pipeline = Pipeline(
        None,
        contract=resolved_contract,
        output_format=output_formats,
        selector_level=resolved_level,
        policy=policy,
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
@click.option('-u', '--url', default=None, help='Single URL to scrape (alternative to positional URL)')
@click.option('-f', '--file', 'file_path', default=None, help='File containing URLs')
@click.option('-l', '--limit', type=int, default=None)
@click.option('-m', '--model', default=None, metavar='PROVIDER:MODEL')
@click.option(
    '-C',
    '--contract',
    type=ContractParamType(),
    default=None,
    help='Contract: @name, path/to/file.json, inline JSON, or path:Class',
)
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
    default=os.getenv('YOSOI_LOG_LEVEL', 'DEBUG'),
)
@click.option('-x', '--selector-level', type=click.Choice(list(_LEVEL_MAP), case_sensitive=False), default='css')
@click.option(
    '--json',
    'json_output',
    is_flag=True,
    default=False,
    help='NDJSON to stdout; exit 0=records, 2=needs_discovery, 1=error.',
)
@click.option('--session-id', default=None)
def scrape(
    urls: tuple[str, ...],
    url: str | None,
    file_path: str | None,
    limit: int | None,
    model: str | None,
    contract: type[Contract] | None,
    skip_verification: bool,
    output: tuple[str, ...],
    fetcher: str,
    log_level: str,
    selector_level: str,
    json_output: bool,
    session_id: str | None,
) -> None:
    """Replay cached selectors against a URL — never runs LLM discovery.

    Returns ``needs_discovery`` (exit 2) when no cached selectors exist.
    Use ``yosoi discover`` to populate the cache first.
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
        False,
        force=False,
        skip_verification=skip_verification,
        fetcher_type=fetcher,
        selector_level=resolved_level,
        output_formats=output_formats,
        quiet=json_output,
        json_output=json_output,
    )

    ui: Console = Console(theme=_THEME, stderr=True) if json_output else console
    ui.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')

    all_urls: list[str] = list(urls) + ([url] if url else []) + (load_urls_from_file(file_path) if file_path else [])
    if not all_urls:
        raise click.UsageError('No URLs provided. Pass URL(s) as arguments or use --url / --file')
    if limit is not None:
        all_urls = all_urls[: max(1, limit)]

    if json_output:
        from urllib.parse import urlparse

        from yosoi.cli import exit_codes
        from yosoi.core.resolve import build_cache_from_selectors, resolve
        from yosoi.models.needs_discovery import NeedsDiscovery
        from yosoi.policy import Policy
        from yosoi.storage import SelectorStorage

        def _domain_from_url(u: str) -> str:
            host = urlparse(u).hostname or u
            return host.removeprefix('www.').lower()

        storage = SelectorStorage()
        spec = resolved_contract.to_spec()
        fp = spec.fingerprint
        had_records = False

        async def _replay_json() -> int:
            for scrape_url in all_urls:
                domain = _domain_from_url(scrape_url)
                raw_selectors = await storage.load_selectors(domain, contract_sig=fp)
                if raw_selectors is None:
                    nd = NeedsDiscovery(
                        domain=domain, contract_fingerprint=fp, fields=sorted(resolved_contract.discovery_field_names())
                    )
                    sys.stdout.write(nd.to_exit_json() + '\n')
                    sys.stdout.flush()
                    return exit_codes.NEEDS_DISCOVERY

                cache = build_cache_from_selectors(domain, fp, raw_selectors)
                # Fetch HTML — use simple HTTP
                import httpx2

                async with httpx2.AsyncClient() as client:
                    resp = await client.get(scrape_url, follow_redirects=True, timeout=30)
                    html = resp.text

                result = resolve(spec, html, cache, domain, url=scrape_url, policy=Policy.from_env())
                if isinstance(result, NeedsDiscovery):
                    sys.stdout.write(result.to_exit_json() + '\n')
                    sys.stdout.flush()
                    return exit_codes.NEEDS_DISCOVERY

                for item in result:
                    sys.stdout.write(json.dumps(item, default=str) + '\n')
                    sys.stdout.flush()
                    nonlocal had_records
                    had_records = True

            return exit_codes.RECORDS

        had_records = False
        try:
            exit_code = asyncio.run(_replay_json())
        except Exception as exc:  # noqa: BLE001
            sys.stdout.write(json.dumps({'type': 'error', 'message': str(exc)}) + '\n')
            sys.stdout.flush()
            sys.exit(exit_codes.ERROR)
        sys.exit(exit_code)

    # Non-JSON mode: delegate to the full pipeline (which may still run discovery
    # on a miss until we fully split scrape/discover in the pipeline).
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
            force=False,
            skip_verification=skip_verification,
            fetcher_type=fetcher,
            origin='cli',
        )
    )


# ── discover command — expensive LLM path ─────────────────────────────────────


@main.command('discover')
@click.argument('urls', nargs=-1)
@click.option('-u', '--url', default=None)
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
    default=os.getenv('YOSOI_LOG_LEVEL', 'DEBUG'),
)
@click.option('-x', '--selector-level', type=click.Choice(list(_LEVEL_MAP), case_sensitive=False), default='css')
@click.option('-w', '--workers', type=int, default=1, metavar='N')
@click.option('--session-id', default=None)
@click.option('--json', 'json_output', is_flag=True, default=False)
def discover(
    urls: tuple[str, ...],
    url: str | None,
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
        max_concurrency=workers,
    )

    ui: Console = Console(theme=_THEME, stderr=True) if json_output else console
    ui.print(f'[cyan]ℹ Log file:[/cyan] [link=file://{log_file}]{log_file}[/link]')
    ui.print('[cyan]ℹ Running LLM discovery (expensive path)...[/cyan]')

    all_urls: list[str] = list(urls) + ([url] if url else []) + (load_urls_from_file(file_path) if file_path else [])
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


# ── cache command group ────────────────────────────────────────────────────────


@main.group('cache')
def cache_group() -> None:
    """Cache management commands."""


@cache_group.command('status')
@click.argument('target')
@click.option('-C', '--contract', type=ContractParamType(), default=None, help='Contract to check fingerprint for')
def cache_status(target: str, contract: type[Contract] | None) -> None:
    """Show cache status for a domain or URL.

    TARGET is a domain name (e.g. example.com) or a full URL.
    """
    from urllib.parse import urlparse

    from yosoi.storage import SelectorStorage
    from yosoi.utils.files import init_yosoi, is_initialized
    from yosoi.utils.signatures import contract_signature

    if not is_initialized():
        init_yosoi()

    if target.startswith('http'):
        host = urlparse(target).hostname or target
        domain = host.removeprefix('www.').lower()
    else:
        domain = target

    storage = SelectorStorage()

    async def _check() -> None:
        contract_sig = contract_signature(contract) if contract is not None else None
        snapshots = await storage.load_snapshots(domain, contract_sig=contract_sig)
        if not snapshots:
            console.print(f'[warning]✗ No cached selectors for {domain!r}[/warning]')
            return

        console.print(f'[success]✓ Cached selectors for {domain!r}[/success]')
        console.print(f'  Fields: {", ".join(sorted(snapshots))}')

        if contract is not None:
            spec = contract.to_spec()
            fp = spec.fingerprint
            console.print(f'  Contract fingerprint: [bold]{fp}[/bold]')
            cached_fields = set(snapshots)
            contract_fields = contract.discovery_field_names()
            missing = contract_fields - cached_fields
            if missing:
                console.print(f'  [warning]Missing fields: {", ".join(sorted(missing))}[/warning]')
            else:
                console.print('  [success]All contract fields cached[/success]')

    asyncio.run(_check())


# ── contracts command group (CAS-122) ─────────────────────────────────────────


@main.group('contracts')
def contracts_group() -> None:
    """Manage the local content-addressed contracts store."""


@contracts_group.command('list')
@click.option('--store', default=None, metavar='DIR', help='Contracts store directory (default: .yosoi/contracts)')
def contracts_list(store: str | None) -> None:
    """List registered contract aliases and their fingerprints."""
    from yosoi.storage.contracts_store import ContractStore

    cs = ContractStore(store)
    aliases = cs.list_aliases()
    if not aliases:
        console.print('[dim]No contracts registered in the local store.[/dim]')
        return
    for name, fp in aliases:
        console.print(f'  [bold]{name}[/bold]  [dim]{fp}[/dim]')


@contracts_group.command('show')
@click.argument('name_or_fp')
@click.option('--store', default=None, metavar='DIR')
def contracts_show(name_or_fp: str, store: str | None) -> None:
    """Show a ContractSpec by name or fingerprint."""
    from yosoi.storage.contracts_store import ContractStore

    cs = ContractStore(store)
    try:
        spec = cs.get(name_or_fp)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(spec.model_dump_json(indent=2))


@contracts_group.command('add')
@click.argument('spec_file')
@click.option('--name', default=None, metavar='ALIAS', help='Alias name (defaults to spec name)')
@click.option('--store', default=None, metavar='DIR')
def contracts_add(spec_file: str, name: str | None, store: str | None) -> None:
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
    console.print(f'[success]✓ Added {alias!r} → {fp}[/success]')


@contracts_group.command('lint')
@click.argument('spec_file')
def contracts_lint(spec_file: str) -> None:
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
        for err in errors:
            console.print(f'[warning]✗ {err}[/warning]')
        sys.exit(1)
    else:
        console.print('[success]✓ Spec is valid[/success]')


@contracts_group.command('migrate')
@click.argument('spec_file')
@click.option('--in-place', is_flag=True, help='Write migrated spec back to the same file')
def contracts_migrate(spec_file: str, in_place: bool) -> None:
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
        console.print(f'[success]✓ Migrated {spec_file!r} to schema_version {migrated.schema_version}[/success]')
    else:
        console.print(output)
