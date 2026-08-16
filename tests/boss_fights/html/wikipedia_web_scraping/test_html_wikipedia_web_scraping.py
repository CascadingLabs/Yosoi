"""Wikipedia, pinned: the negative control that separates pruning from rendering.

Books to Scrape proves the reducer works on a page built from records. This one proves what the
reducer is NOT: on an article of unique prose, a correct reduction is still far too large to put
in a model's context. The fix is a second stage, not a more aggressive first one — dropping the
prose would destroy exactly the evidence the index exists to address.

So the assertions here are about the renderer: does a budgeted overview still show every section
the article declares, does it say what it left out, and is everything it left out still one hop
away?
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.boss_fights.conftest import HtmlWorkload
from yosoi.observations.index.inspect import InspectionBudget
from yosoi.observations.index.render import CharacterEstimator, ObservationIndexRenderer, RenderPolicy
from yosoi.observations.models.view import RenderedView

WORKLOAD = Path(__file__).parent


@pytest.fixture(scope='module')
def article(html_workload: Callable[[Path, str], HtmlWorkload]) -> HtmlWorkload:
    """Assemble the pinned Wikipedia revision once per module."""
    return html_workload(WORKLOAD, 'wikipedia_web_scraping.html')


@pytest.fixture(scope='module')
def policy(article: HtmlWorkload) -> RenderPolicy:
    """Return the render policy this workload gates."""
    return RenderPolicy(
        tokenizer_id=article.manifest['tokenizer_id'], token_budget=article.manifest['budget_overview_tokens']
    )


@pytest.fixture(scope='module')
def overview(article: HtmlWorkload, policy: RenderPolicy) -> RenderedView:
    """Render the article's index under the gated budget."""
    return ObservationIndexRenderer().render(article.index, policy)


def test_frozen_artifact_matches_its_manifest_digest(article: HtmlWorkload) -> None:
    assert article.snapshot.artifacts[0].sha256 == article.manifest['artifact_sha256']


def test_the_index_alone_is_too_large_to_be_an_overview(article: HtmlWorkload) -> None:
    """The negative control itself. If this ever fails, the renderer stopped being necessary."""
    index_bytes = sum(view.stats.output_bytes for view in article.views)

    assert len(article.index.entries) > 500, 'an article of unique prose must produce many entries'
    assert index_bytes > 40_000, 'the structured index is expected to be large here — that is the control'


def test_a_budgeted_overview_keeps_every_section_heading(
    article: HtmlWorkload, overview: RenderedView, policy: RenderPolicy
) -> None:
    """Routing lives in the headings: an unseen section cannot be asked about."""
    required = next(item for item in article.ground_truth['required_overview'] if item['id'] == 'section_headings')
    headings = article.entries_reaching(required['oracle_xpath'])
    assert headings, 'the article declares no headings — the oracle or the capture is wrong'

    shown = set(overview.included_refs)
    missing = [ordinal for ordinal in headings if article.index.entries[ordinal].ref not in shown]

    assert not missing, f'{len(missing)} of {len(headings)} section headings never reached the overview'
    assert overview.token_count <= policy.token_budget
    assert len(overview.text.encode()) <= article.manifest['budget_overview_bytes']


def test_the_overview_states_what_it_omitted(article: HtmlWorkload, overview: RenderedView) -> None:
    """A short overview that dropped 900 entries must not read like a short page."""
    omitted = len(article.index.entries) - len(overview.included_refs)

    assert overview.truncated
    assert omitted > 0
    assert str(omitted) in overview.text, 'the omission count must be stated, not implied'
    assert 'omitted' in overview.text


def test_omitted_evidence_is_still_one_inspect_hop_away(article: HtmlWorkload) -> None:
    """Bounded resident context is only acceptable because nothing became unreachable."""
    unreachable = []
    for evidence in article.ground_truth['required_evidence']:
        ordinals = article.entries_reaching(evidence['oracle_xpath'])
        if not ordinals:
            unreachable.append(evidence['id'])
            continue
        detail = article.inspect_bytes(ordinals[0], InspectionBudget(max_bytes=4_000))
        if not detail:
            unreachable.append(f'{evidence["id"]} (addressed, no bytes)')
    assert not unreachable, f'evidence unreachable from the index: {unreachable}'


def test_repeated_lists_cost_regions_not_entries_per_item(article: HtmlWorkload) -> None:
    """A list-heavy article must spend regions on its lists."""
    expected = article.ground_truth['required_region'][0]
    regions = article.regions_reaching(expected['oracle_xpath'])

    assert regions, 'the article list is not collapsed into a region'
    region = article.index.entries[regions[0]]
    assert region.coverage is not None
    assert region.coverage.complete


def test_rendering_is_deterministic_and_changes_nothing(article: HtmlWorkload, policy: RenderPolicy) -> None:
    """Rendering reads the index; it never re-prunes, and never touches canonical bytes."""
    renderer = ObservationIndexRenderer()
    before = [(entry.ref, entry.label, entry.summary, entry.ref_id) for entry in article.index.entries]
    digest_before = article.snapshot.artifacts[0].sha256

    first = renderer.render(article.index, policy)
    second = renderer.render(article.index, policy)

    assert first.text == second.text
    assert first.included_refs == second.included_refs
    assert [(entry.ref, entry.label, entry.summary, entry.ref_id) for entry in article.index.entries] == before
    assert article.snapshot.artifacts[0].sha256 == digest_before


def test_a_tokenizer_may_not_measure_another_tokenizers_budget(article: HtmlWorkload) -> None:
    """A rendering must never claim a budget it was not measured against."""
    foreign = RenderPolicy(tokenizer_id='some-provider/v9', token_budget=500)

    with pytest.raises(ValueError, match='cannot measure a budget'):
        ObservationIndexRenderer().render(article.index, foreign, CharacterEstimator())


def test_a_tiny_budget_still_produces_a_usable_and_honest_overview(article: HtmlWorkload) -> None:
    """Squeezed hard, the overview degrades by showing less — never by lying about it."""
    tiny = RenderPolicy(tokenizer_id=article.manifest['tokenizer_id'], token_budget=120)

    view = ObservationIndexRenderer().render(article.index, tiny)

    assert view.token_count <= tiny.token_budget
    assert view.truncated
    assert 'omitted' in view.text
    assert view.included_refs, 'a budget that fits the footer must still fit some entries'
