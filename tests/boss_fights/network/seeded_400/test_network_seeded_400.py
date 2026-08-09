"""The seeded 400-request trace: can two important requests survive 398 unimportant ones?

The threat is dilution, and the gate is a *ranking* gate, which is the uncomfortable one — it is
where "deterministic" and "useful" pull apart. So the ordering under test is lexicographic over an
enumerated tuple of rarity features, each either a closed specification or a property measured
against this trace, and the assertions below check the ORDER as well as the presence: a defect that
appears in the overview only because the overview happens to hold every entry has not been ranked.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from tests.boss_fights.generators.network_trace import render_network_trace
from tests.boss_fights.network.network_workload import NetworkWorkload, build_network_workload
from yosoi.observations.index.addressing import ObservationAddressError, parse_address
from yosoi.observations.index.inspect import InspectionBudget
from yosoi.observations.models.view import RegionRef
from yosoi.observations.network_tree import (
    RARITY_FEATURES,
    group_rank_key,
    group_requests,
    rank_key,
    rarity_profile,
    trace_context,
)

pytestmark = pytest.mark.boss_fight

WORKLOAD = Path(__file__).parent


@pytest.fixture(scope='module')
def trace() -> NetworkWorkload:
    """Assemble the seeded 400-request workload once per module."""
    return build_network_workload(WORKLOAD)


def _evidence(workload: NetworkWorkload, evidence_id: str) -> dict:
    """Return one ground-truth evidence record by id."""
    return next(item for item in workload.ground_truth['required_evidence'] if item['id'] == evidence_id)


def _region(workload: NetworkWorkload, region_id: str) -> dict:
    """Return one ground-truth region record by id."""
    return next(item for item in workload.ground_truth['required_region'] if item['id'] == region_id)


def test_the_generated_trace_matches_its_pinned_digest_and_composition(trace: NetworkWorkload) -> None:
    manifest = trace.manifest

    assert hashlib.sha256(trace.data).hexdigest() == manifest['generated_sha256']
    assert len(trace.data) == manifest['generated_bytes']
    assert trace.trace.observed_request_count == manifest['total_requests'] == 400
    assert (
        manifest['assets']
        + manifest['telemetry']
        + manifest['duplicate_api']
        + manifest['irrelevant_json']
        + manifest['useful_api']
        + manifest['defects']
        == 400
    )


def test_four_hundred_requests_reduce_to_a_few_dozen_entries(trace: NetworkWorkload) -> None:
    assert trace.view.stats.retained_items == len(trace.index.entries)
    # The population is every addressable thing — the trace, its origins, its endpoints, and its
    # requests — so `omitted_items` lands exactly on the requests that got no individual entry.
    assert trace.view.stats.source_items == 1 + 5 + 33 + 400
    assert trace.view.stats.omitted_items == 400 - len(trace.members())
    assert len(trace.index.entries) <= trace.manifest['max_index_entries']
    # 330 assets and telemetry calls are the bulk of the trace and must cost almost nothing.
    noisy = [
        entry
        for entry in trace.index.entries
        if entry.coverage is not None and entry.coverage.observed >= 15 and 'application/json' not in entry.summary
    ]
    assert sum(entry.coverage.observed for entry in noisy if entry.coverage) >= 330


def test_both_defect_requests_are_addressable_from_the_index(trace: NetworkWorkload) -> None:
    for evidence_id in ('defect_status_500', 'defect_shape_drift'):
        evidence = _evidence(trace, evidence_id)
        ordinals = trace.entries_reaching(evidence['oracle_request_id'])
        assert ordinals, f'{evidence_id} is unreachable from the index'
        # One of them must address the request ITSELF, not merely the group holding it.
        members = [ordinal for ordinal in ordinals if ordinal in trace.members()]
        assert len(members) == 1, f'{evidence_id} has {len(members)} individual entries; expected exactly 1'
        detail = trace.inspect_bytes(members[0]).decode()
        assert f'"request_id":"{evidence["oracle_request_id"]}"' in detail
        assert f'"status":{evidence["expect_status"]}' in detail


def test_the_defects_are_the_two_highest_ranked_things_in_the_reduction(trace: NetworkWorkload) -> None:
    """Presence is not enough: the ordering itself has to put them first."""
    context = trace_context(trace.trace)
    groups = sorted(group_requests(trace.trace), key=lambda g: group_rank_key(g, context))
    expected = {
        _evidence(trace, 'defect_status_500')['oracle_request_id'],
        _evidence(trace, 'defect_shape_drift')['oracle_request_id'],
    }

    top = {
        request.request_id
        for group in groups[:2]
        for request in group.requests
        if any(rarity_profile(request, context))
    }
    assert top == expected

    # And the emitted index agrees with that ranking: both individual entries sit in the first ten.
    for evidence_id in ('defect_status_500', 'defect_shape_drift'):
        oracle = _evidence(trace, evidence_id)['oracle_request_id']
        rank = min(ordinal for ordinal in trace.entries_reaching(oracle) if ordinal in trace.members())
        assert rank <= 10, f'{evidence_id} is entry {rank}; the ranking did not lift it'


def test_the_defects_outrank_every_irrelevant_singleton(trace: NetworkWorkload) -> None:
    """The decoys fire the weakest feature; the ordering must not confuse them with a defect."""
    context = trace_context(trace.trace)
    defects = {
        _evidence(trace, 'defect_status_500')['oracle_request_id'],
        _evidence(trace, 'defect_shape_drift')['oracle_request_id'],
    }
    ranks = {
        request.request_id: rank_key(rarity_profile(request, context))
        for group in group_requests(trace.trace)
        for request in group.requests
    }
    worst_defect = max(ranks[request_id] for request_id in defects)
    others = [
        rank for request_id, rank in ranks.items() if request_id not in defects and rank != (1,) * len(RARITY_FEATURES)
    ]

    assert others, 'the fixture has no decoys firing a weak feature; the ordering claim is vacuous'
    assert worst_defect < min(others), 'a decoy ranks at or above a defect'


def test_the_overview_fits_the_budget_and_states_both_defects(trace: NetworkWorkload) -> None:
    budget = trace.manifest['budget_tokens']
    overview = trace.render(budget)

    assert overview.token_count <= budget
    included = {ref.locator for ref in overview.included_refs}
    for evidence_id in ('defect_status_500', 'defect_shape_drift'):
        oracle = _evidence(trace, evidence_id)['oracle_request_id']
        ordinals = [o for o in trace.entries_reaching(oracle) if o in trace.members()]
        assert trace.index.entries[ordinals[0]].ref.locator in included, f'{evidence_id} is not in the overview'
    # The overview never claims completeness it does not have.
    assert 'entries shown' in overview.text
    assert str(len(trace.index.entries)) in overview.text


def test_bound_defect_members_tier_with_their_regions_at_the_budget_floor(trace: NetworkWorkload) -> None:
    """The bottom of the declared budget band must retain both deviations.

    Each defect member is semantically bound to the endpoint region immediately before it. Paging
    already preserves that relation; rendering must see the same fact instead of packing all 33
    regions ahead of the two lines that identify the actual defects.
    """
    members = trace.members()
    overview = trace.render(trace.manifest['budget_floor_tokens'])
    included = {ref.locator for ref in overview.included_refs}

    assert len([ordinal for ordinal in members if trace.index.entries[ordinal].ref.locator in included]) == 2
    for position, entry in enumerate(trace.index.entries):
        if entry.bound_to_previous and entry.ref.locator in included:
            assert trace.index.entries[position - 1].ref.locator in included
    assert overview.truncated


def test_duplicate_requests_stay_countable_and_individually_reachable(trace: NetworkWorkload) -> None:
    expected = _region(trace, 'duplicate_cart_polls')
    region = next(
        entry
        for entry in trace.index.entries
        if entry.coverage is not None and expected['oracle_path_template'] in entry.label
    )

    assert region.coverage is not None
    assert region.coverage.observed == expected['expected_members'] == 41
    assert region.coverage.complete
    assert f'×{expected["expected_members"]}' in region.summary

    page = trace.expand(region.ordinal, InspectionBudget(max_items=100))
    assert [member.ordinal for member in page.members] == list(range(41))
    assert not page.truncated
    assert len({member.ref.locator for member in page.members}) == 41
    # Exactly one member earned a durable key: the one that differs from the other forty. The rest
    # are positional, which is the truth about forty indistinguishable polls.
    assert sum(1 for member in page.members if member.stable) == 1


def test_the_failing_request_stays_inside_its_endpoint_group(trace: NetworkWorkload) -> None:
    expected = _region(trace, 'failing_product_endpoint')
    region = next(
        entry
        for entry in trace.index.entries
        if entry.coverage is not None and entry.label.endswith(expected['oracle_path_template'])
    )

    assert region.coverage is not None
    assert region.coverage.observed == expected['expected_members'] == 6
    assert '500×1' in region.summary
    assert '200×5' in region.summary
    assert 'deviate from this group' in region.summary


def test_the_root_entry_states_the_defaults_and_what_the_ranking_ignored(trace: NetworkWorkload) -> None:
    root = trace.index.entries[0]

    assert root.label == 'network trace'
    assert 'defaults:' in root.summary
    for feature in RARITY_FEATURES:
        assert feature.name in root.summary
    assert 'NOT considered' in root.summary
    assert 'cardinality mismatch' in root.summary
    # A capability the producer could not capture stays visible as an absence.
    assert 'NOT captured: request_shapes' in root.summary


def test_no_credential_or_parameter_value_can_appear_in_the_artifact(trace: NetworkWorkload) -> None:
    """Every object key in the artifact is a declared schema field — there is no slot for a value."""
    import json

    from yosoi.observations.models.network import (
        NetworkCapability,
        NetworkRedaction,
        NetworkRequest,
        NetworkTrace,
        QueryParam,
        RestrictedBody,
        ShapeSignature,
    )

    declared = {
        name
        for model in (
            NetworkTrace,
            NetworkRequest,
            QueryParam,
            ShapeSignature,
            NetworkCapability,
            NetworkRedaction,
            RestrictedBody,
        )
        for name in model.model_fields
    }
    seen: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            seen.update(node)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(json.loads(trace.data))
    assert seen <= declared, f'undeclared keys in a value-free artifact: {sorted(seen - declared)}'

    text = trace.data.decode()
    assert 'Bearer' not in text
    assert 'set-cookie' not in text.lower()
    # Header names ARE present, because a name is evidence and no value exists to pair with it.
    assert '"authorization"' in text
    assert '"header_values":"dropped"' in text
    assert '"param_values":"classed"' in text
    # No raw URL survived: only origins and templates, so no query string can be in the bytes.
    assert '?' not in text


def test_every_emitted_reference_resolves_and_foreign_ones_fail_closed(trace: NetworkWorkload) -> None:
    for entry in trace.index.entries:
        assert trace.inspector.inspect(entry.ref, InspectionBudget()).returned_bytes > 0

    foreign = RegionRef(
        snapshot_id=trace.snapshot.snapshot_id,
        artifact_sha256=trace.index.entries[0].ref.artifact_sha256,
        modality=trace.index.entries[0].ref.modality,
        locator='//*[@data-origin="https://nowhere.example"]#anchor=data-origin%3Dhttps%3A%2F%2Fnowhere.example',
    )
    with pytest.raises(ObservationAddressError):
        trace.inspector.inspect(foreign, InspectionBudget())

    stale = RegionRef(
        snapshot_id='a_different_capture',
        artifact_sha256=trace.index.entries[0].ref.artifact_sha256,
        modality=trace.index.entries[0].ref.modality,
        locator=trace.index.entries[0].ref.locator,
    )
    with pytest.raises(ObservationAddressError):
        trace.inspector.inspect(stale, InspectionBudget())


def test_identity_survives_a_second_capture_while_locations_do_not(trace: NetworkWorkload) -> None:
    again = build_network_workload(WORKLOAD, snapshot_id='network_seeded_400_recaptured')

    assert [entry.ref_id for entry in again.index.entries] == [entry.ref_id for entry in trace.index.entries]
    assert trace.index.entries[0].label == 'network trace'
    assert trace.index.entries[0].ref_id is None
    assert all(entry.ref_id is not None for entry in trace.index.entries[1:])
    assert again.index.entries[2].ref != trace.index.entries[2].ref


def test_the_reduction_is_byte_identical_across_runs(trace: NetworkWorkload) -> None:
    again = build_network_workload(WORKLOAD)

    assert render_network_trace(trace.manifest['id']) == trace.data
    assert again.view.policy_hash == trace.view.policy_hash
    assert [(entry.ref, entry.label, entry.summary) for entry in again.index.entries] == [
        (entry.ref, entry.label, entry.summary) for entry in trace.index.entries
    ]


def test_reduction_cost_is_bounded(trace: NetworkWorkload) -> None:
    """A 400-request trace is not a large artifact; the reduction must not act like it is."""
    from yosoi.observations.pruning.network import NetworkPruner
    from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy

    source = PruningInput(source=trace.snapshot.artifacts[0], data=trace.data)
    policy = PruningPolicy()
    pruner = NetworkPruner()
    pruner.prune(source, policy)

    elapsed = min(_timed(pruner, source, policy) for _ in range(3))
    assert elapsed < 1.0, f'reducing 400 requests took {elapsed:.3f}s'


def _timed(pruner, source, policy) -> float:
    """Return the wall time of one full reduction."""
    start = time.perf_counter()
    pruner.prune(source, policy)
    return time.perf_counter() - start


def test_addresses_carry_no_positional_guess_above_a_region_member(trace: NetworkWorkload) -> None:
    for entry in trace.index.entries:
        address = parse_address(entry.ref.locator)
        if entry.label == 'network trace':
            assert not address.is_anchored
            assert entry.ref_id is None
        else:
            assert address.is_anchored, f'{entry.label} is not anchored'
            assert (entry.ref_id is None) == (not address.is_stable)
        assert address.is_positional_free
