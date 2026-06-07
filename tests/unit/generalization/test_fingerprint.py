"""Tests for page observations, structural signals, and the HTML adapter."""

import pytest
from parsel import Selector

from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import (
    ElementObservation,
    PageObservation,
    filter_class_tokens,
    observe_element,
    structural_signals,
    tag_cosine,
)

pytestmark = pytest.mark.unit


def test_tag_cosine_identical_is_one() -> None:
    """Identical histograms are maximally similar."""
    h = {'div': 10, 'a': 5}
    assert tag_cosine(h, h) == pytest.approx(1.0)


def test_tag_cosine_is_magnitude_invariant() -> None:
    """Proportional histograms (a scaled-down listing) are ~identical in shape."""
    big = {'div': 54, 'span': 69, 'a': 43, 'blockquote': 10}
    small = {'div': 18, 'span': 23, 'a': 14, 'blockquote': 3}
    assert tag_cosine(big, small) > 0.99


def test_tag_cosine_disjoint_is_zero() -> None:
    """No shared tags -> zero similarity."""
    assert tag_cosine({'div': 1}, {'article': 1}) == 0.0


def test_tag_cosine_both_empty_is_one() -> None:
    """Two empty histograms are vacuously identical."""
    assert tag_cosine({}, {}) == 1.0


def test_tag_cosine_one_empty_is_zero() -> None:
    """Exactly one empty histogram is maximally dissimilar."""
    assert tag_cosine({'div': 1}, {}) == 0.0


def test_kind_tokens_strip_flavor() -> None:
    """Sort/filter flavor tokens are removed so sorts of one kind compare equal."""
    obs = PageObservation(url='https://x.com/', body_class='listing-page top-page')
    assert obs.kind_tokens() == frozenset({'listing-page'})


def test_link_density_and_prose_share() -> None:
    """Scalars are tag-share fractions in [0, 1]."""
    obs = PageObservation(url='https://x.com/', tag_hist={'a': 4, 'p': 4, 'div': 2})
    assert obs.link_density() == pytest.approx(0.4)
    assert obs.prose_share() == pytest.approx(0.4)


def test_structural_signals_rows_ratio_two_sided() -> None:
    """rows_ratio is min/max so it penalises both too-few and too-many rows."""
    seed = PageObservation(url='https://x.com/', rows=10, tag_hist={'div': 1})
    replay = PageObservation(url='https://x.com/p/2', rows=3, tag_hist={'div': 1})
    sig = structural_signals(seed, replay)
    assert sig.rows_ratio == pytest.approx(0.3)
    assert sig.rows_seed == 10
    assert sig.rows_replay == 3


def test_structural_signals_zero_rows_ratio() -> None:
    """A zero-row replay against a populated seed has ratio 0."""
    seed = PageObservation(url='https://x.com/', rows=10, tag_hist={'div': 1})
    replay = PageObservation(url='https://x.com/x', rows=0, tag_hist={'div': 1})
    assert structural_signals(seed, replay).rows_ratio == 0.0


def test_observe_html_counts_rows_and_tags() -> None:
    """observe_html parses title, body-class, row count, and tag histogram."""
    html = (
        '<html><head><title>T</title></head>'
        '<body class="listing-page top-page">'
        '<div class="q"><a>x</a></div><div class="q"><a>y</a></div>'
        '</body></html>'
    )
    obs = observe_html('https://x.com/', html, row_selector='.q')
    assert obs.title == 'T'
    assert obs.body_class == 'listing-page top-page'
    assert obs.rows == 2
    assert obs.tag_hist['div'] == 2
    assert obs.tag_hist['a'] == 2


def test_observe_html_bad_selector_yields_zero_rows() -> None:
    """A malformed row selector degrades to zero rows, not an exception."""
    obs = observe_html('https://x.com/', '<html><body><p>hi</p></body></html>', row_selector='::::')
    assert obs.rows == 0


# ---------------------------------------------------------------------------
# ElementObservation + observe_element tests (CAS-141)
# ---------------------------------------------------------------------------

_PRICE_HTML = (
    '<html><body>'
    '<div class="product-card">'
    '<span id="price" data-testid="price-display" class="price css-1a2b3c">$9.99</span>'
    '</div>'
    '</body></html>'
)


def test_observe_element_captures_tag_identity_and_text() -> None:
    """observe_element extracts tag, stable identity attrs, and text content."""
    sel = Selector(text=_PRICE_HTML)
    obs = observe_element(sel.css('span#price')[0])
    assert obs.tag == 'span'
    assert obs.identity_attrs == {'id': 'price', 'data-testid': 'price-display'}
    assert obs.text == '$9.99'


def test_observe_element_drops_hash_shaped_class_tokens() -> None:
    """CSS-in-JS hash tokens are stripped; semantic tokens are kept."""
    sel = Selector(text=_PRICE_HTML)
    obs = observe_element(sel.css('span#price')[0])
    assert 'price' in obs.class_tokens
    assert not any('css' in t and any(c.isdigit() for c in t) for t in obs.class_tokens)


def test_observe_element_captures_ancestry() -> None:
    """ancestry is the root-to-node tag chain."""
    sel = Selector(text=_PRICE_HTML)
    obs = observe_element(sel.css('span#price')[0])
    assert obs.ancestry == ('html', 'body', 'div')
    assert obs.parent_tag == 'div'


def test_observe_element_captures_siblings() -> None:
    """siblings captures preceding and following element tags."""
    html = '<html><body><ul><li>a</li><li id="mid">b</li><li>c</li></ul></body></html>'
    sel = Selector(text=html)
    obs = observe_element(sel.css('li#mid')[0])
    assert 'li' in obs.siblings


def test_filter_class_tokens_keeps_semantic_drops_hashes() -> None:
    """Semantic tokens survive; CSS-in-JS hash tokens are removed."""
    tokens = filter_class_tokens('price label sc-abc12 css-a1b2c3 MuiChip-root')
    assert 'price' in tokens
    assert 'label' in tokens
    assert not any('abc12' in t or 'a1b2c3' in t for t in tokens)


def test_filter_class_tokens_pure_word_tokens_kept() -> None:
    """Pure word tokens with no digits are never dropped."""
    tokens = filter_class_tokens('listing-page top-page product')
    assert tokens == frozenset({'listing-page', 'top-page', 'product'})


def test_observe_element_no_identity_attrs_when_absent() -> None:
    """A plain element with no id/data-testid yields empty identity_attrs."""
    html = '<html><body><p class="note">hello</p></body></html>'
    obs = observe_element(Selector(text=html).css('p')[0])
    assert obs.identity_attrs == {}
    assert obs.text == 'hello'


def test_element_observation_roundtrip_json() -> None:
    """ElementObservation serialises and deserialises via model_dump_json."""
    orig = ElementObservation(
        tag='span',
        identity_attrs={'id': 'price'},
        class_tokens=frozenset({'price', 'bold'}),
        text='$9.99',
        ancestry=('html', 'body', 'div'),
        siblings=('li', 'li'),
        parent_tag='div',
    )
    restored = ElementObservation.model_validate_json(orig.model_dump_json())
    assert restored.tag == 'span'
    assert restored.identity_attrs == {'id': 'price'}
    assert restored.class_tokens == frozenset({'price', 'bold'})
    assert restored.ancestry == ('html', 'body', 'div')


# ── page_shape_fp (P1: coarse structural bucket, URL-independent) ───────────────


def _serp_html(n_results: int, *, tld: str, body_class: str = 'serp results-page') -> str:
    """A minimal SERP-shaped doc: a fixed tag vocabulary, N repeating result rows."""
    rows = ''.join(
        f'<div class="result"><a href="https://x{i}.{tld}">title {i}</a><span>snippet</span></div>'
        for i in range(n_results)
    )
    return f'<html><head><title>q - search</title></head><body class="{body_class}"><div id="main">{rows}</div></body></html>'


def test_page_shape_same_template_same_bucket() -> None:
    """Same template on two hosts (google.com vs google.co.uk) → one shape bucket."""
    from yosoi.generalization.fingerprint import page_shape_fp

    a = page_shape_fp(observe_html('https://google.com/search?q=x', _serp_html(10, tld='com'), row_selector=''))
    b = page_shape_fp(observe_html('https://google.co.uk/search?q=x', _serp_html(10, tld='co.uk'), row_selector=''))
    assert a == b


def test_page_shape_robust_to_row_count_drift() -> None:
    """10 vs 30 results on the same template stay in one bucket (counts excluded)."""
    from yosoi.generalization.fingerprint import page_shape_fp

    few = page_shape_fp(observe_html('https://google.com/search?q=x', _serp_html(10, tld='com'), row_selector=''))
    many = page_shape_fp(observe_html('https://google.com/search?q=y', _serp_html(30, tld='com'), row_selector=''))
    assert few == many


def test_page_shape_different_template_different_bucket() -> None:
    """A structurally different page (different tag vocabulary) splits buckets."""
    from yosoi.generalization.fingerprint import page_shape_fp

    serp = page_shape_fp(observe_html('https://google.com/search?q=x', _serp_html(10, tld='com'), row_selector=''))
    article_html = (
        '<html><head><title>Story</title></head><body class="article-page">'
        '<article><h1>Headline</h1><p>para one</p><p>para two</p><p>para three</p>'
        '<blockquote>quote</blockquote><cite>src</cite></article></body></html>'
    )
    article = page_shape_fp(observe_html('https://news.example.com/story', article_html, row_selector=''))
    assert serp != article


def test_page_shape_page_kind_splits_bucket() -> None:
    """Same tags but a different page-kind body class → different bucket."""
    from yosoi.generalization.fingerprint import page_shape_fp

    listing = page_shape_fp(
        observe_html('https://x.com/a', _serp_html(10, tld='com', body_class='listing-page'), row_selector='')
    )
    profile = page_shape_fp(
        observe_html('https://x.com/b', _serp_html(10, tld='com', body_class='profile-page'), row_selector='')
    )
    assert listing != profile


def test_page_shape_degenerate_sentinel() -> None:
    """A too-thin page returns the degenerate sentinel, never a real bucket."""
    from yosoi.generalization.fingerprint import SHAPE_SCHEME_VERSION, page_shape_fp

    blank = page_shape_fp(observe_html('https://x.com/empty', '<html><body></body></html>', row_selector=''))
    assert blank == f'{SHAPE_SCHEME_VERSION}:degenerate'


def test_page_shape_is_scheme_prefixed() -> None:
    """Real buckets carry the scheme prefix so a shape-key change is observable."""
    from yosoi.generalization.fingerprint import SHAPE_SCHEME_VERSION, page_shape_fp

    fp = page_shape_fp(observe_html('https://google.com/search?q=x', _serp_html(10, tld='com'), row_selector=''))
    assert fp.startswith(f'{SHAPE_SCHEME_VERSION}:')
    assert len(fp.split(':', 1)[1]) == 16


# ── template-skeleton fingerprint (P5/WF1) ──────────────────────────────────────


def _listing(n_rows: int) -> str:
    rows = ''.join(
        f'<li class="item"><a class="lnk" href="/x{i}">t{i}</a><span class="px">{i}</span></li>' for i in range(n_rows)
    )
    return (
        f'<html><body class="listing-page"><header><nav><a class="logo">H</a></nav></header>'
        f'<main class="content"><ul class="results">{rows}</ul></main></body></html>'
    )


_ARTICLE = (
    '<html><body class="article-page"><header><nav><a class="logo">H</a></nav></header>'
    '<article class="story"><h1>T</h1><p>a</p><p>b</p><p>c</p><blockquote>q</blockquote>'
    '<time>2h</time></article></body></html>'
)


def test_skeleton_is_content_volume_invariant() -> None:
    from yosoi.generalization.fingerprint import same_shape, skeleton_jaccard

    # 5 rows vs 40 rows of the SAME template — set-of-shingles dedups the repeats.
    assert skeleton_jaccard(_listing(5), _listing(40)) > 0.9
    assert same_shape(_listing(5), _listing(40))


def test_skeleton_distinguishes_templates() -> None:
    from yosoi.generalization.fingerprint import same_shape, skeleton_jaccard

    assert skeleton_jaccard(_listing(10), _ARTICLE) < 0.5
    assert not same_shape(_listing(10), _ARTICLE)


def test_skeleton_fp_prefix_and_degenerate() -> None:
    from yosoi.generalization.fingerprint import page_skeleton_fp

    assert page_skeleton_fp(_listing(10)).startswith('t1:')
    assert page_skeleton_fp('<html><body></body></html>') == 't1:degenerate'


# ── L2 semantic layer + conjunctive same_shape (P5) ─────────────────────────────


def test_semantics_extracts_landmarks_and_schema() -> None:
    from yosoi.generalization.fingerprint import page_semantics

    html = (
        '<html><body><header></header><nav></nav><main><h1>x</h1></main><footer></footer>'
        '<script type="application/ld+json">{"@type": "FinancialProduct"}</script></body></html>'
    )
    feats = page_semantics(html)
    assert 'lm:header' in feats
    assert 'lm:main' in feats
    assert 'schema:FinancialProduct' in feats


def test_same_shape_conjunctive_true_for_same_template() -> None:
    from yosoi.generalization.fingerprint import PageFingerprint, same_shape

    sim = PageFingerprint.of(_listing(5)).similarity(PageFingerprint.of(_listing(40)))
    assert sim.same_shape  # both layers agree
    assert same_shape(_listing(5), _listing(40))


def test_same_shape_rejects_different_template_even_if_one_layer_high() -> None:
    from yosoi.generalization.fingerprint import PageFingerprint, same_shape

    sim = PageFingerprint.of(_listing(10)).similarity(PageFingerprint.of(_ARTICLE))
    # the structural skeleton vetoes the merge regardless of the semantic layer (fail-closed)
    assert sim.skeleton < 0.5
    assert not sim.same_shape
    assert not same_shape(_listing(10), _ARTICLE)


# ── edge cases (round 1) ────────────────────────────────────────────────────────


def test_degenerate_pages_never_match() -> None:
    from yosoi.generalization.fingerprint import PageFingerprint, same_shape

    # two empty pages, and two DIFFERENT thin pages, must NOT vacuously merge
    assert not same_shape('<html><body></body></html>', '<html><body></body></html>')
    a = PageFingerprint.of('<html><body><div>hi</div></body></html>')
    b = PageFingerprint.of('<html><body><span>yo</span></body></html>')
    assert a.degenerate
    assert b.degenerate
    assert not a.matches(b)


def test_similarity_thresholds_are_overridable() -> None:
    from yosoi.generalization.fingerprint import PageFingerprint

    a = PageFingerprint.of(_listing(10))
    b = PageFingerprint.of(_ARTICLE)
    # a permissive caller can lower thresholds (bring your own) — but degenerate guard still applies
    strict = a.similarity(b, skeleton_threshold=0.9, semantic_threshold=0.9)
    loose = a.similarity(b, skeleton_threshold=0.0, semantic_threshold=0.0)
    assert not strict.same_shape
    assert loose.same_shape  # non-degenerate listings, thresholds satisfied
