"""P3 atom-backed reads: unambiguous reuse, fail-closed ambiguity, flag-gated resolve()."""

from __future__ import annotations

from yosoi.core.atom_read import (
    AtomResolution,
    atom_reads_enabled,
    resolve_via_atoms,
    selector_map_from_atoms,
)
from yosoi.core.resolve import resolve
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import page_shape_fp
from yosoi.models.spec import ContractSpec, FieldSpec
from yosoi.storage.atoms import AtomStore, FieldAtom

SHAPE = 's1:abc'


def _atom(region: str, field: str, value: str, yt: str | None = None) -> FieldAtom:
    return FieldAtom(
        page_shape=SHAPE, region_role=region, field_name=field, yosoi_type=yt, selector={'type': 'css', 'value': value}
    )


def test_unambiguous_field_is_a_hit() -> None:
    store = AtomStore()
    store.upsert(_atom('.MjjYud', 'url', 'a::attr(href)', 'url'))
    res = resolve_via_atoms(SHAPE, [('url', 'url')], store)
    assert res.fully_resolved
    assert res.hits['url'].selector['value'] == 'a::attr(href)'


def test_missing_field_is_a_miss() -> None:
    res = resolve_via_atoms(SHAPE, [('snippet', 'text')], AtomStore())
    assert res.misses == ['snippet']
    assert not res.fully_resolved


def test_two_regions_make_a_field_ambiguous_fail_closed() -> None:
    # `url` exists for BOTH an ad region and an organic region → cannot reuse blindly.
    store = AtomStore()
    store.upsert(_atom('.uEierd', 'url', 'a::attr(href)', 'url'))
    store.upsert(_atom('.MjjYud', 'url', 'a::attr(href)', 'url'))
    res = resolve_via_atoms(SHAPE, [('url', 'url')], store)
    assert res.ambiguous == ['url']
    assert 'url' in res.to_discover
    assert not res.fully_resolved


def test_different_shape_never_served() -> None:
    store = AtomStore()
    store.upsert(_atom('.MjjYud', 'url', 'a::attr(href)', 'url'))
    res = resolve_via_atoms('s1:OTHER', [('url', 'url')], store)
    assert res.misses == ['url']  # exact-shape only; near/other shapes refused


def test_selector_map_reconstructs_root_and_handles_rootless() -> None:
    hits = {
        'url': _atom('.MjjYud', 'url', 'a::attr(href)', 'url'),
        'note': _atom('name:Foo', 'note', '.note::text', 'text'),
    }
    smap = selector_map_from_atoms(hits)
    assert smap['url']['root'] == {'type': 'css', 'value': '.MjjYud'}  # case preserved
    assert 'root' not in smap['note']  # name:-scoped → no root


def test_flag_helper(monkeypatch) -> None:
    monkeypatch.delenv('YOSOI_ATOM_READS', raising=False)
    assert atom_reads_enabled() is False
    monkeypatch.setenv('YOSOI_ATOM_READS', '1')
    assert atom_reads_enabled() is True


# ── resolve() integration ──────────────────────────────────────────────────────

_HTML = '<body class="q"><div id="hdr"><h1>AAPL</h1><span class="px">171.52</span></div></body>'


def _quote_spec() -> ContractSpec:
    return ContractSpec(
        name='Quote',
        doc='A stock quote.',
        fields={'symbol': FieldSpec(yosoi_type=None), 'price': FieldSpec(yosoi_type=None)},
    )


def _warm_store() -> AtomStore:
    shape = page_shape_fp(observe_html('https://finance.example/quote/AAPL', _HTML, row_selector=''))
    store = AtomStore()
    store.upsert(
        FieldAtom(
            page_shape=shape,
            region_role='#hdr',
            field_name='symbol',
            yosoi_type=None,
            selector={'type': 'css', 'value': 'h1::text'},
        )
    )
    store.upsert(
        FieldAtom(
            page_shape=shape,
            region_role='#hdr',
            field_name='price',
            yosoi_type=None,
            selector={'type': 'css', 'value': '.px::text'},
        )
    )
    return store


def test_resolve_serves_from_atoms_when_flag_on(monkeypatch) -> None:
    monkeypatch.setenv('YOSOI_ATOM_READS', '1')
    result = resolve(
        _quote_spec(), _HTML, {}, 'finance.example', url='https://finance.example/quote/AAPL', atom_store=_warm_store()
    )
    assert isinstance(result, list)  # extracted, not NeedsDiscovery
    assert result
    assert result[0].get('symbol') == 'AAPL'


def test_resolve_falls_back_to_discovery_when_flag_off(monkeypatch) -> None:
    from yosoi.models.needs_discovery import NeedsDiscovery

    monkeypatch.delenv('YOSOI_ATOM_READS', raising=False)
    result = resolve(
        _quote_spec(), _HTML, {}, 'finance.example', url='https://finance.example/quote/AAPL', atom_store=_warm_store()
    )
    assert isinstance(result, NeedsDiscovery)  # flag off → atoms ignored


def test_resolve_discovers_when_atoms_partial(monkeypatch) -> None:
    from yosoi.models.needs_discovery import NeedsDiscovery

    monkeypatch.setenv('YOSOI_ATOM_READS', '1')
    spec = ContractSpec(
        name='Quote',
        doc='A stock quote.',
        fields={
            'symbol': FieldSpec(yosoi_type=None),
            'price': FieldSpec(yosoi_type=None),
            'volume': FieldSpec(yosoi_type=None),  # no atom → partial → discover
        },
    )
    result = resolve(
        spec, _HTML, {}, 'finance.example', url='https://finance.example/quote/AAPL', atom_store=_warm_store()
    )
    assert isinstance(result, NeedsDiscovery)


def test_atom_resolution_model_defaults() -> None:
    r = AtomResolution()
    assert r.fully_resolved
    assert r.to_discover == []


# ── trust tiers / quarantine ────────────────────────────────────────────────────


def test_strict_mode_quarantines_fingerprint(monkeypatch) -> None:
    from yosoi.core.atom_read import allowed_sources

    monkeypatch.setenv('YOSOI_ATOM_TRUST', 'strict')
    allowed = allowed_sources()
    assert allowed is not None
    assert 'fingerprint' not in allowed
    assert {'verified', 'llm', 'manual'} <= allowed


def test_yellow_mode_lets_it_ride(monkeypatch) -> None:
    from yosoi.core.atom_read import allowed_sources

    monkeypatch.setenv('YOSOI_ATOM_TRUST', 'yellow')
    assert allowed_sources() is None  # all tiers served


def test_trust_mode_defaults_strict(monkeypatch) -> None:
    from yosoi.core.atom_read import atom_trust_mode

    monkeypatch.delenv('YOSOI_ATOM_TRUST', raising=False)
    assert atom_trust_mode() == 'strict'


def test_resolve_filters_quarantined_source() -> None:
    store = AtomStore()
    store.upsert(
        FieldAtom(
            page_shape=SHAPE,
            region_role='.MjjYud',
            field_name='url',
            yosoi_type='url',
            selector={'type': 'css', 'value': 'a::attr(href)'},
            source='fingerprint',
        )
    )
    strict = frozenset({'verified', 'llm', 'manual'})
    # quarantined under strict → invisible → miss → would discover
    assert resolve_via_atoms(SHAPE, [('url', 'url')], store, allowed=strict).misses == ['url']
    # yellow (allowed=None) → served
    assert resolve_via_atoms(SHAPE, [('url', 'url')], store, allowed=None).fully_resolved
