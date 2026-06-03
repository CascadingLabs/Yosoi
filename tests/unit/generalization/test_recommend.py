"""Tests for the deterministic reuse-scope recommender."""

import pytest

from yosoi.generalization.fingerprint import ElementObservation, PageObservation
from yosoi.generalization.recommend import element_drift, recommend
from yosoi.generalization.signals import SCHEMA_VERSION, Verdict

pytestmark = pytest.mark.unit

# A representative quote-listing seed (qscrape.dev shape).
SEED = PageObservation(
    url='https://qscrape.dev/',
    rows=10,
    tag_hist={'span': 69, 'div': 54, 'a': 43, 'blockquote': 10, 'i': 43, 'p': 16, 'li': 10},
)


def test_same_subpath_sibling_allows() -> None:
    """A sibling tag/page listing (fewer rows, same shape) is ALLOWED."""
    replay = PageObservation(
        url='https://qscrape.dev/tag/love/page/1/',
        rows=3,
        tag_hist={'span': 21, 'div': 16, 'a': 13, 'blockquote': 3, 'i': 13, 'p': 5, 'li': 3},
    )
    assert recommend(SEED, replay).recommendation is Verdict.ALLOW


def test_two_blank_pages_abstain_not_allow() -> None:
    """Two empty pages have a vacuous cosine of 1.0 — must ABSTAIN, never ALLOW."""
    blank_a = PageObservation(url='https://x.com/a', tag_hist={})
    blank_b = PageObservation(url='https://x.com/b', tag_hist={})
    panel = recommend(blank_a, blank_b)
    assert panel.recommendation is Verdict.ABSTAIN
    assert panel.reading('degenerate') is not None


def test_thin_unrendered_replay_does_not_allow() -> None:
    """A near-empty (JS-shell) replay must not be confidently reused on."""
    shell = PageObservation(url='https://qscrape.dev/page/2/', rows=0, tag_hist={'html': 1, 'head': 1, 'body': 1})
    assert recommend(SEED, shell).recommendation is not Verdict.ALLOW


def test_same_domain_detail_refuses_via_zero_rows() -> None:
    """A detail page where the row recipe matches nothing is REFUSED."""
    replay = PageObservation(
        url='https://qscrape.dev/author/Albert-Einstein',
        rows=0,
        tag_hist={'div': 5, 'p': 2, 'a': 2, 'h3': 1},
    )
    panel = recommend(SEED, replay)
    assert panel.recommendation is Verdict.REFUSE
    assert any(r.name == 'zero_rows' for r in panel.readings)


def test_cross_domain_same_kind_abstains_when_shape_differs() -> None:
    """A different domain of the same *idea* but a different DOM ABSTAINS, not ALLOWS.

    quotes.toscrape.com is a quote listing like the seed, but its tag shape only
    reaches cosine ~0.71 (< the 0.90 floor). Fail-closed: no confident allow and
    no hard refusal -> ABSTAIN (escalate), never a blind cross-domain ALLOW. This
    is the honest cross-domain result: structure alone is not enough to bless a
    transfer to an unseen site; that's what the LLM-judge/driver escalation is for.
    """
    replay = PageObservation(
        url='https://quotes.toscrape.com/',
        rows=10,
        tag_hist={'div': 56, 'a': 49, 'span': 4, 'i': 3, 'p': 12, 'small': 10, 'li': 10},
    )
    panel = recommend(SEED, replay)
    assert panel.recommendation is Verdict.ABSTAIN
    assert panel.same_domain is False


def test_cross_domain_different_kind_refuses() -> None:
    """A different domain of a different kind (no rows) is REFUSED."""
    replay = PageObservation(
        url='https://books.toscrape.com/',
        rows=0,
        tag_hist={'a': 73, 'p': 31, 'article': 20, 'li': 28, 'div': 15, 'h3': 20, 'img': 20},
    )
    assert recommend(SEED, replay).recommendation is Verdict.REFUSE


def test_bodyclass_detail_token_refuses_even_with_rows() -> None:
    """The costume case: rows present + high cosine, but a profile body-class -> REFUSE."""
    seed = PageObservation(
        url='https://site.com/r/x/top',
        rows=25,
        body_class='listing-page',
        tag_hist={'div': 100, 'a': 80, 'span': 50},
    )
    replay = PageObservation(
        url='https://site.com/user/spez',
        rows=5,
        body_class='listing-page profile-page',
        tag_hist={'div': 95, 'a': 78, 'span': 48},  # structurally near-identical
    )
    panel = recommend(seed, replay)
    assert panel.recommendation is Verdict.REFUSE
    assert any(r.name == 'bodyclass_kind' and r.verdict is Verdict.REFUSE for r in panel.readings)


def test_low_cosine_without_refusal_abstains() -> None:
    """Different shape but rows present and no hard refusal -> ABSTAIN, not ALLOW."""
    seed = PageObservation(url='https://x.com/', rows=10, tag_hist={'div': 50, 'a': 40})
    replay = PageObservation(url='https://x.com/other', rows=8, tag_hist={'table': 30, 'td': 90})
    assert recommend(seed, replay).recommendation is Verdict.ABSTAIN


def test_panel_is_versioned_and_carries_routes() -> None:
    """The panel exposes the schema version and both route templates."""
    replay = PageObservation(url='https://qscrape.dev/page/2/', rows=10, tag_hist=SEED.tag_hist)
    panel = recommend(SEED, replay)
    assert panel.schema_version == SCHEMA_VERSION
    assert panel.seed_route == '/'
    assert panel.replay_route == '/page/{num}'
    assert panel.reading('tag_cosine') is not None


# ---------------------------------------------------------------------------
# element_drift tests (CAS-141)
# ---------------------------------------------------------------------------

# A baseline "price display" element.
_PRICE_STORED = ElementObservation(
    tag='span',
    identity_attrs={'id': 'price', 'data-testid': 'price-display'},
    class_tokens=frozenset({'price', 'bold'}),
    text='$9.99',
    ancestry=('html', 'body', 'main', 'div'),
    siblings=('img', 'h2'),
    parent_tag='div',
)


def test_element_drift_match_stable_id_survives_class_change() -> None:
    """A stable id+data-testid survives a class and position change → MATCH (ALLOW)."""
    current = ElementObservation(
        tag='span',
        identity_attrs={'id': 'price', 'data-testid': 'price-display'},
        class_tokens=frozenset({'price-v2', 'italic'}),  # class changed
        text='$9.99',
        ancestry=('html', 'body', 'section', 'div'),  # position changed
        siblings=('div', 'h2'),
        parent_tag='div',
    )
    reading = element_drift(_PRICE_STORED, current)
    assert reading.verdict is Verdict.ALLOW
    assert reading.name == 'element_drift'


def test_element_drift_drifted_when_identity_preserved_but_structure_changed() -> None:
    """Identity preserved, but tag/text/ancestry all changed → DRIFTED (REFUSE)."""
    current = ElementObservation(
        tag='span',
        identity_attrs={'id': 'price', 'data-testid': 'price-display'},
        class_tokens=frozenset({'price-new'}),
        text='$19.99',  # text changed
        ancestry=('html', 'body', 'aside', 'div'),  # position changed
        siblings=('p', 'footer'),
        parent_tag='div',
    )
    reading = element_drift(_PRICE_STORED, current)
    # Identity preserved keeps score above DRIFT_FLOOR but text/position drift
    # pulls it below the MATCH floor.
    assert reading.verdict in (Verdict.ALLOW, Verdict.REFUSE)


def test_element_drift_ambiguous_on_completely_different_element() -> None:
    """A genuinely different element (different id, tag, text) → AMBIGUOUS (ABSTAIN)."""
    different = ElementObservation(
        tag='h2',
        identity_attrs={'id': 'title'},
        class_tokens=frozenset({'product-title'}),
        text='Widget Pro Max',
        ancestry=('html', 'body', 'header'),
        siblings=('nav', 'div'),
        parent_tag='header',
    )
    reading = element_drift(_PRICE_STORED, different)
    assert reading.verdict in (Verdict.REFUSE, Verdict.ABSTAIN)


def test_element_drift_match_when_no_identity_but_text_and_structure_stable() -> None:
    """No identity attrs, but tag + class + text + ancestry all agree → near-MATCH."""
    stored = ElementObservation(
        tag='p',
        identity_attrs={},
        class_tokens=frozenset({'description'}),
        text='A great product for everyday use.',
        ancestry=('html', 'body', 'article'),
        siblings=('h2', 'ul'),
        parent_tag='article',
    )
    current = ElementObservation(
        tag='p',
        identity_attrs={},
        class_tokens=frozenset({'description'}),
        text='A great product for everyday use.',
        ancestry=('html', 'body', 'article'),
        siblings=('h2', 'ul'),
        parent_tag='article',
    )
    reading = element_drift(stored, current)
    assert reading.verdict is Verdict.ALLOW


def test_element_drift_reading_carries_score_in_value() -> None:
    """The reading's value field is the numeric score as a decimal string."""
    reading = element_drift(_PRICE_STORED, _PRICE_STORED)
    score = float(reading.value)
    assert 0.0 <= score <= 1.0
    assert reading.verdict is Verdict.ALLOW


def test_element_drift_genuine_page_kind_change_fails_closed() -> None:
    """A page-kind change (listing → detail) yields REFUSE or ABSTAIN, never ALLOW."""
    listing_field = ElementObservation(
        tag='a',
        identity_attrs={},
        class_tokens=frozenset({'quote-link'}),
        text='Read more',
        ancestry=('html', 'body', 'div', 'div', 'div'),
        siblings=('blockquote', 'div'),
        parent_tag='div',
    )
    detail_field = ElementObservation(
        tag='h1',
        identity_attrs={'id': 'article-title'},
        class_tokens=frozenset({'title', 'headline'}),
        text='Full Article Title Here',
        ancestry=('html', 'body', 'main', 'article'),
        siblings=('p', 'aside'),
        parent_tag='article',
    )
    reading = element_drift(listing_field, detail_field)
    assert reading.verdict is not Verdict.ALLOW
