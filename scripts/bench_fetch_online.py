"""Live benchmark harness for Yosoi fetch acquisition.

Examples:
    uv run python scripts/bench_fetch_online.py \
      https://en.wikipedia.org/wiki/Web_scraping --runs 3 --chars 1000

The harness uses Yosoi's public operation layer in-process so it measures the
fetch/clean/render hot path, not uv/CLI startup. It defaults to an isolated
working directory to avoid stale .yosoi fetch-strategy cache affecting timings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from yosoi.operations import FetchRequest, run_fetch

DEFAULT_MODES = ('auto:text', 'simple:text', 'headless:rendered-html')


@contextmanager
def _working_dir(path: Path | None) -> Iterator[None]:
    if path is None:
        yield
        return
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _parse_mode(value: str) -> tuple[str, str]:
    if ':' not in value:
        return value, 'text'
    fetcher, view = value.split(':', 1)
    return fetcher, view


async def _one(url: str, *, fetcher: str, view: str, chars: int) -> dict[str, Any]:
    start = time.perf_counter()
    result = await run_fetch(
        FetchRequest.from_axes(
            url,
            view=view,
            fetcher_type=fetcher,
            page_size=chars,
        )
    )
    wall = time.perf_counter() - start
    unit = result.results[0]
    return {
        'url': url,
        'mode': f'{fetcher}:{view}',
        'status': unit.status,
        'status_code': unit.status_code,
        'wall_seconds': wall,
        'fetch_time_seconds': unit.fetch_time,
        'fetcher_type': unit.fetcher_type,
        'raw_html_chars': unit.raw_html_chars,
        'cleaned_html_chars': unit.cleaned_html_chars,
        'text_chars': unit.text_chars,
        'content_chars': unit.content_chars,
        'truncated': unit.truncated,
        'error': unit.error,
    }


async def _bench(urls: Sequence[str], modes: Sequence[str], *, runs: int, chars: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for url in urls:
        for raw_mode in modes:
            fetcher, view = _parse_mode(raw_mode)
            for run in range(1, runs + 1):
                row = await _one(url, fetcher=fetcher, view=view, chars=chars)
                row['run'] = run
                rows.append(row)
                print(json.dumps(row, sort_keys=True), file=sys.stderr, flush=True)

    summary: list[dict[str, Any]] = []
    for key in sorted({(row['url'], row['mode']) for row in rows}):
        group = [row for row in rows if (row['url'], row['mode']) == key]
        walls = [float(row['wall_seconds']) for row in group]
        fetch_times = [float(row['fetch_time_seconds']) for row in group]
        summary.append(
            {
                'url': key[0],
                'mode': key[1],
                'runs': len(group),
                'wall_min': min(walls),
                'wall_median': statistics.median(walls),
                'wall_max': max(walls),
                'fetch_time_median': statistics.median(fetch_times),
                'statuses': sorted({str(row['status']) for row in group}),
                'errors': [row['error'] for row in group if row['error']],
            }
        )
    return {'summary': summary, 'rows': rows}


def main() -> None:
    """Run the CLI entry point."""
    parser = argparse.ArgumentParser(description='Benchmark live Yosoi fetch paths.')
    parser.add_argument('urls', nargs='+', help='Live URL(s) to fetch.')
    parser.add_argument('--mode', action='append', dest='modes', help='Fetcher:view, e.g. auto:text or simple:text.')
    parser.add_argument('--runs', type=int, default=3, help='Runs per URL/mode.')
    parser.add_argument('--chars', type=int, default=1_000, help='Fetch page size/chars.')
    parser.add_argument('--reuse-storage', action='store_true', help='Use the current .yosoi storage/cache.')
    parser.add_argument('--output', type=Path, default=None, help='Write final JSON summary to this path.')
    args = parser.parse_args()

    modes = tuple(args.modes or DEFAULT_MODES)
    if args.runs < 1:
        parser.error('--runs must be >= 1')
    if args.chars < 1:
        parser.error('--chars must be >= 1')

    if args.reuse_storage:
        result = asyncio.run(_bench(args.urls, modes, runs=args.runs, chars=args.chars))
    else:
        with tempfile.TemporaryDirectory(prefix='yosoi-fetch-bench-') as tmp, _working_dir(Path(tmp)):
            result = asyncio.run(_bench(args.urls, modes, runs=args.runs, chars=args.chars))

    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + '\n', encoding='utf-8')
    else:
        print(payload)


if __name__ == '__main__':
    main()
