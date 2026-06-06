"""L1 identity-attribute layer + the waterfall 'compare on the common layer' rule."""

from __future__ import annotations

from yosoi.generalization.fingerprint import PageFingerprint, identity_jaccard, page_identity


def _rows(n: int, data_key: str | None = None) -> str:
    da = f' {data_key}="x"' if data_key else ''
    return ''.join(
        f'<article class="card"{da}><h3><a href="/i/{i}">Item {i}</a></h3><p class="price">{i}</p></article>'
        for i in range(n)
    )


def _page(n: int, data_key: str | None = None) -> str:
    return (
        '<html lang="en"><head><title>t</title></head><body>'
        '<header><nav><a>h</a></nav></header>'
        f'<main><section><ol class="row">{_rows(n, data_key)}</ol></section></main>'
        '<footer>f</footer></body></html>'
    )


def test_identity_collects_data_keys_not_values_nor_ids() -> None:
    html = '<html><body><div id="History" data-testid="row" data-mw="x">a</div></body></html>'
    idn = page_identity(html)
    assert idn == frozenset({'data:data-testid', 'data:data-mw'})
    # the id VALUE ('History') is content-derived → never included; only data-* KEYS
    assert not any('History' in t for t in idn)
    # values aren't taken either — 'row'/'x' must not appear
    assert not any(v in t for t in idn for v in ('row', ':x'))


def test_identity_empty_when_no_data_attrs() -> None:
    assert page_identity('<html><body><div id="x"><p>hi</p></div></body></html>') == frozenset()


def test_identity_jaccard_disjoint_namespaces() -> None:
    assert identity_jaccard(_page(12, 'data-testid'), _page(12, 'data-qa')) == 0.0


def test_fingerprint_default_identity_is_empty() -> None:
    # backward-compat: constructing without identity (the pre-waterfall shape) defaults to "not carried"
    fp = PageFingerprint(skeleton=frozenset(f's{i}' for i in range(10)), semantic=frozenset({'lm:main'}))
    assert fp.identity == frozenset()


def test_identity_layer_skipped_when_not_carried_by_both() -> None:
    # one page exposes data-* attrs, the other doesn't → identity is None and never decides the match
    a = PageFingerprint.of(_page(12, 'data-testid'))
    b = PageFingerprint.of(_page(12, None))
    sim = a.similarity(b)
    assert sim.identity is None  # not carried by both → layer absent
    assert sim.same_shape  # same structure → matches on skeleton+semantic alone


def test_identity_layer_vetoes_when_both_carry_and_disagree() -> None:
    # identical STRUCTURE (skeleton+semantic would merge) but DIFFERENT data-* namespaces → veto.
    a = PageFingerprint.of(_page(12, 'data-testid'))
    b = PageFingerprint.of(_page(12, 'data-qa'))
    sim = a.similarity(b)
    assert sim.skeleton >= 0.40  # structure agrees
    assert sim.semantic >= 0.50
    assert sim.identity == 0.0  # but the high-trust identity layer disagrees
    assert not sim.same_shape  # → conjunctive veto, fail closed


def test_identity_layer_passes_when_both_carry_and_agree() -> None:
    a = PageFingerprint.of(_page(12, 'data-testid'))
    b = PageFingerprint.of(_page(30, 'data-testid'))  # same template + same data namespace, more rows
    sim = a.similarity(b)
    assert sim.identity == 1.0
    assert sim.same_shape
