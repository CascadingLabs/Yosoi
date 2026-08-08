"""Multi-hop navigation: is the whole investigation bounded, or only each call?

Every other workload here checks one operation at a time. That is not the claim the product
makes. The claim is that an agent can start from a small overview, cross several levels of
nested structure, and end holding one exact record — having read a small fraction of the page.
A tool suite where each call is bounded and a five-hop session still returns most of the
document has not bounded anything; it has just split the same payload across five messages.

So this measures the SESSION: every byte handed back across the route, summed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.boss_fights.conftest import HtmlWorkload
from tests.boss_fights.generators import render_nested_page
from yosoi.observations.index.addressing import ObservationAddressError, parse_address
from yosoi.observations.index.inspect import InspectionBudget, RegionPage
from yosoi.observations.index.render import ObservationIndexRenderer, RenderPolicy
from yosoi.observations.models.view import RegionRef

WORKLOAD = Path(__file__).parent


def _manifest() -> dict:
    """Read the manifest without assembling a workload."""
    import tomllib

    return tomllib.loads((WORKLOAD / 'manifest.toml').read_text())


@pytest.fixture(scope='module')
def nested(generated_html_workload: Callable[..., HtmlWorkload]) -> HtmlWorkload:
    """Assemble the nested-repeat page once per module."""
    manifest = _manifest()
    return generated_html_workload(
        WORKLOAD, render_nested_page(manifest['departments'], manifest['teams'], manifest['rows'])
    )


def _region_entry(workload: HtmlWorkload, oracle: str) -> int:
    """Return the single region ordinal that collapsed the oracle's elements."""
    regions = workload.regions_reaching(oracle)
    assert len(regions) == 1, f'{oracle} must collapse into exactly one region, got {len(regions)}'
    return regions[0]


def test_generated_artifact_matches_its_pinned_digest(nested: HtmlWorkload) -> None:
    import hashlib

    assert hashlib.sha256(nested.data).hexdigest() == nested.manifest['generated_sha256']
    assert len(nested.data) == nested.manifest['generated_bytes']


def test_three_nesting_levels_each_cost_one_region(nested: HtmlWorkload) -> None:
    """120 leaf records must not become 120 entries at any level."""
    for expected in nested.ground_truth['required_region']:
        entry = nested.index.entries[_region_entry(nested, expected['oracle_xpath'])]
        assert entry.coverage is not None
        assert entry.coverage.observed == expected['expected_members'], expected['id']
        assert entry.coverage.complete

    leaves = nested.manifest['leaf_records']
    assert len(nested.index.entries) * 10 < leaves * 2, 'the index must not scale with the leaf count'


def test_every_composed_address_resolves_and_keeps_its_identity(nested: HtmlWorkload) -> None:
    """An address four segments deep is only useful if every segment still resolves."""
    deepest = max(nested.index.entries, key=lambda entry: len(parse_address(entry.ref.locator).segments))
    address = parse_address(deepest.ref.locator)

    assert len(address.segments) >= 3, 'the workload must actually produce deep addresses'
    assert nested.inspector.inspect(deepest.ref, InspectionBudget()).content
    # Depth must not cost identity: every segment of a deep address is a key, not a position.
    assert deepest.ref_id is not None
    assert all(entry.ref_id is not None for entry in nested.index.entries), (
        'a keyed, anchored page must not produce an entry without identity'
    )


def test_a_five_hop_investigation_stays_inside_a_session_budget(nested: HtmlWorkload) -> None:
    """The real claim: the whole route reads a small fraction of the page, not each call."""
    route = nested.ground_truth['route']
    manifest = nested.manifest
    spent = 0

    # Hop 1 — the overview. This is all the agent knows before it asks for anything.
    overview = ObservationIndexRenderer().render(
        nested.index,
        RenderPolicy(tokenizer_id=manifest['tokenizer_id'], token_budget=manifest['budget_overview_tokens']),
    )
    spent += len(overview.text.encode())

    # Hop 2 — expand the outermost region to learn which departments exist.
    departments_ordinal = _region_entry(nested, route['region_oracle'])
    departments: RegionPage = nested.expand(departments_ordinal, InspectionBudget(max_items=10))
    spent += sum(len(member.summary.encode()) for member in departments.members)
    assert [member.stable for member in departments.members] == [True] * len(departments.members)

    # Hop 3 — inspect one department, bounded. Without a bound this alone is a quarter of the page.
    chosen = next(
        member
        for member in departments.members
        if parse_address(member.ref.locator).segments[-1].key == route['member_key']
    )
    department = nested.inspector.inspect(chosen.ref, InspectionBudget(max_bytes=1_200))
    spent += department.returned_bytes
    assert department.truncated, 'a whole department subtree must not fit — that is why hops are bounded'

    # Hop 4 — expand the innermost region, learned through the exemplar branch.
    rows_ordinal = _region_entry(nested, route['nested_region_oracle'])
    rows = nested.expand(rows_ordinal, InspectionBudget(max_items=10))
    spent += sum(len(member.summary.encode()) for member in rows.members)

    # Hop 5 — one exact leaf record.
    leaf = next(member for member in rows.members if route['leaf_text'] in member.summary)
    detail = nested.inspector.inspect(leaf.ref, InspectionBudget(max_bytes=600))
    spent += detail.returned_bytes

    assert route['leaf_text'] in detail.content.decode(errors='replace')
    assert spent <= manifest['budget_session_bytes'], (
        f'the five-hop route read {spent} B of an {len(nested.data)} B document'
    )
    # And the point of the exercise: a small fraction of the page, not most of it.
    assert spent < len(nested.data) / 3


def test_a_route_learned_at_the_exemplar_transfers_to_another_branch(nested: HtmlWorkload) -> None:
    """The index describes department 1. Department 3 must be reachable without indexing it."""
    expected = nested.ground_truth['rebind']
    learned = nested.index.entries[_region_entry(nested, expected['learned_at_oracle'])].ref

    rebound = nested.inspector.rebind(learned, expected['target_member_keys'])
    page = nested.inspector.expand(rebound, InspectionBudget(max_items=10))

    assert page.members, 'the rebound region resolved to no members'
    assert all(expected['expect_text'] in member.summary for member in page.members), (
        'rebinding resolved to the wrong branch'
    )
    # The route changed branch, not shape: same member count, same coverage completeness.
    original = nested.expand(_region_entry(nested, expected['learned_at_oracle']), InspectionBudget(max_items=10))
    assert len(page.members) == len(original.members)
    assert page.coverage.complete == original.coverage.complete


def test_rebinding_to_a_member_that_does_not_exist_fails_now_not_later(nested: HtmlWorkload) -> None:
    """A reference that cannot resolve must never be handed back to be discovered downstream."""
    expected = nested.ground_truth['rebind']
    learned = nested.index.entries[_region_entry(nested, expected['learned_at_oracle'])].ref

    with pytest.raises(ObservationAddressError):
        nested.inspector.rebind(learned, expected['absent_keys'])


def test_rebinding_a_reference_with_no_member_segment_is_refused(nested: HtmlWorkload) -> None:
    """Only an address that selects a member has a member to swap."""
    plain = next(entry for entry in nested.index.entries if not parse_address(entry.ref.locator).member_segments())

    with pytest.raises(ObservationAddressError, match='cannot rebind'):
        nested.inspector.rebind(plain.ref, 'id=dept-3')


def test_rebinding_an_outer_member_without_the_inner_ones_is_refused(nested: HtmlWorkload) -> None:
    """Member keys below the swap are branch-specific: `id=team-1-1` exists only in department 1.

    Accepting one key here would produce a reference that either fails deep inside resolution or,
    worse, resolves in the old branch while the caller believes it moved.
    """
    expected = nested.ground_truth['rebind']
    learned = nested.index.entries[_region_entry(nested, expected['learned_at_oracle'])].ref

    with pytest.raises(ObservationAddressError, match='branch-specific'):
        nested.inspector.rebind(learned, expected['target_member_keys'][0])


def test_the_route_is_reproducible_hop_for_hop(nested: HtmlWorkload) -> None:
    """Two agents walking the same route must be handed identical bytes."""
    ordinal = _region_entry(nested, nested.ground_truth['route']['nested_region_oracle'])

    first = nested.expand(ordinal, InspectionBudget(max_items=3))
    second = nested.expand(ordinal, InspectionBudget(max_items=3))
    detail_a = nested.inspector.inspect(first.members[0].ref, InspectionBudget())
    detail_b = nested.inspector.inspect(second.members[0].ref, InspectionBudget())

    assert first == second
    assert detail_a.content == detail_b.content


def test_no_hop_can_return_the_whole_document(nested: HtmlWorkload) -> None:
    """Every entry, inspected at once under a shared budget, stays bounded per call."""
    budget = InspectionBudget(max_bytes=1_000)
    oversized = [
        entry.ordinal
        for entry in nested.index.entries
        if nested.inspector.inspect(entry.ref, budget).returned_bytes > budget.max_bytes
    ]

    assert not oversized, f'entries {oversized} exceeded their inspection budget'


def test_an_expanded_page_never_exceeds_its_item_budget(nested: HtmlWorkload) -> None:
    """Paging is the only way to see many members; a region may not dump them."""
    for expected in nested.ground_truth['required_region']:
        ordinal = _region_entry(nested, expected['oracle_xpath'])
        page = nested.expand(ordinal, InspectionBudget(max_items=2))

        assert len(page.members) == 2
        assert page.truncated == (expected['expected_members'] > 2)
        assert page.coverage.observed == expected['expected_members'], 'coverage reports the region, not the page'


def test_a_rebound_reference_is_an_ordinary_reference(nested: HtmlWorkload) -> None:
    """Rebinding must not mint a second-class address: same grammar, same identity rules."""
    expected = nested.ground_truth['rebind']
    learned = nested.index.entries[_region_entry(nested, expected['learned_at_oracle'])].ref

    rebound = nested.inspector.rebind(learned, expected['target_member_keys'])
    address = parse_address(rebound.locator)

    assert isinstance(rebound, RegionRef)
    assert address.is_region
    assert address.is_anchored
    assert address.is_stable
    assert rebound.locator != learned.locator
