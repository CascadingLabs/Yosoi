"""voidcrawl memory capacity-planning harness (local spike).

Answers the question: *how many concurrent tabs can I cram onto a box with N GB
of RAM, and what specs do I need for a target throughput?*

Why this is not a CodSpeed benchmark
------------------------------------
CodSpeed measures CPU/walltime of the **Python** process. voidcrawl's memory
lives in two places CodSpeed cannot see:

1. **In-process (Python + Rust):** voidcrawl is a PyO3 extension (``_ext.*.so``),
   so the Rust ``BrowserPool`` overhead is part of the Python process RSS.
2. **Chrome process tree:** the actual renderers are separate OS child
   processes — this is where the memory bottleneck really is.

So we sample real resident memory with ``psutil`` across the whole process tree
and report the two pools separately. We use **PSS** (proportional set size), not
RSS: Chrome spawns many processes that share large read-only mappings, and
summing RSS double-counts those shared pages — PSS apportions them, giving the
true marginal footprint you must budget for on a server.

What it produces
----------------
Three estimates, each fit from a tab-count sweep, plus capacity/sizing tables:
* **base idle** — pool up, browser launched, no page (the floor for running voidcrawl).
* **L1 static** — light server-rendered catalog (DOM only).
* **L2 SPA** — JS-rendered proxy with a retained renderer heap (``--spa-heap-mb``).

Each profile runs in its OWN subprocess so one profile's in-process
accumulation/leak can't contaminate another's baseline. Metrics can be emitted
as ``--json`` in github-action-benchmark schema for CI time-series tracking.

Caveat (L2): the *synthetic* SPA heap does not reliably manifest as per-tab
renderer memory here (same-origin tabs share renderers; the probe's page
lifecycle frees it), so L2 tends to measure ≈ L1. For a trustworthy SPA number,
calibrate against a real app with ``--url`` (real SPAs hold 30-150 MB V8 heap
per tab). base idle and L1 are solid as measured.

Run it
------
    uv run python benchmarks/voidcrawl_memory_capacity.py                    # L1 + L2, default sweep
    uv run python benchmarks/voidcrawl_memory_capacity.py --sweep 1,2,4,8 --json metrics.json
    uv run python benchmarks/voidcrawl_memory_capacity.py --url https://real-spa.example  # calibrate L2
    uv run python benchmarks/voidcrawl_memory_capacity.py --headful          # measure headful cost

To attribute the *in-process* slice (Python interpreter vs Rust extension vs
otel/langfuse buffers — the post-teardown residue), run one profile under memray:

    uv run memray run -o vc.bin benchmarks/voidcrawl_memory_capacity.py --profile l1 --sweep 4
    uv run memray flamegraph vc.bin

Pages are generated locally (no network) unless ``--url`` is given.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil
import voidcrawl.scale as vscale
from rich.console import Console
from rich.table import Table

from tests.benchmarks.fixtures import build_catalog_html, build_spa_html
from yosoi.core.fetcher.voiddriver import HeadfulFetcher, HeadlessFetcher

console = Console()

# Headroom factor applied to free RAM before sizing — leaves slack for the OS,
# page cache, and transient spikes during navigation.
_HEADROOM = 0.80


# ── local page server ───────────────────────────────────────────────────────


def _serve_site(pages: dict[str, str]) -> tuple[ThreadingHTTPServer, dict[str, str]]:
    """Serve each {route: html} on an ephemeral localhost port. Returns (server, {route: url})."""
    bodies = {f'/{name}': html.encode('utf-8') for name, html in pages.items()}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = bodies.get(self.path.split('?')[0])
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:  # silence access logs
            return

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    addr = server.server_address
    host, port = str(addr[0]), addr[1]
    return server, {name: f'http://{host}:{port}/{name}' for name in pages}


# ── memory sampling ───────────────────────────────────────────────────────────


def _pss_mb(proc: psutil.Process) -> float:
    """PSS in MB for one process, falling back to RSS where PSS is unavailable."""
    try:
        info = proc.memory_full_info()
        val = getattr(info, 'pss', None)
        raw = info.rss if val is None else val
        return float(raw) / 1048576
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return 0.0


@dataclass
class MemSample:
    self_pss: float  # Python interpreter + in-process Rust pool
    chrome_pss: float  # sum of PSS across all Chrome child processes
    n_chrome: int

    @property
    def total(self) -> float:
        return self.self_pss + self.chrome_pss


def _sample(root: psutil.Process) -> MemSample:
    children = root.children(recursive=True)
    chrome = sum(_pss_mb(c) for c in children)
    return MemSample(self_pss=_pss_mb(root), chrome_pss=chrome, n_chrome=len(children))


class PeakSampler:
    """Background thread that tracks peak total PSS over a workload window."""

    def __init__(self, root: psutil.Process, interval: float = 0.25) -> None:
        self._root = root
        self._interval = interval
        self._stop = threading.Event()
        self._peak = MemSample(0.0, 0.0, 0)
        self._thread: threading.Thread | None = None

    def __enter__(self) -> PeakSampler:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            s = _sample(self._root)
            if s.total > self._peak.total:
                self._peak = s
            self._stop.wait(self._interval)

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def peak(self) -> MemSample:
        return self._peak


# ── per-concurrency measurement ───────────────────────────────────────────────


@dataclass
class LevelResult:
    n_tabs: int
    boot: MemSample  # right after pool enter, before any navigation (idle floor)
    idle: MemSample  # pool warm (1 fetch done), no active load
    peak: MemSample  # under N concurrent fetches
    teardown_self: float  # in-process PSS after pool close (leak check)
    n_chrome_peak: int


async def _measure_level(
    *,
    n_tabs: int,
    url: str,
    rounds: int,
    headful: bool,
    chrome_path: str | None,
) -> LevelResult:
    root = psutil.Process()
    fetcher_cls = HeadfulFetcher if headful else HeadlessFetcher
    fetcher = fetcher_cls(
        timeout=30,
        max_concurrent=n_tabs,
        no_sandbox=True,
        browser_executable_path=chrome_path,
    )

    async with fetcher:
        await asyncio.sleep(1.0)  # let the pool/browser process settle
        boot = _sample(root)  # pool up, no page loaded yet → idle floor

        # Warm: one fetch forces the pool to spin up its tabs/renderers.
        await fetcher.fetch(url)
        await asyncio.sleep(1.0)
        idle = _sample(root)

        with PeakSampler(root) as sampler:
            for _ in range(rounds):
                await asyncio.gather(*(fetcher.fetch(url) for _ in range(n_tabs)))
            await asyncio.sleep(0.5)  # let the sampler catch the tail
            peak = sampler.peak

    await asyncio.sleep(1.0)  # allow Chrome teardown to settle
    teardown = _sample(root)
    return LevelResult(
        n_tabs=n_tabs,
        boot=boot,
        idle=idle,
        peak=peak,
        teardown_self=teardown.self_pss,
        n_chrome_peak=peak.n_chrome,
    )


@dataclass
class ProfileModel:
    """Fitted memory model for one page profile (e.g. L1 static, L2 SPA)."""

    name: str
    results: list[LevelResult]
    chrome_slope: float  # MB per concurrent tab (clean concurrency signal)
    chrome_base: float  # MB chrome browser/GPU base at N→0
    inproc_base: float  # MB Python+Rust at rest
    boot_floor: float  # MB total PSS with pool up, no page (idle floor)
    inproc_growth: float  # MB in-process growth across the sweep
    leak: float  # MB still resident after pool teardown

    @property
    def base(self) -> float:
        return self.chrome_base + self.inproc_base

    @property
    def per_tab(self) -> float:
        return self.chrome_slope


def _build_model(name: str, results: list[LevelResult]) -> ProfileModel:
    chrome_slope, chrome_base = _fit([(r.n_tabs, r.peak.chrome_pss) for r in results])
    # In-process growth is confounded with total fetch count (rounds x N), so we
    # take only the at-rest intercept as the fixed cost, never a per-tab slope.
    _, inproc_base = _fit([(r.n_tabs, r.peak.self_pss) for r in results])
    boot_floor = min(r.boot.total for r in results)
    growth = max(r.peak.self_pss for r in results) - min(r.peak.self_pss for r in results)
    leak = max(r.teardown_self - r.boot.self_pss for r in results)
    return ProfileModel(
        name=name,
        results=results,
        chrome_slope=chrome_slope,
        chrome_base=chrome_base,
        inproc_base=inproc_base,
        boot_floor=boot_floor,
        inproc_growth=growth,
        leak=leak,
    )


# ── linear model + capacity ────────────────────────────────────────────────────


def _fit(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Ordinary least squares. Returns (slope per tab, intercept/base MB)."""
    n = len(points)
    if n < 2:
        return (points[0][1] if points else 0.0, 0.0)
    sx = sum(x for x, _ in points)
    sy = sum(y for _, y in points)
    sxx = sum(x * x for x, _ in points)
    sxy = sum(x * y for x, y in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return (0.0, sy / n)
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


# ── reporting ───────────────────────────────────────────────────────────────


def _print_profile_table(model: ProfileModel) -> None:
    table = Table(title=f'{model.name} — per concurrency (PSS)')
    table.add_column('tabs', justify='right')
    table.add_column('chrome procs', justify='right')
    table.add_column('in-proc (Py+Rust) MB', justify='right')
    table.add_column('chrome tree MB', justify='right')
    table.add_column('total MB', justify='right')
    table.add_column('MB / tab', justify='right')
    for r in model.results:
        per_tab = r.peak.chrome_pss / r.n_tabs if r.n_tabs else 0.0
        table.add_row(
            str(r.n_tabs),
            str(r.n_chrome_peak),
            f'{r.peak.self_pss:.0f}',
            f'{r.peak.chrome_pss:.0f}',
            f'{r.peak.total:.0f}',
            f'{per_tab:.0f}',
        )
    console.print(table)
    console.print(
        f'  model: chrome ≈ {model.chrome_base:.0f} MB + [bold]{model.per_tab:.0f} MB/tab[/bold]; '
        f'in-proc base ≈ {model.inproc_base:.0f} MB; '
        f'[yellow]post-teardown residue {model.leak:+.0f} MB[/yellow]\n'
    )


def _print_summary(models: list[ProfileModel], headful: bool) -> None:
    snap = vscale.detect_resources()
    usable = snap.effective_ram_mb * _HEADROOM
    # Idle floor is page-independent (measured before navigation) — take the min.
    idle_floor = min(m.boot_floor for m in models)
    mode = 'headful' if headful else 'headless'

    console.rule('[bold]THREE ESTIMATES (PSS, ' + mode + ')')
    console.print(
        f'  [bold]base idle[/bold]      ≈ [bold]{idle_floor:.0f} MB[/bold]  — pool up, browser launched, no page loaded'
    )
    for m in models:
        console.print(
            f'  [bold]{m.name:<12}[/bold] ≈ [bold]{m.per_tab:.0f} MB per concurrent tab[/bold] '
            f'(+ ~{m.base:.0f} MB fixed pool overhead)'
        )
    console.print(
        '\n[dim]base idle = the floor just for running voidcrawl. Per-tab is the marginal cost of one '
        'more concurrent fetch of that page type. SPA = renderer V8 heap dominates; static = light DOM only.[/dim]'
    )

    console.print()
    console.rule('[bold]capacity & sizing for THIS machine')
    console.print(
        f'  RAM: {snap.total_ram_mb} MB total, {snap.free_ram_mb} MB free, {snap.cpu_cores} cores; '
        f'usable @ {_HEADROOM:.0%} = {usable:.0f} MB'
    )
    rec = vscale.compute_scale('balanced', snapshot=snap)
    console.print(
        f'  voidcrawl.scale "balanced" oracle: {rec.browsers}×{rec.tabs_per_browser} = '
        f'[bold]{rec.total_tabs}[/bold] tabs (headless={rec.headless})\n'
    )

    cap = Table(title='max concurrent tabs in usable RAM (single pool)')
    cap.add_column('profile')
    cap.add_column('MB/tab', justify='right')
    cap.add_column('fixed MB', justify='right')
    cap.add_column('max tabs', justify='right')
    for m in models:
        max_tabs = max(0, int((usable - m.base) / m.per_tab)) if m.per_tab > 0 else 0
        cap.add_row(m.name, f'{m.per_tab:.0f}', f'{m.base:.0f}', f'[bold]{max_tabs}[/bold]')
    console.print(cap)

    sizing = Table(title='RAM needed (GB, incl. OS headroom) for a target tab count')
    sizing.add_column('target tabs', justify='right')
    for m in models:
        sizing.add_column(m.name, justify='right')
    for tabs in (50, 100, 250, 500, 1000):
        row = [str(tabs)]
        for m in models:
            ram_mb = m.base + m.per_tab * tabs
            row.append(f'{ram_mb / _HEADROOM / 1024:.1f}')
        sizing.add_row(*row)
    console.print(sizing)

    worst = max(models, key=lambda m: m.leak)
    console.print(
        f'\n[yellow]Note:[/yellow] in-process memory left {worst.leak:+.0f} MB resident after teardown '
        f'({worst.name}) — scales with work done, not concurrency (otel/langfuse spans, logs, or Rust '
        f'retention). Profile with memray and budget extra headroom for long-running rigs.\n'
        '[dim]SPA per-tab is tunable via --spa-heap-mb to match a real target you have profiled; '
        'pass --url to measure an actual live site.[/dim]'
    )


# ── entrypoint ────────────────────────────────────────────────────────────────


_PROFILE_NAMES = {'l1': 'L1 static', 'l2': 'L2 SPA', 'live': 'live'}


def _model_to_dict(m: ProfileModel) -> dict[str, object]:
    """Serialize a ProfileModel's scalar fields (results are not needed downstream)."""
    return {
        'name': m.name,
        'chrome_slope': m.chrome_slope,
        'chrome_base': m.chrome_base,
        'inproc_base': m.inproc_base,
        'boot_floor': m.boot_floor,
        'inproc_growth': m.inproc_growth,
        'leak': m.leak,
    }


def _float_from_metric(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    raise TypeError(f'expected numeric metric value, got {type(value).__name__}')


def _model_from_dict(d: dict[str, object]) -> ProfileModel:
    return ProfileModel(
        name=str(d['name']),
        results=[],
        chrome_slope=_float_from_metric(d['chrome_slope']),
        chrome_base=_float_from_metric(d['chrome_base']),
        inproc_base=_float_from_metric(d['inproc_base']),
        boot_floor=_float_from_metric(d['boot_floor']),
        inproc_growth=_float_from_metric(d['inproc_growth']),
        leak=_float_from_metric(d['leak']),
    )


def _emit_json(models: list[ProfileModel], headful: bool, path: str) -> None:
    """Write metrics in github-action-benchmark 'customSmallerIsBetter' schema.

    Each entry is {name, unit, value}; the action stores history on gh-pages,
    renders a chart per metric, and can comment/fail on regression. This is how
    the cross-process memory numbers get tracked over time in CI per release —
    CodSpeed only tracks the in-process CPU benchmarks, not Chrome RSS.
    """
    suffix = ' (headful)' if headful else ''
    entries: list[dict[str, object]] = []
    if models:
        entries.append(
            {'name': f'voidcrawl base idle{suffix}', 'unit': 'MB', 'value': round(min(m.boot_floor for m in models), 1)}
        )
    for m in models:
        entries.append({'name': f'voidcrawl {m.name} per-tab{suffix}', 'unit': 'MB/tab', 'value': round(m.per_tab, 1)})
        entries.append({'name': f'voidcrawl {m.name} fixed overhead{suffix}', 'unit': 'MB', 'value': round(m.base, 1)})
    if models:
        entries.append(
            {
                'name': f'voidcrawl post-teardown residue{suffix}',
                'unit': 'MB',
                'value': round(max(m.leak for m in models), 1),
            }
        )
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(entries, fh, indent=2)
    console.print(f'[dim]wrote {len(entries)} metrics → {path} (github-action-benchmark schema)[/dim]')


async def _run_profile(name: str, url: str, args: argparse.Namespace, sweep: list[int]) -> ProfileModel:
    console.rule(f'[bold]{name}  ({url})')
    results: list[LevelResult] = []
    for n in sweep:
        t0 = time.time()
        res = await _measure_level(
            n_tabs=n,
            url=url,
            rounds=args.rounds,
            headful=args.headful,
            chrome_path=args.chrome,
        )
        results.append(res)
        console.print(
            f'   {n:>3} tab(s): peak {res.peak.total:.0f} MB '
            f'({res.peak.chrome_pss:.0f} chrome / {res.peak.self_pss:.0f} in-proc), '
            f'boot {res.boot.total:.0f} MB, {res.n_chrome_peak} procs, {time.time() - t0:.0f}s'
        )
    model = _build_model(name, results)
    _print_profile_table(model)
    return model


async def _worker(args: argparse.Namespace) -> ProfileModel:
    """Measure ONE profile in this (fresh) process and return its model.

    Each profile runs in its own process so the in-process accumulation/leak from
    one profile never contaminates another's baseline (the bug that made a
    second profile's 'boot' and 'fixed overhead' wrong when both ran in-process).
    """
    sweep = [int(x) for x in args.sweep.split(',') if x.strip()]
    slug = args.profile
    server = None
    if slug == 'live':
        name, url = 'live', args.url
    else:
        page = (
            build_catalog_html(args.page_items) if slug == 'l1' else build_spa_html(args.page_items, args.spa_heap_mb)
        )
        server, urls = _serve_site({slug: page})
        url, name = urls[slug], _PROFILE_NAMES[slug]
    try:
        return await _run_profile(name, url, args, sweep)
    finally:
        if server is not None:
            server.shutdown()


def _orchestrate(args: argparse.Namespace) -> None:
    """Run each profile in an isolated subprocess, then aggregate + report."""
    slugs = ['l1', 'l2'] + (['live'] if args.url else [])
    console.print(
        f'[dim]Profiles: {", ".join(_PROFILE_NAMES[s] for s in slugs)} '
        f'(each in its own process); {args.page_items} items, ~{args.spa_heap_mb} MB SPA heap; '
        f'sweep={args.sweep}, rounds={args.rounds}, {"headful" if args.headful else "headless"}[/dim]\n'
    )
    models: list[ProfileModel] = []
    for slug in slugs:
        with tempfile.NamedTemporaryFile('r', suffix='.json', delete=False) as tmp:
            model_out = tmp.name
        cmd = [
            sys.executable,
            __file__,
            '--profile',
            slug,
            '--sweep',
            args.sweep,
            '--rounds',
            str(args.rounds),
            '--page-items',
            str(args.page_items),
            '--spa-heap-mb',
            str(args.spa_heap_mb),
            '--chrome',
            args.chrome,
            '--model-out',
            model_out,
        ]
        if args.headful:
            cmd.append('--headful')
        if slug == 'live' and args.url:
            cmd += ['--url', args.url]
        subprocess.run(cmd, check=True)  # fixed argv, no shell
        with open(model_out, encoding='utf-8') as fh:
            models.append(_model_from_dict(json.load(fh)))

    if models:
        console.print()
        _print_summary(models, args.headful)
        if args.json:
            _emit_json(models, args.headful, args.json)


def main() -> None:
    parser = argparse.ArgumentParser(description='voidcrawl memory capacity planning')
    parser.add_argument('--sweep', default='1,4,8', help='comma-separated tab counts to measure')
    parser.add_argument('--rounds', type=int, default=2, help='concurrent fetch rounds per level')
    parser.add_argument('--page-items', type=int, default=150, help='catalog items per page (L1 + L2)')
    parser.add_argument('--spa-heap-mb', type=int, default=25, help='retained JS heap (MB) for the L2 SPA proxy')
    parser.add_argument('--headful', action='store_true', help='measure headful Chrome instead of headless')
    parser.add_argument('--chrome', default='/usr/bin/chromium', help='chrome/chromium executable path')
    parser.add_argument('--url', default=None, help='optional live URL to measure as a third "live" profile')
    parser.add_argument('--json', default=None, help='write metrics JSON (github-action-benchmark schema) to this path')
    # Internal: single-profile worker mode (one isolated process per profile).
    parser.add_argument('--profile', default=None, choices=['l1', 'l2', 'live'], help=argparse.SUPPRESS)
    parser.add_argument('--model-out', default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.profile:
        model = asyncio.run(_worker(args))
        if args.model_out:
            with open(args.model_out, 'w', encoding='utf-8') as fh:
                json.dump(_model_to_dict(model), fh)
    else:
        _orchestrate(args)


if __name__ == '__main__':
    main()
