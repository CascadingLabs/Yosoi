"""Deterministic discrimination + genericity (yosoi.core.discovery.discrimination)."""

from __future__ import annotations

from yosoi.core.discovery.discrimination import discriminated, is_generic, match_count

# A SERP with one sponsored anchor (first in DOM) and three organic anchors.
_HTML = """<body>
  <div class="uEierd"><a href="https://ad.example/lp"><h3>Ad</h3></a></div>
  <div class="MjjYud"><a href="https://o1.example/"><h3>One</h3></a></div>
  <div class="MjjYud"><a href="https://o2.example/"><h3>Two</h3></a></div>
  <div class="MjjYud"><a href="https://o3.example/"><h3>Three</h3></a></div>
</body>"""


def _slot(primary: str, root: str | None = None) -> dict:
    d: dict = {'primary': {'type': 'css', 'value': primary}}
    if root:
        d['root'] = {'type': 'css', 'value': root}
    return d


def test_generic_selector_overlaps_and_fails_discrimination() -> None:
    # The lucky SERP "pass": AdResult.url = bare `a` (matches ALL anchors) vs OrganicResult
    # rooted in .MjjYud (matches organic anchors). Their element sets OVERLAP -> NOT
    # discriminated, even though `a` extracts the ad's href first.
    ad = {'url': _slot('a::attr(href)')}
    organic = {'url': _slot('a::attr(href)', root='.MjjYud')}
    assert discriminated(_HTML, ad, organic) is False


def test_properly_rooted_selectors_are_disjoint_and_discriminated() -> None:
    ad = {'url': _slot('a::attr(href)', root='.uEierd')}
    organic = {'url': _slot('a::attr(href)', root='.MjjYud')}
    assert discriminated(_HTML, ad, organic) is True


def test_identical_selectors_are_not_discriminated() -> None:
    a = {'url': _slot('div.MjjYud a::attr(href)')}
    b = {'url': _slot('div.MjjYud a::attr(href)')}
    assert discriminated(_HTML, a, b) is False


def test_match_count_and_genericity() -> None:
    # bare `a` matches 4 anchors -> generic for a single-record field.
    assert match_count(_HTML, _slot('a::attr(href)')) == 4
    assert is_generic(_HTML, _slot('a::attr(href)')) is True
    # rooted under the ad block it matches exactly 1 -> fingerprinted.
    assert match_count(_HTML, _slot('a::attr(href)', root='.uEierd')) == 1
    assert is_generic(_HTML, _slot('a::attr(href)', root='.uEierd')) is False


def test_mutual_discrimination_across_blocks() -> None:
    from yosoi.core.discovery.discrimination import mutually_discriminated, overlapping_pairs

    ad = {'url': _slot('a::attr(href)', root='.uEierd')}
    organic = {'url': _slot('a::attr(href)', root='.MjjYud')}
    # A third "block" that overlaps organic (generic): matches all anchors.
    generic = {'url': _slot('a::attr(href)')}

    assert mutually_discriminated(_HTML, {'ad': ad, 'organic': organic}) is True
    report = overlapping_pairs(_HTML, {'ad': ad, 'organic': organic, 'generic': generic})
    # 'generic' overlaps BOTH ad and organic; ad vs organic stays clean.
    assert ('ad', 'organic') not in report
    assert report[('ad', 'generic')] >= 1
    assert report[('organic', 'generic')] >= 1
    assert mutually_discriminated(_HTML, {'ad': ad, 'organic': organic, 'generic': generic}) is False


def test_pseudo_element_stripped_to_compare_elements_not_attr_nodes() -> None:
    # `a::attr(href)` and `a` resolve to the SAME elements (the anchors), so two contracts
    # using them in the same region are (correctly) not discriminated.
    a = {'url': _slot('a::attr(href)', root='.uEierd')}
    b = {'url': _slot('a', root='.uEierd')}
    assert discriminated(_HTML, a, b) is False
