"""Benchmark: yd (Rust/chromiumoxide pool) vs zendriver on a WAF-protected page.

Measures per engine/mode:
  - Cold start latency (browser launch → first page ready)
  - Single-page fetch latency (navigate + wait)
  - Parallel fetch throughput (N concurrent tabs)
  - Chrome RSS during sequential vs parallel phases
  - Memory efficiency (MB per 100K chars of fetched content)

yd uses fully event-driven CDP lifecycle events (zero sleeps, zero polling).
zendriver uses its native polling approach for a fair comparison.

Run:
  uv run python benchmarks/bench_yd_vs_zd.py
  uv run python benchmarks/bench_yd_vs_zd.py --runs 3 --parallel 3
  uv run python benchmarks/bench_yd_vs_zd.py --yd-only --mode balanced
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

MIN_CONTENT_LEN = 10_000


# ── Helpers ──────────────────────────────────────────────────────────────


def _rss_mb() -> float:
    """Current process RSS in MB."""
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def _chrome_proc_rss(proc: psutil.Process) -> float:
    """Return RSS in MB for a single chrome process, or 0 on error."""
    try:
        if 'chrom' in (proc.info['name'] or '').lower():
            return proc.info['memory_info'].rss / 1024 / 1024
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return 0.0


def _all_chrome_rss_mb() -> float:
    """Total RSS of ALL chrome/chromium processes on the system in MB."""
    return sum(_chrome_proc_rss(p) for p in psutil.process_iter(['name', 'memory_info']))


class Result:
    """Collected metrics for one benchmark run."""

    def __init__(self, name: str) -> None:
        """Initialise empty result container for *name*."""
        self.name = name
        self.cold_start: float = 0.0
        self.single_fetches: list[float] = []
        self.parallel_time: float = 0.0
        self.parallel_count: int = 0
        self.seq_chrome_rss_peak: float = 0.0
        self.par_chrome_rss_peak: float = 0.0
        self.python_rss_delta: float = 0.0
        self.html_lengths: list[int] = []
        self.blocked: int = 0
        self.wait_events: list[str] = []

    @property
    def chrome_rss_peak(self) -> float:
        """Peak Chrome RSS across both sequential and parallel phases."""
        return max(self.seq_chrome_rss_peak, self.par_chrome_rss_peak)

    @property
    def total_content_chars(self) -> int:
        """Total characters across all fetched pages."""
        return sum(self.html_lengths)

    @property
    def mem_efficiency(self) -> float:
        """MB per 100K chars of content. Lower = better."""
        total_100k = self.total_content_chars / 100_000
        if total_100k == 0:
            return 0.0
        return self.chrome_rss_peak / total_100k

    def summary(self) -> str:
        """Format a human-readable summary of all collected metrics."""
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
        lines.append(f'  Chrome RSS (sequential):      {self.seq_chrome_rss_peak:.0f} MB')
        if self.par_chrome_rss_peak > 0:
            lines.append(f'  Chrome RSS (parallel):        {self.par_chrome_rss_peak:.0f} MB')
        lines.append(f'  Memory efficiency:            {self.mem_efficiency:.1f} MB / 100K chars')
        lines.append(f'  Python RSS delta:             {self.python_rss_delta:+.1f} MB')
        if self.html_lengths:
            lines.append(
                f'  HTML sizes:                   '
                f'avg {statistics.mean(self.html_lengths):,.0f} chars  '
                f'(min {min(self.html_lengths):,}, max {max(self.html_lengths):,})'
            )
        if self.blocked:
            lines.append(f'  Blocked fetches:              {self.blocked}')
        if self.wait_events:
            from collections import Counter

            counts = Counter(self.wait_events)
            lines.append(f'  Wait events:                  {dict(counts)}')
        return '\n'.join(lines)


# ── YD benchmark ─────────────────────────────────────────────────────────


async def bench_yd(url: str, runs: int, parallel: int, mode: str, *, headless: bool = False) -> Result:
    """Run yd benchmark with given performance mode."""
    from yosoi import yd

    cfg = yd.PoolConfig(mode=mode, headless=headless, tabs_per_browser=max(parallel, 1))
    vp = cfg.effective_viewport
    label = f'yd {mode} ({vp.width}x{vp.height}, {cfg.effective_browsers}b×{cfg.effective_tabs_per_browser}t)'
    r = Result(label)
    gc.collect()
    py_rss_before = _rss_mb()

    t0 = time.perf_counter()
    pool_ctx = await yd.create_pool(cfg)
    pool = await pool_ctx.__aenter__()
    r.cold_start = time.perf_counter() - t0

    async def _yd_fetch(pool_ref: object) -> tuple[int, float, bool, str]:
        """Event-driven fetch. Zero sleeps, zero polling."""
        t = time.perf_counter()
        async with await pool_ref.acquire() as tab:  # type: ignore[union-attr]
            await tab.navigate(url)
            event = await tab.wait_for_network_idle(timeout=30.0)
            html = await tab.content()
        elapsed = time.perf_counter() - t
        blocked = not event or 'Access Denied' in html or len(html) < MIN_CONTENT_LEN
        return len(html), elapsed, blocked, event or 'timeout'

    try:
        for i in range(runs):
            length, elapsed, blocked, event = await _yd_fetch(pool)
            r.single_fetches.append(elapsed)
            r.html_lengths.append(length)
            r.wait_events.append(event)
            if blocked:
                r.blocked += 1
            r.seq_chrome_rss_peak = max(r.seq_chrome_rss_peak, _all_chrome_rss_mb())
            status = 'BLOCKED' if blocked else f'{length:,} chars'
            print(f'  yd/{mode} [{i + 1}/{runs}]: {elapsed:.2f}s  {status}  ({event})')

        if parallel > 1:
            print(f'  yd/{mode} parallel [{parallel} tabs]...')
            t2 = time.perf_counter()
            results = await asyncio.gather(*[_yd_fetch(pool) for _ in range(parallel)])
            r.parallel_time = time.perf_counter() - t2
            r.parallel_count = parallel
            for length, elapsed, blocked, event in results:
                r.html_lengths.append(length)
                r.wait_events.append(event)
                if blocked:
                    r.blocked += 1
                status = 'BLOCKED' if blocked else f'{length:,} chars'
                print(f'    tab: {elapsed:.2f}s  {status}  ({event})')
            r.par_chrome_rss_peak = _all_chrome_rss_mb()
    finally:
        await pool_ctx.__aexit__(None, None, None)

    r.python_rss_delta = _rss_mb() - py_rss_before
    return r


# ── Zendriver benchmark ──────────────────────────────────────────────────


async def bench_zd(url: str, runs: int, parallel: int, *, headless: bool = False) -> Result:
    """Run zendriver benchmark: native polling-based DOM stability waits."""
    import zendriver as zd

    r = Result('zendriver (Python/nodriver)')
    gc.collect()
    py_rss_before = _rss_mb()

    t0 = time.perf_counter()
    browser = await zd.start(headless=headless)
    r.cold_start = time.perf_counter() - t0

    async def _zd_fetch(tab_url: str) -> tuple[int, float, bool]:
        t = time.perf_counter()
        tab = await browser.get(tab_url, new_tab=True)
        await tab.wait_for_ready_state('complete', timeout=20)
        deadline = time.time() + 25
        prev, stable = 0, 0
        while time.time() < deadline:
            size = await tab.evaluate('document.body ? document.body.innerHTML.length : 0')
            if size > MIN_CONTENT_LEN and size == prev:
                stable += 1
                if stable >= 5:
                    break
            else:
                stable = 0
                prev = size
            await asyncio.sleep(0.3)
        html = await tab.evaluate('document.body.innerHTML')
        elapsed = time.perf_counter() - t
        length = len(html) if html else 0
        blocked = not html or 'Access Denied' in str(html) or length < MIN_CONTENT_LEN
        with contextlib.suppress(Exception):
            await tab.close()
        return length, elapsed, blocked

    try:
        for i in range(runs):
            length, elapsed, blocked = await _zd_fetch(url)
            r.single_fetches.append(elapsed)
            r.html_lengths.append(length)
            if blocked:
                r.blocked += 1
            r.seq_chrome_rss_peak = max(r.seq_chrome_rss_peak, _all_chrome_rss_mb())
            status = 'BLOCKED' if blocked else f'{length:,} chars'
            print(f'  zd [{i + 1}/{runs}]: {elapsed:.2f}s  {status}')

        if parallel > 1:
            print(f'  zd parallel [{parallel} tabs]...')
            t2 = time.perf_counter()
            results = await asyncio.gather(*[_zd_fetch(url) for _ in range(parallel)])
            r.parallel_time = time.perf_counter() - t2
            r.parallel_count = parallel
            for length, elapsed, blocked in results:
                r.html_lengths.append(length)
                if blocked:
                    r.blocked += 1
                status = 'BLOCKED' if blocked else f'{length:,} chars'
                print(f'    tab: {elapsed:.2f}s  {status}')
            r.par_chrome_rss_peak = _all_chrome_rss_mb()
    finally:
        with contextlib.suppress(Exception):
            await browser.stop()

    r.python_rss_delta = _rss_mb() - py_rss_before
    return r


# ── Comparison ───────────────────────────────────────────────────────────


def _print_comparison(yd_r: Result, zd_r: Result) -> None:
    """Print head-to-head comparison between an yd result and zendriver."""
    print('\n  vs zendriver:')

    yd_avg = statistics.mean(yd_r.single_fetches) if yd_r.single_fetches else 0
    zd_avg = statistics.mean(zd_r.single_fetches) if zd_r.single_fetches else 0
    if yd_avg and zd_avg:
        faster = 'yd' if yd_avg < zd_avg else 'zd'
        ratio = max(yd_avg, zd_avg) / min(yd_avg, zd_avg)
        print(f'    Single fetch:    {faster} is {ratio:.1f}x faster')

    if yd_r.parallel_time and zd_r.parallel_time:
        faster = 'yd' if yd_r.parallel_time < zd_r.parallel_time else 'zd'
        ratio = max(yd_r.parallel_time, zd_r.parallel_time) / min(yd_r.parallel_time, zd_r.parallel_time)
        print(f'    Parallel fetch:  {faster} is {ratio:.1f}x faster')

    faster = 'yd' if yd_r.cold_start < zd_r.cold_start else 'zd'
    ratio = max(yd_r.cold_start, zd_r.cold_start) / min(yd_r.cold_start, zd_r.cold_start)
    print(f'    Cold start:      {faster} is {ratio:.1f}x faster')

    if yd_r.chrome_rss_peak and zd_r.chrome_rss_peak:
        lighter = 'yd' if yd_r.chrome_rss_peak < zd_r.chrome_rss_peak else 'zd'
        diff = abs(yd_r.chrome_rss_peak - zd_r.chrome_rss_peak)
        print(f'    Chrome RSS:      {lighter} uses {diff:.0f} MB less')

    if yd_r.mem_efficiency and zd_r.mem_efficiency:
        better = 'yd' if yd_r.mem_efficiency < zd_r.mem_efficiency else 'zd'
        ratio = max(yd_r.mem_efficiency, zd_r.mem_efficiency) / min(yd_r.mem_efficiency, zd_r.mem_efficiency)
        print(f'    Mem efficiency:  {better} is {ratio:.1f}x better (MB/100K chars)')


# ── Main ─────────────────────────────────────────────────────────────────


async def main() -> None:
    """Parse args, run benchmarks, and print results."""
    parser = argparse.ArgumentParser(description='Benchmark yd vs zendriver')
    parser.add_argument('--url', default=URL, help='Target URL')
    parser.add_argument('--runs', type=int, default=2, help='Sequential fetch runs per engine')
    parser.add_argument('--parallel', type=int, default=2, help='Parallel tab count')
    parser.add_argument('--yd-only', action='store_true', help='Only run yd benchmarks')
    parser.add_argument('--zd-only', action='store_true', help='Only run zendriver benchmark')
    parser.add_argument(
        '--mode',
        choices=['full', 'balanced', 'lite', 'all'],
        default='all',
        help='yd performance mode (default: all three)',
    )
    parser.add_argument('--headless', action='store_true', help='Run browsers in headless mode')
    args = parser.parse_args()

    print(f'URL:      {args.url}')
    print(f'Runs:     {args.runs} sequential + {args.parallel} parallel')
    print(f'System:   {psutil.virtual_memory().total / 1024**3:.1f} GB RAM, {psutil.cpu_count()} CPUs')
    print()

    baseline_chrome = _all_chrome_rss_mb()
    if baseline_chrome > 0:
        print(f'Note: {baseline_chrome:.0f} MB of existing Chrome processes detected\n')

    yd_modes = ['full', 'balanced', 'lite'] if args.mode == 'all' else [args.mode]
    yd_results: list[Result] = []
    zd_result: Result | None = None

    # ── yd benchmarks ─────────────────────────────────────────────
    if not args.zd_only:
        for mode in yd_modes:
            print(f'─── yd/{mode} ─────────────────────────────────────────')
            result = await bench_yd(args.url, args.runs, args.parallel, mode, headless=args.headless)
            yd_results.append(result)
            gc.collect()

    # ── zendriver benchmark ───────────────────────────────────────
    if not args.yd_only:
        print('\n─── zendriver (Python, polling) ────────────────────────')
        zd_result = await bench_zd(args.url, args.runs, args.parallel, headless=args.headless)

    # ── Results ───────────────────────────────────────────────────
    for r in yd_results:
        print(r.summary())
    if zd_result:
        print(zd_result.summary())

    # ── Head-to-head comparisons ──────────────────────────────────
    if yd_results and zd_result:
        print(f'\n{"=" * 60}')
        print('  HEAD-TO-HEAD')
        print('=' * 60)
        for r in yd_results:
            print(f'\n  {r.name}')
            _print_comparison(r, zd_result)

    print()


if __name__ == '__main__':
    asyncio.run(main())
