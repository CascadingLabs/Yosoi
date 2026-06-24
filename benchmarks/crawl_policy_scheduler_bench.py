"""Synthetic benchmark for policy-driven crawl scheduler behavior.

This uses the clean `ys.Policy` stack plus `CrawlCoordinator` against an
in-memory graph fetcher. It isolates frontier/scheduler behavior from network,
browser rendering, robots, and model cost.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from yosoi.core.crawler import CrawlCoordinator
from yosoi.models.results import FetchResult
from yosoi.policy import CrawlBudget, CrawlPolicy, CrawlSafety, Policy, SchedulerPolicy

BENCH_HOST = 'bench.local'
BENCH_ORIGIN = f'https://{BENCH_HOST}'


@dataclass(frozen=True, slots=True)
class Scenario:
    """A deterministic crawl graph shape."""

    name: str
    seed: str
    adjacency: dict[str, tuple[str, ...]]
    max_depth: int
    max_pages: int


@dataclass(frozen=True, slots=True)
class BenchRow:
    """One scheduler benchmark observation."""

    scenario: str
    workers: int
    pages_fetched: int
    unique_urls_seen: int
    idle_worker_slots: int
    dispatch_slot_idle_ratio: float
    average_batch_fill: float
    wall_time: float


class GraphFetcher:
    """Async fetcher that returns link-only HTML from a synthetic graph."""

    def __init__(self, adjacency: dict[str, tuple[str, ...]]) -> None:
        self.adjacency = adjacency

    async def fetch(self, url: str) -> FetchResult:
        children = self.adjacency.get(url, ())
        html = '<html><body>' + ''.join(f'<a href="{child}">{child}</a>' for child in children) + '</body></html>'
        return FetchResult(url=url, html=html, status_code=200, fetch_time=0.0)


def _url(name: str) -> str:
    return f'{BENCH_ORIGIN}/{name}'


def _chain(length: int) -> Scenario:
    adjacency: dict[str, tuple[str, ...]] = {}
    for index in range(length - 1):
        adjacency[_url(f'chain-{index}')] = (_url(f'chain-{index + 1}'),)
    adjacency[_url(f'chain-{length - 1}')] = ()
    return Scenario('chain', _url('chain-0'), adjacency, length - 1, length)


def _wide(width: int) -> Scenario:
    seed = _url('wide-root')
    adjacency = {seed: tuple(_url(f'wide-{index}') for index in range(width))}
    adjacency.update({_url(f'wide-{index}'): () for index in range(width)})
    return Scenario('wide', seed, adjacency, 1, width + 1)


def _tree(fanout: int, depth: int) -> Scenario:
    adjacency: dict[str, tuple[str, ...]] = {}
    frontier = ['tree-root']
    for _current_depth in range(depth):
        next_frontier: list[str] = []
        for parent in frontier:
            children = [f'{parent}-{child}' for child in range(fanout)]
            adjacency[_url(parent)] = tuple(_url(child) for child in children)
            next_frontier.extend(children)
        frontier = next_frontier
    for leaf in frontier:
        adjacency[_url(leaf)] = ()
    return Scenario(f'tree-f{fanout}', _url('tree-root'), adjacency, depth, len(adjacency))


def _scenarios() -> tuple[Scenario, ...]:
    return (_chain(16), _wide(24), _tree(fanout=3, depth=3))


async def _run_once(scenario: Scenario, *, workers: int) -> BenchRow:
    policy = Policy(
        crawl=CrawlPolicy(
            budget=CrawlBudget(max_pages=scenario.max_pages, max_depth=scenario.max_depth),
            scheduler=SchedulerPolicy(max_workers=workers, per_host_concurrency=1, politeness_delay=0),
            safety=CrawlSafety(allowed_hosts=(BENCH_HOST,)),
        )
    )
    runtime = policy.check_crawl(seeds=(scenario.seed,)).runtime
    if runtime is None:
        raise RuntimeError('policy check did not produce runtime config')
    summary = await CrawlCoordinator(
        fetcher=GraphFetcher(scenario.adjacency),
        config=runtime,
        persist_frontier=False,
    ).run()
    return BenchRow(
        scenario=scenario.name,
        workers=workers,
        pages_fetched=summary.pages_fetched,
        unique_urls_seen=summary.unique_urls_seen,
        idle_worker_slots=summary.idle_worker_slots,
        dispatch_slot_idle_ratio=summary.dispatch_slot_idle_ratio,
        average_batch_fill=summary.average_batch_fill,
        wall_time=summary.wall_time,
    )


async def _benchmark(workers: tuple[int, ...]) -> list[BenchRow]:
    rows: list[BenchRow] = []
    for scenario in _scenarios():
        for worker_count in workers:
            rows.append(await _run_once(scenario, workers=worker_count))  # noqa: PERF401
    return rows


def _build_table(rows: list[BenchRow]) -> Table:
    table = Table(title='Policy Crawl Scheduler Benchmark')
    table.add_column('Scenario')
    table.add_column('Workers', justify='right')
    table.add_column('Pages', justify='right')
    table.add_column('Seen', justify='right')
    table.add_column('Idle Slots', justify='right')
    table.add_column('Idle Ratio', justify='right')
    table.add_column('Avg Fill', justify='right')
    table.add_column('Wall', justify='right')
    for row in rows:
        table.add_row(
            row.scenario,
            str(row.workers),
            str(row.pages_fetched),
            str(row.unique_urls_seen),
            str(row.idle_worker_slots),
            f'{row.dispatch_slot_idle_ratio:.1%}',
            f'{row.average_batch_fill:.2f}',
            f'{row.wall_time:.4f}s',
        )
    return table


def _format_report(rows: list[BenchRow]) -> str:
    lines = [
        '# Policy Crawl Scheduler Benchmark',
        '',
        f'- timestamp: {datetime.now(timezone.utc).isoformat()}',
        '- llm_hotpath: false',
        '- network: synthetic only',
        '',
        '| scenario | workers | pages | seen | idle slots | dispatch idle ratio | avg fill | wall |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    lines.extend(
        f'| {row.scenario} | {row.workers} | {row.pages_fetched} | {row.unique_urls_seen} | '
        f'{row.idle_worker_slots} | {row.dispatch_slot_idle_ratio:.1%} | '
        f'{row.average_batch_fill:.2f} | {row.wall_time:.4f}s |'
        for row in rows
    )
    lines.extend(
        [
            '',
            '## Read',
            '',
            '- Chain-shaped crawls starve extra workers because each fetch discovers one next URL.',
            '- Wide/tree crawls pay off once the initial seed expands the frontier.',
            '- This benchmark proves policy-derived scheduler defaults can be measured without live traffic.',
            '',
        ]
    )
    return '\n'.join(lines)


def _write_report(rows: list[BenchRow]) -> Path:
    report_dir = Path('spike-results')
    report_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = report_dir / f'{stamp}-crawl-policy-scheduler-bench.md'
    path.write_text(_format_report(rows), encoding='utf-8')
    return path


async def amain() -> None:
    parser = argparse.ArgumentParser(description='Benchmark policy-driven crawl scheduler behavior.')
    parser.add_argument('--workers', default='1,2,3,5,8', help='Comma-separated worker counts.')
    args = parser.parse_args()
    workers = tuple(int(value.strip()) for value in args.workers.split(',') if value.strip())
    if not workers or min(workers) < 1:
        raise SystemExit('--workers must contain positive integers')

    rows = await _benchmark(workers)
    console = Console()
    console.print(_build_table(rows))
    report_path = _write_report(rows)
    console.print(f'[dim]report: {report_path}[/dim]')


if __name__ == '__main__':
    asyncio.run(amain())
