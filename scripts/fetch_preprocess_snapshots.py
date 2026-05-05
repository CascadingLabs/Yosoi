"""Fetch real-world page snapshots for the CAS-18 preprocess spike.

Downloads HTML from a curated list of representative pages (news, finance,
encyclopedia, e-commerce, framework-heavy SPAs) and writes each to
``tests/data/preprocess/real/<slug>.html``. Snapshots are reused offline by
the integration test ``tests/integration/test_preprocess_real_pages.py``.

Usage::

    uv run python scripts/fetch_preprocess_snapshots.py             # full set
    uv run python scripts/fetch_preprocess_snapshots.py --only cnn  # subset

The script is intentionally polite:
* one URL at a time (no concurrent fan-out),
* a 30s timeout,
* a realistic browser-style ``User-Agent``,
* tenacity-backed retries with exponential wait (3 attempts max).

We do *not* commit copyrighted snapshots. A ``.gitignore`` in the target
directory keeps them out of git; CI fetches fresh on demand.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

REAL_DIR = Path(__file__).parents[1] / 'tests' / 'data' / 'preprocess' / 'real'

_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('fetch_preprocess_snapshots')


@dataclass(frozen=True)
class Snapshot:
    """One target page to fetch."""

    slug: str
    url: str
    note: str


# Curated set: covers news (CNN, BBC), finance (Yahoo Finance), encyclopedia
# (Wikipedia - CC-BY-SA, safe to commit), and a framework-heavy SPA
# (GitHub PR - React app with hydration JSON). Six pages = mid-range of
# the spike's 5-10 fixtures requirement.
SNAPSHOTS: tuple[Snapshot, ...] = (
    Snapshot('cnn_homepage', 'https://www.cnn.com/', 'CNN homepage — heavy ad/widget noise'),
    Snapshot(
        'yahoo_finance_aapl',
        'https://finance.yahoo.com/quote/AAPL/',
        'Yahoo Finance ticker page — React SPA with large hydration payload',
    ),
    Snapshot('bbc_news_homepage', 'https://www.bbc.com/news', 'BBC News — server-rendered article grid'),
    Snapshot(
        'wikipedia_python',
        'https://en.wikipedia.org/wiki/Python_(programming_language)',
        'Wikipedia — long article with JSON-LD and infobox',
    ),
    Snapshot(
        'github_pulls',
        'https://github.com/python/cpython/pulls',
        'GitHub pulls — React SPA with embedded JSON state',
    ),
    Snapshot(
        'mdn_array',
        'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array',
        'MDN reference — content-heavy article with sidebars',
    ),
    # ---- Iteration 1 long-tail expansion ----
    Snapshot(
        'hackernews_front',
        'https://news.ycombinator.com/',
        'Hacker News — minimal table-based layout, baseline lower bound',
    ),
    Snapshot(
        'stackoverflow_question',
        'https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python',
        'Stack Overflow — heavy JSON-LD, long Q+A thread, multiple code blocks',
    ),
    Snapshot(
        'zillow_homepage',
        'https://www.zillow.com/',
        'Zillow homepage — React SPA with massive hydration JSON + image grid',
    ),
    Snapshot(
        'whitehouse_homepage',
        'https://www.whitehouse.gov/',
        'WhiteHouse.gov — WordPress-based government site with hero images',
    ),
    # ---- Iteration 2 expansion: heavy hydration / e-commerce / docs ----
    Snapshot(
        'reddit_front',
        'https://old.reddit.com/',
        'Old Reddit — server-rendered listing, dense link soup',
    ),
    Snapshot(
        'arstechnica_front',
        'https://arstechnica.com/',
        'Ars Technica homepage — magazine layout with multiple article cards',
    ),
    Snapshot(
        'rust_lang_docs',
        'https://doc.rust-lang.org/std/index.html',
        'Rust std docs — generated docs with sidebar nav and JSON-LD',
    ),
    Snapshot(
        'go_dev_pkg',
        'https://pkg.go.dev/net/http',
        'Go pkg docs — content-heavy reference with TOC',
    ),
    Snapshot(
        'arxiv_abstract',
        'https://arxiv.org/abs/1706.03762',
        'arXiv abstract — academic paper landing page (Attention Is All You Need)',
    ),
    Snapshot(
        'github_gist',
        'https://gist.github.com/discover',
        'GitHub Gist Discover — mixed listing + auth widgets',
    ),
    # ---- Iteration 3 expansion: heavy ads / SPA / e-commerce ----
    Snapshot(
        'espn_front',
        'https://www.espn.com/',
        'ESPN homepage — heavy module grid + scores hydration',
    ),
    Snapshot(
        'allrecipes_front',
        'https://www.allrecipes.com/',
        'Allrecipes homepage — dense recipe cards with ratings',
    ),
    Snapshot(
        'substack_explore',
        'https://substack.com/',
        'Substack home — Next.js with hydration JSON',
    ),
    Snapshot(
        'nbc_news_front',
        'https://www.nbcnews.com/',
        'NBC News homepage — heavy ads + section grid',
    ),
    Snapshot(
        'theatlantic_front',
        'https://www.theatlantic.com/',
        'Atlantic homepage — magazine layout, heavy meta',
    ),
)


def _fetch(url: str, *, timeout: float = 30.0) -> str:
    """Fetch *url* with retries. Returns response text on 2xx; raises otherwise."""
    headers = {
        'User-Agent': _USER_AGENT,
        'Accept': ('text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'),
        'Accept-Language': 'en-US,en;q=0.9',
    }
    last_exc: Exception | None = None
    for attempt in Retrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    ):
        with attempt:
            log.info('GET %s (attempt %d)', url, attempt.retry_state.attempt_number)
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text
    # Unreachable due to ``reraise=True``, but keeps mypy happy.
    raise RuntimeError(f'Failed to fetch {url}: {last_exc}')


def fetch_all(only: list[str] | None = None) -> dict[str, Path]:
    """Fetch every configured snapshot (or the subset named in ``only``)."""
    REAL_DIR.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for snap in SNAPSHOTS:
        if only and snap.slug not in only:
            continue
        target = REAL_DIR / f'{snap.slug}.html'
        try:
            html_text = _fetch(snap.url)
        except Exception as exc:  # noqa: BLE001 - one bad URL must not abort the run
            log.warning('skip %s: %s', snap.slug, exc)
            continue
        target.write_text(html_text)
        log.info('wrote %s (%d KB) — %s', target.name, len(html_text) // 1024, snap.note)
        written[snap.slug] = target
    return written


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', nargs='*', help='Subset of slugs to fetch.')
    parser.add_argument('--list', action='store_true', help='List configured snapshots and exit.')
    args = parser.parse_args(argv)

    if args.list:
        for snap in SNAPSHOTS:
            print(f'{snap.slug:24s} {snap.url}\n    {snap.note}')
        return 0

    written = fetch_all(only=args.only)
    log.info('done: %d snapshots written to %s', len(written), REAL_DIR)
    return 0 if written else 1


if __name__ == '__main__':
    sys.exit(main())
