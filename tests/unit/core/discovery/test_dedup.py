"""Soft duplicate-selector diagnostics (yosoi.core.discovery.dedup)."""

from __future__ import annotations

from yosoi.core.discovery.dedup import duplicate_fields, maps_collide


def _slot(value: str, root: str | None = None) -> dict:
    d: dict = {'primary': {'type': 'css', 'value': value}}
    if root:
        d['root'] = {'type': 'css', 'value': root}
    return d


def test_duplicate_fields_flags_two_fields_sharing_one_selector() -> None:
    dups = duplicate_fields({'url': _slot('a'), 'title': _slot('a')})
    assert 'a' in dups
    assert sorted(dups['a']) == ['title', 'url']


def test_distinct_selectors_are_not_flagged() -> None:
    assert duplicate_fields({'url': _slot('a::attr(href)'), 'title': _slot('h3')}) == {}


def test_structural_root_field_excluded_and_distinct_roots_disambiguate() -> None:
    # Same leaf 'a' but scoped under different roots -> NOT duplicates (root buys discrimination).
    smap = {'url': _slot('a', root='.MjjYud'), 'title': _slot('a', root='.uEierd'), 'root': _slot('.x')}
    assert duplicate_fields(smap) == {}


def test_maps_collide_when_two_contracts_share_identical_selectors() -> None:
    a = {'url': _slot('a'), 'title': _slot('h3')}
    b = {'url': _slot('a'), 'title': _slot('h3')}
    assert maps_collide(a, b) is True


def test_maps_do_not_collide_when_roots_differ() -> None:
    organic = {'url': _slot('a', root='.MjjYud'), 'title': _slot('h3', root='.MjjYud')}
    ad = {'url': _slot('a', root='.uEierd'), 'title': _slot('h3', root='.uEierd')}
    assert maps_collide(organic, ad) is False


def test_empty_maps_do_not_collide() -> None:
    assert maps_collide({}, {}) is False
    assert maps_collide(None, None) is False
