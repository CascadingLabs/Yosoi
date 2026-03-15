"""Concurrent URL processing with rich Live progress display."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich.live import Live

from yosoi.cli.utils import console
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel

if TYPE_CHECKING:
    from rich.table import Table

    from yosoi.core.configs import YosoiConfig

_STATUS_STYLES: dict[str, tuple[str, bool]] = {
    'Queued': ('dim', False),
    'Running': ('bold yellow', True),
    'Done': ('bold green', False),
    'Skipped': ('dim', False),
    'Failed': ('bold red', False),
}


def _build_progress_table(url_status: dict[str, tuple[str, float]]) -> Table:
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
    yosoi_config: YosoiConfig,
    contract: type[Contract],
    urls: list[str],
    output_format: str | list[str] = 'json',
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'simple',
    max_workers: int = 5,
    selector_level: SelectorLevel | None = None,
) -> None:
    """Run URL processing concurrently with a rich Live progress table.

    This is the CLI entry point for concurrent mode. It delegates to
    :meth:`Pipeline.process_urls(workers=N) <yosoi.core.pipeline.Pipeline.process_urls>`
    which manages the taskiq broker lifecycle. The Live display is driven
    by the ``on_complete`` callback.

    Args:
        yosoi_config: Validated YosoiConfig.
        contract: Contract subclass.
        urls: URLs to process.
        output_format: Output format.
        force: Force re-discovery.
        skip_verification: Skip verification step.
        fetcher_type: Fetcher type.
        max_workers: Max concurrent workers.
        selector_level: Maximum selector strategy level. Defaults to CSS.

    """
    from yosoi.core.pipeline import Pipeline

    url_status: dict[str, tuple[str, float]] = dict.fromkeys(urls, ('Queued', 0.0))

    live = Live(_build_progress_table(url_status), console=console, refresh_per_second=4)

    async def _on_start(url: str) -> None:
        url_status[url] = ('Running', time.monotonic())
        live.update(_build_progress_table(url_status))

    async def _on_complete(url: str, success: bool, elapsed: float) -> None:
        url_status[url] = ('Done' if success else 'Failed', elapsed)
        live.update(_build_progress_table(url_status))

    pipeline = Pipeline(
        yosoi_config,
        contract=contract,
        output_format=output_format,
        quiet=True,
        selector_level=selector_level or SelectorLevel.CSS,
    )

    with live:
        await pipeline.process_urls(
            urls,
            force=force,
            skip_verification=skip_verification,
            fetcher_type=fetcher_type,
            workers=max_workers,
            on_complete=_on_complete,
            on_start=_on_start,
        )
