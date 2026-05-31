"""Download qscrape.dev L1 HTML fixtures to tests/fixtures/html/.

Run this to refresh fixture snapshots:
    uv run python scripts/download_fixtures.py
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

PAGES: dict[str, str] = {
    'mountainhome_home.html': 'https://qscrape.dev/l1/news/',
    'mountainhome_articles.html': 'https://qscrape.dev/l1/news/articles',
    'vaultmart_home.html': 'https://qscrape.dev/l1/eshop/',
    'vaultmart_catalog.html': 'https://qscrape.dev/l1/eshop/catalog',
    'scoretap_home.html': 'https://qscrape.dev/l1/scoretap/',
    'eldoria_registry.html': 'https://qscrape.dev/l1/taxes/',
}

OUT_DIR = Path(__file__).parent.parent / 'tests' / 'fixtures' / 'html'


def fetch(url: str) -> str:
    """Return the response body from *url* as a UTF-8 string."""
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', errors='replace')


def main() -> None:
    """Download all fixture pages and write them to tests/fixtures/html/."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in PAGES.items():
        print(f'  Fetching {url} ...', end=' ', flush=True)
        html = fetch(url)
        (OUT_DIR / filename).write_text(html, encoding='utf-8')
        print(f'{len(html):,} chars -> {filename}')
    print(f'\nSaved {len(PAGES)} fixtures to {OUT_DIR}')


if __name__ == '__main__':
    main()
