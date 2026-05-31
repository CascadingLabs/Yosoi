"""Tests for the deterministic reuse-scope recommender."""

import pytest

from yosoi.generalization.fingerprint import PageObservation
from yosoi.generalization.recommend import recommend
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
