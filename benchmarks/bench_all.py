"""Benchmark: yd vs Playwright vs Puppeteer vs zendriver vs nodriver.

Measures per engine:
  - Cold start latency (browser launch -> first page ready)
  - Single-page fetch latency (navigate + wait)
  - Parallel fetch throughput (N concurrent tabs)
  - Chrome RSS during sequential vs parallel phases
  - Memory efficiency (MB per 100K chars of fetched content)

yd uses fully event-driven CDP lifecycle events (zero sleeps, zero polling).
Other engines use their native wait strategies for a fair comparison.

Run:
  uv run python benchmarks/bench_all.py
  uv run python benchmarks/bench_all.py --runs 3 --parallel 3
  uv run python benchmarks/bench_all.py --engines yd,playwright
  uv run python benchmarks/bench_all.py --yd-mode balanced --headless
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import json
import os
import statistics
import sys
import time
from pathlib import Path

import psutil

URL = 'https://en.wikipedia.org/wiki/Web_scraping'

MIN_CONTENT_LEN = 10_000

ALL_ENGINES = ['yd', 'yd-docker', 'playwright', 'puppeteer', 'zendriver', 'nodriver']


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
        lines.append(f'  Cold start (launch -> ready):  {self.cold_start:.2f}s')
        if self.single_fetches:
            avg = statistics.mean(self.single_fetches)
            std = statistics.stdev(self.single_fetches) if len(self.single_fetches) > 1 else 0
            lines.append(f'  Single fetch latency:         {avg:.2f}s +/- {std:.2f}s  (n={len(self.single_fetches)})')
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
    label = f'yd {mode} ({vp.width}x{vp.height}, {cfg.effective_browsers}b x {cfg.effective_tabs_per_browser}t)'
    r = Result(label)
    gc.collect()
    py_rss_before = _rss_mb()

    t0 = time.perf_counter()
    pool_ctx = await yd.pool(cfg)
    pool = await pool_ctx.__aenter__()
    r.cold_start = time.perf_counter() - t0

    async def _yd_fetch(pool_ref: object) -> tuple[int, float, bool, str]:
        """Event-driven fetch. Zero sleeps, zero polling."""
        t = time.perf_counter()
        async with await pool_ref.acquire() as tab:  # type: ignore[union-attr]
            event = await tab.goto(url, timeout=30.0)
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


# ── Playwright benchmark ────────────────────────────────────────────────


async def bench_playwright(url: str, runs: int, parallel: int, *, headless: bool = False) -> Result:
    """Run Playwright benchmark with networkidle wait strategy."""
    from playwright.async_api import async_playwright

    r = Result('playwright (Python)')
    gc.collect()
    py_rss_before = _rss_mb()

    t0 = time.perf_counter()
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=headless)
    context = await browser.new_context()
    r.cold_start = time.perf_counter() - t0

    async def _pw_fetch() -> tuple[int, float, bool]:
        t = time.perf_counter()
        page = await context.new_page()
        await page.goto(url, wait_until='networkidle', timeout=30000)
        html = await page.content()
        await page.close()
        elapsed = time.perf_counter() - t
        length = len(html)
        blocked = 'Access Denied' in html or length < MIN_CONTENT_LEN
        return length, elapsed, blocked

    try:
        for i in range(runs):
            length, elapsed, blocked = await _pw_fetch()
            r.single_fetches.append(elapsed)
            r.html_lengths.append(length)
            if blocked:
                r.blocked += 1
            r.seq_chrome_rss_peak = max(r.seq_chrome_rss_peak, _all_chrome_rss_mb())
            status = 'BLOCKED' if blocked else f'{length:,} chars'
            print(f'  playwright [{i + 1}/{runs}]: {elapsed:.2f}s  {status}')

        if parallel > 1:
            print(f'  playwright parallel [{parallel} tabs]...')
            t2 = time.perf_counter()
            results = await asyncio.gather(*[_pw_fetch() for _ in range(parallel)])
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
        await context.close()
        await browser.close()
        await pw.stop()

    r.python_rss_delta = _rss_mb() - py_rss_before
    return r


# ── Puppeteer benchmark (via subprocess) ────────────────────────────────


async def bench_puppeteer(url: str, runs: int, parallel: int, *, headless: bool = False) -> Result:
    """Run Puppeteer benchmark via Node.js subprocess."""
    script = Path(__file__).parent / 'bench_puppeteer.mjs'
    cmd = ['node', str(script), url, str(runs), str(parallel)]
    if headless:
        cmd.append('--headless')

    r = Result('puppeteer (Node.js)')
    gc.collect()
    py_rss_before = _rss_mb()

    t0 = time.perf_counter()
    # Measure Chrome RSS externally since Puppeteer runs in a subprocess
    chrome_rss_before = _all_chrome_rss_mb()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()

    total_time = time.perf_counter() - t0

    # Print stderr (progress lines) to our stderr
    if stderr_bytes:
        sys.stderr.buffer.write(stderr_bytes)
        sys.stderr.buffer.flush()
        # Also print to stdout for consistency
        for line in stderr_bytes.decode().strip().splitlines():
            print(line)

    if proc.returncode != 0:
        print(f'  puppeteer FAILED (exit code {proc.returncode})')
        r.cold_start = total_time
        return r

    # Parse JSON result
    data = json.loads(stdout_bytes.decode().strip())
    r.cold_start = data['cold_start']
    r.single_fetches = data['single_fetches']
    r.parallel_time = data.get('parallel_time', 0)
    r.parallel_count = data.get('parallel_count', 0)
    r.html_lengths = data['html_lengths']
    r.blocked = data.get('blocked', 0)

    # Chrome RSS was measured from Python side during the subprocess run
    r.seq_chrome_rss_peak = max(_all_chrome_rss_mb() - chrome_rss_before, 0)
    r.python_rss_delta = _rss_mb() - py_rss_before
    return r


# ── Zendriver benchmark ─────────────────────────────────────────────────


async def bench_zendriver(url: str, runs: int, parallel: int, *, headless: bool = False) -> Result:
    """Run zendriver benchmark: native polling-based DOM stability waits."""
    import zendriver as zd

    r = Result('zendriver (Python)')
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
            print(f'  zendriver [{i + 1}/{runs}]: {elapsed:.2f}s  {status}')

        if parallel > 1:
            print(f'  zendriver parallel [{parallel} tabs]...')
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


# ── Nodriver benchmark ──────────────────────────────────────────────────


async def bench_nodriver(url: str, runs: int, parallel: int, *, headless: bool = False) -> Result:
    """Run nodriver benchmark: same approach as zendriver (it's the upstream)."""
    import nodriver as nd

    r = Result('nodriver (Python)')
    gc.collect()
    py_rss_before = _rss_mb()

    t0 = time.perf_counter()
    browser = await nd.start(headless=headless)
    r.cold_start = time.perf_counter() - t0

    async def _nd_fetch(tab_url: str) -> tuple[int, float, bool]:
        t = time.perf_counter()
        tab = await browser.get(tab_url, new_tab=True)
        # nodriver doesn't have wait_for_ready_state; use wait + polling
        await tab.wait(2)
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
            length, elapsed, blocked = await _nd_fetch(url)
            r.single_fetches.append(elapsed)
            r.html_lengths.append(length)
            if blocked:
                r.blocked += 1
            r.seq_chrome_rss_peak = max(r.seq_chrome_rss_peak, _all_chrome_rss_mb())
            status = 'BLOCKED' if blocked else f'{length:,} chars'
            print(f'  nodriver [{i + 1}/{runs}]: {elapsed:.2f}s  {status}')

        if parallel > 1:
            print(f'  nodriver parallel [{parallel} tabs]...')
            t2 = time.perf_counter()
            results = await asyncio.gather(*[_nd_fetch(url) for _ in range(parallel)])
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


# ── YD Docker headful benchmark ──────────────────────────────────────────


async def _docker_compose_up(compose_file: str, profile: str) -> None:
    """Start docker compose and wait for Chrome to be ready."""
    proc = await asyncio.create_subprocess_exec(
        'docker',
        'compose',
        '-f',
        compose_file,
        '--profile',
        profile,
        'up',
        '-d',
        '--build',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f'docker compose up failed: {stderr.decode()}')


async def _docker_compose_down(compose_file: str, profile: str) -> None:
    """Tear down the docker compose stack."""
    proc = await asyncio.create_subprocess_exec(
        'docker',
        'compose',
        '-f',
        compose_file,
        '--profile',
        profile,
        'down',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


async def _wait_for_chrome_in_docker(ws_urls: list[str], timeout: float = 60) -> None:
    """Poll Chrome CDP endpoints inside docker until they respond."""
    deadline = time.time() + timeout
    for ws_url in ws_urls:
        version_url = f'{ws_url}/json/version'
        while time.time() < deadline:
            try:
                proc = await asyncio.create_subprocess_exec(
                    'curl',
                    '-sf',
                    version_url,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                ret = await proc.wait()
                if ret == 0:
                    break
            except OSError:
                pass
            await asyncio.sleep(0.5)
        else:
            raise TimeoutError(f'Chrome at {ws_url} not ready after {timeout}s')


def _detect_gpu_profile() -> str:
    """Auto-detect the GPU profile matching run-headful.sh logic."""
    render_node = Path('/sys/class/drm/renderD128/device/driver')
    if render_node.exists():
        driver = render_node.resolve().name
        if driver == 'amdgpu':
            return 'amd'
        if driver in ('i915', 'xe'):
            return 'intel'
        if driver == 'nvidia':
            return 'nvidia'
    if Path('/dev/nvidia0').exists():
        return 'nvidia'
    return 'cpu'


async def bench_yd_docker(
    url: str,
    runs: int,
    parallel: int,
    *,
    headless: bool = False,
) -> Result:
    """Run yd benchmark against Chrome running headful inside Docker with GPU + Sway + VNC."""
    import yosoi_driver

    compose_file = str(Path(__file__).parent.parent / 'docker' / 'docker-compose.headful.yml')
    gpu_profile = _detect_gpu_profile()
    label = f'yd docker-headful ({gpu_profile} GPU, sway+wayvnc)'

    r = Result(label)
    gc.collect()
    py_rss_before = _rss_mb()

    # Start Docker container
    t0 = time.perf_counter()
    print(f'  Starting Docker container (profile={gpu_profile})...')
    await _docker_compose_up(compose_file, gpu_profile)

    ws_urls = ['http://localhost:19222', 'http://localhost:19223']
    await _wait_for_chrome_in_docker(ws_urls)
    r.cold_start = time.perf_counter() - t0
    print(f'  Docker container ready in {r.cold_start:.2f}s')

    # Connect yd pool to the Docker Chrome instances
    os.environ['CHROME_WS_URLS'] = ','.join(ws_urls)
    os.environ['TABS_PER_BROWSER'] = str(max(parallel, 2))

    pool_cls = yosoi_driver.BrowserPool
    pool_ctx = await pool_cls.from_env()
    pool = await pool_ctx.__aenter__()

    async def _fetch(pool_ref: object) -> tuple[int, float, bool, str]:
        t = time.perf_counter()
        async with await pool_ref.acquire() as tab:  # type: ignore[union-attr]
            event = await tab.goto(url, timeout=30.0)
            html = await tab.content()
        elapsed = time.perf_counter() - t
        blocked = not event or 'Access Denied' in html or len(html) < MIN_CONTENT_LEN
        return len(html), elapsed, blocked, event or 'timeout'

    try:
        for i in range(runs):
            length, elapsed, blocked, event = await _fetch(pool)
            r.single_fetches.append(elapsed)
            r.html_lengths.append(length)
            r.wait_events.append(event)
            if blocked:
                r.blocked += 1
            r.seq_chrome_rss_peak = max(r.seq_chrome_rss_peak, _all_chrome_rss_mb())
            status = 'BLOCKED' if blocked else f'{length:,} chars'
            print(f'  yd-docker [{i + 1}/{runs}]: {elapsed:.2f}s  {status}  ({event})')

        if parallel > 1:
            print(f'  yd-docker parallel [{parallel} tabs]...')
            t2 = time.perf_counter()
            results = await asyncio.gather(*[_fetch(pool) for _ in range(parallel)])
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
        # Clean env vars
        os.environ.pop('CHROME_WS_URLS', None)
        os.environ.pop('TABS_PER_BROWSER', None)
        # Tear down Docker
        print('  Tearing down Docker container...')
        await _docker_compose_down(compose_file, gpu_profile)

    r.python_rss_delta = _rss_mb() - py_rss_before
    return r


# ── Comparison ───────────────────────────────────────────────────────────


def _print_comparison(yd_r: Result, other: Result) -> None:
    """Print head-to-head comparison between yd and another engine."""
    print(f'\n  vs {other.name}:')

    yd_avg = statistics.mean(yd_r.single_fetches) if yd_r.single_fetches else 0
    other_avg = statistics.mean(other.single_fetches) if other.single_fetches else 0
    if yd_avg and other_avg:
        faster = 'yd' if yd_avg < other_avg else other.name.split()[0]
        ratio = max(yd_avg, other_avg) / min(yd_avg, other_avg)
        print(f'    Single fetch:    {faster} is {ratio:.1f}x faster')

    if yd_r.parallel_time and other.parallel_time:
        faster = 'yd' if yd_r.parallel_time < other.parallel_time else other.name.split()[0]
        ratio = max(yd_r.parallel_time, other.parallel_time) / min(yd_r.parallel_time, other.parallel_time)
        print(f'    Parallel fetch:  {faster} is {ratio:.1f}x faster')

    if yd_r.cold_start and other.cold_start:
        faster = 'yd' if yd_r.cold_start < other.cold_start else other.name.split()[0]
        ratio = max(yd_r.cold_start, other.cold_start) / min(yd_r.cold_start, other.cold_start)
        print(f'    Cold start:      {faster} is {ratio:.1f}x faster')

    if yd_r.chrome_rss_peak and other.chrome_rss_peak:
        lighter = 'yd' if yd_r.chrome_rss_peak < other.chrome_rss_peak else other.name.split()[0]
        diff = abs(yd_r.chrome_rss_peak - other.chrome_rss_peak)
        print(f'    Chrome RSS:      {lighter} uses {diff:.0f} MB less')


# ── Main ─────────────────────────────────────────────────────────────────


async def _run_engines(
    engines: list[str],
    args: argparse.Namespace,
) -> tuple[list[Result], list[Result]]:
    """Execute each requested engine benchmark and return (all_results, yd_results)."""
    all_results: list[Result] = []
    yd_results: list[Result] = []

    if 'yd' in engines:
        yd_modes = ['full', 'balanced', 'lite'] if args.yd_mode == 'all' else [args.yd_mode]
        for mode in yd_modes:
            print(f'--- yd/{mode} {"─" * 45}')
            result = await bench_yd(args.url, args.runs, args.parallel, mode, headless=args.headless)
            yd_results.append(result)
            all_results.append(result)
            gc.collect()
            await asyncio.sleep(1)

    if 'yd-docker' in engines:
        print(f'\n--- yd-docker {"─" * 43}')
        result = await bench_yd_docker(args.url, args.runs, args.parallel, headless=args.headless)
        yd_results.append(result)
        all_results.append(result)
        gc.collect()
        await asyncio.sleep(1)

    if 'playwright' in engines:
        print(f'\n--- playwright {"─" * 42}')
        result = await bench_playwright(args.url, args.runs, args.parallel, headless=args.headless)
        all_results.append(result)
        gc.collect()
        await asyncio.sleep(1)

    if 'puppeteer' in engines:
        print(f'\n--- puppeteer {"─" * 43}')
        result = await bench_puppeteer(args.url, args.runs, args.parallel, headless=args.headless)
        all_results.append(result)
        gc.collect()
        await asyncio.sleep(1)

    if 'zendriver' in engines:
        print(f'\n--- zendriver {"─" * 43}')
        result = await bench_zendriver(args.url, args.runs, args.parallel, headless=args.headless)
        all_results.append(result)
        gc.collect()
        await asyncio.sleep(1)

    if 'nodriver' in engines:
        print(f'\n--- nodriver {"─" * 44}')
        result = await bench_nodriver(args.url, args.runs, args.parallel, headless=args.headless)
        all_results.append(result)
        gc.collect()

    return all_results, yd_results


async def main() -> None:
    """Parse args, run benchmarks, and print results."""
    parser = argparse.ArgumentParser(description='Benchmark yd vs all browser automation tools')
    parser.add_argument('--url', default=URL, help='Target URL')
    parser.add_argument('--runs', type=int, default=2, help='Sequential fetch runs per engine')
    parser.add_argument('--parallel', type=int, default=2, help='Parallel tab count')
    parser.add_argument(
        '--engines',
        default=','.join(ALL_ENGINES),
        help=f'Comma-separated engines to benchmark (default: {",".join(ALL_ENGINES)})',
    )
    parser.add_argument(
        '--yd-mode',
        choices=['full', 'balanced', 'lite', 'all'],
        default='balanced',
        help='yd performance mode (default: balanced)',
    )
    parser.add_argument('--headless', action='store_true', help='Run browsers in headless mode')
    args = parser.parse_args()

    engines = [e.strip() for e in args.engines.split(',')]

    print(f'URL:      {args.url}')
    print(f'Runs:     {args.runs} sequential + {args.parallel} parallel')
    print(f'Engines:  {", ".join(engines)}')
    print(f'System:   {psutil.virtual_memory().total / 1024**3:.1f} GB RAM, {psutil.cpu_count()} CPUs')
    print()

    baseline_chrome = _all_chrome_rss_mb()
    if baseline_chrome > 0:
        print(f'Note: {baseline_chrome:.0f} MB of existing Chrome processes detected\n')

    all_results, yd_results = await _run_engines(engines, args)

    # ── Results ───────────────────────────────────────────────────
    for r in all_results:
        print(r.summary())

    # ── Head-to-head: yd vs each other engine ─────────────────────
    others = [r for r in all_results if r not in yd_results]
    if yd_results and others:
        print(f'\n{"=" * 60}')
        print('  HEAD-TO-HEAD')
        print('=' * 60)
        for yd_r in yd_results:
            print(f'\n  {yd_r.name}')
            for other in others:
                _print_comparison(yd_r, other)

    print()


if __name__ == '__main__':
    asyncio.run(main())
