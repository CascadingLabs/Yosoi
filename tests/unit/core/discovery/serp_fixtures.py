"""High-signal SERP fixtures for discrimination-gate regression tests.

Each :class:`GateScenario` pairs a realistic SERP-shaped HTML document with a named
set of contract selector maps and the EXPECTED gate verdict. They exist so a change
that silently weakens region discrimination — the bug that lets an ``AdResult``
selector quietly serve organic links — is caught by a failing assertion, not in
production.

The HTML uses real-world-ish container classes (Google ``uEierd``/``MjjYud``/``VkpGBb``,
Bing ``b_ad``/``b_algo``) so the fixtures read like the pages they stand in for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def slot(primary: str, root: str | None = None) -> dict[str, Any]:
    """One field's selector map entry: a primary selector + optional region root."""
    entry: dict[str, Any] = {'primary': {'type': 'css', 'value': primary}}
    if root:
        entry['root'] = {'type': 'css', 'value': root}
    return entry


# ── HTML fixtures ──────────────────────────────────────────────────────────────

# Google-style SERP: a shared page <h1>, one sponsored block (.uEierd, FIRST in DOM),
# three organic results (.MjjYud), a local pack (.VkpGBb), and a shopping unit
# (.sh-dlr__list-result with a price). The ad anchor being first is what lets a generic
# `a` "pass" by luck while actually claiming every anchor.
GOOGLE_SERP = """<body>
  <h1 id="page-title">widgets - Google Search</h1>
  <div id="rso">
    <div class="uEierd"><span>Sponsored</span><a href="https://buy.example/lp"><h3>Buy Widgets Online</h3></a></div>
    <div class="MjjYud"><div class="yuRUbf"><a href="https://en.wikipedia.org/wiki/Widget"><h3>Widget - Wikipedia</h3></a></div></div>
    <div class="MjjYud"><div class="yuRUbf"><a href="https://widgets.io/guide"><h3>The Widget Guide</h3></a></div></div>
    <div class="MjjYud"><div class="yuRUbf"><a href="https://news.example/widgets"><h3>Widget News</h3></a></div></div>
    <div class="VkpGBb"><a href="https://maps.example/widget-store"><span class="dbg0pd">Widget Store</span></a></div>
    <div class="sh-dlr__list-result"><a href="https://shop.example/widget-x"><span class="a8Pemb">$19.99</span></a></div>
  </div>
</body>"""

# Bing-style SERP: sponsored (.b_ad) and organic (.b_algo) list items.
BING_SERP = """<body>
  <ol id="b_results">
    <li class="b_ad"><div class="sb_add"><h2><a href="https://buy.example/bing-lp">Buy Widgets - Ad</a></h2></div></li>
    <li class="b_algo"><h2><a href="https://en.wikipedia.org/wiki/Widget">Widget - Wikipedia</a></h2></li>
    <li class="b_algo"><h2><a href="https://widgets.io/guide">The Widget Guide</a></h2></li>
  </ol>
</body>"""

# Shared-class trap: BOTH the ad and the organic results are wrapped in the SAME
# coarse class `.g`, with the real distinction one level deeper (.ad-tag vs .organic).
# Rooting on `.g` therefore CANNOT separate them — a tempting but wrong region key.
SHARED_CLASS_SERP = """<body>
  <div class="g ad-tag"><a href="https://buy.example/lp"><h3>Ad</h3></a></div>
  <div class="g organic"><a href="https://en.wikipedia.org/wiki/Widget"><h3>One</h3></a></div>
  <div class="g organic"><a href="https://widgets.io/guide"><h3>Two</h3></a></div>
</body>"""


# ── scenarios ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateScenario:
    """One regression case: HTML + contract maps + the expected gate verdict."""

    name: str
    html: str
    maps: dict[str, dict[str, Any]]
    expected_accepted: bool
    note: str


SCENARIOS: list[GateScenario] = [
    GateScenario(
        name='google_rooted_disjoint_2way',
        html=GOOGLE_SERP,
        maps={
            'AdResult': {'url': slot('a::attr(href)', root='.uEierd')},
            'OrganicResult': {'url': slot('a::attr(href)', root='.MjjYud')},
        },
        expected_accepted=True,
        note='Each query rooted in its own region — disjoint footprints.',
    ),
    GateScenario(
        name='google_generic_overlap',
        html=GOOGLE_SERP,
        maps={
            'AdResult': {'url': slot('a::attr(href)')},  # bare `a` grabs every anchor
            'OrganicResult': {'url': slot('a::attr(href)', root='.MjjYud')},
        },
        expected_accepted=False,
        note='The "lucky pass": a bare `a` extracts the ad URL but matches all anchors.',
    ),
    GateScenario(
        name='google_identical_selectors',
        html=GOOGLE_SERP,
        maps={
            'A': {'url': slot('.MjjYud a::attr(href)')},
            'B': {'url': slot('.MjjYud a::attr(href)')},
        },
        expected_accepted=False,
        note='Identical selectors → identical footprints → never disjoint.',
    ),
    GateScenario(
        name='google_empty_footprint',
        html=GOOGLE_SERP,
        maps={
            'OrganicResult': {'url': slot('a::attr(href)', root='.MjjYud')},
            'Ghost': {'url': slot('a::attr(href)', root='.does-not-exist')},
        },
        expected_accepted=False,
        note='A region that matches nothing cannot be discriminated (empty footprint).',
    ),
    GateScenario(
        name='google_threeway_disjoint',
        html=GOOGLE_SERP,
        maps={
            'AdResult': {'url': slot('a::attr(href)', root='.uEierd')},
            'OrganicResult': {'url': slot('a::attr(href)', root='.MjjYud')},
            'LocalPack': {'url': slot('a::attr(href)', root='.VkpGBb')},
        },
        expected_accepted=True,
        note='Three regions, pairwise disjoint — N-way discrimination.',
    ),
    GateScenario(
        name='google_threeway_one_overlap',
        html=GOOGLE_SERP,
        maps={
            'AdResult': {'url': slot('a::attr(href)', root='.uEierd')},
            'OrganicResult': {'url': slot('a::attr(href)', root='.MjjYud')},
            'LocalPack': {'url': slot('a::attr(href)')},  # generic — overlaps the others
        },
        expected_accepted=False,
        note='One generic selector in an N-way set fails the whole set.',
    ),
    GateScenario(
        name='google_heterogeneous_fields_disjoint',
        html=GOOGLE_SERP,
        maps={
            'OrganicResult': {'url': slot('a::attr(href)', root='.MjjYud')},
            'ShoppingResult': {'price': slot('.a8Pemb::text', root='.sh-dlr__list-result')},
        },
        expected_accepted=True,
        note='Heterogeneous contracts (different field names) still discriminate by region.',
    ),
    GateScenario(
        name='google_multifield_partial_overlap',
        html=GOOGLE_SERP,
        maps={
            'AdResult': {
                'url': slot('a::attr(href)', root='.uEierd'),
                'title': slot('#page-title::text'),  # shared page header — overlaps
            },
            'OrganicResult': {
                'url': slot('a::attr(href)', root='.MjjYud'),
                'title': slot('#page-title::text'),  # same shared header
            },
        },
        expected_accepted=False,
        note='url fields are disjoint but title fields share the page <h1> → reject.',
    ),
    GateScenario(
        name='bing_rooted_disjoint',
        html=BING_SERP,
        maps={
            'AdResult': {'url': slot('a::attr(href)', root='.b_ad')},
            'OrganicResult': {'url': slot('a::attr(href)', root='.b_algo')},
        },
        expected_accepted=True,
        note='Same gate works on a different engine (Bing class names).',
    ),
    GateScenario(
        name='shared_coarse_class_trap',
        html=SHARED_CLASS_SERP,
        maps={
            'AdResult': {'url': slot('a::attr(href)', root='.g')},
            'OrganicResult': {'url': slot('a::attr(href)', root='.g')},
        },
        expected_accepted=False,
        note='A too-coarse shared class (.g) roots BOTH — discrimination needs the deeper class.',
    ),
]
