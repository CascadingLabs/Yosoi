"""Microbenchmark: ``HTMLCleaner`` vs ``HTMLPreprocessor`` on real snapshots.

Runs every snapshot in ``tests/data/preprocess/real/`` through both code
paths and prints per-page timing + bytes-out so the spike write-up has a
concrete throughput comparison.

Usage::

    uv run python scripts/bench_preprocess.py
    uv run python scripts/bench_preprocess.py --iterations 20

Both stages are CPU-bound and lxml-vs-BeautifulSoup is the main delta —
preprocess wins on speed because it skips BeautifulSoup parsing.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from yosoi.core.cleaning.cleaner import HTMLCleaner
from yosoi.core.cleaning.preprocess import HTMLPreprocessor

REAL_DIR = Path(__file__).parents[1] / 'tests' / 'data' / 'preprocess' / 'real'

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')


@dataclass
class Sample:
    """One per-page measurement."""

    name: str
    raw_kb: int
    cleaner_ms: float
    cleaner_out_kb: int
    preprocess_ms: float
    preprocess_out_kb: int
    preprocess_ratio: float


def _bench_one(path: Path, iterations: int) -> Sample:
    raw = path.read_text()
    cleaner = HTMLCleaner(console=Console(quiet=True))
    pp = HTMLPreprocessor()

    cleaner_times: list[float] = []
    cleaner_out = ''
    for _ in range(iterations):
        t0 = time.perf_counter()
        cleaner_out = cleaner.clean_html(raw)
        cleaner_times.append((time.perf_counter() - t0) * 1000)

    pp_times: list[float] = []
    pp_result = pp.preprocess(raw)
    for _ in range(iterations):
        t0 = time.perf_counter()
        pp_result = pp.preprocess(raw)
        pp_times.append((time.perf_counter() - t0) * 1000)

    return Sample(
        name=path.name,
        raw_kb=len(raw) // 1024,
        cleaner_ms=statistics.median(cleaner_times),
        cleaner_out_kb=len(cleaner_out) // 1024,
        preprocess_ms=statistics.median(pp_times),
        preprocess_out_kb=len(pp_result.html) // 1024,
        preprocess_ratio=pp_result.reduction_ratio,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=10, help='runs per page (default 10)')
    args = parser.parse_args(argv)

    paths = sorted(REAL_DIR.glob('*.html'))
    if not paths:
        print(
            f'No snapshots in {REAL_DIR}. Run scripts/fetch_preprocess_snapshots.py first.',
            file=sys.stderr,
        )
        return 1

    samples = [_bench_one(p, args.iterations) for p in paths]
    header = (
        f'{"page":30s}  {"raw_KB":>6}  {"cleaner_ms":>10}  {"cleaner_KB":>10}'
        f'  {"prep_ms":>8}  {"prep_KB":>8}  {"prep_ratio":>10}'
    )
    print(header)
    print('-' * len(header))
    for s in samples:
        print(
            f'{s.name:30s}  {s.raw_kb:>6}  {s.cleaner_ms:>10.2f}  {s.cleaner_out_kb:>10}'
            f'  {s.preprocess_ms:>8.2f}  {s.preprocess_out_kb:>8}  {s.preprocess_ratio:>10.3f}'
        )
    print()
    cleaner_total = sum(s.cleaner_ms for s in samples)
    pp_total = sum(s.preprocess_ms for s in samples)
    print(
        f'totals (median * iterations): cleaner {cleaner_total:.1f} ms,'
        f' preprocess {pp_total:.1f} ms,'
        f' speedup {cleaner_total / pp_total:.2f}x'
        if pp_total
        else 'n/a'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
