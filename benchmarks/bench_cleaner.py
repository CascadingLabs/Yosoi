"""Benchmark the HTMLCleaner pass pipeline.

Usage:
    uv run python benchmarks/bench_cleaner.py           # run + compare to baseline
    uv run python benchmarks/bench_cleaner.py --save     # save current run as baseline
    uv run poe bench                                     # same as above (via poe)

Generates fixtures if missing, then runs the cleaner with and without budget,
reporting size reduction, estimated tokens, wall-clock time, and per-pass costs.

Also dumps per-pass intermediate HTML into benchmarks/output/ so you can
eyeball what each stage does to the markup.
"""

import inspect
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path

from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table

from yosoi.core.cleaning.cleaner import HTMLCleaner
from yosoi.core.cleaning.passes.budget import enforce_budget, estimate_tokens
from yosoi.core.cleaning.passes.classes import strip_utility_classes
from yosoi.core.cleaning.passes.compress import compress_html
from yosoi.core.cleaning.passes.content import extract_content
from yosoi.core.cleaning.passes.dedup import deduplicate_siblings
from yosoi.core.cleaning.passes.density import prune_by_density
from yosoi.core.cleaning.passes.flatten import flatten_wrappers
from yosoi.core.cleaning.passes.noise import remove_noise
from yosoi.core.cleaning.whitespace import collapse_whitespace

FIXTURES_DIR = Path(__file__).parent / 'fixtures'
OUTPUT_DIR = Path(__file__).parent / 'output'
BASELINE_PATH = Path(__file__).parent / 'baseline.json'
WARMUP_RUNS = 2
BENCH_RUNS = 10

# Pull default budget from the cleaner so we stay in sync
_DEFAULT_BUDGET = int(inspect.signature(HTMLCleaner.__init__).parameters['token_budget'].default)

# Ordered pass pipeline — matches HTMLCleaner.clean_html
PASSES: list[tuple[str, str]] = [
    ('0_raw', 'Raw HTML (no processing)'),
    ('1_noise', 'After noise removal (scripts, styles, nav, sidebar, ads)'),
    ('2_content', 'After content extraction (main/body region)'),
    ('3_flatten', 'After flattening wrapper divs/spans'),
    ('4_compress', 'After compression (attrs, comments, hidden, non-semantic)'),
    ('5_classes', 'After utility class stripping (Tailwind/Bootstrap)'),
    ('6_dedup', 'After sibling deduplication'),
    ('7_density', 'After density pruning'),
    ('8_whitespace', 'After whitespace collapse'),
    ('9_budget', f'After token budget enforcement ({_DEFAULT_BUDGET:,})'),
]


def _load_fixtures() -> dict[str, str]:
    """Load all .html fixture files from the fixtures directory."""
    fixtures: dict[str, str] = {}
    for path in sorted(FIXTURES_DIR.glob('*.html')):
        fixtures[path.stem] = path.read_text(encoding='utf-8')
    if not fixtures:
        from benchmarks.fixtures.generate import generate_all

        generate_all()
        for path in sorted(FIXTURES_DIR.glob('*.html')):
            fixtures[path.stem] = path.read_text(encoding='utf-8')
    return fixtures


def _time_pass(fn: Callable[[], None]) -> float:
    """Time a single pass invocation, returning elapsed ms."""
    start = time.perf_counter_ns()
    fn()
    return (time.perf_counter_ns() - start) / 1_000_000


def _run_passes(html: str) -> tuple[dict[str, str], dict[str, float]]:
    """Run each pass individually and capture intermediate output + per-pass timing."""
    stages: dict[str, str] = {}
    timings: dict[str, float] = {}

    # 0 — raw
    stages['0_raw'] = html
    timings['0_raw'] = 0.0

    # 1 — noise removal
    soup = BeautifulSoup(html, 'lxml')
    timings['1_noise'] = _time_pass(lambda: remove_noise(soup))
    stages['1_noise'] = str(soup)

    # 2 — content extraction
    content_soup = soup  # will be reassigned

    def _extract() -> None:
        nonlocal content_soup
        content_soup, _ = extract_content(soup)

    timings['2_content'] = _time_pass(_extract)
    stages['2_content'] = str(content_soup)

    # 3 — flatten
    timings['3_flatten'] = _time_pass(lambda: flatten_wrappers(content_soup))
    stages['3_flatten'] = str(content_soup)

    # 4 — compress
    timings['4_compress'] = _time_pass(lambda: compress_html(content_soup))
    stages['4_compress'] = str(content_soup)

    # 5 — class stripping
    timings['5_classes'] = _time_pass(lambda: strip_utility_classes(content_soup))
    stages['5_classes'] = str(content_soup)

    # 6 — sibling dedup
    timings['6_dedup'] = _time_pass(lambda: deduplicate_siblings(content_soup))
    stages['6_dedup'] = str(content_soup)

    # 7 — density pruning
    timings['7_density'] = _time_pass(lambda: prune_by_density(content_soup))
    stages['7_density'] = str(content_soup)

    # 8 — whitespace collapse
    content_str = ''

    def _whitespace() -> None:
        nonlocal content_str
        content_str = collapse_whitespace(str(content_soup))

    timings['8_whitespace'] = _time_pass(_whitespace)
    stages['8_whitespace'] = content_str

    # 9 — budget enforcement
    budget_result = ''

    def _budget() -> None:
        nonlocal budget_result
        budget_result = enforce_budget(content_str, _DEFAULT_BUDGET)

    timings['9_budget'] = _time_pass(_budget)
    stages['9_budget'] = budget_result

    return stages, timings


def _dump_pass_outputs(name: str, stages: dict[str, str], pass_timings: dict[str, float]) -> Path:
    """Write each pass stage to benchmarks/output/<fixture>/ for visual inspection."""
    fixture_dir = OUTPUT_DIR / name
    fixture_dir.mkdir(parents=True, exist_ok=True)

    for stage_key, html in stages.items():
        path = fixture_dir / f'{stage_key}.html'
        path.write_text(html, encoding='utf-8')

    # Write a summary file with sizes and per-pass timing
    summary_lines = [f'Pass pipeline for: {name}', '=' * 80, '']
    for stage_key, description in PASSES:
        html = stages.get(stage_key, '')
        chars = len(html)
        tokens = estimate_tokens(html)
        ms = pass_timings.get(stage_key, 0.0)
        summary_lines.append(f'{stage_key:<16} {chars:>8,} chars  ~{tokens:>6,} tokens  {ms:>7.1f}ms  | {description}')
    summary_lines.append('')
    raw = len(stages.get('0_raw', ''))
    final = len(stages.get('9_budget', ''))
    if raw > 0:
        summary_lines.append(f'Total compression: {raw:,} → {final:,} chars ({(1 - final / raw) * 100:.0f}% reduction)')
    total_ms = sum(pass_timings.values())
    summary_lines.append(f'Total pass time:   {total_ms:.1f}ms')
    (fixture_dir / 'SUMMARY.txt').write_text('\n'.join(summary_lines), encoding='utf-8')
    return fixture_dir


def _bench_cleaner(html: str, cleaner: HTMLCleaner) -> tuple[str, list[float]]:
    """Run cleaner multiple times and collect timings."""
    for _ in range(WARMUP_RUNS):
        cleaner.clean_html(html)

    timings: list[float] = []
    result = ''
    for _ in range(BENCH_RUNS):
        start = time.perf_counter_ns()
        result = cleaner.clean_html(html)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        timings.append(elapsed_ms)
    return result, timings


def _load_baseline() -> dict[str, dict[str, float]] | None:
    """Load baseline results if they exist."""
    if not BASELINE_PATH.exists():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding='utf-8'))


def _save_baseline(results: dict[str, dict[str, float]]) -> None:
    """Save current results as the baseline."""
    BASELINE_PATH.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')


def _print_pass_timing_table(
    console: Console,
    fixtures: dict[str, str],
    all_pass_timings: dict[str, dict[str, float]],
) -> None:
    """Print a table showing per-pass timing breakdown for each fixture."""
    pass_table = Table(title='Per-Pass Timing (ms)', expand=True)
    pass_table.add_column('Pass', style='cyan')
    for name in fixtures:
        pass_table.add_column(name, justify='right', style='yellow')

    for stage_key, _description in PASSES:
        row = [stage_key]
        for name in fixtures:
            ms = all_pass_timings.get(name, {}).get(stage_key, 0.0)
            row.append(f'{ms:.1f}')
        pass_table.add_row(*row)

    total_row: list[str] = ['[bold]TOTAL[/bold]']
    for name in fixtures:
        total = sum(all_pass_timings.get(name, {}).values())
        total_row.append(f'[bold]{total:.1f}[/bold]')
    pass_table.add_row(*total_row)
    console.print(pass_table)


def _run_e2e_benchmark(console: Console, fixtures: dict[str, str]) -> dict[str, dict[str, float]]:
    """Run end-to-end cleaner benchmarks and print results table."""
    cleaner_full = HTMLCleaner(console=Console(quiet=True), token_budget=_DEFAULT_BUDGET)
    cleaner_no_budget = HTMLCleaner(console=Console(quiet=True), token_budget=0)
    budget_k = _DEFAULT_BUDGET // 1000

    table = Table(title='Cleaner Benchmark Results', expand=True)
    table.add_column('Fixture', style='cyan', ratio=2)
    table.add_column('Raw', justify='right', style='dim')
    table.add_column('Cleaned\n(no budget)', justify='right')
    table.add_column(f'Cleaned\n({budget_k}k budget)', justify='right')
    table.add_column('Compression', justify='right', style='green')
    table.add_column('Est. Tokens\n(no budget)', justify='right')
    table.add_column(f'Est. Tokens\n({budget_k}k budget)', justify='right')
    table.add_column('Median ms\n(no budget)', justify='right', style='yellow')
    table.add_column(f'Median ms\n({budget_k}k budget)', justify='right', style='yellow')

    current_results: dict[str, dict[str, float]] = {}

    for name, html in fixtures.items():
        raw_size = len(html)
        result_no_budget, timings_no_budget = _bench_cleaner(html, cleaner_no_budget)
        result_full, timings_full = _bench_cleaner(html, cleaner_full)

        cleaned_size_nb = len(result_no_budget)
        cleaned_size_full = len(result_full)
        tokens_nb = estimate_tokens(result_no_budget)
        tokens_full = estimate_tokens(result_full)
        compression = (1 - cleaned_size_nb / raw_size) * 100 if raw_size > 0 else 0
        median_ms_nb = statistics.median(timings_no_budget)
        median_ms_full = statistics.median(timings_full)

        current_results[name] = {
            'median_ms_no_budget': median_ms_nb,
            'median_ms_full': median_ms_full,
            'compression_pct': compression,
            'tokens_no_budget': tokens_nb,
            'tokens_full': tokens_full,
        }

        table.add_row(
            name,
            f'{raw_size:,}',
            f'{cleaned_size_nb:,}',
            f'{cleaned_size_full:,}',
            f'{compression:.0f}%',
            f'{tokens_nb:,}',
            f'{tokens_full:,}',
            f'{median_ms_nb:.1f}',
            f'{median_ms_full:.1f}',
        )

    console.print(table)
    return current_results


def _compare_baseline(console: Console, current_results: dict[str, dict[str, float]]) -> None:
    """Compare current results against saved baseline and print regression report."""
    baseline = _load_baseline()
    if not baseline:
        console.print('\n[dim]No baseline found. Run with --save to create one.[/dim]')
        return

    console.print('\n[bold]Regression check vs baseline:[/bold]')
    any_regression = False
    for name, current in current_results.items():
        if name not in baseline:
            console.print(f'  [dim]{name}: no baseline (new fixture)[/dim]')
            continue
        base = baseline[name]
        ms_change = current['median_ms_full'] - base['median_ms_full']
        pct_change = (ms_change / base['median_ms_full'] * 100) if base['median_ms_full'] > 0 else 0
        token_change = current['tokens_full'] - base['tokens_full']

        if pct_change > 20:
            console.print(f'  [bold red]{name}: {ms_change:+.1f}ms ({pct_change:+.0f}%) REGRESSION[/bold red]')
            any_regression = True
        elif pct_change < -10:
            console.print(f'  [bold green]{name}: {ms_change:+.1f}ms ({pct_change:+.0f}%) faster[/bold green]')
        else:
            console.print(f'  [dim]{name}: {ms_change:+.1f}ms ({pct_change:+.0f}%) ~stable[/dim]')

        if token_change != 0:
            style = 'red' if token_change > 0 else 'green'
            console.print(f'    [{style}]tokens: {token_change:+,}[/{style}]')

    if any_regression:
        console.print('\n[bold red]Regressions detected! Run with --save to update baseline.[/bold red]')


def main() -> None:
    """Run the full benchmark suite: per-pass dumps, timing, and regression check."""
    import sys

    save_baseline = '--save' in sys.argv
    console = Console()
    fixtures = _load_fixtures()

    if not fixtures:
        console.print('[bold red]No fixtures found![/bold red]')
        return

    console.print(f'\n[bold]Benchmarking HTMLCleaner on {len(fixtures)} fixtures[/bold]')
    console.print(f'Warmup: {WARMUP_RUNS} runs, Bench: {BENCH_RUNS} runs each')
    console.print(f'Default token budget: {_DEFAULT_BUDGET:,}')
    console.print(f'Output dir: {OUTPUT_DIR}\n')

    # --- Dump per-pass outputs with timing ---
    console.print('[bold]Dumping per-pass HTML to output/...[/bold]')
    all_pass_timings: dict[str, dict[str, float]] = {}
    for name, html in fixtures.items():
        stages, pass_timings = _run_passes(html)
        all_pass_timings[name] = pass_timings
        out_dir = _dump_pass_outputs(name, stages, pass_timings)
        console.print(f'  {name}: {len(stages)} stages → {out_dir}')

    console.print()
    _print_pass_timing_table(console, fixtures, all_pass_timings)

    # --- End-to-end timing benchmark ---
    console.print()
    current_results = _run_e2e_benchmark(console, fixtures)

    # --- Baseline comparison ---
    if not save_baseline:
        _compare_baseline(console, current_results)

    if save_baseline:
        _save_baseline(current_results)
        console.print(f'\n[bold green]Baseline saved to {BASELINE_PATH}[/bold green]')

    console.print('\n[bold]Rust decision criteria:[/bold]')
    console.print('  - If median > 500ms on typical pages → Rust justified')
    console.print('  - If median < 100ms → stay Python (heuristics matter more than speed)')
    console.print(f'\n[dim]Inspect per-pass HTML diffs in: {OUTPUT_DIR}/[/dim]\n')


if __name__ == '__main__':
    main()
