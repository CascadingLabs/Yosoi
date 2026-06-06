"""Cross-domain / cross-page-type generalization experiments for the page fingerprint.

Fetches a battery of REAL pages across domains and page types, computes each one's
``PageFingerprint`` ONCE, then asks ``a.matches(b)`` for every pair and checks the verdict
against a hand-labelled "same template family" ground truth. Reports recall (same-family
pairs that bucketed) and precision (different-family pairs correctly split), plus the
cross-locale (Wikipedia en/de, same CMS / different domain) case.

Run (static, no LLM, ~30s):
    uv run python experiments/fingerprint_generalization.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from yosoi.core.fetcher.simple import SimpleFetcher
from yosoi.generalization.fingerprint import PageFingerprint


@dataclass(frozen=True)
class Page:
    label: str
    family: str  # same family == same template (ground truth)
    url: str


PAGES: list[Page] = [
    Page('yahoo:AAPL', 'yahoo-quote', 'https://finance.yahoo.com/quote/AAPL'),
    Page('yahoo:MSFT', 'yahoo-quote', 'https://finance.yahoo.com/quote/MSFT'),
    Page('yahoo:markets', 'yahoo-markets', 'https://finance.yahoo.com/markets/'),
    Page('books:detailA', 'books-detail', 'https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html'),
    Page('books:detailB', 'books-detail', 'https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html'),
    Page('books:listing', 'books-listing', 'https://books.toscrape.com/index.html'),
    Page('quotes:p1', 'quotes-listing', 'https://quotes.toscrape.com/page/1/'),
    Page('quotes:p2', 'quotes-listing', 'https://quotes.toscrape.com/page/2/'),
    Page('wiki:en:python', 'wiki', 'https://en.wikipedia.org/wiki/Python_(programming_language)'),
    Page('wiki:en:scrape', 'wiki', 'https://en.wikipedia.org/wiki/Web_scraping'),
    Page('wiki:de:python', 'wiki-de', 'https://de.wikipedia.org/wiki/Python_(Programmiersprache)'),
    Page('hn:front', 'hackernews', 'https://news.ycombinator.com/'),
]


async def main() -> None:
    fp: dict[str, PageFingerprint] = {}
    async with SimpleFetcher() as f:
        for p in PAGES:
            html = getattr(await f.fetch(p.url), 'html', '') or ''
            fp[p.label] = PageFingerprint.of(html)
            print(
                f'  fetched {p.label:<16} skeleton={len(fp[p.label].skeleton):>4}  semantic={len(fp[p.label].semantic):>3}'
            )

    fam = {p.label: p.family for p in PAGES}
    same_hits = same_tot = diff_hits = diff_tot = 0
    confusions: list[str] = []
    for i, a in enumerate(PAGES):
        for b in PAGES[i + 1 :]:
            sim = fp[a.label].similarity(fp[b.label])
            if fam[a.label] == fam[b.label]:
                same_tot += 1
                same_hits += sim.same_shape
                if not sim.same_shape:
                    confusions.append(f'  MISS  {a.label} ~ {b.label}  skel={sim.skeleton:.2f} sem={sim.semantic:.2f}')
            else:
                diff_tot += 1
                diff_hits += not sim.same_shape
                if sim.same_shape:
                    confusions.append(f'  FALSE {a.label} ~ {b.label}  skel={sim.skeleton:.2f} sem={sim.semantic:.2f}')

    print('\n  ── results ──')
    print(f'  same-template recall   : {same_hits}/{same_tot} pairs bucketed together')
    print(f'  diff-template precision: {diff_hits}/{diff_tot} pairs correctly split')
    locale = fp['wiki:en:python'].similarity(fp['wiki:de:python'])
    print(
        f'\n  cross-locale (wiki en vs de): skel={locale.skeleton:.2f} sem={locale.semantic:.2f} same={locale.same_shape}'
    )
    if confusions:
        print('\n  ── confusions ──')
        for c in confusions:
            print(c)
    print('\n  Takeaway: the fingerprint buckets SAME-TEMPLATE pages (any ticker/book/article),')
    print('  not "same page type across different sites" — different sites are different templates.')


if __name__ == '__main__':
    asyncio.run(main())
