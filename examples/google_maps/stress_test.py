# yosoi: allow-hardcoded-selectors -- benchmark-only field-presence probes; no extraction cache is produced.
"""Compare bounded headless/headful Google Maps acquisition on a shared tab pool.

This is an opt-in live experiment. It performs only public, read-only navigation and
writes a compact JSON report instead of saving page HTML.

Run both modes against three exact-business queries:
    uv run python examples/google_maps/stress_test.py

Run one mode or change the concurrency cap:
    uv run python examples/google_maps/stress_test.py --mode headless --max-concurrency 2
"""

from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rich.console import Console

from examples.google_maps.google_maps import build_maps_search_url
from yosoi.core.fetcher.voiddriver import HeadfulFetcher, HeadlessFetcher
from yosoi.models.results import FetchResult

DEFAULT_OUTPUT = Path('.yosoi/browser-qa/google-maps-live-stress/results.json')
TARGETS = (
    ('Six Flags Over Georgia', 'Austell, GA'),
    ('Georgia Aquarium', 'Atlanta, GA'),
    ('World of Coca-Cola', 'Atlanta, GA'),
    ('The Varsity', 'Atlanta, GA'),
    ('Ponce City Market', 'Atlanta, GA'),
)

_TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r'<[^>]+>')
_RATING_RE = re.compile(r'aria-label="(\d+(?:\.\d+)?)\s+stars?\b', re.IGNORECASE)
_REVIEW_LABEL_RE = re.compile(r'aria-label="[^"]*?(\d[\d,]*)\s+Reviews?\b', re.IGNORECASE)
_PAREN_REVIEW_RE = re.compile(r'>\s*\(([\d,]+)\)\s*<')
_ADDRESS_RE = re.compile(r'aria-label="Address:\s*([^"]*?)\s*"', re.IGNORECASE)
_PHONE_RE = re.compile(r'data-item-id="phone:tel:([^"&]+)', re.IGNORECASE)
_WEBSITE_RE = re.compile(r'<a\b[^>]*data-item-id="authority"[^>]*href="([^"]+)"', re.IGNORECASE)
_PLUS_CODE_RE = re.compile(r'aria-label="Plus code:\s*([^"]*?)\s*"', re.IGNORECASE)


@dataclass(frozen=True)
class Target:
    """One exact-business Maps query."""

    business: str
    location: str
    url: str


@dataclass
class Observation:
    """Compact evidence from one rendered navigation."""

    business: str
    success: bool
    elapsed_seconds: float
    fetch_seconds: float
    status_code: int | None
    title: str | None = None
    detail_name: str | None = None
    rating: float | None = None
    review_count: int | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    plus_code: str | None = None
    limited_view: bool = False
    html_chars: int = 0
    error: str | None = None


@dataclass
class BatchResult:
    """Timing and field-availability summary for a serial or concurrent pass."""

    wall_seconds: float
    success_count: int
    rating_count: int
    review_count: int
    address_count: int
    phone_count: int
    website_count: int
    plus_code_count: int
    limited_view_count: int
    observations: list[Observation]


def _plain_text(markup: str) -> str:
    return html_lib.unescape(_TAG_RE.sub('', markup)).strip()


def _first_match(pattern: re.Pattern[str], source: str) -> str | None:
    match = pattern.search(source)
    return match.group(1).strip() if match else None


def _review_count(detail_html: str) -> int | None:
    raw = _first_match(_REVIEW_LABEL_RE, detail_html) or _first_match(_PAREN_REVIEW_RE, detail_html)
    return int(raw.replace(',', '')) if raw else None


def _observe(target: Target, fetched: FetchResult, elapsed: float) -> Observation:
    html = fetched.html or ''
    h1_match = _H1_RE.search(html)
    # Keep field probes near the primary h1 so nearby-place cards do not masquerade
    # as the requested business's rating/review count.
    panel_html = html[h1_match.start() :] if h1_match else html
    detail_html = panel_html[:20_000]
    rating_raw = _first_match(_RATING_RE, detail_html)
    # These detail rows can sit well below the h1 in markup. Ignore matching
    # labels/item ids before the primary heading so unrelated page chrome cannot win.
    address = _first_match(_ADDRESS_RE, panel_html)
    phone = _first_match(_PHONE_RE, panel_html)
    website = _first_match(_WEBSITE_RE, panel_html)
    plus_code = _first_match(_PLUS_CODE_RE, panel_html)
    title_raw = _first_match(_TITLE_RE, html)
    detail_name = _plain_text(h1_match.group(1)) if h1_match else None
    return Observation(
        business=target.business,
        success=fetched.success,
        elapsed_seconds=round(elapsed, 3),
        fetch_seconds=round(fetched.fetch_time, 3),
        status_code=fetched.status_code,
        title=_plain_text(title_raw) if title_raw else None,
        detail_name=detail_name,
        rating=float(rating_raw) if rating_raw else None,
        review_count=_review_count(detail_html),
        address=html_lib.unescape(address) if address else None,
        phone=phone,
        website=html_lib.unescape(website) if website else None,
        plus_code=html_lib.unescape(plus_code) if plus_code else None,
        limited_view='limited view of Google Maps' in html,
        html_chars=len(html),
        error=fetched.block_reason,
    )


async def _fetch_one(fetcher: Any, target: Target) -> Observation:
    started = time.perf_counter()
    try:
        fetched = await fetcher.fetch(target.url)
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return Observation(
            business=target.business,
            success=False,
            elapsed_seconds=round(elapsed, 3),
            fetch_seconds=round(elapsed, 3),
            status_code=None,
            error=f'{type(exc).__name__}: {exc}',
        )
    return _observe(target, fetched, time.perf_counter() - started)


def _summarize(observations: list[Observation], wall_seconds: float) -> BatchResult:
    return BatchResult(
        wall_seconds=round(wall_seconds, 3),
        success_count=sum(item.success for item in observations),
        rating_count=sum(item.rating is not None for item in observations),
        review_count=sum(item.review_count is not None for item in observations),
        address_count=sum(item.address is not None for item in observations),
        phone_count=sum(item.phone is not None for item in observations),
        website_count=sum(item.website is not None for item in observations),
        plus_code_count=sum(item.plus_code is not None for item in observations),
        limited_view_count=sum(item.limited_view for item in observations),
        observations=observations,
    )


async def _serial(fetcher: Any, targets: list[Target]) -> BatchResult:
    started = time.perf_counter()
    observations = [await _fetch_one(fetcher, target) for target in targets]
    return _summarize(observations, time.perf_counter() - started)


async def _concurrent(fetcher: Any, targets: list[Target]) -> BatchResult:
    started = time.perf_counter()
    observations = await asyncio.gather(*(_fetch_one(fetcher, target) for target in targets))
    return _summarize(observations, time.perf_counter() - started)


async def _run_mode(mode: str, targets: list[Target], max_concurrency: int) -> dict[str, Any]:
    fetcher_cls = HeadlessFetcher if mode == 'headless' else HeadfulFetcher
    fetcher = fetcher_cls(
        timeout=45,
        max_concurrent=max_concurrency,
        lightweight_fetch=True,
        console=Console(quiet=True),
    )

    pool_started = time.perf_counter()
    async with fetcher:
        pool_start_seconds = time.perf_counter() - pool_started
        cold = await _fetch_one(fetcher, targets[0])
        warm = await _fetch_one(fetcher, targets[0])
        serial = await _serial(fetcher, targets)
        concurrent_first = await _concurrent(fetcher, targets)
        concurrent_warm = await _concurrent(fetcher, targets)

    speedup = serial.wall_seconds / concurrent_warm.wall_seconds if concurrent_warm.wall_seconds else None
    cold_to_warm = cold.elapsed_seconds / warm.elapsed_seconds if warm.elapsed_seconds else None
    return {
        'mode': mode,
        'max_concurrency': max_concurrency,
        'pool_start_seconds': round(pool_start_seconds, 3),
        'cold': asdict(cold),
        'warm': asdict(warm),
        'cold_to_warm_ratio': round(cold_to_warm, 3) if cold_to_warm is not None else None,
        'serial': asdict(serial),
        'concurrent_first': asdict(concurrent_first),
        'concurrent_warm': asdict(concurrent_warm),
        'serial_to_warm_concurrent_speedup': round(speedup, 3) if speedup is not None else None,
    }


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError('value must be at least 1')
    return parsed


def parse_args() -> argparse.Namespace:
    """Parse bounded live-stress options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', action='append', choices=('headless', 'headful'), help='Repeat to select modes')
    parser.add_argument('--max-concurrency', type=_positive_int, default=3)
    parser.add_argument('--limit', type=int, default=3, choices=range(1, len(TARGETS) + 1))
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


async def main() -> None:
    """Run the live matrix and write compact evidence."""
    args = parse_args()
    modes = args.mode or ['headless', 'headful']
    targets = [
        Target(business=business, location=location, url=build_maps_search_url(f'{business}, {location}'))
        for business, location in TARGETS[: args.limit]
    ]

    mode_results = [await _run_mode(mode, targets, args.max_concurrency) for mode in modes]
    report = {
        'target_count': len(targets),
        'targets': [asdict(target) for target in targets],
        'modes': mode_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')

    for result in mode_results:
        warm = result['concurrent_warm']
        print(
            f'{result["mode"]}: pool={result["pool_start_seconds"]}s, '
            f'cold/warm={result["cold_to_warm_ratio"]}x, '
            f'serial={result["serial"]["wall_seconds"]}s, warm concurrent={warm["wall_seconds"]}s, '
            f'speedup={result["serial_to_warm_concurrent_speedup"]}x, '
            f'success={warm["success_count"]}/{len(targets)}, reviews={warm["review_count"]}/{len(targets)}, '
            f'addresses={warm["address_count"]}/{len(targets)}, phones={warm["phone_count"]}/{len(targets)}, '
            f'websites={warm["website_count"]}/{len(targets)}, plus_codes={warm["plus_code_count"]}/{len(targets)}, '
            f'limited={warm["limited_view_count"]}/{len(targets)}'
        )
    print(f'report: {args.output}')


if __name__ == '__main__':
    asyncio.run(main())
