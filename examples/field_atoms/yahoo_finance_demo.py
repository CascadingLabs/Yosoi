"""Yahoo Finance: page_shape generalizes across subdomains / domains / paths.

A page's shape is keyed on its STRUCTURE, not its URL — so every Yahoo Finance *quote*
page (any ticker, any subdomain, any TLD) is ONE shape bucket, and the selectors
learned on ``finance.yahoo.com/quote/AAPL`` replay for free on
``uk.finance.yahoo.com/quote/MSFT``. A different template (news feed) is a different
bucket. This demo prints the shape matrix, then internalizes a quote page's atoms once
and shows every other quote URL reuse them (only provenance grows).

Run:
    uv run python examples/field_atoms/yahoo_finance_demo.py
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from yosoi.core.discovery.discrimination import evaluate_discrimination
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import page_shape_fp
from yosoi.storage.atoms import AtomStore, derive_atoms


def quote_page(name: str, ticker: str, price: str) -> str:
    """A Yahoo-Finance-style quote page — identical structure for every ticker."""
    return f"""<body class="quote-page">
  <header><nav><a href="/">Finance</a><a href="/watchlists">Watchlists</a></nav></header>
  <div id="quote-header-info">
    <h1>{name} ({ticker})</h1>
    <fin-streamer data-field="regularMarketPrice">{price}</fin-streamer>
    <fin-streamer data-field="regularMarketChange">+1.23</fin-streamer>
  </div>
  <div id="quote-summary"><table><tbody>
    <tr><td>Previous Close</td><td>171.05</td></tr>
    <tr><td>Market Cap</td><td>2.7T</td></tr>
  </tbody></table></div>
</body>"""


NEWS_PAGE = """<body class="news-page">
  <header><nav><a href="/">Finance</a></nav></header>
  <main>
    <article><h3><a href="/news/a">Markets rally</a></h3><p>Stocks...</p><time>2h</time></article>
    <article><h3><a href="/news/b">Fed holds</a></h3><p>The bank...</p><time>4h</time></article>
  </main>
</body>"""

# (url, html) matrix — three quote pages varying ticker/path/subdomain, plus a news page.
MATRIX: list[tuple[str, str]] = [
    ('https://finance.yahoo.com/quote/AAPL', quote_page('Apple Inc.', 'AAPL', '171.52')),
    ('https://finance.yahoo.com/quote/MSFT', quote_page('Microsoft Corp.', 'MSFT', '378.91')),
    ('https://uk.finance.yahoo.com/quote/MSFT', quote_page('Microsoft Corp.', 'MSFT', '378.91')),
    ('https://finance.yahoo.com/news', NEWS_PAGE),
]


def _shape(url: str, html: str) -> str:
    return page_shape_fp(observe_html(url, html, row_selector=''))


# Two disjoint contracts on a quote page: the header region vs the summary region.
Spec = dict[str, tuple[str, str, str | None]]  # field -> (primary, root, yosoi_type)
QUOTE_HEADER: Spec = {
    'symbol': ('h1::text', '#quote-header-info', 'text'),
    'price': ('fin-streamer[data-field="regularMarketPrice"]::text', '#quote-header-info', 'number'),
}
KEY_STATS: Spec = {'market_cap': ('tr:last-child td:last-child::text', '#quote-summary', 'text')}


def _gate_maps(contracts: dict[str, Spec]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            field: {'primary': {'type': 'css', 'value': p}, 'root': {'type': 'css', 'value': root}}
            for field, (p, root, _yt) in fields.items()
        }
        for name, fields in contracts.items()
    }


def main() -> None:
    print('PAGE-SHAPE MATRIX (shape is keyed on structure, NOT the URL)')
    print('─' * 88)
    for url, html in MATRIX:
        print(f'  {url:<46} → {_shape(url, html)}')
    print('  ↑ the three /quote pages (two paths, a uk subdomain) share ONE bucket; news differs.\n')

    contracts = {'QuoteHeader': QUOTE_HEADER, 'KeyStats': KEY_STATS}
    store = AtomStore()
    print('INTERNALIZE the quote shape once, then watch every other quote URL REUSE it')
    print('─' * 88)
    for url, html in MATRIX:
        if 'quote' not in url:
            continue
        domain = urlparse(url).netloc
        report = evaluate_discrimination(html, _gate_maps(contracts))
        if not report.accepted:
            print(f'  {domain:<26} gate ⛔ {report.reason}')
            continue
        shape = _shape(url, html)
        minted = reused = 0
        for name, fields in contracts.items():
            specs = [(f, {'type': 'css', 'value': p}, root, yt) for f, (p, root, yt) in fields.items()]
            new = store.upsert_all(derive_atoms(shape, name, domain, specs))
            minted += new
            reused += len(fields) - new
        print(f'  {domain:<26} gate ✅  minted={minted} reused={reused}  store_total={len(store)}')

    print('\nFINAL CORPUS — 3 atoms, each seen on every quote domain (provenance), discovered ONCE')
    print('─' * 88)
    for atom in sorted(store.all(), key=lambda a: (a.region_role, a.field_name)):
        print(f'  {atom.region_role:<20} {atom.field_name:<11} seen_on={atom.domains_seen}')
    print('\nTakeaway: subdomain (uk.), path (/AAPL vs /MSFT), and TLD never fragment the shape —')
    print('the quote selectors are learned once and replay across the whole quote family.')


if __name__ == '__main__':
    main()
