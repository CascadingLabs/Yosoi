"""L1 identity-attribute layer + L2 rendered-AX layer + the waterfall 'common layer' rule."""

from __future__ import annotations

from dataclasses import dataclass

from yosoi.generalization.fingerprint import (
    PageFingerprint,
    ax_spine_features,
    identity_jaccard,
    page_identity,
)


def _rows(n: int, data_keys: tuple[str, ...] = ()) -> str:
    da = ''.join(f' {k}="x"' for k in data_keys)
    return ''.join(
        f'<article class="card"{da}><h3><a href="/i/{i}">Item {i}</a></h3><p class="price">{i}</p></article>'
        for i in range(n)
    )


def _page(n: int, *data_keys: str) -> str:
    # data_keys: zero or more data-* attribute names stamped on every row (the identity layer).
    return (
        '<html lang="en"><head><title>t</title></head><body>'
        '<header><nav><a>h</a></nav></header>'
        f'<main><section><ol class="row">{_rows(n, data_keys)}</ol></section></main>'
        '<footer>f</footer></body></html>'
    )


# Three distinct data-* namespaces → identity layer is substantively carried (>= the thinness floor).
_NS_A = ('data-testid', 'data-component', 'data-state')
_NS_B = ('data-qa', 'data-widget', 'data-flag')


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
    assert identity_jaccard(_page(12, *_NS_A), _page(12, *_NS_B)) == 0.0


def test_fingerprint_default_identity_is_empty() -> None:
    # backward-compat: constructing without identity (the pre-waterfall shape) defaults to "not carried"
    fp = PageFingerprint(skeleton=frozenset(f's{i}' for i in range(10)), semantic=frozenset({'lm:main'}))
    assert fp.identity == frozenset()


def test_identity_layer_skipped_when_not_carried_by_both() -> None:
    # one page exposes data-* attrs, the other doesn't → identity is None and never decides the match
    a = PageFingerprint.of(_page(12, *_NS_A))
    b = PageFingerprint.of(_page(12))
    sim = a.similarity(b)
    assert sim.identity is None  # not carried by both → layer absent
    assert sim.same_shape  # same structure → matches on skeleton+semantic alone


def test_identity_layer_vetoes_when_both_carry_and_disagree() -> None:
    # identical STRUCTURE (skeleton+semantic would merge) but DIFFERENT data-* namespaces → veto.
    a = PageFingerprint.of(_page(12, *_NS_A))
    b = PageFingerprint.of(_page(12, *_NS_B))
    sim = a.similarity(b)
    assert sim.skeleton >= 0.40  # structure agrees
    assert sim.semantic >= 0.50
    assert sim.identity == 0.0  # but the high-trust identity layer disagrees
    assert not sim.same_shape  # → conjunctive veto, fail closed


def test_identity_layer_passes_when_both_carry_and_agree() -> None:
    a = PageFingerprint.of(_page(12, *_NS_A))
    b = PageFingerprint.of(_page(30, *_NS_A))  # same template + same data namespace, more rows
    sim = a.similarity(b)
    assert sim.identity == 1.0
    assert sim.same_shape


# ── L2 rendered AX-spine layer (WF0: fed from a browser tier's ax_snapshot) ───────────────────


@dataclass
class _FakeAxTarget:
    role: str
    name: str


@dataclass
class _FakeAxSnapshot:
    targets: tuple[_FakeAxTarget, ...]


def _ax(*roles: str) -> _FakeAxSnapshot:
    # names are content; the spine must depend only on roles + banded counts
    return _FakeAxSnapshot(targets=tuple(_FakeAxTarget(role=r, name=f'n{i}') for i, r in enumerate(roles)))


def test_ax_spine_is_role_only_content_free() -> None:
    feats = ax_spine_features(_ax('navigation', 'main', 'article'))
    assert {'ax:navigation', 'ax:main', 'ax:article'} <= feats
    # no node NAME ('n0'/'n1'/...) ever leaks into the spine
    assert not any(t.startswith('ax:n') and t[3:].isdigit() for t in feats)


def test_ax_spine_empty_for_none_or_no_targets() -> None:
    assert ax_spine_features(None) == frozenset()
    assert ax_spine_features(_FakeAxSnapshot(targets=())) == frozenset()


def test_of_carries_ax_layer_only_when_snapshot_passed() -> None:
    html = _page(12)
    assert PageFingerprint.of(html).ax_spine == frozenset()  # static fetch → layer not carried
    assert PageFingerprint.of(html, ax_snapshot=_ax('main', 'navigation')).ax_spine  # browser tier → carried


def test_ax_layer_skipped_when_not_carried_by_both() -> None:
    a = PageFingerprint.of(_page(12), ax_snapshot=_ax('main', 'navigation'))
    b = PageFingerprint.of(_page(12))  # static, no AX
    sim = a.similarity(b)
    assert sim.ax is None  # not carried by both → never decides
    assert sim.same_shape  # matches on L1 alone


def test_thin_optional_layers_abstain_not_vacuously_pass() -> None:
    # Round-1 review finding: two pages each carrying a SINGLE shared data-* key (or a 1-role AX
    # spine) must NOT score a vacuous Jaccard 1.0 and rubber-stamp a match — the layer is too thin
    # to be a trustworthy veto, so it abstains (None).
    a = PageFingerprint.of(_page(12, 'data-x'))  # one data-key → below the floor
    b = PageFingerprint.of(_page(12, 'data-x'))
    assert len(a.identity) < 3
    assert a.similarity(b).identity is None  # abstains, does not report 1.0

    a_ax = PageFingerprint.of(_page(12), ax_snapshot=_ax('main'))  # 1-role spine → below floor
    b_ax = PageFingerprint.of(_page(12), ax_snapshot=_ax('main'))
    assert a_ax.similarity(b_ax).ax is None


def test_ax_spine_features_survives_malformed_snapshot() -> None:
    # duck-typed input: a non-iterable .targets must degrade to empty, never raise into of()
    @dataclass
    class _Bad:
        targets: int

    assert ax_spine_features(_Bad(targets=42)) == frozenset()
    assert PageFingerprint.of(_page(12), ax_snapshot=_Bad(targets=42)).ax_spine == frozenset()


def test_ax_layer_vetoes_when_both_carry_and_disagree() -> None:
    # identical static structure, but the RENDERED AX spines disagree → conjunctive veto
    a = PageFingerprint.of(_page(12), ax_snapshot=_ax('main', 'navigation', 'article'))
    b = PageFingerprint.of(_page(12), ax_snapshot=_ax('form', 'button', 'textbox', 'checkbox'))
    sim = a.similarity(b)
    assert sim.skeleton >= 0.40
    assert sim.ax is not None
    assert sim.ax < 0.50
    assert not sim.same_shape
