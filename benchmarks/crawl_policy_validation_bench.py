"""Synthetic benchmark for crawl policy validation overhead.

This benchmark isolates the declarative policy stack from network, browser,
robots, and model cost. It answers whether `ys.check_policy(...)` is cheap
enough to run before every crawl job.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from yosoi.policies import CrawlBudget, CrawlPolicy, CrawlSafety, Policy, SchedulerPolicy, check_policy


@dataclass(frozen=True, slots=True)
class BenchRow:
    """One policy validation benchmark observation."""

    scenario: str
    iterations: int
    elapsed_seconds: float
    checks_per_second: float
    microseconds_per_check: float


def _policy_scenarios() -> dict[str, Policy | str]:
    return {
        'preset': 'crawl.conservative',
        'inline_small': Policy(
            crawl=CrawlPolicy(
                budget=CrawlBudget(max_pages=20, max_depth=1),
                scheduler=SchedulerPolicy(max_workers=2, per_host_concurrency=1),
                safety=CrawlSafety(allowed_hosts=('example.com',)),
            )
        ),
        'inline_large': Policy(
            crawl=CrawlPolicy(
                budget=CrawlBudget(max_pages=200_000, max_depth=3, max_attempts=250_000, max_pages_per_host=20_000),
                scheduler=SchedulerPolicy(
                    max_workers=32,
                    per_host_concurrency=1,
                    politeness_delay=0.25,
                    fetch_timeout_seconds=20.0,
                ),
                safety=CrawlSafety(
                    allowed_hosts=('example.com', 'news.example.com', 'sports.example.com'),
                    blocked_path_prefixes=('/login', '/cart', '/checkout'),
                ),
            )
        ),
    }


def _run_scenario(name: str, policy: Policy | str, *, iterations: int) -> BenchRow:
    seeds = ('https://example.com/news/start',)
    started = time.perf_counter()
    for _ in range(iterations):
        check = check_policy(policy, seeds=seeds)
        if not check.valid:
            raise RuntimeError(f'policy check failed for {name}')
    elapsed = time.perf_counter() - started
    checks_per_second = iterations / elapsed if elapsed else float('inf')
    return BenchRow(
        scenario=name,
        iterations=iterations,
        elapsed_seconds=elapsed,
        checks_per_second=checks_per_second,
        microseconds_per_check=(elapsed / iterations) * 1_000_000,
    )


def _build_table(rows: list[BenchRow]) -> Table:
    table = Table(title='Crawl Policy Validation Benchmark')
    table.add_column('Scenario')
    table.add_column('Iterations', justify='right')
    table.add_column('Elapsed', justify='right')
    table.add_column('Checks/s', justify='right')
    table.add_column('us/check', justify='right')
    for row in rows:
        table.add_row(
            row.scenario,
            str(row.iterations),
            f'{row.elapsed_seconds:.4f}s',
            f'{row.checks_per_second:.0f}',
            f'{row.microseconds_per_check:.1f}',
        )
    return table


def _format_report(rows: list[BenchRow]) -> str:
    lines = [
        '# Crawl Policy Validation Benchmark',
        '',
        f'- timestamp: {datetime.now(timezone.utc).isoformat()}',
        '- llm_hotpath: false',
        '- network: false',
        '',
        '## What This Measures',
        '',
        'This measures `ys.check_policy(...)` plus runtime config derivation. It does not include '
        'frontier scheduling, fetching, robots checks, browser work, or extraction.',
        '',
        '## Results',
        '',
        '| scenario | iterations | elapsed | checks/s | us/check |',
        '| --- | ---: | ---: | ---: | ---: |',
    ]
    lines.extend(
        f'| {row.scenario} | {row.iterations} | {row.elapsed_seconds:.4f}s | '
        f'{row.checks_per_second:.0f} | {row.microseconds_per_check:.1f} |'
        for row in rows
    )
    lines.extend(
        [
            '',
            '## Read',
            '',
            '- Policy validation should stay cheap enough to run before every crawl job.',
            '- Large crawl budgets should not materially change validation overhead.',
            '- This benchmark fails fast if a preset or inline policy can no longer be checked.',
            '',
        ]
    )
    return '\n'.join(lines)


def _write_report(rows: list[BenchRow]) -> Path:
    report_dir = Path('spike-results')
    report_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = report_dir / f'{stamp}-crawl-policy-validation-bench.md'
    path.write_text(_format_report(rows), encoding='utf-8')
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description='Benchmark crawl policy validation overhead.')
    parser.add_argument('--iterations', type=int, default=10_000)
    args = parser.parse_args()
    if args.iterations < 1:
        raise SystemExit('--iterations must be >= 1')

    rows = [_run_scenario(name, policy, iterations=args.iterations) for name, policy in _policy_scenarios().items()]
    console = Console()
    console.print(_build_table(rows))
    report_path = _write_report(rows)
    console.print(f'[dim]report: {report_path}[/dim]')


if __name__ == '__main__':
    main()
