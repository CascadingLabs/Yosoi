"""Field-atom store (P2): gate → internalize → SHARE across contracts and domains.

The web is the SSoT; a Contract is a query; an atom is one materialized
``(field -> selector)`` fact in a verified region of a page SHAPE (not a domain). This
demo runs four rounds against a Google-style SERP and prints what the corpus does:

  1. AdResult + OrganicResult on google.com  → gate ACCEPTS → 4 atoms minted.
  2. AdResult + SearchResult{url,title,snippet} (search shares the organic region)
       → only `snippet` is new; url/title REUSE the organic atoms (the field-grain win).
  3. AdResult + OrganicResult on google.co.uk (same shape, new domain)
       → 0 minted; existing atoms just gain a domain in provenance.
  4. A conflated set (bare `a`) → gate REJECTS → nothing internalized (fail closed).

Run:
    uv run python examples/tutorial/field_atoms/atom_store_demo.py
"""

from __future__ import annotations

from typing import Any

from yosoi.core.discovery.discrimination import evaluate_discrimination
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import page_shape_fp
from yosoi.storage.atoms import AtomStore, derive_atoms

SERP_HTML = """<body>
  <div class="uEierd"><a href="https://buy.example/lp"><h3>Buy Widgets</h3></a></div>
  <div class="MjjYud"><a href="https://en.wikipedia.org/wiki/Widget"><h3>Widget - Wikipedia</h3><div class="snippet">A widget is a small gadget.</div></div>
  <div class="MjjYud"><a href="https://widgets.io/guide"><h3>The Widget Guide</h3><div class="snippet">Everything about widgets.</div></div>
</body>"""

PAGE_SHAPE = page_shape_fp(observe_html('https://google.com/search?q=widgets', SERP_HTML, row_selector=''))

# A contract spec for the demo: field -> (primary css, root css | None, yosoi_type).
Spec = dict[str, tuple[str, str | None, str | None]]


def _gate_maps(contracts: dict[str, Spec]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, fields in contracts.items():
        smap: dict[str, Any] = {}
        for field, (primary, root, _yt) in fields.items():
            entry: dict[str, Any] = {'primary': {'type': 'css', 'value': primary}}
            if root:
                entry['root'] = {'type': 'css', 'value': root}
            smap[field] = entry
        out[name] = smap
    return out


def round_(store: AtomStore, title: str, contracts: dict[str, Spec], domain: str) -> None:
    print(f'\n{"═" * 78}\n {title}\n{"═" * 78}')
    report = evaluate_discrimination(SERP_HTML, _gate_maps(contracts))
    if not report.accepted:
        print(f'  gate: ⛔ REJECTED — {report.reason}')
        print('  → nothing internalized (a conflation must never enter the index).')
        return
    print(f'  gate: ✅ ACCEPTED ({report.reason})')
    minted = reused = 0
    for name, fields in contracts.items():
        specs = [(f, {'type': 'css', 'value': p}, root, yt) for f, (p, root, yt) in fields.items()]
        atoms = derive_atoms(PAGE_SHAPE, name, domain, specs)
        new = store.upsert_all(atoms)
        minted += new
        reused += len(atoms) - new
    print(f'  internalized on {domain}: minted={minted}  reused={reused}  store_total={len(store)}')


def dump(store: AtomStore) -> None:
    print(f'\n{"─" * 78}\n FINAL ATOM CORPUS ({len(store)} atoms — keyed by shape × region × field × type)\n{"─" * 78}')
    for atom in sorted(store.all(), key=lambda a: (a.region_role, a.field_name)):
        print(
            f'  region={atom.region_role:<10} {atom.field_name:<8} type={atom.yosoi_type!s:<6} '
            f'selector={atom.selector["value"]!r}'
        )
        print(f'  {"":<10}   seen_on={atom.domains_seen}  contracts={atom.contracts}')


def main() -> None:
    print(f'page_shape = {PAGE_SHAPE}   (one bucket for every same-template SERP, any domain)')
    store = AtomStore()  # in-memory for the demo

    ad: Spec = {'url': ('a::attr(href)', '.uEierd', 'url'), 'title': ('h3::text', '.uEierd', 'title')}
    organic: Spec = {'url': ('a::attr(href)', '.MjjYud', 'url'), 'title': ('h3::text', '.MjjYud', 'title')}
    search: Spec = {
        'url': ('a::attr(href)', '.MjjYud', 'url'),
        'title': ('h3::text', '.MjjYud', 'title'),
        'snippet': ('.snippet::text', '.MjjYud', 'text'),
    }
    generic: Spec = {'url': ('a::attr(href)', None, 'url')}

    round_(store, '1) AdResult + OrganicResult on google.com', {'AdResult': ad, 'OrganicResult': organic}, 'google.com')
    round_(
        store,
        '2) AdResult + SearchResult (search shares the organic region)',
        {'AdResult': ad, 'SearchResult': search},
        'google.com',
    )
    round_(
        store,
        '3) AdResult + OrganicResult on google.co.uk (same shape, new domain)',
        {'AdResult': ad, 'OrganicResult': organic},
        'google.co.uk',
    )
    round_(
        store,
        '4) Conflated set — both use a bare `a`',
        {'AdResult': generic, 'OrganicResult': {'url': ('a::attr(href)', '.MjjYud', 'url')}},
        'google.com',
    )

    dump(store)
    print('\nTakeaway: SearchResult added ONE atom (snippet) and reused organic url/title;')
    print('a second domain minted nothing; the conflated set was gated out. Contracts are')
    print('queries; the atom corpus is the shared, domain-independent index they draw on.')


if __name__ == '__main__':
    main()
