"""The network reducer: grouping, deviation, the restricted band, and both refusals."""

from __future__ import annotations

import pytest

from yosoi.observations.artifacts.memory import MemoryArtifactStore
from yosoi.observations.index.addressing import ObservationAddressError, parse_address
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector
from yosoi.observations.models.artifact import EvidenceKind, Sensitivity
from yosoi.observations.models.network import (
    NetworkCapability,
    NetworkCapabilityKind,
    NetworkRedaction,
    NetworkRequest,
    NetworkTrace,
    ResourceType,
    RestrictedBody,
    TimingBucket,
    duplicate_key,
    serialize_network_trace,
)
from yosoi.observations.models.snapshot import CaptureProfile, ObservationSnapshot
from yosoi.observations.network_tree import (
    RARITY_FEATURES,
    assign_request_member_keys,
    fallback_path,
    group_requests,
    matches_fallback,
    rarity_profile,
    trace_context,
)
from yosoi.observations.pruning.network import NetworkPruner
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy

SNAPSHOT = 'unit_network'
BODY_DIGEST = 'b' * 64


def _request(request_id: str, path: str = '/v1/cart', **overrides) -> NetworkRequest:
    """Build one valid request with the fixture's defaults."""
    fields = {
        'request_id': request_id,
        'method': 'GET',
        'origin': 'https://api.example',
        'path_template': path,
        'params': (),
        'status': 200,
        'resource_type': ResourceType.XHR,
        'mime': 'application/json',
        'timing': TimingBucket.FAST,
    }
    fields.update(overrides)
    fields.setdefault(
        'duplicate_key',
        duplicate_key(fields['method'], fields['origin'], fields['path_template'], tuple(fields['params'])),
    )
    return NetworkRequest(**fields)


def _complete(*requests: NetworkRequest, **overrides) -> NetworkTrace:
    """Build a trace that declares itself complete."""
    return NetworkTrace(
        snapshot_id=SNAPSHOT,
        requests=requests,
        capabilities=(NetworkCapability(kind=NetworkCapabilityKind.COMPLETE_TRACE, available=True),),
        **overrides,
    )


def _reduce(trace: NetworkTrace, policy: PruningPolicy | None = None, sensitivity=Sensitivity.MODEL_SAFE):
    """Prune a trace and return (view, store, snapshot)."""
    data = serialize_network_trace(trace)
    store = MemoryArtifactStore()
    artifact = store.put(
        snapshot_id=trace.snapshot_id,
        kind=EvidenceKind.NETWORK,
        media_type='application/json',
        data=data,
        sensitivity=sensitivity,
    )
    snapshot = ObservationSnapshot(
        run_id='r',
        episode_id='e',
        snapshot_id=trace.snapshot_id,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(artifact,),
    )
    view = NetworkPruner().prune(PruningInput(source=artifact, data=data), policy or PruningPolicy())
    return view, store, snapshot


def _labels(view) -> list[str]:
    """Return the emitted labels in order."""
    return [fragment.label for fragment in view.fragments]


# ── Grouping and the two-level tree ───────────────────────────────────────────


def test_identical_calls_collapse_to_one_region_that_still_counts_them() -> None:
    trace = _complete(*(_request(f'r{index}') for index in range(12)))

    view, _, _ = _reduce(trace)

    region = next(f for f in view.fragments if f.coverage is not None)
    assert region.coverage is not None
    assert region.coverage.observed == 12
    assert region.coverage.complete
    assert '×12' in region.summary
    # 12 requests cost 3 entries: the trace, its origin, and one endpoint region.
    assert len(view.fragments) == 3
    # Population = the trace, its origin, its endpoint, and its 12 requests; the 12 requests that
    # got no individual entry are exactly what `omitted_items` reports.
    assert view.stats.source_items == 15
    assert view.stats.omitted_items == 12


def test_depth_reflects_the_tree_the_modality_actually_has() -> None:
    trace = _complete(_request('r1'), _request('r2', path='/v1/other'))

    view, _, _ = _reduce(trace)

    assert _labels(view) == ['network trace', 'https://api.example', 'GET /v1/cart', 'GET /v1/other']


def test_an_incomplete_trace_never_reports_a_complete_region() -> None:
    trace = NetworkTrace(
        snapshot_id=SNAPSHOT,
        requests=(_request('r1'), _request('r2')),
        capabilities=(
            NetworkCapability(
                kind=NetworkCapabilityKind.COMPLETE_TRACE, available=False, reason='capture armed after navigation'
            ),
        ),
    )

    view, _, _ = _reduce(trace)

    region = next(f for f in view.fragments if f.coverage is not None)
    assert region.coverage is not None
    assert region.coverage.declared is None
    assert not region.coverage.complete
    assert 'this count is a floor' in region.summary
    assert 'NOT captured: complete_trace' in view.fragments[0].summary


# ── Deviation, not enumeration ────────────────────────────────────────────────


def test_a_member_that_deviates_from_its_own_group_earns_its_own_entry() -> None:
    trace = _complete(
        *(_request(f'ok{index}') for index in range(5)),
        _request('broken', status=500, mime='application/problem+json'),
    )

    view, _, _ = _reduce(trace)

    assert _labels(view)[-1] == 'GET /v1/cart → 500'
    assert 'rare: status_not_success' in view.fragments[-1].summary
    assert '500×1' in view.fragments[2].summary
    assert 'deviate from this group' in view.fragments[2].summary


def test_a_group_of_one_never_gets_a_second_entry_restating_itself() -> None:
    """The childless-exemplar cost the DOM reducer measured; not paid again here."""
    trace = _complete(*(_request(f'ok{index}') for index in range(3)), _request('only', status=500, path='/v1/lonely'))

    view, _, _ = _reduce(trace)

    lonely = [f for f in view.fragments if f.label == 'GET /v1/lonely']
    assert len(lonely) == 1
    assert not any(parse_address(f.ref.locator).segments[-1].selects_member for f in view.fragments)
    # The region line still carries the failure, so nothing was lost by not duplicating it.
    assert 'statuses 500×1' in lonely[0].summary


def test_the_anomalous_member_is_the_one_that_earns_a_durable_key() -> None:
    requests = (*(_request(f'ok{index}') for index in range(4)), _request('broken', status=503))

    keys = assign_request_member_keys(requests)

    assert keys[:4] == (None, None, None, None)
    assert keys[4] == 'status=503'


def test_ranking_is_a_strict_precedence_with_nothing_to_tune() -> None:
    trace = _complete(
        *(_request(f'ok{index}') for index in range(3)),
        _request('failing', status=500),
        _request('singleton', path='/v1/once'),
    )
    context = trace_context(trace)
    by_id = {request.request_id: rarity_profile(request, context) for request in trace.requests}

    # A failure fires the first feature; a one-off endpoint fires only the last.
    assert by_id['failing'][0] is True
    assert by_id['singleton'] == (False,) * (len(RARITY_FEATURES) - 1) + (True,)
    assert by_id['ok0'] == (False,) * len(RARITY_FEATURES)


def test_no_host_or_path_is_ever_named_by_the_reducer() -> None:
    """Two traces that differ only in their host must reduce identically in structure."""
    first = _complete(_request('r1'), _request('r2', path='/v1/other'))
    second = _complete(
        _request('r1', origin='https://doubleclick.example'),
        _request('r2', origin='https://doubleclick.example', path='/v1/other'),
    )

    one, _, _ = _reduce(first)
    two, _, _ = _reduce(second)

    assert [f.summary for f in one.fragments][2:] == [f.summary for f in two.fragments][2:]


# ── Facts only when they deviate from the stated default ──────────────────────


def test_a_default_valued_fact_is_stated_once_on_the_root_and_nowhere_else() -> None:
    trace = _complete(*(_request(f'r{index}') for index in range(3)))

    view, _, _ = _reduce(trace)

    root, _, region = view.fragments
    assert 'defaults: method=GET status=200 timing=fast' in root.summary
    assert 'status=200' not in region.summary
    assert 'timing=fast' not in region.summary


def test_a_deviating_fact_is_stated_where_it_deviates() -> None:
    trace = _complete(
        *(_request(f'r{index}') for index in range(3)),
        _request('slow', path='/v1/slow', timing=TimingBucket.VERY_SLOW),
    )

    view, _, _ = _reduce(trace)

    slow = next(f for f in view.fragments if f.label == 'GET /v1/slow')
    assert 'timing=very_slow' in slow.summary


# ── The restricted band rides the two gates that already exist ────────────────


def _restricted_trace() -> NetworkTrace:
    """A trace whose one request points at a raw body kept as a separate artifact."""
    body = RestrictedBody(artifact_sha256=BODY_DIGEST, media_type='application/json', size_bytes=64)
    return NetworkTrace(
        snapshot_id=SNAPSHOT,
        requests=(_request('r1', restricted_body=body),),
        capabilities=(NetworkCapability(kind=NetworkCapabilityKind.COMPLETE_TRACE, available=True),),
        redaction=NetworkRedaction(bodies='restricted_artifact'),
    )


def test_a_retained_body_is_acknowledged_but_not_addressed_without_the_gate() -> None:
    view, _, _ = _reduce(_restricted_trace(), PruningPolicy())

    assert 'restricted raw body artifact' in view.fragments[0].summary
    assert 'include_restricted is off' in view.fragments[0].summary
    assert BODY_DIGEST not in ' '.join(f.summary for f in view.fragments)


def test_the_existing_pruning_gate_is_what_names_the_restricted_artifact() -> None:
    view, _, _ = _reduce(_restricted_trace(), PruningPolicy(include_restricted=True))

    assert 'named below' in view.fragments[0].summary
    # The pointer rides the group summary, because a request with a retained body is not
    # necessarily a request that deviates from its group.
    assert f'restricted body artifact(s): {BODY_DIGEST}' in view.fragments[2].summary


def test_a_restricted_network_artifact_is_refused_by_both_stages() -> None:
    trace = _complete(_request('r1'))
    with pytest.raises(PermissionError, match='explicit pruning permission'):
        _reduce(trace, PruningPolicy(), sensitivity=Sensitivity.RESTRICTED)

    view, store, snapshot = _reduce(trace, PruningPolicy(include_restricted=True), sensitivity=Sensitivity.RESTRICTED)
    inspector = ObservationInspector(store, snapshot)
    with pytest.raises(PermissionError, match='explicit inspection permission'):
        inspector.inspect(view.fragments[0].ref, InspectionBudget())
    assert inspector.inspect(view.fragments[0].ref, InspectionBudget(allow_restricted=True)).returned_bytes > 0


# ── Addressing, resolution, and refusal ───────────────────────────────────────


def _indexed(trace: NetworkTrace):
    """Reduce, compile, and bind a trace so its addresses can be resolved."""
    view, store, snapshot = _reduce(trace)
    index = ObservationIndexCompiler().compile(snapshot, (view,))
    return index, ObservationInspector(store, snapshot)


def test_expand_pages_a_region_and_keys_only_what_is_distinguishable() -> None:
    trace = _complete(*(_request(f'r{index}') for index in range(5)), _request('broken', status=500))
    index, inspector = _indexed(trace)
    region = next(entry for entry in index.entries if entry.coverage is not None)

    page = inspector.expand(region.ref, InspectionBudget(max_items=4))
    assert [member.ordinal for member in page.members] == [0, 1, 2, 3]
    assert page.truncated
    assert not any(member.stable for member in page.members)

    tail = inspector.expand(region.ref, InspectionBudget(max_items=4), offset=4)
    assert [member.ordinal for member in tail.members] == [4, 5]
    assert tail.members[-1].stable
    assert not tail.truncated


def test_inspecting_a_request_returns_its_exact_canonical_record() -> None:
    trace = _complete(_request('r1', path='/v1/one'), _request('broken', status=500), _request('ok'))
    index, inspector = _indexed(trace)
    region = next(entry for entry in index.entries if entry.coverage is not None and 'cart' in entry.label)

    member = inspector.expand(region.ref, InspectionBudget())
    detail = inspector.inspect(member.members[0].ref, InspectionBudget()).content.decode()

    assert '"request_id"' in detail
    assert '"origin":"https://api.example"' in detail


def test_expand_refuses_an_element_address_and_inspect_refuses_a_foreign_one() -> None:
    trace = _complete(_request('r1'))
    index, inspector = _indexed(trace)

    with pytest.raises(ObservationAddressError, match='requires a region address'):
        inspector.expand(index.entries[0].ref, InspectionBudget())

    unknown = index.entries[1].ref.model_copy(
        update={
            'locator': '//*[@data-origin="https://absent.example"]#anchor=data-origin%3Dhttps%3A%2F%2Fabsent.example'
        }
    )
    with pytest.raises(ObservationAddressError, match='resolved to 0 things'):
        inspector.inspect(unknown, InspectionBudget())


def test_a_payload_that_disagrees_with_its_artifact_is_refused() -> None:
    trace = _complete(_request('r1'))
    data = serialize_network_trace(trace)
    store = MemoryArtifactStore()
    artifact = store.put(
        snapshot_id='a_different_snapshot', kind=EvidenceKind.NETWORK, media_type='application/json', data=data
    )

    with pytest.raises(ValueError, match='payload snapshot disagrees'):
        NetworkPruner().prune(PruningInput(source=artifact, data=data), PruningPolicy())


def test_the_network_pruner_refuses_another_modality() -> None:
    store = MemoryArtifactStore()
    artifact = store.put(snapshot_id=SNAPSHOT, kind=EvidenceKind.SOURCE_HTML, media_type='text/html', data=b'<p>x</p>')

    with pytest.raises(ValueError, match='cannot consume source_html'):
        NetworkPruner().prune(PruningInput(source=artifact, data=b'<p>x</p>'), PruningPolicy())


# ── Identity: earned, or refused ──────────────────────────────────────────────


def test_every_entry_of_an_ordinary_trace_earns_an_identity() -> None:
    trace = _complete(_request('r1'), _request('broken', status=500))
    index, _ = _indexed(trace)

    assert all(entry.ref_id is not None for entry in index.entries)
    assert all(parse_address(entry.ref.locator).is_anchored for entry in index.entries)


def test_a_positional_member_is_refused_an_identity_rather_than_given_a_weak_one() -> None:
    trace = _complete(*(_request(f'r{index}') for index in range(3)), _request('broken', status=500))
    index, _ = _indexed(trace)
    region = next(entry for entry in index.entries if entry.coverage is not None)
    inspector = _indexed(trace)[1]

    page = inspector.expand(region.ref, InspectionBudget())
    from yosoi.observations.index.addressing import ref_id

    positional = next(member for member in page.members if not member.stable)
    keyed = next(member for member in page.members if member.stable)
    assert ref_id(positional.ref.modality, positional.ref.locator) is None
    assert ref_id(keyed.ref.modality, keyed.ref.locator) is not None


def test_an_origin_the_locator_grammar_cannot_express_falls_back_and_is_refused_identity() -> None:
    """The `net1` validators keep this off the normal path, so it is proved directly."""
    # TWO origins, because with one the tag tier legitimately anchors it: `tag:origin` occurring
    # exactly once is a durable key. The fallback is what happens when NO tier is expressible.
    trace = _complete(
        _request('r1', origin='https://ho|st.example'),
        _request('r2', origin='https://ok.example', path='/v1/other'),
    )
    index, inspector = _indexed(trace)

    origin_entry = next(entry for entry in index.entries if entry.label == 'https://ho|st.example')
    assert origin_entry.ref_id is None
    assert not parse_address(origin_entry.ref.locator).is_anchored
    assert matches_fallback(origin_entry.ref.locator, 'https://ho|st.example')
    assert fallback_path('https://ho|st.example') == origin_entry.ref.locator
    # Refusal of an identity is not refusal of resolution: it still resolves inside its own snapshot.
    assert inspector.inspect(origin_entry.ref, InspectionBudget()).returned_bytes > 0


def test_grouping_is_stable_under_reordering_of_the_same_calls() -> None:
    forward = _complete(_request('a'), _request('b', path='/v1/other'), _request('c'))
    groups = group_requests(forward)

    assert [(group.path_template, len(group.requests)) for group in groups] == [('/v1/cart', 2), ('/v1/other', 1)]
