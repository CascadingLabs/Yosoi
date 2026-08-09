"""Shared network shape/key/rarity primitives, defined once for producer and pruner.

The counterpart of `html_tree` and `dom_tree`: one definition of how a URL becomes a template,
how a value becomes a class, how requests group, and what makes one request *rare*. A producer
normalizing a live capture and a pruner reducing the resulting artifact must agree on all four, or
an artifact's `duplicate_key` disagrees with the grouping the index is built from.

Network evidence is a genuine two-level tree — origin → path template → requests — and collapsing
a run of identical call shapes into one region plus a count *is* duplicate-call grouping. So this
module has no dedup mechanism of its own: it groups, and `pruning/network.py` hands the groups to
the shared region machinery that source HTML and DOM already use.

Identity comes from `anchoring.py` and nothing else. A request's durable key is its own structure
— method, origin, path template — which is expressible as the ordered attribute sequence the
shared census already takes, so the tiers, the uniqueness check, and the reserved-character rule
are the same ones every other modality gets.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from yosoi.observations import anchoring
from yosoi.observations.index.addressing import ObservationAddress, ObservationAddressError
from yosoi.observations.models.network import (
    NetworkRequest,
    NetworkTrace,
    QueryParam,
    ShapeSignature,
    ValueClass,
    shape_digest,
)
from yosoi.observations.models.view import RegionCoverage

# ── Credential posture, inherited from VoidCrawl ──────────────────────────────

SENSITIVE_HEADER_SUBSTRINGS: tuple[str, ...] = (
    'authorization',
    'authenticate',
    'authentication',
    'x-auth',
    'cookie',
    'token',
    'api-key',
    'apikey',
    'secret',
    'credential',
    'password',
    'signature',
    'session',
)
"""Substrings marking a header name as credential-bearing.

Copied verbatim from VoidCrawl's `network_capture`
(`crates/mcp_server/src/tools/network.rs::SENSITIVE_HEADER_SUBSTRINGS`) rather than reinvented:
that list is where the redaction posture is decided, it is deny-by-default and substring-matched
so a novel `x-my-session-token` is caught, and two lists would eventually disagree about what a
credential is. Yosoi never holds the values, so what this list is used for here is the opposite of
redaction — naming which credential-bearing headers an endpoint *requires*, which is evidence.
"""


def credential_header_names(names: Iterable[str]) -> tuple[str, ...]:
    """Return the header names that are credential-bearing, in the order given."""
    return tuple(name for name in names if any(needle in name for needle in SENSITIVE_HEADER_SUBSTRINGS))


# ── Value classification ──────────────────────────────────────────────────────

_ISO_TIMESTAMP = re.compile(r'^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$')
_EPOCH = re.compile(r'^\d{10}$|^\d{13}$')
_UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_INTEGER = re.compile(r'^\d+$')
_HEX = re.compile(r'^(?:[0-9a-fA-F]{2}){4,}$')
_TOKENISH = re.compile(r'^[A-Za-z0-9_-]{20,}$')
_ENUMISH = re.compile(r'^[A-Za-z][A-Za-z0-9_.-]{0,23}$')

CLASSIFICATION_ORDER = ('empty', 'timestamp', 'id', 'token', 'enum', 'opaque')
"""The one order `classify_value` tries the classes in.

Stated because the classes overlap and the overlaps have to resolve the same way everywhere: a
ten-digit string is an epoch second *and* an integer id, and a lowercase hex string of 20
characters is a hex id *and* token-shaped. Timestamp before id and id before token means those
two cases resolve as timestamp and id, always.
"""


def classify_value(value: str) -> ValueClass:
    """Return the closed-set class of one parameter or path-segment value.

    Regex-only and total: every string lands in exactly one class, so classification never depends
    on how often a value was seen. A frequency rule would have been a threshold, and a threshold is
    the tuning knob this modality's ranking is not allowed to have.
    """
    if not value:
        return ValueClass.EMPTY
    if _ISO_TIMESTAMP.match(value) or _EPOCH.match(value):
        return ValueClass.TIMESTAMP
    if _INTEGER.match(value) or _UUID.match(value) or _HEX.match(value):
        return ValueClass.ID
    if _TOKENISH.match(value) and any(c.isalpha() for c in value) and any(c.isdigit() for c in value):
        return ValueClass.TOKEN
    if _ENUMISH.match(value):
        return ValueClass.ENUM
    return ValueClass.OPAQUE


TEMPLATED_CLASSES = frozenset({ValueClass.TIMESTAMP, ValueClass.ID, ValueClass.TOKEN})
"""Which classes replace a path segment with a placeholder.

`ENUM` and `OPAQUE` stay literal: an enum segment is part of what the endpoint IS (`/v1/orders`
against `/v1/users`), and an opaque segment is not recognizably a value, so templating it would
erase a real path element on a guess. Nothing here is measured against a threshold — `/static/`
does not become `{opaque}` because 300 files live under it.
"""

_EXTENSION = re.compile(r'^[A-Za-z0-9]{1,8}$')


def template_segment(segment: str) -> str:
    """Return one path segment as itself or as its value-class placeholder."""
    stem, dot, extension = segment.rpartition('.')
    if not dot or not _EXTENSION.match(extension):
        stem, extension = segment, ''
    value_class = classify_value(stem)
    if value_class not in TEMPLATED_CLASSES:
        return segment
    placeholder = '{' + value_class.value + '}'
    return f'{placeholder}.{extension}' if extension else placeholder


def path_template(path: str) -> str:
    """Return a path with every value-bearing segment replaced by its class placeholder."""
    if not path.startswith('/'):
        path = f'/{path}'
    segments = [template_segment(segment) for segment in path.split('/') if segment]
    trailing = '/' if path.endswith('/') and segments else ''
    return '/' + '/'.join(segments) + trailing if segments else '/'


def classify_params(query: str) -> tuple[QueryParam, ...]:
    """Return parameter NAMES with value classes, in first-appearance order.

    A repeated name keeps the class of its first occurrence. Multi-valued parameters therefore
    report one class rather than a set — a stated simplification, not an inference.
    """
    seen: dict[str, QueryParam] = {}
    for name, value in parse_qsl(query, keep_blank_values=True):
        if name and name not in seen:
            seen[name] = QueryParam(name=name, value_class=classify_value(value))
    return tuple(seen.values())


def normalize_url(url: str) -> tuple[str, str, tuple[QueryParam, ...]]:
    """Split one raw URL into the origin, path template, and classed parameter names it keeps.

    This is the producer-side half of the security boundary expressed as code: a raw URL goes in
    and no value comes out. The fragment is dropped entirely, since it never reaches a server.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f'network url {url!r} has no origin to normalize')
    origin = f'{parts.scheme.lower()}://{parts.netloc.lower()}'
    return origin, path_template(parts.path or '/'), classify_params(parts.query)


TIMING_BOUNDS_MS = ((50, 'instant'), (200, 'fast'), (1_000, 'moderate'), (3_000, 'slow'))
"""Upper bounds, in milliseconds, for every timing bucket below `very_slow`.

Part of `net1`, not of a policy: two consumers that bucket the same duration differently cannot
compare their traces, and a bucket boundary a caller can move is a bucket that means nothing.
"""


def timing_bucket(duration_ms: float | None) -> str:
    """Return the bucket name for one measured duration, or `unknown` when unmeasured."""
    if duration_ms is None or duration_ms < 0:
        return 'unknown'
    return next((name for bound, name in TIMING_BOUNDS_MS if duration_ms < bound), 'very_slow')


# ── Payload shape ─────────────────────────────────────────────────────────────

MAX_SHAPE_KEYS = 64
"""How many skeleton keys one shape signature keeps. Beyond this the signature says so."""


def json_key_skeleton(payload: object) -> tuple[str, ...]:
    """Return the sorted dotted key paths of a decoded JSON payload, with no values.

    A list contributes `[]` and the UNION of its members' keys, so a two-element and a
    two-thousand-element list of the same records have the same skeleton. That is the point:
    shape is the collapse equivalence, and cardinality is carried separately as a declared count.
    """
    keys: set[str] = set()
    _walk_shape(payload, prefix='', keys=keys)
    return tuple(sorted(keys))


def _walk_shape(payload: object, *, prefix: str, keys: set[str]) -> None:
    """Accumulate dotted key paths for one JSON node."""
    if isinstance(payload, dict):
        for name in payload:
            path = f'{prefix}.{name}' if prefix else str(name)
            keys.add(path)
            _walk_shape(payload[name], prefix=path, keys=keys)
    elif isinstance(payload, list):
        path = f'{prefix}[]'
        keys.add(path)
        for item in payload:
            _walk_shape(item, prefix=path, keys=keys)


def shape_signature(payload: object) -> ShapeSignature:
    """Return the bounded key skeleton and digest of a decoded JSON payload."""
    keys = json_key_skeleton(payload)
    kept = keys[:MAX_SHAPE_KEYS]
    return ShapeSignature(digest=shape_digest(kept), keys=kept, truncated=len(kept) < len(keys))


# ── Grouping: the two-level tree ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EndpointGroup:
    """Every observed call to one `method origin path_template`, in trace order."""

    origin: str
    method: str
    path_template: str
    requests: tuple[NetworkRequest, ...]

    @property
    def anchor_value(self) -> str:
        """Return the durable, trace-unique description this group is addressed by."""
        return f'{self.method} {self.origin}{self.path_template}'

    @property
    def shape(self) -> str:
        """Return the call-signature digest every member of this group shares."""
        return self.requests[0].duplicate_key

    @property
    def duplicate_counts(self) -> tuple[tuple[str, int], ...]:
        """Return how many members share each duplicate key, largest run first."""
        counts = Counter(request.duplicate_key for request in self.requests)
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def group_requests(trace: NetworkTrace) -> tuple[EndpointGroup, ...]:
    """Group a trace by origin and path template, preserving first-appearance order."""
    buckets: dict[tuple[str, str, str], list[NetworkRequest]] = {}
    for request in trace.requests:
        buckets.setdefault((request.origin, request.method, request.path_template), []).append(request)
    return tuple(
        EndpointGroup(origin=origin, method=method, path_template=template, requests=tuple(requests))
        for (origin, method, template), requests in buckets.items()
    )


def group_by_origin(groups: Sequence[EndpointGroup]) -> tuple[tuple[str, tuple[EndpointGroup, ...]], ...]:
    """Return endpoint groups bucketed by origin, preserving first-appearance order."""
    buckets: dict[str, list[EndpointGroup]] = {}
    for group in groups:
        buckets.setdefault(group.origin, []).append(group)
    return tuple((origin, tuple(members)) for origin, members in buckets.items())


def group_coverage(trace: NetworkTrace, group: EndpointGroup) -> RegionCoverage:
    """Return how much of one endpoint's traffic this trace actually observed.

    `declared` is stated only when the producer declared the trace complete. A capture armed late
    or capped by a byte budget holds an unknown fraction of an endpoint's calls, and reporting
    `40/40 complete` for it would turn a partial trace into a total one.
    """
    observed = len(group.requests)
    complete = trace.complete
    return RegionCoverage(observed=observed, declared=observed if complete else None, complete=complete)


# ── Identity: the shared anchoring recipe, applied to a trace ─────────────────

ORIGIN_ATTRIBUTE = 'data-origin'
ENDPOINT_ATTRIBUTE = 'data-endpoint'

TRACE_TAG = 'trace'
"""The tag the trace root is anchored by. It carries no attributes; see `pseudo_elements`."""

_ORIGIN_TAG = 'origin'
_ENDPOINT_TAG = 'endpoint'

_FALLBACK_PREFIX = '/net/node/'


PseudoElement = tuple[str, tuple[tuple[str, str], ...]]
"""A tag plus an ordered attribute sequence — all `anchoring` needs to mint an identity."""


def pseudo_elements(trace: NetworkTrace, groups: Sequence[EndpointGroup]) -> list[PseudoElement]:
    """Return the trace as `(tag, ordered attributes)` pairs the shared census can count.

    Network evidence has no markup, but identity does not need markup — it needs a tag and an
    ordered attribute sequence, which is exactly what an origin and an endpoint have. Expressing
    them that way is what lets `anchoring.build_census` and `anchoring.usable_anchor` do the work
    here without a second identity recipe existing anywhere.

    The trace root deliberately carries NO attributes and is anchored by its tag alone. Keying it on
    the snapshot id was the obvious move and was wrong: `ref_id` must be computed from nothing the
    capture provides, and a root keyed on the snapshot id minted a different identity for every
    capture of the same page — measured as 40 of 41 identities matching across two captures instead
    of 41.
    """
    return [pseudo_element for pseudo_element, _, _ in _addressables(trace, groups)]


def _addressables(
    trace: NetworkTrace, groups: Sequence[EndpointGroup]
) -> list[tuple[PseudoElement, str, NetworkTarget]]:
    """Return every addressable thing: its pseudo element, its fallback value, and the thing."""
    found: list[tuple[PseudoElement, str, NetworkTarget]] = [((TRACE_TAG, ()), TRACE_TAG, trace)]
    found.extend(
        (((_ORIGIN_TAG, ((ORIGIN_ATTRIBUTE, origin),)), origin, origin) for origin, _ in group_by_origin(groups))
    )
    found.extend(
        ((_ENDPOINT_TAG, ((ENDPOINT_ATTRIBUTE, group.anchor_value),)), group.anchor_value, group) for group in groups
    )
    return found


def anchor_census(trace: NetworkTrace, groups: Sequence[EndpointGroup]) -> dict[str, int]:
    """Return the anchor-key census for one trace, built once and consulted per entry."""
    return anchoring.build_census(pseudo_elements(trace, groups))


def trace_anchor(census: dict[str, int]) -> str | None:
    """Return the durable key for the trace root, or None when it has none."""
    return anchoring.usable_anchor(TRACE_TAG, (), census)


def origin_anchor(origin: str, census: dict[str, int]) -> str | None:
    """Return the durable key for one origin, or None when it has none."""
    return anchoring.usable_anchor(_ORIGIN_TAG, ((ORIGIN_ATTRIBUTE, origin),), census)


def endpoint_anchor(group: EndpointGroup, census: dict[str, int]) -> str | None:
    """Return the durable key for one endpoint group, or None when it has none."""
    return anchoring.usable_anchor(_ENDPOINT_TAG, ((ENDPOINT_ATTRIBUTE, group.anchor_value),), census)


def fallback_path(anchor_value: str) -> str:
    """Return a snapshot-local path for evidence the trace offers no expressible key for.

    The network counterpart of `/dom/node/<producer id>`: it resolves exactly inside its own
    snapshot and `ref_id` refuses it an identity, which is honest about a key that cannot survive
    the locator grammar rather than inventing an escape the resolver would have to guess at.
    """
    return f'{_FALLBACK_PREFIX}{shape_digest((anchor_value,))}'


def fallback_digest(path: str) -> str:
    """Return the digest a network fallback path carries."""
    if not path.startswith(_FALLBACK_PREFIX):
        raise ValueError(f'{path!r} is not a network fallback path')
    return path[len(_FALLBACK_PREFIX) :]


def matches_fallback(path: str, anchor_value: str) -> bool:
    """Return whether a fallback path names the evidence described by `anchor_value`."""
    return fallback_digest(path) == shape_digest((anchor_value,))


# ── Member keys ───────────────────────────────────────────────────────────────


def request_candidate_keys(request: NetworkRequest) -> tuple[str, ...]:
    """Return the keys that could distinguish one request inside its endpoint group, best first.

    Deliberately derived from the response rather than from the capture: `request_id` would key
    every member durably within this snapshot and none of them across two, which is the weaker id
    the identity tier refuses. What survives a re-capture is what the endpoint DID — the call
    signature it was made with, the status it returned, the shape it returned.

    The useful consequence is that the anomalous member is the one that earns a key: a single 500
    among 40 identical polls is `status=500`, unique in its group, while the 40 look-alikes are
    addressable only by position — which is the truth about them.
    """
    candidates = [f'dup={request.duplicate_key}']
    if request.status is not None:
        candidates.append(f'status={request.status}')
    if request.response_shape is not None:
        candidates.append(f'rshape={request.response_shape.digest}')
    if request.mime:
        candidates.append(f'mime={request.mime}')
    return tuple(
        candidate
        for candidate in candidates
        if not any(character in candidate for character in anchoring.LOCATOR_RESERVED)
    )


def assign_request_member_keys(requests: Sequence[NetworkRequest]) -> tuple[str | None, ...]:
    """Assign each request its best group-unique key, or None when it has none."""
    census = Counter(key for request in requests for key in request_candidate_keys(request))
    return tuple(
        next((key for key in request_candidate_keys(request) if census[key] == 1), None) for request in requests
    )


# ── Rarity: the only thing ranking is allowed to look at ──────────────────────


@dataclass(frozen=True, slots=True)
class RarityFeature:
    """One enumerated, computable reason a request might deserve a reader's attention."""

    name: str
    basis: str
    description: str


RARITY_FEATURES: tuple[RarityFeature, ...] = (
    RarityFeature(
        'status_not_success',
        'closed spec',
        'status class is neither 2xx nor 3xx (RFC 9110 §15), or no response arrived',
    ),
    RarityFeature(
        'response_shape_deviates',
        'measured',
        'response key skeleton differs from the modal skeleton of its own duplicate group',
    ),
    RarityFeature(
        'problem_mime',
        'closed spec',
        'response media type is application/problem+json (RFC 9457)',
    ),
    RarityFeature(
        'mime_deviates',
        'measured',
        'response media type differs from the modal media type of its own duplicate group',
    ),
    RarityFeature(
        'item_count_deviates',
        'measured',
        'declared collection size differs from the modal declared size of its own duplicate group',
    ),
    RarityFeature(
        'singleton_template',
        'measured',
        'this path template was requested exactly once in the whole trace',
    ),
)
"""Every feature ranking may consider, in the ONE order it considers them.

Ranking is lexicographic over the boolean tuple in this declared order — a strict precedence, not
a weighted score. There is no coefficient to fit, so there is nothing to overfit to a fixture: a
feature either fired or it did not, and a feature earlier in this tuple always outranks every
feature after it. Each entry states its basis, and the two bases are the only ones allowed: a
closed specification, or a property measured against the trace itself.

What is deliberately NOT here, because it would be a weight or a guess: how many bytes a response
was, how slow it was relative to its peers, how unusual its host is, whether its path "looks like"
an API, and any judgement about first- vs third-party. `OMITTED_RANKING_SIGNALS` states these in
the reduction itself, so a reader is told what the ranking did not look at.
"""

OMITTED_RANKING_SIGNALS: tuple[str, ...] = (
    'API/DOM cardinality mismatch (needs the DOM modality; only the network-internal half is computed)',
    'response size and duration outliers (would need a tuned threshold)',
    'request ordering, dependency chains, and races',
    'host or path reputation of any kind',
    'server-sent events and WebSocket frames (not modelled by net1)',
)
"""Signals a reader might expect the ranking to use, which it does not. Stated, never silent."""


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Trace-wide properties measured once, so a feature is never a per-request guess."""

    modal_shape: dict[str, str]
    modal_mime: dict[str, str]
    modal_item_count: dict[str, int]
    duplicate_size: dict[str, int]
    template_count: dict[str, int]


def _modal(values: Iterable[object]) -> str | None:
    """Return the most common value as text, breaking ties by that text so it is total."""
    counts = Counter(str(value) for value in values if value is not None)
    if not counts:
        return None
    return min(counts.items(), key=lambda item: (-item[1], item[0]))[0]


def trace_context(trace: NetworkTrace) -> TraceContext:
    """Measure every trace-wide property the rarity features are computed against."""
    by_duplicate: dict[str, list[NetworkRequest]] = {}
    for request in trace.requests:
        by_duplicate.setdefault(request.duplicate_key, []).append(request)

    modal_shape: dict[str, str] = {}
    modal_mime: dict[str, str] = {}
    modal_item_count: dict[str, int] = {}
    for key, members in by_duplicate.items():
        shape = _modal(r.response_shape.digest for r in members if r.response_shape is not None)
        if shape is not None:
            modal_shape[key] = shape
        mime = _modal(r.mime for r in members)
        if mime is not None:
            modal_mime[key] = mime
        count = _modal(r.declared_item_count for r in members)
        if count is not None:
            modal_item_count[key] = int(count)

    return TraceContext(
        modal_shape=modal_shape,
        modal_mime=modal_mime,
        modal_item_count=modal_item_count,
        duplicate_size={key: len(members) for key, members in by_duplicate.items()},
        template_count=Counter(request.path_template for request in trace.requests),
    )


def rarity_profile(request: NetworkRequest, context: TraceContext) -> tuple[bool, ...]:
    """Return which of `RARITY_FEATURES` fired for one request, in declared order."""
    key = request.duplicate_key
    group_size = context.duplicate_size.get(key, 1)
    shape = request.response_shape.digest if request.response_shape is not None else None
    modal_shape = context.modal_shape.get(key)
    modal_mime = context.modal_mime.get(key)
    modal_count = context.modal_item_count.get(key)
    return (
        request.status_class not in {2, 3},
        group_size > 1 and shape is not None and modal_shape is not None and shape != modal_shape,
        request.mime == 'application/problem+json',
        group_size > 1 and request.mime is not None and modal_mime is not None and request.mime != modal_mime,
        (
            group_size > 1
            and request.declared_item_count is not None
            and modal_count is not None
            and request.declared_item_count != modal_count
        ),
        context.template_count.get(request.path_template, 0) == 1,
    )


def rank_key(profile: Sequence[bool]) -> tuple[int, ...]:
    """Return the lexicographic sort key for one rarity profile; lower sorts first."""
    return tuple(0 if fired else 1 for fired in profile)


def fired_features(profile: Sequence[bool]) -> tuple[str, ...]:
    """Return the names of the features that fired, in declared order."""
    return tuple(feature.name for feature, fired in zip(RARITY_FEATURES, profile, strict=True) if fired)


def group_rank_key(group: EndpointGroup, context: TraceContext) -> tuple[int, ...]:
    """Return the best (lowest) rarity rank any member of this group achieves."""
    return min(rank_key(rarity_profile(request, context)) for request in group.requests)


def deviant_requests(group: EndpointGroup, context: TraceContext) -> tuple[NetworkRequest, ...]:
    """Return the members of a group that stand out from the rest of that same group.

    A group of ONE is never deviant: its region entry already states that request's own facts, and
    a second entry restating them is the childless-exemplar cost the DOM reducer measured at 4.5%
    of a real index. So a flagged member always means "this request differs from its neighbours",
    never "this request is the only one here".
    """
    if len(group.requests) < 2:
        return ()
    return tuple(request for request in group.requests if any(rarity_profile(request, context)))


# ── Resolution ────────────────────────────────────────────────────────────────
#
# Deliberately here rather than in `index/inspect.py`, where the DOM equivalent lives. The
# inspector is shared by every modality and edited by every modality's author at once; keeping the
# network branch down to a dispatch line makes a hand merge trivial. The asymmetry is recorded in
# `docs/plans/network-modality-notes.md` rather than left to be discovered.

NetworkTarget = NetworkTrace | str | EndpointGroup | NetworkRequest
"""What one network address can name: the trace, an origin, an endpoint group, or one request."""


def _resolve_first_segment(trace: NetworkTrace, groups: Sequence[EndpointGroup], segment) -> NetworkTarget:
    """Resolve an address's first segment to the trace, an origin, or an endpoint group.

    Anchored addresses resolve by their KEY, exactly as the DOM resolver does: the locator carries
    both a key and the path it implies and `AddressSegment` has already checked them against each
    other, so re-deriving a match from the path would be a second interpretation of one fact, free
    to disagree with the first.
    """
    addressable = _addressables(trace, groups)
    if segment.anchor is not None:
        matches = [
            target
            for (tag, attributes), _, target in addressable
            if segment.anchor in anchoring.anchor_keys(tag, attributes)
        ]
    else:
        matches = [target for _, value, target in addressable if _safe_fallback_match(segment.path, value)]
    if len(matches) != 1:
        raise ObservationAddressError(f'network address segment {segment.path!r} resolved to {len(matches)} things')
    return matches[0]


def _safe_fallback_match(path: str, anchor_value: str) -> bool:
    """Return whether a path is a network fallback naming `anchor_value`, without raising."""
    try:
        return matches_fallback(path, anchor_value)
    except ValueError:
        return False


def network_region_members(group: EndpointGroup, shape: str) -> tuple[NetworkRequest, ...]:
    """Return the members of one endpoint region, failing closed on a foreign shape."""
    if group.shape != shape:
        raise ObservationAddressError(f'no members of shape {shape!r} remain in this network region')
    return group.requests


def _select_member(group: EndpointGroup, segment) -> NetworkRequest:
    """Select one request from a region by durable key, or by declared-unstable position."""
    members = network_region_members(group, segment.shape or '')
    if segment.key is not None:
        matched = [member for member in members if segment.key in request_candidate_keys(member)]
        if len(matched) != 1:
            raise ObservationAddressError(f'network region key {segment.key!r} resolved to {len(matched)} members')
        return matched[0]
    position = segment.ordinal or 0
    if position >= len(members):
        raise ObservationAddressError(f'network member ordinal {position} is past the {len(members)} members present')
    return members[position]


def resolve_network_address(trace: NetworkTrace, address: ObservationAddress) -> NetworkTarget:
    """Resolve one network address against exact trace bytes, failing closed at any ambiguity."""
    groups = group_requests(trace)
    if len(address.segments) != 1:
        raise ObservationAddressError('a network address is one segment; the trace tree is carried by depth')
    segment = address.segments[0]
    target = _resolve_first_segment(trace, groups, segment)
    if segment.shape is None:
        return target
    if not isinstance(target, EndpointGroup):
        raise ObservationAddressError('only an endpoint group can be addressed as a network region')
    if segment.selects_member:
        return _select_member(target, segment)
    network_region_members(target, segment.shape)
    return target


def resolve_network_region(trace: NetworkTrace, address: ObservationAddress) -> EndpointGroup:
    """Resolve one address that must name an endpoint region, failing closed when it does not."""
    target = resolve_network_address(trace, address)
    if not isinstance(target, EndpointGroup):
        raise ObservationAddressError('expand requires an endpoint region address')
    return target


def network_detail(target: NetworkTarget) -> bytes:
    """Return deterministic canonical JSON detail for whatever an address named."""
    if isinstance(target, NetworkRequest):
        payload: object = target.model_dump(mode='json')
    elif isinstance(target, EndpointGroup):
        payload = {
            'origin': target.origin,
            'method': target.method,
            'path_template': target.path_template,
            'observed': len(target.requests),
            'duplicate_counts': [list(item) for item in target.duplicate_counts],
            'request_ids': [request.request_id for request in target.requests],
        }
    elif isinstance(target, NetworkTrace):
        payload = {
            'schema_version': target.schema_version,
            'snapshot_id': target.snapshot_id,
            'observed_requests': target.observed_request_count,
            'complete': target.complete,
            'redaction': target.redaction.model_dump(mode='json'),
            'capabilities': [capability.model_dump(mode='json') for capability in target.capabilities],
        }
    else:
        payload = {'origin': target}
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')


# ── Defaults and description ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TraceDefaults:
    """The trace's own modal values, stated once so every entry can state only deviations.

    Measured from the trace, not declared by a policy: a trace of an image-heavy page has
    different defaults from a trace of a GraphQL client, and a fixed default list would make one of
    them repeat itself on every line.
    """

    method: str
    status: str
    timing: str
    initiator: str
    resource_type: str
    mime: str

    def describe(self) -> str:
        """State every default in one line, in a fixed field order."""
        return (
            f'defaults: method={self.method} status={self.status} timing={self.timing} '
            f'initiator={self.initiator} type={self.resource_type} mime={self.mime}'
        )


def trace_defaults(trace: NetworkTrace) -> TraceDefaults:
    """Measure the modal method, status, timing, initiator, resource type, and media type."""
    return TraceDefaults(
        method=_modal(r.method for r in trace.requests) or 'none',
        status=_modal(r.status for r in trace.requests) or 'none',
        timing=_modal(r.timing.value for r in trace.requests) or 'unknown',
        initiator=_modal(r.initiator.value for r in trace.requests) or 'unknown',
        resource_type=_modal(r.resource_type.value for r in trace.requests) or 'other',
        mime=_modal(r.mime for r in trace.requests) or 'none',
    )


def request_label(request: NetworkRequest) -> str:
    """Return one request's compact label: what was called and what came back."""
    outcome = 'no response' if request.status is None else str(request.status)
    return f'{request.method} {request.path_template} → {outcome}'


def endpoint_label(group: EndpointGroup) -> str:
    """Return one endpoint group's compact label. The origin lives on the origin entry."""
    return f'{group.method} {group.path_template}'


def _deviations(request: NetworkRequest, defaults: TraceDefaults) -> list[str]:
    """Return only the facts about one request that differ from the trace's own defaults."""
    stated: list[str] = []
    if str(request.status) != defaults.status:
        stated.append(f'status={request.status if request.status is not None else "no response"}')
    if request.mime and request.mime != defaults.mime:
        stated.append(f'mime={request.mime}')
    if request.timing.value != defaults.timing:
        stated.append(f'timing={request.timing.value}')
    if request.initiator.value != defaults.initiator:
        stated.append(f'initiator={request.initiator.value}')
    if request.resource_type.value != defaults.resource_type:
        stated.append(f'type={request.resource_type.value}')
    return stated


def _param_text(params: Sequence[QueryParam]) -> str:
    """Return parameter names with their value classes, never their values."""
    return ','.join(f'{param.name}:{param.value_class.value}' for param in params)


def request_summary(request: NetworkRequest, context: TraceContext, defaults: TraceDefaults) -> str:
    """Summarize one request: its deviations from the trace defaults, then why it stands out."""
    parts = _deviations(request, defaults)
    if request.params:
        parts.append(f'params {_param_text(request.params)}')
    if request.response_shape is not None:
        parts.append(f'response shape {request.response_shape.digest}')
    if request.declared_item_count is not None:
        parts.append(f'declared items={request.declared_item_count}')
    credentials = credential_header_names(request.request_header_names)
    if credentials:
        parts.append(f'credential headers (names only): {",".join(credentials)}')
    if request.restricted_body is not None:
        parts.append('raw body retained as a restricted artifact')
    fired = fired_features(rarity_profile(request, context))
    if fired:
        parts.append(f'rare: {",".join(fired)}')
    return '; '.join(parts) or 'matches every trace default'


def _status_text(group: EndpointGroup) -> str:
    """Return the status breakdown for one group, largest class first."""
    counts = Counter('no response' if r.status is None else str(r.status) for r in group.requests)
    return ', '.join(f'{status}×{count}' for status, count in sorted(counts.items(), key=lambda i: (-i[1], i[0])))


def endpoint_summary(group: EndpointGroup, trace: NetworkTrace, context: TraceContext, defaults: TraceDefaults) -> str:
    """Summarize one endpoint group so its members stay countable without being listed."""
    observed = len(group.requests)
    parts = [f'×{observed}']
    distinct = {str(r.status) for r in group.requests}
    if len(distinct) > 1 or distinct != {defaults.status}:
        parts.append(f'statuses {_status_text(group)}')
    duplicates = group.duplicate_counts
    if len(duplicates) > 1:
        parts.append(f'{len(duplicates)} call signatures: ' + ', '.join(f'{key[:8]}×{n}' for key, n in duplicates))
    elif observed > 1:
        parts.append(f'{observed} identical calls (duplicate key {group.shape[:8]})')
    shapes = {r.response_shape.digest for r in group.requests if r.response_shape is not None}
    if len(shapes) > 1:
        parts.append(f'{len(shapes)} response shapes')
    first = group.requests[0]
    if first.params:
        parts.append(f'params {_param_text(first.params)}')
    parts.extend(fact for fact in _deviations(first, defaults) if not fact.startswith('status='))
    credentials = credential_header_names(first.request_header_names)
    if credentials:
        parts.append(f'credential headers (names only): {",".join(credentials)}')
    deviants = deviant_requests(group, context)
    if deviants:
        parts.append(f'{len(deviants)} member(s) deviate from this group — indexed below')
    if not trace.complete:
        parts.append('trace incomplete: this count is a floor')
    return '; '.join(parts)


def origin_summary(groups: Sequence[EndpointGroup]) -> str:
    """Summarize one origin: how much traffic it carried and across how many endpoints."""
    requests = sum(len(group.requests) for group in groups)
    return f'{requests} request(s) across {len(groups)} endpoint(s)'


def unavailable_capabilities(trace: NetworkTrace) -> str:
    """State every capability the producer declared unavailable, with its stated reason.

    A modality that was not captured must stay visible as an absence. Silence here would let a
    reader treat "no request shapes in this index" as "no request had a body".
    """
    missing = [c for c in trace.capabilities if not c.available]
    if not missing:
        return 'every declared capability was captured'
    return 'NOT captured: ' + '; '.join(f'{c.kind.value} ({c.reason})' for c in missing)


def index_conventions(trace: NetworkTrace) -> str:
    """State what this reduction ranked on, what it did not look at, and what was not captured."""
    ranked = ', '.join(f'{feature.name} ({feature.basis})' for feature in RARITY_FEATURES)
    omitted = '; '.join(OMITTED_RANKING_SIGNALS)
    completeness = 'complete trace' if trace.complete else 'INCOMPLETE trace — counts are floors'
    return (
        f'{completeness}; {unavailable_capabilities(trace)}; ranked lexicographically on: {ranked}; '
        f'no weights or learned scores; NOT considered: {omitted}'
    )


__all__ = [
    'CLASSIFICATION_ORDER',
    'ENDPOINT_ATTRIBUTE',
    'MAX_SHAPE_KEYS',
    'OMITTED_RANKING_SIGNALS',
    'ORIGIN_ATTRIBUTE',
    'RARITY_FEATURES',
    'SENSITIVE_HEADER_SUBSTRINGS',
    'TEMPLATED_CLASSES',
    'TIMING_BOUNDS_MS',
    'TRACE_TAG',
    'EndpointGroup',
    'NetworkTarget',
    'PseudoElement',
    'RarityFeature',
    'TraceContext',
    'TraceDefaults',
    'anchor_census',
    'assign_request_member_keys',
    'classify_params',
    'classify_value',
    'credential_header_names',
    'deviant_requests',
    'endpoint_anchor',
    'endpoint_label',
    'endpoint_summary',
    'fallback_digest',
    'fallback_path',
    'fired_features',
    'group_by_origin',
    'group_coverage',
    'group_rank_key',
    'group_requests',
    'index_conventions',
    'json_key_skeleton',
    'matches_fallback',
    'network_detail',
    'network_region_members',
    'normalize_url',
    'origin_anchor',
    'origin_summary',
    'path_template',
    'pseudo_elements',
    'rank_key',
    'rarity_profile',
    'request_candidate_keys',
    'request_label',
    'request_summary',
    'resolve_network_address',
    'resolve_network_region',
    'shape_signature',
    'template_segment',
    'timing_bucket',
    'trace_anchor',
    'trace_context',
    'trace_defaults',
    'unavailable_capabilities',
]
