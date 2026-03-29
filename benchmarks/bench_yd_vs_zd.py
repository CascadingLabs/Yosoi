"""Benchmark: yd (Rust/chromiumoxide pool) vs zendriver on a WAF-protected page.

Measures:
  - Cold start latency (browser launch → first page ready)
  - Single-page fetch latency (navigate + DOM stable)
  - Parallel fetch throughput (N concurrent tabs)
  - Peak memory (RSS) of the browser process tree
  - Python-side memory (process RSS delta)

Run:
  uv run python benchmarks/bench_yd_vs_zd.py
  uv run python benchmarks/bench_yd_vs_zd.py --runs 5 --parallel 4
  uv run python benchmarks/bench_yd_vs_zd.py --url https://example.com
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import os
import statistics
import time

import psutil

URL = (
    'https://www.businesswire.com/news/home/20251114087859/en/'
    'Latin-America-AI-in-Payments-and-E-Commerce-Analysis-Report-2025-'
    'Featuring-OpenAI-Google-Anthropic-Galileo-JPMorgan-Pix-and-Latitud-'
    '--ResearchAndMarkets.com/'
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _rss_mb() -> float:
    """Current process RSS in MB."""
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def _chrome_rss_mb() -> float:
    """Total RSS of all chrome/chromium child processes in MB."""
    total = 0.0
    me = psutil.Process(os.getpid())
    for child in me.children(recursive=True):
        try:
            name = child.name().lower()
            if 'chrom' in name:
                total += child.memory_info().rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total


def _all_chrome_rss_mb() -> float:
    """Total RSS of ALL chrome/chromium processes on the system in MB."""
    total = 0.0
    for proc in psutil.process_iter(['name', 'memory_info']):
        try:
            if 'chrom' in (proc.info['name'] or '').lower():
                total += proc.info['memory_info'].rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total


class Result:
    """Collected metrics for one benchmark run."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.cold_start: float = 0.0
        self.single_fetches: list[float] = []
        self.parallel_time: float = 0.0
        self.parallel_count: int = 0
        self.chrome_rss_peak: float = 0.0
        self.python_rss_delta: float = 0.0
        self.html_lengths: list[int] = []
        self.blocked: int = 0

    def summary(self) -> str:
        lines = [f'\n{"=" * 60}', f'  {self.name}', '=' * 60]
        lines.append(f'  Cold start (launch → ready):  {self.cold_start:.2f}s')
        if self.single_fetches:
            avg = statistics.mean(self.single_fetches)
            std = statistics.stdev(self.single_fetches) if len(self.single_fetches) > 1 else 0
            lines.append(f'  Single fetch latency:         {avg:.2f}s ± {std:.2f}s  (n={len(self.single_fetches)})')
        if self.parallel_count > 0:
            lines.append(
                f'  Parallel fetch ({self.parallel_count} tabs):     '
                f'{self.parallel_time:.2f}s total, '
                f'{self.parallel_time / self.parallel_count:.2f}s/page avg'
            )
        lines.append(f'  Chrome RSS peak:              {self.chrome_rss_peak:.0f} MB')
        lines.append(f'  Python RSS delta:             {self.python_rss_delta:+.1f} MB')
        if self.html_lengths:
            lines.append(
                f'  HTML sizes:                   '
                f'avg {statistics.mean(self.html_lengths):,.0f} chars  '
                f'(min {min(self.html_lengths):,}, max {max(self.html_lengths):,})'
            )
        if self.blocked:
            lines.append(f'  Blocked fetches:              {self.blocked}')
        return '\n'.join(lines)


# ── YD benchmark ─────────────────────────────────────────────────────────


async def bench_yd(url: str, runs: int, parallel: int) -> Result:
    from yosoi import yd

    r = Result('yd (Rust/chromiumoxide pool)')
    gc.collect()
    py_rss_before = _rss_mb()

    # Min content to distinguish real page from Akamai challenge stubs
    min_len = 10_000

    # Cold start
    t0 = time.perf_counter()
    pool_ctx = await yd.pool(headless=False, tabs_per_browser=max(parallel, 1))
    # Use __aenter__/__aexit__ for proper lifecycle
    pool = await pool_ctx.__aenter__()
    r.cold_start = time.perf_counter() - t0

    async def _yd_fetch_one(pool_ref: object) -> tuple[int, float, bool]:
        """Fetch one page, handling WAF challenge redirects gracefully."""
        t = time.perf_counter()
        async with await pool_ref.acquire() as tab:  # type: ignore[union-attr]
            await tab.navigate(url)
            try:
                stabilised = await tab.wait_for_stable_dom(timeout=25.0, min_length=min_len)
            except RuntimeError:
                # WAF challenge may redirect and invalidate JS context.
                # Fall back to a fixed wait then grab whatever content is there.
                await asyncio.sleep(8)
                stabilised = False
            html = await tab.content()
        elapsed = time.perf_counter() - t
        blocked = not stabilised or 'Access Denied' in html or len(html) < min_len
        return len(html), elapsed, blocked

    try:
        # Single-page fetches
        for i in range(runs):
            length, elapsed, blocked = await _yd_fetch_one(pool)
            r.single_fetches.append(elapsed)
            if blocked:
                r.blocked += 1
            r.html_lengths.append(length)
            r.chrome_rss_peak = max(r.chrome_rss_peak, _all_chrome_rss_mb())
            print(f'  yd single [{i + 1}/{runs}]: {elapsed:.2f}s  {"BLOCKED" if blocked else f"{length:,} chars"}')

        # Parallel fetches
        if parallel > 1:
            print(f'  yd parallel [{parallel} tabs]...')
            t2 = time.perf_counter()
            results = await asyncio.gather(*[_yd_fetch_one(pool) for _ in range(parallel)])
            r.parallel_time = time.perf_counter() - t2
            r.parallel_count = parallel
            for length, elapsed, blocked in results:
                r.html_lengths.append(length)
                if blocked:
                    r.blocked += 1
                print(f'    tab: {elapsed:.2f}s  {"BLOCKED" if blocked else f"{length:,} chars"}')
            r.chrome_rss_peak = max(r.chrome_rss_peak, _all_chrome_rss_mb())
    finally:
        await pool_ctx.__aexit__(None, None, None)

    r.python_rss_delta = _rss_mb() - py_rss_before
    return r


# ── Zendriver benchmark ──────────────────────────────────────────────────


async def bench_zd(url: str, runs: int, parallel: int) -> Result:
    import zendriver as zd

    r = Result('zendriver (Python/nodriver)')
    gc.collect()
    py_rss_before = _rss_mb()

    # Cold start
    t0 = time.perf_counter()
    browser = await zd.start(headless=False)
    r.cold_start = time.perf_counter() - t0

    async def _zd_fetch_tab(tab_url: str) -> tuple[str | None, float, bool]:
        t = time.perf_counter()
        tab = await browser.get(tab_url, new_tab=True)
        await tab.wait_for_ready_state('complete', timeout=20)
        # DOM stability polling (same algorithm as yd)
        deadline = time.time() + 25
        prev, stable = 0, 0
        while time.time() < deadline:
            size = await tab.evaluate('document.body ? document.body.innerHTML.length : 0')
            if size > 10000 and size == prev:
                stable += 1
                if stable >= 5:
                    break
            else:
                stable = 0
                prev = size
            await asyncio.sleep(0.3)
        html = await tab.evaluate('document.body.innerHTML')
        elapsed = time.perf_counter() - t
        blocked = not html or 'Access Denied' in str(html) or len(html) < 10000
        with contextlib.suppress(Exception):
            await tab.close()
        return html, elapsed, blocked

    try:
        # Single-page fetches
        for i in range(runs):
            html, elapsed, blocked = await _zd_fetch_tab(url)
            r.single_fetches.append(elapsed)
            length = len(html) if html else 0
            r.html_lengths.append(length)
            if blocked:
                r.blocked += 1
            r.chrome_rss_peak = max(r.chrome_rss_peak, _all_chrome_rss_mb())
            print(f'  zd single [{i + 1}/{runs}]: {elapsed:.2f}s  {"BLOCKED" if blocked else f"{length:,} chars"}')

        # Parallel fetches
        if parallel > 1:
            print(f'  zd parallel [{parallel} tabs]...')
            t2 = time.perf_counter()
            results = await asyncio.gather(*[_zd_fetch_tab(url) for _ in range(parallel)])
            r.parallel_time = time.perf_counter() - t2
            r.parallel_count = parallel
            for html, elapsed, blocked in results:
                length = len(html) if html else 0
                r.html_lengths.append(length)
                if blocked:
                    r.blocked += 1
                print(f'    tab: {elapsed:.2f}s  {"BLOCKED" if blocked else f"{length:,} chars"}')
            r.chrome_rss_peak = max(r.chrome_rss_peak, _all_chrome_rss_mb())
    finally:
        with contextlib.suppress(Exception):
            await browser.stop()

    r.python_rss_delta = _rss_mb() - py_rss_before
    return r


# ── Main ─────────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(description='Benchmark yd vs zendriver')
    parser.add_argument('--url', default=URL, help='Target URL')
    parser.add_argument('--runs', type=int, default=3, help='Sequential fetch runs per engine')
    parser.add_argument('--parallel', type=int, default=3, help='Parallel tab count')
    args = parser.parse_args()

    print(f'URL:      {args.url}')
    print(f'Runs:     {args.runs} sequential + {args.parallel} parallel')
    print(f'System:   {psutil.virtual_memory().total / 1024**3:.1f} GB RAM, {psutil.cpu_count()} CPUs')
    print()

    # Kill stale chrome processes to get a clean baseline
    baseline_chrome = _all_chrome_rss_mb()
    if baseline_chrome > 0:
        print(f'Note: {baseline_chrome:.0f} MB of existing Chrome processes detected\n')

    print('─── yd (Rust pool) ────────────────────────────────────')
    yd_result = await bench_yd(args.url, args.runs, args.parallel)

    # Brief pause between engines to let OS reclaim memory
    gc.collect()
    await asyncio.sleep(2)

    print('\n─── zendriver ─────────────────────────────────────────')
    zd_result = await bench_zd(args.url, args.runs, args.parallel)

    # ── Comparison ────────────────────────────────────────────────
    print(yd_result.summary())
    print(zd_result.summary())

    print(f'\n{"=" * 60}')
    print('  HEAD-TO-HEAD')
    print('=' * 60)

    yd_avg = statistics.mean(yd_result.single_fetches) if yd_result.single_fetches else 0
    zd_avg = statistics.mean(zd_result.single_fetches) if zd_result.single_fetches else 0
    if yd_avg and zd_avg:
        faster = 'yd' if yd_avg < zd_avg else 'zd'
        ratio = max(yd_avg, zd_avg) / min(yd_avg, zd_avg)
        print(f'  Single fetch:    {faster} is {ratio:.1f}x faster')

    if yd_result.parallel_time and zd_result.parallel_time:
        faster = 'yd' if yd_result.parallel_time < zd_result.parallel_time else 'zd'
        ratio = max(yd_result.parallel_time, zd_result.parallel_time) / min(
            yd_result.parallel_time, zd_result.parallel_time
        )
        print(f'  Parallel fetch:  {faster} is {ratio:.1f}x faster')

    faster = 'yd' if yd_result.cold_start < zd_result.cold_start else 'zd'
    ratio = max(yd_result.cold_start, zd_result.cold_start) / min(yd_result.cold_start, zd_result.cold_start)
    print(f'  Cold start:      {faster} is {ratio:.1f}x faster')

    if yd_result.chrome_rss_peak and zd_result.chrome_rss_peak:
        lighter = 'yd' if yd_result.chrome_rss_peak < zd_result.chrome_rss_peak else 'zd'
        diff = abs(yd_result.chrome_rss_peak - zd_result.chrome_rss_peak)
        print(f'  Chrome memory:   {lighter} uses {diff:.0f} MB less')

    print()


if __name__ == '__main__':
    asyncio.run(main())
