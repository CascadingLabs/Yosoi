"""Atom-backed reads (P3): a contract resolves as a JOIN over the field-atom index.

Once the corpus is warm (P2), a Contract is answered by LOOKING UP its fields instead of
re-discovering them — exact page-shape, unambiguous regions only (fail closed). This demo
warms the index from one quote page, then shows four reads:

  A. a fresh Quote on a NEW ticker (same shape) → fully served, ZERO discovery.
  B. Quote + a new `volume` field → only `volume` misses (the field-grain win).
  C. a SERP `url` that lives in TWO regions (ad + organic) → AMBIGUOUS → discover.
  D. the same Quote on a DIFFERENT shape → not served (exact-shape only).

Run:
    uv run python examples/field_atoms/atom_read_demo.py
"""

from __future__ import annotations

from yosoi.core.atom_read import resolve_via_atoms
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import page_shape_fp
from yosoi.storage.atoms import AtomStore, derive_atoms

QUOTE_HTML = """<body class="quote-page">
  <div id="quote-header-info"><h1>Apple (AAPL)</h1><fin-streamer data-field="regularMarketPrice">171.52</fin-streamer></div>
  <div id="quote-summary"><table><tbody><tr><td>Market Cap</td><td>2.7T</td></tr></tbody></table></div>
</body>"""

NEWS_HTML = """<body class="news-page"><main>
  <article><h3><a href="/n/a">A</a></h3><p>x</p></article>
  <article><h3><a href="/n/b">B</a></h3><p>y</p></article>
</main></body>"""

SERP_HTML = """<body class="serp">
  <div class="uEierd"><a href="https://ad/lp"><h3>Ad</h3></a></div>
  <div class="MjjYud"><a href="https://o/1"><h3>One</h3></a></div>
</body>"""

QUOTE_SHAPE = page_shape_fp(observe_html('https://finance.yahoo.com/quote/AAPL', QUOTE_HTML, row_selector=''))
NEWS_SHAPE = page_shape_fp(observe_html('https://finance.yahoo.com/news', NEWS_HTML, row_selector=''))
SERP_SHAPE = page_shape_fp(observe_html('https://google.com/search', SERP_HTML, row_selector=''))


def _read(label: str, shape: str, requested: list[tuple[str, str | None]], store: AtomStore) -> None:
    res = resolve_via_atoms(shape, requested, store)
    served = '✅ served from index (0 discovery)' if res.fully_resolved else '↪ partial → discover'
    print(f'\n  {label}\n    {served}')
    print(f'    hits={sorted(res.hits)}  misses={res.misses}  ambiguous={res.ambiguous}')
    if res.to_discover:
        print(f'    → would discover only: {res.to_discover}')


def main() -> None:
    store = AtomStore()
    # Warm the corpus: internalize a quote page's two regions (as a gate-accepted set would).
    store.upsert_all(
        derive_atoms(
            QUOTE_SHAPE,
            'QuoteHeader',
            'finance.yahoo.com',
            [
                ('symbol', {'type': 'css', 'value': 'h1::text'}, '#quote-header-info', 'text'),
                ('price', {'type': 'css', 'value': 'fin-streamer::text'}, '#quote-header-info', 'number'),
            ],
        )
    )
    store.upsert_all(
        derive_atoms(
            QUOTE_SHAPE,
            'KeyStats',
            'finance.yahoo.com',
            [
                ('market_cap', {'type': 'css', 'value': 'td:last-child::text'}, '#quote-summary', 'text'),
            ],
        )
    )
    print(f'corpus warmed: {len(store)} atoms on quote shape {QUOTE_SHAPE}')

    _read(
        'A) fresh Quote{symbol,price,market_cap} on a NEW ticker (same shape)',
        QUOTE_SHAPE,
        [('symbol', 'text'), ('price', 'number'), ('market_cap', 'text')],
        store,
    )

    _read(
        'B) Quote grows a `volume` field',
        QUOTE_SHAPE,
        [('symbol', 'text'), ('price', 'number'), ('market_cap', 'text'), ('volume', 'number')],
        store,
    )

    # Add a SERP where `url` lives in TWO regions on one shape → ambiguous.
    store.upsert_all(
        derive_atoms(
            SERP_SHAPE, 'AdResult', 'google.com', [('url', {'type': 'css', 'value': 'a::attr(href)'}, '.uEierd', 'url')]
        )
    )
    store.upsert_all(
        derive_atoms(
            SERP_SHAPE,
            'OrganicResult',
            'google.com',
            [('url', {'type': 'css', 'value': 'a::attr(href)'}, '.MjjYud', 'url')],
        )
    )
    _read('C) SERP `url` exists in TWO regions (ad + organic) → fail-closed', SERP_SHAPE, [('url', 'url')], store)

    _read(
        'D) Quote{symbol,price} on a DIFFERENT shape (news)',
        NEWS_SHAPE,
        [('symbol', 'text'), ('price', 'number')],
        store,
    )

    print('\nTakeaway: same-shape unambiguous fields are served from the index for free;')
    print('a new field or an ambiguous region falls through to discovery — never a guess.')


if __name__ == '__main__':
    main()
