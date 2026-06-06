"""Portfolio Monitor at scale — the field-atom corpus solves the discovery-cost explosion.

THE SCALING PROBLEM
    You monitor a portfolio across a fleet of pages: every ticker has a Yahoo-Finance
    quote page, served from several hosts (finance.yahoo.com, uk.…, de.…). Naively, an
    LLM must DISCOVER selectors for every field on every page — cost grows with
    pages x fields. At 24 quote pages x 3 fields that is 72 LLM discoveries, and it
    repeats the moment you add a metric or a new mirror appears.

THE FIX (this repo)
    A page's identity is its SHAPE, not its URL. Selectors are field-atoms keyed by
    (page_shape, region, field, type). So you DISCOVER ONCE per shape and REPLAY across
    every same-shape page — any ticker, subdomain, or TLD — for free. The discrimination
    gate keeps the quote-header and key-stats regions from conflating before anything is
    internalized, and growing a contract by one metric costs exactly one new atom.

This simulation is fully offline and deterministic. "Discovery" is modelled as a counter
(each one stands for an LLM call); atom hits are free replays. Run:

    uv run python mocked-projects/portfolio-monitor/run.py
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from yosoi.core.atom_read import resolve_via_atoms, selector_map_from_atoms
from yosoi.core.discovery.discrimination import evaluate_discrimination
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import page_shape_fp
from yosoi.storage.atoms import AtomStore, derive_atoms

# ── the mocked web (the source of truth) ────────────────────────────────────────


def quote_html(name: str, ticker: str, price: str) -> str:
    """A Yahoo-Finance quote page — identical structure for every ticker/host."""
    return f"""<body class="quote-page">
  <header><nav><a href="/">Finance</a></nav></header>
  <div id="quote-header-info"><h1>{name} ({ticker})</h1>
    <fin-streamer data-field="regularMarketPrice">{price}</fin-streamer></div>
  <div id="quote-summary"><table><tbody>
    <tr><td>Market Cap</td><td>2.7T</td></tr>
    <tr><td>P/E Ratio</td><td>29.4</td></tr>
  </tbody></table></div>
</body>"""


TICKERS = [
    ('Apple', 'AAPL', '171.52'),
    ('Microsoft', 'MSFT', '378.91'),
    ('Amazon', 'AMZN', '146.80'),
    ('Alphabet', 'GOOG', '139.10'),
    ('Nvidia', 'NVDA', '494.20'),
    ('Meta', 'META', '352.00'),
    ('Tesla', 'TSLA', '238.83'),
    ('Netflix', 'NFLX', '486.10'),
]
HOSTS = ['finance.yahoo.com', 'uk.finance.yahoo.com', 'de.finance.yahoo.com']

# The whole fleet: every ticker on every host (same shape, 24 distinct URLs).
FLEET = [
    (f'https://{host}/quote/{ticker}', quote_html(name, ticker, price))
    for (name, ticker, price) in TICKERS
    for host in HOSTS
]


# ── the queries (contracts) and the selectors discovery WOULD return ─────────────


@dataclass(frozen=True)
class FieldDef:
    name: str
    region: str  # the root selector the field lives under
    yosoi_type: str | None
    selector: str  # ground-truth primary a discovery would return


# Two disjoint contracts per quote page → the discrimination gate has something to judge.
def quote_contracts(*, with_pe: bool) -> dict[str, list[FieldDef]]:
    stats = [FieldDef('market_cap', '#quote-summary', 'text', 'tr:nth-child(1) td:last-child::text')]
    if with_pe:  # the "analyst adds a metric" expansion
        stats.append(FieldDef('pe_ratio', '#quote-summary', 'number', 'tr:nth-child(2) td:last-child::text'))
    return {
        'QuoteHeader': [
            FieldDef('symbol', '#quote-header-info', 'text', 'h1::text'),
            FieldDef('price', '#quote-header-info', 'number', 'fin-streamer::text'),
        ],
        'KeyStats': stats,
    }


# ── the engine: read-from-atoms → discover misses → gate → internalize ───────────


class Engine:
    """Scrapes a page by reading the atom corpus first and only DISCOVERING the gaps."""

    def __init__(self) -> None:
        self.store = AtomStore()  # in-memory corpus for the demo
        self.discoveries = 0  # each one stands for one (costly) LLM call

    def scrape(self, url: str, html: str, contracts: dict[str, list[FieldDef]]) -> tuple[int, int]:
        shape = page_shape_fp(observe_html(url, html, row_selector=''))
        domain = urlparse(url).netloc
        served = discovered = 0
        full_maps: dict[str, dict] = {}

        for cname, fields in contracts.items():
            res = resolve_via_atoms(shape, [(f.name, f.yosoi_type) for f in fields], self.store)
            smap = selector_map_from_atoms(res.hits)
            served += len(res.hits)
            for field in fields:
                if field.name in res.to_discover:  # not safely in the corpus → DISCOVER
                    self.discoveries += 1
                    discovered += 1
                    smap[field.name] = {
                        'primary': {'type': 'css', 'value': field.selector},
                        'root': {'type': 'css', 'value': field.region},
                    }
            full_maps[cname] = smap

        # Gate the full contract set; only a discriminated set may be internalized.
        if evaluate_discrimination(html, full_maps).accepted:
            for cname, fields in contracts.items():
                specs = [(f.name, full_maps[cname][f.name]['primary'], f.region, f.yosoi_type) for f in fields]
                self.store.upsert_all(derive_atoms(shape, cname, domain, specs))
        return served, discovered


# ── run the fleet and score it ───────────────────────────────────────────────────


def _fields_per_page(contracts: dict[str, list[FieldDef]]) -> int:
    return sum(len(v) for v in contracts.values())


def main() -> None:
    engine = Engine()
    naive = 0
    print(f'FLEET: {len(FLEET)} quote pages — {len(TICKERS)} tickers x {len(HOSTS)} hosts\n')

    print('PASS 1 — monitor {symbol, price, market_cap} across the fleet')
    base = quote_contracts(with_pe=False)
    per_page = _fields_per_page(base)
    first = True
    for url, html in FLEET:
        served, discovered = engine.scrape(url, html, base)
        naive += per_page
        if first:
            print(f'  {urlparse(url).netloc:<24} discovered={discovered} served={served}  (cold: first of its shape)')
            first = False
    print(f'  …{len(FLEET) - 1} more pages: discovered=0 served={per_page} each — all replayed from the corpus')

    print('\nPASS 2 — analyst adds a `pe_ratio` metric, re-runs the SAME fleet')
    grown = quote_contracts(with_pe=True)
    per_page = _fields_per_page(grown)
    before = engine.discoveries
    for url, html in FLEET:
        engine.scrape(url, html, grown)
        naive += per_page
    print(
        f'  cost to add the metric across {len(FLEET)} pages: {engine.discoveries - before} discovery '
        f'(one atom, then replayed everywhere)'
    )

    print('\n' + '─' * 70)
    print('SCOREBOARD'.center(70))
    print('─' * 70)
    reduction = 100 * (1 - engine.discoveries / naive)
    print(f'  naive  (discover every field, every page) : {naive:>4} LLM discoveries')
    print(f'  atoms  (discover once per shape, replay)  : {engine.discoveries:>4} LLM discoveries')
    print(f'  → {reduction:.1f}% fewer discoveries  ·  corpus = {len(engine.store)} atoms\n')

    print('CORPUS — each selector discovered ONCE, confirmed across every host:')
    for atom in sorted(engine.store.all(), key=lambda a: (a.region_role, a.field_name)):
        print(f'  {atom.field_name:<11} region={atom.region_role:<20} seen_on={atom.domains_seen}')

    print('\nThe whole fleet — every ticker, the uk. and de. subdomains, and a brand-new')
    print('metric — cost a handful of discoveries because they all share ONE page shape.')


if __name__ == '__main__':
    main()
