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
