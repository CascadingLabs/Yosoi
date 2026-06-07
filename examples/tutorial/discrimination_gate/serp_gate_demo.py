"""Discrimination gate (P1.5) on a Google-style SERP — ACCEPT vs REJECT.

The web is the source of truth; a Contract is a *query* over it. On one SERP we run
TWO queries — ``AdResult`` and ``OrganicResult`` — that have the SAME shape
(``{url, title}``) and differ only by intent. Discovery proposes selectors; this
module is the deterministic JUDGE: the two queries are *discriminated* only if their
selectors resolve to DISJOINT sets of DOM elements.

Why it matters: a generic ``a::attr(href)`` *looks* fine — it extracts the ad's URL —
but it also matches every organic anchor, so the two contracts claim overlapping
regions. Internalizing that selector into the durable field-atom index (P2) would bake
in a conflation: ``OrganicResult`` silently serving ad links. The gate catches it
BEFORE internalization (fail closed): reject, re-discover, never cache a conflation.

Run:
    uv run python examples/tutorial/discrimination_gate/serp_gate_demo.py
"""

from __future__ import annotations

from typing import Any

from parsel import Selector

from yosoi.core.discovery.discrimination import evaluate_discrimination

# A minimal Google-style SERP: one sponsored block (.uEierd, first in DOM) and three
# organic results (.MjjYud). The ad anchor is FIRST, so a generic `a` grabs it by luck.
SERP_HTML = """<body>
  <div class="uEierd"><a href="https://buy.example/lp"><h3>Sponsored — Buy Widgets</h3></a></div>
  <div class="MjjYud"><a href="https://en.wikipedia.org/wiki/Widget"><h3>Widget — Wikipedia</h3></a></div>
  <div class="MjjYud"><a href="https://widgets.io/guide"><h3>The Widget Guide</h3></a></div>
  <div class="MjjYud"><a href="https://news.example/widgets"><h3>Widget News</h3></a></div>
</body>"""


def slot(primary: str, root: str | None = None) -> dict[str, Any]:
    """Build a one-field selector map entry: a primary selector + optional region root."""
    entry: dict[str, Any] = {'primary': {'type': 'css', 'value': primary}}
    if root:
        entry['root'] = {'type': 'css', 'value': root}
    return entry


def _extract_urls(smap: dict[str, Any]) -> list[str]:
    """What this contract's ``url`` field actually pulls from the page (root-scoped)."""
    sel = Selector(text=SERP_HTML)
    field = smap['url']
    scope = sel
    root = field.get('root')
    if root:
        roots = sel.css(root['value'])
        if not roots:
            return []
        scope = roots[0]
    return scope.css(field['primary']['value']).getall()


def show(title: str, maps: dict[str, dict[str, Any]]) -> None:
    """Run the gate over a contract set and print the verdict + what each query pulls."""
    print(f'\n{"═" * 78}\n {title}\n{"═" * 78}')
    for name, smap in maps.items():
        urls = _extract_urls(smap)
        print(
            f'  {name:<14} selector={smap["url"]["primary"]["value"]!r:<22} '
            f'root={(smap["url"].get("root") or {}).get("value", "—")!r}'
        )
        print(f'  {"":<14} extracts → {urls}')
    report = evaluate_discrimination(SERP_HTML, maps)
    verdict = '✅ ACCEPTED — safe to internalize' if report.accepted else '⛔ REJECTED — do NOT internalize'
    print(f'\n  gate: {verdict}')
    print(f'  reason:     {report.reason}')
    print(f'  footprints: {report.footprints}   (DOM elements each contract claims)')
    print(f'  overlaps:   {report.overlaps or "{}"}   (shared elements between contracts)')


def main() -> None:
    print('Discrimination gate demo — two contracts ({url, title}) on one SERP.')
    print('The web is the SSoT; each contract is a query; the gate judges region disjointness.')

    # Scenario A — each query rooted in its OWN region: disjoint footprints → ACCEPTED.
    show(
        'A) Properly-rooted queries — ad in .uEierd, organic in .MjjYud',
        {
            'AdResult': {'url': slot('a::attr(href)', root='.uEierd')},
            'OrganicResult': {'url': slot('a::attr(href)', root='.MjjYud')},
        },
    )

    # Scenario B — the "lucky pass": a bare `a` extracts the ad URL fine, but matches
    # EVERY anchor, so AdResult and OrganicResult claim overlapping regions → REJECTED.
    show(
        'B) Generic selector — both queries use a bare `a::attr(href)`',
        {
            'AdResult': {'url': slot('a::attr(href)')},
            'OrganicResult': {'url': slot('a::attr(href)', root='.MjjYud')},
        },
    )

    print(f'\n{"─" * 78}')
    print('Takeaway: B extracts a plausible ad URL, so value-equality would PASS it —')
    print('but the regions overlap, so the gate REJECTS it before it can poison the index.')


if __name__ == '__main__':
    main()
