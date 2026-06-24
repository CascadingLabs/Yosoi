"""Human-friendly terminal display helpers for scraped data."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from types import TracebackType
from typing import Any, Literal, cast
from urllib.parse import urlparse

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

ShowFormat = Literal['auto', 'table', 'plain', 'json']

_console = Console()
_VALID_FORMATS: set[str] = {'auto', 'table', 'plain', 'json'}
_CRAWL_LANE_LIMIT = 20
_CRAWL_LIVE_MIN_ROWS = 6
_CRAWL_LIVE_MAX_ROWS = 28
_CRAWL_STATUS_STYLES: dict[str, str] = {
    'running': 'bold yellow',
    'succeeded': 'bold green',
    'policy_blocked': 'magenta',
    'failed': 'bold red',
}


class RichCrawlProgress:
    """Live Rich renderer for crawl runtime progress."""

    def __init__(self, *, console: Console | None = None, refresh_per_second: float = 4.0) -> None:
        """Create a live crawl progress renderer."""
        self.console = console or Console(stderr=True)
        self.refresh_per_second = refresh_per_second
        self._started_at = time.monotonic()
        self._live: Live | None = None
        self._seeds: tuple[str, ...] = ()
        self._max_pages = 0
        self._max_depth = 0
        self._max_workers = 0
        self._rows: dict[str, dict[str, Any]] = {}
        self._summary: Any | None = None
        self._event_index = 0

    def __enter__(self) -> RichCrawlProgress:
        """Start live rendering."""
        if not self.console.is_terminal:
            return self
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=self.refresh_per_second,
            vertical_overflow='crop',
        )
        self._live.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop live rendering after a final refresh."""
        if self._live is not None:
            self._live.update(self._render())
            self._live.__exit__(exc_type, exc, tb)
        elif self._rows or self._summary is not None:
            self.console.print(self._render())

    def start(self, *, seeds: tuple[str, ...], summary: Any, config: Any) -> None:
        """Record crawl startup."""
        self._seeds = seeds
        self._summary = summary
        self._max_pages = int(getattr(config, 'max_pages', 0) or 0)
        self._max_depth = int(getattr(config, 'max_depth', 0) or 0)
        self._max_workers = int(getattr(config, 'max_workers', 0) or 0)
        for seed in seeds:
            if seed not in self._rows:
                self._rows[seed] = self._row(status='queued', depth=0, links=0, elapsed=None, note='seed')
        self._update()

    def batch(self, jobs: tuple[Any, ...], summary: Any) -> None:
        """Record a reserved worker batch."""
        self._summary = summary
        for job in jobs:
            self._rows[job.url] = self._row(
                status='running',
                depth=job.depth,
                links=0,
                elapsed=None,
                note='fetching',
            )
        self._update()

    def result(self, result: Any, summary: Any) -> None:
        """Record one worker result."""
        self._summary = summary
        self._rows[result.job.url] = self._row(
            status=result.status,
            depth=result.job.depth,
            links=len(result.discovered_links),
            elapsed=result.fetch_time,
            note=result.error or '',
        )
        self._update()

    def finish(self, summary: Any) -> None:
        """Record crawl completion."""
        self._summary = summary
        self._update()

    def _update(self) -> None:
        if self._live is not None:
            self._live.update(self._render())

    def _row(self, *, status: str, depth: int, links: int, elapsed: float | None, note: str) -> dict[str, Any]:
        self._event_index += 1
        return {
            'status': status,
            'depth': depth,
            'links': links,
            'elapsed': elapsed,
            'note': note,
            'updated_at': self._event_index,
        }

    def _render(self) -> Table:
        summary = self._summary
        elapsed = time.monotonic() - self._started_at
        pages_fetched = getattr(summary, 'pages_fetched', 0) if summary is not None else 0
        attempted = getattr(summary, 'attempted_urls', 0) if summary is not None else 0
        seen = getattr(summary, 'unique_urls_seen', 0) if summary is not None else len(self._rows)
        blocked = getattr(summary, 'policy_blocked', 0) if summary is not None else 0
        failed = getattr(summary, 'failures', 0) if summary is not None else 0

        title = (
            f'Crawl - {pages_fetched}/{self._max_pages or "?"} pages, '
            f'{attempted} attempted, {seen} seen, {blocked} blocked, {failed} failed, {elapsed:.1f}s'
        )
        table = Table(title=title, expand=True)
        table.add_column('#', style='dim', width=4, no_wrap=True)
        table.add_column('URL', style='cyan', ratio=4, overflow='ellipsis', no_wrap=True)
        table.add_column('Status', width=16, no_wrap=True)
        table.add_column('Depth', justify='right', width=6, no_wrap=True)
        table.add_column('Links', justify='right', width=6, no_wrap=True)
        table.add_column('Elapsed', style='dim', width=9, no_wrap=True)
        table.add_column('Note', style='dim', ratio=2, overflow='ellipsis', no_wrap=True)

        visible_rows, omitted = self._visible_rows()
        if omitted > 0:
            table.caption = f'{omitted} older rows hidden; showing running URLs and most recent updates.'

        for idx, url, row in visible_rows:
            status = str(row['status'])
            style = _CRAWL_STATUS_STYLES.get(status, 'dim')
            elapsed_cell = ''
            if row.get('elapsed') is not None:
                elapsed_cell = f'{float(row["elapsed"]):.2f}s'
            table.add_row(
                str(idx),
                _url_cell(url),
                f'[{style}]{status}[/{style}]',
                str(row['depth']),
                str(row['links']),
                elapsed_cell,
                str(row.get('note') or ''),
            )
        if omitted > 0:
            table.add_row('…', f'… {omitted} older rows hidden', '…', '…', '…', '', '')
        if not self._rows:
            table.add_row('-', '(no crawl work yet)', 'queued', '-', '-', '', '')
        return table

    def _visible_rows(self) -> tuple[list[tuple[int, str, dict[str, Any]]], int]:
        indexed = [(idx, url, row) for idx, (url, row) in enumerate(self._rows.items(), 1)]
        limit = self._live_row_limit()
        if len(indexed) <= limit:
            return indexed, 0

        running = [item for item in indexed if item[2].get('status') == 'running']
        running = sorted(running, key=lambda item: int(item[2].get('updated_at', 0)), reverse=True)[:limit]
        selected = {url for _, url, _ in running}
        remaining_slots = max(0, limit - len(running))
        recent = sorted(
            (item for item in indexed if item[1] not in selected),
            key=lambda item: int(item[2].get('updated_at', 0)),
            reverse=True,
        )[:remaining_slots]
        visible = sorted([*running, *recent], key=lambda item: item[0])
        return visible, len(indexed) - len(visible)

    def _live_row_limit(self) -> int:
        height = self.console.size.height if self.console.is_terminal else 24
        # Reserve space for title/header/borders/caption and keep every row single-line.
        return max(_CRAWL_LIVE_MIN_ROWS, min(_CRAWL_LIVE_MAX_ROWS, height - 8))


def show(
    value: Any,
    *,
    format: ShowFormat = 'auto',
    title: str | None = None,
    console: Console | None = None,
    fingerprint: object | bool | None = None,
) -> None:
    """Render scraped data or fingerprint reports in a terminal-friendly form."""
    if format not in _VALID_FORMATS:
        raise ValueError(f'Unknown show format {format!r}. Expected one of: {", ".join(sorted(_VALID_FORMATS))}.')

    con = console or _console
    if title:
        _print_line(con, title)

    if fingerprint is True or _is_page_fingerprint(value):
        from yosoi.reporting.fingerprint import fingerprint_table

        con.print(fingerprint_table(value))
        return

    if fingerprint is not None and fingerprint is not False:
        from yosoi.reporting.fingerprint import fingerprint_table

        con.print(fingerprint_table(value, compare_to=fingerprint))
        return

    if _is_crawl_summary(value):
        _render_crawl_summary(value, con)
        return

    if format == 'json':
        _print_line(con, json.dumps(value, indent=2, ensure_ascii=False, default=_json_default))
        return

    if format == 'plain':
        con.print(value, markup=False, soft_wrap=True)
        return

    if _render_tables(value, con):
        return

    if format == 'table':
        raise TypeError(
            'format="table" requires list[dict], dict[str, list[dict]], or dict[str, dict[str, list[dict]]].'
        )

    con.print(value, markup=False, soft_wrap=True)


def _render_tables(value: Any, console: Console) -> bool:
    if _is_records(value):
        _render_record_table(value, console)
        return True

    if not _is_table_mapping(value):
        return False

    for group, group_value in value.items():
        if _is_records(group_value):
            _print_line(console, str(group))
            _render_record_table(group_value, console)
            continue

        _print_line(console, str(group))
        for subgroup, records in group_value.items():
            _print_line(console, f'  {subgroup}')
            _render_record_table(records, console)

    return True


def _is_table_mapping(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    for group_value in value.values():
        if _is_records(group_value):
            continue
        if isinstance(group_value, Mapping) and all(_is_records(records) for records in group_value.values()):
            continue
        return False
    return True


def _render_record_table(records: Sequence[Mapping[str, Any]], console: Console) -> None:
    if not records:
        _print_line(console, '  (no rows)')
        return

    columns = _columns(records)
    table = Table(show_lines=False)
    for column in columns:
        table.add_column(str(column), overflow='fold')

    for record in records:
        table.add_row(*[_cell(record.get(column)) for column in columns])

    console.print(table)


def _render_crawl_summary(summary: Any, console: Console) -> None:
    metrics = Table(title='Crawl summary', show_header=False, show_lines=False)
    metrics.add_column('metric', overflow='fold')
    metrics.add_column('value', overflow='fold')
    metrics.add_row('pages fetched', str(summary.pages_fetched))
    metrics.add_row('urls attempted', str(summary.attempted_urls))
    metrics.add_row('urls seen', str(summary.unique_urls_seen))
    metrics.add_row('blocked', str(summary.policy_blocked))
    metrics.add_row('failed', str(summary.failures))
    metrics.add_row('wall time', f'{summary.wall_time:.2f}s')
    console.print(metrics)

    _render_url_lane_table('Succeeded', summary.outcome_lanes.get('succeeded', ()), console)

    path_counts = summary.path_prefix_counts(depth=2) if hasattr(summary, 'path_prefix_counts') else {}
    if path_counts:
        _render_count_table('Crawl path coverage', path_counts, console)

    content_type_counts = summary.content_type_counts() if hasattr(summary, 'content_type_counts') else {}
    if content_type_counts:
        _render_count_table('Crawl content types', content_type_counts, console)

    discovered = sorted({link.url for result in summary.results for link in result.discovered_links})
    if discovered:
        _render_url_lane_table('Discovered links', discovered, console)

    representative = (
        summary.representative_urls(limit=_CRAWL_LANE_LIMIT) if hasattr(summary, 'representative_urls') else []
    )
    if representative:
        _render_url_lane_table('Representative inventory URLs', representative, console)

    scrape_targets = (
        summary.scrape_target_urls(limit=_CRAWL_LANE_LIMIT) if hasattr(summary, 'scrape_target_urls') else []
    )
    if scrape_targets:
        _render_url_lane_table('Neutral scrape target URLs', scrape_targets, console)

    blocked = summary.outcome_lanes.get('policy_blocked', ())
    if blocked:
        _render_url_lane_table('Policy blocked', blocked, console)

    failed = summary.outcome_lanes.get('failed', ())
    if failed:
        _render_url_lane_table('Failed', failed, console)


def _render_count_table(title: str, counts: Mapping[str, int], console: Console) -> None:
    table = Table(title=title, show_header=True, show_lines=False)
    table.add_column('bucket', overflow='fold')
    table.add_column('count', justify='right')
    for bucket, count in list(counts.items())[:_CRAWL_LANE_LIMIT]:
        table.add_row(str(bucket), str(count))
    omitted = len(counts) - _CRAWL_LANE_LIMIT
    if omitted > 0:
        table.add_row(f'... {omitted} more', '')
    console.print(table)


def _render_url_lane_table(title: str, urls: Sequence[str], console: Console) -> None:
    table = Table(title=title, show_header=False, show_lines=False)
    table.add_column('url', overflow='fold')
    if urls:
        visible = urls[:_CRAWL_LANE_LIMIT]
        for url in visible:
            table.add_row(_url_cell(url))
        omitted = len(urls) - len(visible)
        if omitted > 0:
            table.add_row(f'... {omitted} more')
    else:
        table.add_row('(none)')
    console.print(table)


def _url_cell(url: str) -> Text:
    return Text(url, style=f'link {url}')


def _columns(records: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            column = str(key)
            if column not in seen:
                columns.append(column)
                seen.add(column)
    return columns


def _cell(value: Any) -> Text:
    if value is None:
        return Text('')
    if isinstance(value, str) and _is_http_url(value):
        return _url_cell(value)
    if isinstance(value, (str, int, float, bool)):
        return Text(str(value))
    return Text(json.dumps(value, ensure_ascii=False, default=_json_default))


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def _is_records(value: Any) -> bool:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return False
    return all(isinstance(item, Mapping) for item in value)


def _is_page_fingerprint(value: Any) -> bool:
    return value.__class__.__name__ == 'PageFingerprint' and hasattr(value, 'similarity') and hasattr(value, 'skeleton')


def _is_crawl_summary(value: Any) -> bool:
    return (
        value.__class__.__name__ == 'CrawlRunSummary' and hasattr(value, 'outcome_lanes') and hasattr(value, 'results')
    )


def _json_default(value: Any) -> Any:
    if hasattr(value, 'model_dump'):
        return value.model_dump()
    if hasattr(value, 'dict'):
        return value.dict()
    if is_dataclass(value):
        return asdict(cast(Any, value))
    return str(value)


def _print_line(console: Console, text: str) -> None:
    console.print(text, markup=False, soft_wrap=True)


__all__ = ['RichCrawlProgress', 'ShowFormat', 'show']
