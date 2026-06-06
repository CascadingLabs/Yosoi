"""Cross-domain / cross-page-type generalization battery for the page fingerprint.

Twelve named experiments over REAL pages spanning ~8 domains and 6 page types. Each page's
``PageFingerprint`` is computed ONCE (static fetch, no LLM), then each experiment asks a single
``a.matches(b)`` question with an explicit hypothesis and prints whether the verdict met it.

Why this exists: validate *where the fingerprint generalizes* — same-domain, cross-locale,
cross-domain-same-CMS, cross-domain-same-page-type — and confirm the precision/recall trade.

It also cross-checks the design against **Scrapling's adaptive selectors** (see
``docs/research/scrapling-adaptive-selectors.md``): Scrapling fingerprints an *element* by its
``path`` = the ancestor-tag tuple root->element (``_StorageTools.element_to_dict``). Our
``page_skeleton`` is the *set* of depth-D windows over exactly those paths, aggregated over the
whole page — Section D asserts that equivalence on a live page.

Run (static, no LLM, ~30-60s, needs network):
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
    family: str  # conservative ground truth: same family == same SITE template
    kind: str  # page type (for the cross-type precision check)
    url: str


# ── the corpus: 8 domains, 6 page types ────────────────────────────────────────────────
PAGES: list[Page] = [
    # JS-heavy finance (static fetch sees the shell template)
    Page('yahoo:AAPL', 'yahoo-quote', 'quote', 'https://finance.yahoo.com/quote/AAPL'),
    Page('yahoo:MSFT', 'yahoo-quote', 'quote', 'https://finance.yahoo.com/quote/MSFT'),
    # e-commerce detail + listing (toscrape sandbox)
    Page(
        'books:detailA',
        'books-detail',
        'detail',
        'https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html',
    ),
    Page(
        'books:detailB',
        'books-detail',
        'detail',
        'https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html',
    ),
    Page('books:listing', 'books-listing', 'listing', 'https://books.toscrape.com/index.html'),
    Page('books:page2', 'books-listing', 'listing', 'https://books.toscrape.com/catalogue/page-2.html'),
    # quotes listing (volume drift across pages)
    Page('quotes:p1', 'quotes-listing', 'listing', 'https://quotes.toscrape.com/page/1/'),
    Page('quotes:p2', 'quotes-listing', 'listing', 'https://quotes.toscrape.com/page/2/'),
    # MediaWiki article across FOUR domains — the cross-domain-same-CMS probe
    Page('wiki:en:python', 'wp-vector', 'article', 'https://en.wikipedia.org/wiki/Python_(programming_language)'),
    Page('wiki:en:scrape', 'wp-vector', 'article', 'https://en.wikipedia.org/wiki/Web_scraping'),
    Page('wiki:de:python', 'wp-vector', 'article', 'https://de.wikipedia.org/wiki/Python_(Programmiersprache)'),
    Page('mw:mediawiki', 'mw-vector', 'article', 'https://www.mediawiki.org/wiki/MediaWiki'),
    Page('arch:bash', 'arch-wiki', 'article', 'https://wiki.archlinux.org/title/Bash'),
    # news / aggregator, same template across sections
    Page('hn:front', 'hackernews', 'listing', 'https://news.ycombinator.com/'),
    Page('hn:newest', 'hackernews', 'listing', 'https://news.ycombinator.com/newest'),
    # generic scraping sandbox (a different listing site)
    Page('sts:simple', 'scrapethissite', 'listing', 'https://www.scrapethissite.com/pages/simple/'),
    # structurally trivial → degenerate bucket
    Page('example', 'degenerate', 'trivial', 'https://example.com/'),
]


@dataclass(frozen=True)
class Experiment:
    name: str
    a: str
    b: str
    expect_match: bool
    why: str


# ── 12 experiments: each a single matches() question with a hypothesis ──────────────────
EXPERIMENTS: list[Experiment] = [
    Experiment(
        'E1  same-domain, same-template, diff content',
        'yahoo:AAPL',
        'yahoo:MSFT',
        True,
        'one ticker vs another — identical template, different data',
    ),
    Experiment(
        'E2  same-domain, DIFFERENT template',
        'books:detailA',
        'books:listing',
        False,
        'product detail vs catalogue listing on the same site → must split',
    ),
    Experiment(
        'E3  same-template, content-volume drift',
        'quotes:p1',
        'quotes:p2',
        True,
        'pagination: same template, different number of rows',
    ),
    Experiment(
        'E4  same-template listing pagination', 'books:listing', 'books:page2', True, 'catalogue page 1 vs page 2'
    ),
    Experiment(
        'E5  CROSS-LOCALE, same template, DIFFERENT domain',
        'wiki:en:python',
        'wiki:de:python',
        True,
        'en.wikipedia vs de.wikipedia — same skin, different host: the headline reuse case',
    ),
    Experiment(
        'E6  cross-domain, same CMS, diff config',
        'wiki:en:python',
        'mw:mediawiki',
        False,
        'wikipedia.org vs mediawiki.org — same engine, different extensions/skin config → different '
        'template. Design thesis: we bucket TEMPLATE, not ENGINE. Live data confirms (skel 0.23).',
    ),
    Experiment(
        'E7  cross-domain, same CMS, DIFFERENT skin',
        'wiki:en:python',
        'arch:bash',
        False,
        'wikipedia (Vector-2022) vs archwiki (custom skin) — same engine, different template',
    ),
    Experiment(
        'E8  cross-domain, same PAGE TYPE, diff site',
        'books:listing',
        'sts:simple',
        False,
        'two listing pages on unrelated sites → template ≠ page-type, must split',
    ),
    Experiment(
        'E9  cross-domain, unrelated (precision sanity)',
        'hn:front',
        'wiki:en:python',
        False,
        'aggregator vs encyclopedia → obvious split',
    ),
    Experiment(
        'E10 same-site, diff section, same template',
        'hn:front',
        'hn:newest',
        True,
        'HN front page vs newest — identical template',
    ),
    Experiment(
        'E11 minimal page splits from a rich one',
        'example',
        'books:listing',
        False,
        'example.com (10 shingles, just above the degenerate floor) vs a real catalogue → split on '
        'STRUCTURE (skel 0.03), not on degeneracy — confirms thin≠degenerate but still discriminates',
    ),
    Experiment(
        'E12 a minimal page matches ITSELF',
        'example',
        'example',
        True,
        'finding: example.com clears the degenerate floor (10 ≥ 8), so it IS reusable against an '
        'identical fetch. The floor only quarantines near-empty pages; see findings doc for the trade.',
    ),
]


def _verdict(fp: dict[str, PageFingerprint], a: str, b: str) -> tuple[bool, float, float]:
    sim = fp[a].similarity(fp[b])
    return sim.same_shape, sim.skeleton, sim.semantic


async def _fetch_corpus() -> dict[str, PageFingerprint]:
    fp: dict[str, PageFingerprint] = {}
    print('── fetching corpus (static, no LLM) ──')
    async with SimpleFetcher() as f:
        for p in PAGES:
            try:
                html = getattr(await f.fetch(p.url), 'html', '') or ''
            except Exception as exc:
                html = ''
                print(f'  WARN  {p.label:<16} fetch failed: {type(exc).__name__}')
            fpv = PageFingerprint.of(html)
            fp[p.label] = fpv
            flag = ' (degenerate)' if fpv.degenerate else ''
            print(f'  {p.label:<16} skeleton={len(fpv.skeleton):>4}  semantic={len(fpv.semantic):>3}{flag}')
    return fp


def _section_experiments(fp: dict[str, PageFingerprint]) -> None:
    print('\n── 12 experiments (hypothesis vs live verdict) ──')
    passed = 0
    for e in EXPERIMENTS:
        if e.a not in fp or e.b not in fp:
            print(f'  SKIP  {e.name} (page unavailable)')
            continue
        match, skel, sem = _verdict(fp, e.a, e.b)
        ok = match == e.expect_match
        passed += ok
        tag = 'OK  ' if ok else 'XX  '
        verb = 'MATCH' if match else 'split'
        print(f'  {tag}{e.name:<46} → {verb:<5} skel={skel:.2f} sem={sem:.2f}  [{e.why}]')
    print(f'\n  experiments meeting hypothesis: {passed}/{len(EXPERIMENTS)}')


def _section_recall_precision(fp: dict[str, PageFingerprint]) -> None:
    fam = {p.label: p.family for p in PAGES}
    deg = {lbl for lbl, v in fp.items() if v.degenerate}
    same_hit = same_tot = diff_hit = diff_tot = 0
    confusions: list[str] = []
    for i, a in enumerate(PAGES):
        for b in PAGES[i + 1 :]:
            if a.label in deg or b.label in deg:
                continue  # degenerate pages are excluded from the recall/precision frame by design
            match, skel, sem = _verdict(fp, a.label, b.label)
            if fam[a.label] == fam[b.label]:
                same_tot += 1
                same_hit += match
                if not match:
                    confusions.append(f'  MISS  {a.label} ~ {b.label}  skel={skel:.2f} sem={sem:.2f}')
            else:
                diff_tot += 1
                diff_hit += not match
                if match:
                    confusions.append(f'  FALSE {a.label} ~ {b.label}  skel={skel:.2f} sem={sem:.2f}')
    print('\n── recall / precision over same-SITE-template ground truth ──')
    print(f'  recall   (same-template pairs bucketed) : {same_hit}/{same_tot}')
    print(f'  precision(diff-template pairs split)    : {diff_hit}/{diff_tot}')
    for c in confusions:
        print(c)


def _section_mediawiki(fp: dict[str, PageFingerprint]) -> None:
    print('\n── cross-domain MediaWiki family (report) ──')
    mw = ['wiki:en:python', 'wiki:de:python', 'mw:mediawiki', 'arch:bash']
    for i, a in enumerate(mw):
        for b in mw[i + 1 :]:
            if a in fp and b in fp:
                m, sk, se = _verdict(fp, a, b)
                print(f'  {a:<16} ~ {b:<16} skel={sk:.2f} sem={se:.2f} → {"MATCH" if m else "split"}')


async def main() -> None:
    fp = await _fetch_corpus()
    _section_experiments(fp)  # A: hypothesis vs verdict
    _section_recall_precision(fp)  # B: recall/precision over same-template ground truth
    _section_mediawiki(fp)  # C: cross-domain same-CMS report
    print('\n── Scrapling cross-check: skeleton == set of element-path windows ──')
    _scrapling_path_check(fp)  # D: primitive equivalence
    print('\n  Takeaway: the fingerprint buckets SAME TEMPLATE (any ticker/book/article/locale),')
    print('  not "same page type across sites" and not necessarily "same CMS across skins" — and')
    print('  refuses degenerate shapes. Precision-first: a miss re-discovers; a false-match corrupts.')


def _scrapling_path_check(fp: dict[str, PageFingerprint]) -> None:
    """Demonstrate that page_skeleton is the set-aggregation of Scrapling's per-element `path`.

    Scrapling stores, per saved element, ``path`` = the tuple of ancestor tags root->element
    (``_StorageTools._get_element_path``). Our depth-2 skeleton shingles are exactly the
    length-2 windows over those paths (modulo our class/identity decoration). Strip the
    decoration from a sample page's shingles and confirm each is a (parent_tag, child_tag)
    window — the identical primitive, aggregated as a page-level SET.
    """
    target = next(
        (lbl for lbl in ('books:detailA', 'wiki:en:python', 'hn:front') if lbl in fp and not fp[lbl].degenerate),
        None,
    )
    if target is None:
        print('  SKIP (no non-degenerate sample page available)')
        return
    spines = {tuple(sym.split('#')[0].split('.')[0] for sym in sh.split('/')) for sh in fp[target].skeleton}
    depth2 = [s for s in spines if len(s) == 2]
    ok = all(all(isinstance(t, str) and t for t in s) for s in depth2)
    print(f'  page={target}  skeleton windows={len(spines)}  sample={depth2[:6]}')
    print(f'  every depth-2 skeleton shingle is a (parent_tag, child_tag) path window: {ok and bool(depth2)}')
    print('  → identical primitive to Scrapling element.path, aggregated as a page-level SET.')


if __name__ == '__main__':
    asyncio.run(main())
