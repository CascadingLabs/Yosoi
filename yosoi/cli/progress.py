"""Concurrent URL processing with rich Live progress display."""

import time
from urllib.parse import urlparse as _urlparse

from rich.live import Live

from yosoi.cli.utils import console
from yosoi.models.contract import Contract

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


async def run_concurrent(
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
    from yosoi.tasks import configure_broker, enqueue_urls, shutdown_broker

    await configure_broker(yosoi_config, contract=contract, output_format=output_format, max_workers=max_workers)
    start_time = time.monotonic()

    url_status: dict[str, tuple[str, float]] = dict.fromkeys(urls, ('Queued', 0.0))

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
