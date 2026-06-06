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


def test_ax_spine_features_survives_raising_accessor() -> None:
    # round-2: a lazy/property-backed snapshot whose .targets RAISES must also degrade to empty,
    # never propagate out of the public of() (real CDP wrappers can be property-backed).
    class _Raises:
        @property
        def targets(self) -> tuple[object, ...]:
            raise RuntimeError('lazy snapshot blew up')

    assert ax_spine_features(_Raises()) == frozenset()
    assert PageFingerprint.of(_page(12), ax_snapshot=_Raises()).ax_spine == frozenset()


def test_known_residue_framework_global_features_vacuously_agree() -> None:
    # KNOWN LIMITATION #2 (documented, not yet fixed): the optional layers can vacuously AGREE on
    # framework-global features that clear the floor but carry no template-discriminating signal.
    # Two STRUCTURALLY DIFFERENT pages that both stamp the same 3 framework-global data-* keys score
    # identity == 1.0 today. This pins the residue so it is visible and flips when the stop-set /
    # down-weighting fix lands. It is currently safe only because fingerprint-tier reuse is
    # strict-quarantined and nothing compares on the read path yet.
    global_keys = ('data-mw', 'data-ooui', 'data-cx')  # present on every page of the framework
    a = PageFingerprint.of(_page(8, *global_keys))  # a card listing
    article = (  # a structurally DIFFERENT template carrying the same framework-global keys
        '<html lang="en"><head><title>t</title></head><body><header><nav><a>h</a></nav></header>'
        '<main><article data-mw="x" data-ooui="x" data-cx="x">'
        + ''.join(f'<section><h2>S{i}</h2><p>p{i}</p><table><tr><td>{i}</td></tr></table></section>' for i in range(20))
        + '</article></main><footer>f</footer></body></html>'
    )
    b = PageFingerprint.of(article)
    sim = a.similarity(b)
    assert sim.skeleton < 1.0  # the structures genuinely differ
    assert sim.identity == 1.0  # <-- residue: identity vacuously AGREES on the non-discriminating keys


def test_ax_layer_vetoes_when_both_carry_and_disagree() -> None:
    # identical static structure, but the RENDERED AX spines disagree → conjunctive veto
    a = PageFingerprint.of(_page(12), ax_snapshot=_ax('main', 'navigation', 'article'))
    b = PageFingerprint.of(_page(12), ax_snapshot=_ax('form', 'button', 'textbox', 'checkbox'))
    sim = a.similarity(b)
    assert sim.skeleton >= 0.40
    assert sim.ax is not None
    assert sim.ax < 0.50
    assert not sim.same_shape


# ── matches() symmetry over the optional layers ──────────────────────────────


def test_matches_symmetric_identity_disagree() -> None:
    # Both carry identity but in disjoint namespaces → veto, and the verdict must not
    # depend on argument order (the conjunction is symmetric).
    a = PageFingerprint.of(_page(12, *_NS_A))
    b = PageFingerprint.of(_page(12, *_NS_B))
    assert a.matches(b) == b.matches(a)
    assert a.matches(b) is False


def test_matches_symmetric_ax_disagree() -> None:
    a = PageFingerprint.of(_page(12), ax_snapshot=_ax('main', 'navigation', 'article'))
    b = PageFingerprint.of(_page(12), ax_snapshot=_ax('form', 'button', 'textbox', 'checkbox'))
    assert a.matches(b) == b.matches(a)
    assert a.matches(b) is False


def test_matches_symmetric_one_side_thin_identity() -> None:
    # One side carries a substantive identity layer, the other carries none. The optional
    # layer abstains regardless of which side is the receiver → verdict is order-independent.
    rich = PageFingerprint.of(_page(12, *_NS_A))
    thin = PageFingerprint.of(_page(12))  # no data-* → identity not carried
    assert rich.matches(thin) == thin.matches(rich)
    # structure agrees and the optional layer abstains → matches on L1 alone
    assert rich.matches(thin) is True
    assert rich.similarity(thin).identity is None
    assert thin.similarity(rich).identity is None


def test_matches_symmetric_one_side_thin_ax() -> None:
    rich = PageFingerprint.of(_page(12), ax_snapshot=_ax('main', 'navigation', 'article'))
    thin = PageFingerprint.of(_page(12))  # static → no AX spine
    assert rich.matches(thin) == thin.matches(rich)
    assert rich.matches(thin) is True
    assert rich.similarity(thin).ax is None
    assert thin.similarity(rich).ax is None


# ── threshold overrides actually move the optional-layer verdict ──────────────


def test_identity_threshold_override_flips_verdict() -> None:
    # Two pages that share SOME but not all of their data-* namespace: a partial identity
    # Jaccard that a strict threshold rejects and a lenient one accepts. The override is the
    # only thing that changes; structure is held identical so identity alone decides.
    shared = ('data-testid', 'data-component')
    a = PageFingerprint.of(_page(12, *shared, 'data-state'))  # 3 keys
    b = PageFingerprint.of(_page(12, *shared, 'data-flag'))  # 3 keys, 2 shared
    sim = a.similarity(b)
    assert sim.identity is not None  # both substantively carried
    part = sim.identity
    assert 0.0 < part < 1.0  # partial overlap (2 shared of 4 union = 0.5)
    # a threshold below the partial score passes; one above it vetoes — same pair, same structure
    assert a.matches(b, identity_threshold=part - 0.01) is True
    assert a.matches(b, identity_threshold=part + 0.01) is False


def test_ax_threshold_override_flips_verdict() -> None:
    # Same structure, AX role SETS that overlap partially (2 shared of 4 union = 0.5) so the ax
    # Jaccard sits strictly between 0 and 1; the threshold override is the sole deciding lever.
    a = PageFingerprint.of(_page(12), ax_snapshot=_ax('navigation', 'main', 'article'))
    b = PageFingerprint.of(_page(12), ax_snapshot=_ax('navigation', 'main', 'form'))
    sim = a.similarity(b)
    assert sim.ax is not None
    part = sim.ax
    assert 0.0 < part < 1.0  # partial role-set overlap
    assert a.matches(b, ax_threshold=part - 0.01) is True
    assert a.matches(b, ax_threshold=part + 0.01) is False


# ── floor boundary: exactly 3 features carries, exactly 2 abstains ────────────


def test_identity_floor_boundary_three_carries_two_abstains() -> None:
    # The optional-layer thinness floor is 3 features. Exactly 3 distinct data-* keys must be
    # SUBSTANTIVELY carried (votes); exactly 2 must ABSTAIN (None), even on a self-compare where
    # the raw Jaccard would be a vacuous 1.0.
    three = PageFingerprint.of(_page(12, 'data-a', 'data-b', 'data-c'))
    two = PageFingerprint.of(_page(12, 'data-a', 'data-b'))
    assert len(three.identity) == 3
    assert len(two.identity) == 2
    # exactly at the floor → carried (a self-compare scores 1.0 and is reported, not abstained)
    assert three.similarity(three).identity == 1.0
    # one below the floor → abstains rather than vacuously passing
    assert two.similarity(two).identity is None
    # and a 3-vs-2 compare abstains too: the layer is only carried when BOTH sides clear the floor
    assert three.similarity(two).identity is None


def test_ax_floor_boundary_three_roles_carries_two_abstains() -> None:
    # ax_spine is one feature per distinct role, so the thinness floor counts distinct roles
    # uniformly with the identity layer: 3 roles carries, 2 abstains.
    three = PageFingerprint.of(_page(12), ax_snapshot=_ax('main', 'navigation', 'article'))
    two = PageFingerprint.of(_page(12), ax_snapshot=_ax('main', 'navigation'))
    assert len(three.ax_spine) == 3
    assert len(two.ax_spine) == 2
    assert three.similarity(three).ax == 1.0  # carried at the boundary
    assert two.similarity(two).ax is None  # below floor → abstain


# ── ax spine is a ROLE SET → fully volume-invariant (no count bands) ──────────


def test_ax_spine_is_volume_invariant() -> None:
    # Same roles, wildly different row COUNT → identical spine. A role SET (not a multiset) carries
    # no count, so volume can never split or veto — same principle as the skeleton set.
    a = PageFingerprint.of(_page(12), ax_snapshot=_ax('navigation', 'main', 'listitem'))
    b = PageFingerprint.of(_page(12), ax_snapshot=_ax('navigation', 'main', *(['listitem'] * 50)))
    sim = a.similarity(b)
    assert sim.ax == 1.0  # role set unchanged by volume
    assert sim.same_shape


# ── degenerate veto dominates: a rich optional layer cannot rescue a thin page ─


def _degenerate_html() -> str:
    # Fewer than the minimum structural shingles → fingerprint.degenerate is True.
    return '<html><body><p>hi</p></body></html>'


def test_degenerate_page_never_matches_despite_rich_ax() -> None:
    # A too-thin page carrying a rich (4-role) AX spine that scores a perfect self-Jaccard still
    # must NOT match itself: the skeleton/degenerate veto dominates, optional layers can't rescue it.
    fp = PageFingerprint.of(_degenerate_html(), ax_snapshot=_ax('main', 'navigation', 'article', 'form'))
    assert fp.degenerate
    assert len(fp.ax_spine) == 4  # rich optional layer present (one feature per distinct role)
    sim = fp.similarity(fp)
    assert sim.ax == 1.0  # the optional layer would otherwise agree perfectly
    assert sim.skeleton == 1.0  # and the skeleton self-Jaccard is vacuously 1.0
    assert sim.same_shape is False  # but degeneracy fails closed regardless
    assert fp.matches(fp) is False


def test_degenerate_page_never_matches_despite_rich_identity() -> None:
    deg_html = '<html><body><p data-a="x" data-b="x" data-c="x" data-d="x">hi</p></body></html>'
    fp = PageFingerprint.of(deg_html)
    assert fp.degenerate
    assert len(fp.identity) >= 3  # substantively-carried identity layer
    sim = fp.similarity(fp)
    assert sim.identity == 1.0
    assert sim.same_shape is False
    assert fp.matches(fp) is False
