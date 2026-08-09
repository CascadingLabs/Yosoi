"""Normalized network-evidence reduction over the versioned `net1` artifact.

Three things make this modality different from the markup ones, and only the third is new work:

* **The tree is already there.** Origin → path template → requests is a genuine two-level tree, so
  `depth` means something without inventing a hierarchy, and "collapse a run of identical shapes
  into one region plus a count" *is* duplicate-call grouping. The shared region mechanism therefore
  gives the boss fight's "duplicate requests remain countable even when represented compactly" for
  free: a region reports 41 members, and `expand` still walks all 41.
* **The artifact is already safe.** Redaction happens before bytes become canonical, so this
  reducer has no redaction step and no way to add one. It cannot leak a header value because
  `models/network.py` has nowhere to put one.
* **Ranking.** 400 requests reduce to a few dozen entries whichever way you order them; whether the
  two that matter are *visible* is an ordering question. Ordering here is lexicographic over an
  enumerated tuple of rarity features (`network_tree.RARITY_FEATURES`), each of which is either a
  closed specification or a property measured against this trace. There is no weight to fit and no
  score to tune, and what the ranking did not look at is stated in the root entry.
"""

from __future__ import annotations

from yosoi.observations.index.addressing import ObservationAddress, anchor_address, element_address, format_address
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.network import NetworkRequest, NetworkTrace, parse_network_trace
from yosoi.observations.network_tree import (
    TRACE_TAG,
    EndpointGroup,
    TraceContext,
    TraceDefaults,
    anchor_census,
    assign_request_member_keys,
    deviant_requests,
    endpoint_anchor,
    endpoint_label,
    endpoint_summary,
    fallback_path,
    group_by_origin,
    group_coverage,
    group_rank_key,
    group_requests,
    index_conventions,
    origin_anchor,
    origin_summary,
    rank_key,
    rarity_profile,
    request_label,
    request_summary,
    trace_anchor,
    trace_context,
    trace_defaults,
)
from yosoi.observations.pruning._base import PruneCandidate, Reduction, SemanticPruner
from yosoi.observations.pruning._shared import require_prunable
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy

NETWORK_PRUNER_VERSION = '1'
"""First implemented version. `scaffold` views refused to exist, so nothing is being invalidated."""

TRACE_DEPTH = 0
ORIGIN_DEPTH = 1
ENDPOINT_DEPTH = 2
"""The tree the modality actually has. Progressive collapse cuts on this axis like any other."""


class _Minter:
    """Mints network addresses through the shared anchoring recipe.

    A request's durable key comes from its own structure — method, origin, path template — which is
    expressible as an ordered attribute sequence, so `anchoring` mints these identities with the
    same tiers, the same uniqueness census, and the same reserved-character rule it applies to an
    HTML element. Nothing modality-specific enters identity; what is modality-specific is only that
    the "elements" are described rather than parsed.
    """

    def __init__(self, trace: NetworkTrace, groups: tuple[EndpointGroup, ...]) -> None:
        """Build the trace-wide census this minter consults per entry."""
        self._trace = trace
        self._census = anchor_census(trace, groups)

    def _address(self, key: str | None, value: str) -> ObservationAddress:
        """Return the anchored address for a durable key, or a snapshot-local fallback."""
        if key is not None:
            return anchor_address(key)
        return element_address(fallback_path(value))

    def trace(self) -> ObservationAddress:
        """Return the address of the trace root, anchored by tag rather than by snapshot."""
        return self._address(trace_anchor(self._census), TRACE_TAG)

    def origin(self, origin: str) -> ObservationAddress:
        """Return the address of one origin."""
        return self._address(origin_anchor(origin, self._census), origin)

    def endpoint(self, group: EndpointGroup) -> ObservationAddress:
        """Return the region address of one endpoint group."""
        return self._address(endpoint_anchor(group, self._census), group.anchor_value).as_region(group.shape)


class NetworkPruner(SemanticPruner):
    """Deterministically reduce one normalized, redacted network trace.

    Emits one entry per origin, one region per endpoint, and one extra entry per request that
    deviates from the other members of its own group. A group of one is never given a second entry:
    its region line already states that request's facts, and restating them is the childless-exemplar
    cost the DOM reducer measured at 4.5% of a real index.
    """

    name = 'network'
    version = NETWORK_PRUNER_VERSION
    evidence_kind = EvidenceKind.NETWORK

    def reduce_once(self, source: PruningInput, policy: PruningPolicy) -> Reduction:
        """Validate the artifact, bind the self-described trace to it, then walk it once.

        Deliberately validates BEFORE parsing rather than calling the template first: handing this
        pruner a source-HTML artifact must report a modality mismatch, not a JSON syntax error about
        `<p>`. `require_prunable` is the template's whole body apart from the walk, so this is the
        same contract in the right order, not a second one.
        """
        require_prunable(source, self.evidence_kind, policy)
        trace = parse_network_trace(source.data)
        if trace.snapshot_id != source.source.snapshot_id:
            raise ValueError('network payload snapshot disagrees with its artifact')
        return self.reduce(source.data, policy)

    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Return a bounded, rarity-ordered proposal over validated network JSON bytes."""
        trace = parse_network_trace(data)
        groups = group_requests(trace)
        context = trace_context(trace)
        defaults = trace_defaults(trace)
        minter = _Minter(trace, groups)

        origins = _ranked_origins(groups, context)
        candidates = [_root_candidate(trace, groups, defaults, policy, minter)]
        for origin, origin_groups in origins:
            candidates.append(
                PruneCandidate(
                    locator=format_address(minter.origin(origin)),
                    label=origin,
                    summary=origin_summary(origin_groups),
                    depth=ORIGIN_DEPTH,
                    descends=True,
                )
            )
            for group in sorted(origin_groups, key=lambda g: (group_rank_key(g, context), endpoint_label(g))):
                candidates.extend(_endpoint_candidates(group, trace, context, defaults, policy, minter))
        return Reduction(candidates=tuple(candidates), source_items=_population(trace, groups, origins))


def _population(trace: NetworkTrace, groups: tuple[EndpointGroup, ...], origins: list) -> int:
    """Count everything this reduction could have addressed, so omission means something.

    The population is not "the requests": the trace root, each origin, and each endpoint group are
    addressable things too, and counting only requests made `retained_items` exceed `source_items`
    on a small trace — one origin and two endpoints out of two requests. Counting all four kinds
    makes the arithmetic land exactly where it should: `omitted_items` is then the number of
    requests the index did NOT give an individual entry to, each still reachable through `expand`.
    """
    return 1 + len(origins) + len(groups) + trace.observed_request_count


def _ranked_origins(
    groups: tuple[EndpointGroup, ...], context: TraceContext
) -> list[tuple[str, tuple[EndpointGroup, ...]]]:
    """Order origins by the rarest thing they carry, then by name so ties are total."""
    return sorted(
        group_by_origin(groups),
        key=lambda item: (min(group_rank_key(group, context) for group in item[1]), item[0]),
    )


def _restricted_note(request: NetworkRequest, policy: PruningPolicy) -> str:
    """Return the addressable pointer to a retained raw body, only under the existing gate.

    `PruningPolicy.include_restricted` decides whether a reduction may name the artifact; reading
    it needs `InspectionBudget.allow_restricted` as well. Both gates already existed, so neither is
    reinvented here, and no third switch is introduced. Without the gate the summary still says a
    body was retained — that a body EXISTS is not the secret — it simply does not say where.
    """
    body = request.restricted_body
    if body is None or not policy.include_restricted:
        return ''
    return f'; restricted body artifact {body.artifact_sha256} ({body.media_type}, {body.size_bytes}B)'


def _restricted_group_note(group: EndpointGroup, policy: PruningPolicy) -> str:
    """Return the retained-body pointer for a whole group, under the same single gate.

    A request with a retained body is not necessarily a request that deviates from its group, so the
    pointer cannot live only on flagged members — without this, an ordinary request's restricted
    artifact was acknowledged on the root entry and then never addressable anywhere.
    """
    retained = [request for request in group.requests if request.restricted_body is not None]
    if not retained:
        return ''
    if not policy.include_restricted:
        return (
            f'; {len(retained)} member(s) retained a raw body as a restricted artifact '
            '(not named: PruningPolicy.include_restricted is off)'
        )
    shown = ', '.join(
        request.restricted_body.artifact_sha256 for request in retained[:3] if request.restricted_body is not None
    )
    more = f' +{len(retained) - 3} more' if len(retained) > 3 else ''
    return f'; restricted body artifact(s): {shown}{more}'


def _root_candidate(
    trace: NetworkTrace,
    groups: tuple[EndpointGroup, ...],
    defaults: TraceDefaults,
    policy: PruningPolicy,
    minter: _Minter,
) -> PruneCandidate:
    """Emit the one entry that declares the defaults every other entry omits."""
    restricted = sum(1 for request in trace.requests if request.restricted_body is not None)
    body_note = ''
    if restricted:
        gate = 'named below' if policy.include_restricted else 'not named: PruningPolicy.include_restricted is off'
        body_note = f'; {restricted} restricted raw body artifact(s), {gate}'
    summary = (
        f'{trace.observed_request_count} request(s), {len(group_by_origin(groups))} origin(s), '
        f'{len(groups)} endpoint(s); {defaults.describe()}; {index_conventions(trace)}{body_note}'
    )
    return PruneCandidate(
        locator=format_address(minter.trace()),
        label='network trace',
        summary=summary,
        depth=TRACE_DEPTH,
        descends=bool(groups),
    )


def _endpoint_candidates(
    group: EndpointGroup,
    trace: NetworkTrace,
    context: TraceContext,
    defaults: TraceDefaults,
    policy: PruningPolicy,
    minter: _Minter,
) -> list[PruneCandidate]:
    """Emit one region for an endpoint, then one entry per member that deviates from it."""
    region = minter.endpoint(group)
    candidates = [
        PruneCandidate(
            locator=format_address(region),
            label=endpoint_label(group),
            summary=endpoint_summary(group, trace, context, defaults) + _restricted_group_note(group, policy),
            coverage=group_coverage(trace, group),
            depth=ENDPOINT_DEPTH,
            descends=True,
        )
    ]
    keys = assign_request_member_keys(group.requests)
    positions = {request.request_id: position for position, request in enumerate(group.requests)}
    member_keys = {request.request_id: key for request, key in zip(group.requests, keys, strict=True)}
    deviants = sorted(
        deviant_requests(group, context),
        key=lambda request: (rank_key(rarity_profile(request, context)), positions[request.request_id]),
    )
    for request in deviants:
        key = member_keys[request.request_id]
        candidates.append(
            PruneCandidate(
                locator=format_address(
                    region.member(key=key, ordinal=None if key is not None else positions[request.request_id])
                ),
                label=request_label(request),
                summary=request_summary(request, context, defaults) + _restricted_note(request, policy),
                depth=ENDPOINT_DEPTH,
                bound_to_previous=True,
            )
        )
    return candidates


__all__ = ['ENDPOINT_DEPTH', 'NETWORK_PRUNER_VERSION', 'ORIGIN_DEPTH', 'TRACE_DEPTH', 'NetworkPruner']
