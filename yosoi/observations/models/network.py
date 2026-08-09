"""Versioned structured artifacts for one normalized, redacted network trace.

The security boundary of this modality is *upstream of this schema*, not inside it. Redaction
happens before bytes become canonical, so there is deliberately nowhere in these models to put a
header value, a query-parameter value, a cookie, or a body. A leak would require adding a field,
which `extra='forbid'` plus the validators below turn into a schema change rather than an
accident.

What the schema keeps, and why each half of the pair is different:

    header NAMES      evidence  — `authorization` present is a fact about the endpoint
    header VALUES     secret    — no field exists to hold one
    parameter NAMES   evidence  — `?cursor=` is how the endpoint pages
    parameter VALUES  secret-ish — carried only as a closed-set `ValueClass`
    request/response  shape     — a JSON KEY skeleton and its digest, never content
    bodies            restricted — a separate artifact at `Sensitivity.RESTRICTED`

The credential-header posture is inherited verbatim from VoidCrawl's `network_capture`
(`crates/mcp_server/src/tools/network.rs`): deny-by-default substring matching over lowercased
header names, over-redacting rather than missing a novel name, with raw access gated by an
operator environment variable rather than a model-controlled flag. This package never sees the
values at all, so the inherited half is the *name* list, which lives in
`yosoi.observations.network_tree`.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NETWORK_SCHEMA_VERSION = 'net1'

_SHAPE_DIGEST_BYTES = 8
"""Width of a shape digest. Part of the schema: changing it invalidates every stored trace."""

_DUPLICATE_DIGEST_BYTES = 8
"""Width of a duplicate-grouping digest. Same contract as the shape digest."""

HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9a-z]+$")
"""An RFC 9110 field name, lowercased.

Narrow on purpose. The one realistic way a header VALUE enters a value-free artifact is a
producer writing `'authorization: Bearer …'` into a name slot, and a field-name grammar that
excludes `:`, space, and uppercase rejects that at validation rather than at review time.
"""

ORIGIN = re.compile(r'^[a-z][a-z0-9+.\-]*://[^/?#\s]+$')
"""A scheme and authority with no path, query, or fragment — the durable half of a URL."""

_LOCATOR_RESERVED = ('"', '#', '|')
"""Characters an address-bearing field cannot contain; mirrors `anchoring.LOCATOR_RESERVED`.

Duplicated as a literal rather than imported so `models/` keeps no dependency on the addressing
layer. `tests/unit/observations/test_network_artifact.py` pins the two to each other.
"""


class NetworkCapabilityKind(str, Enum):
    """Facts a network producer may or may not have been able to capture."""

    COMPLETE_TRACE = 'complete_trace'
    TIMINGS = 'timings'
    SIZES = 'sizes'
    INITIATORS = 'initiators'
    REQUEST_SHAPES = 'request_shapes'
    RESPONSE_SHAPES = 'response_shapes'
    HEADER_NAMES = 'header_names'
    ITEM_COUNTS = 'item_counts'


class NetworkCapability(BaseModel):
    """Explicit availability for one network capture capability."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    kind: NetworkCapabilityKind
    available: bool
    reason: str | None = None

    @model_validator(mode='after')
    def _require_reason_when_unavailable(self) -> NetworkCapability:
        if not self.available and not self.reason:
            raise ValueError('an unavailable network capability must state a reason')
        return self


class ValueClass(str, Enum):
    """What a parameter or path-segment value *is*, standing in for what it says.

    A closed set, matched in one declared order (see `network_tree.classify_value`), so two
    producers cannot classify the same value two ways. `ENUM` is the only class whose members are
    plausibly non-sensitive, and it is still never carried verbatim: the point of the tier is that
    a reader learns the endpoint takes a short word here, not which word.
    """

    EMPTY = 'empty'
    TIMESTAMP = 'timestamp'
    ID = 'id'
    TOKEN = 'token'
    ENUM = 'enum'
    OPAQUE = 'opaque'


class ResourceType(str, Enum):
    """Producer-reported request category, as browsers already classify it."""

    DOCUMENT = 'document'
    STYLESHEET = 'stylesheet'
    SCRIPT = 'script'
    IMAGE = 'image'
    FONT = 'font'
    MEDIA = 'media'
    XHR = 'xhr'
    FETCH = 'fetch'
    WEBSOCKET = 'websocket'
    BEACON = 'beacon'
    OTHER = 'other'


class InitiatorKind(str, Enum):
    """Who caused the request, at the granularity a trace can state without a stack."""

    PARSER = 'parser'
    SCRIPT = 'script'
    PRELOAD = 'preload'
    REDIRECT = 'redirect'
    OTHER = 'other'
    UNKNOWN = 'unknown'


class TimingBucket(str, Enum):
    """Coarse duration band, with boundaries fixed by the schema rather than by a policy.

    Buckets rather than milliseconds because a millisecond is a property of the machine and the
    link, not of the page: two captures of an unchanged endpoint differ in every digit, which
    would make every diff report churn. The boundaries are stated once, in
    `network_tree.timing_bucket`, and are part of `net1`.
    """

    INSTANT = 'instant'
    FAST = 'fast'
    MODERATE = 'moderate'
    SLOW = 'slow'
    VERY_SLOW = 'very_slow'
    UNKNOWN = 'unknown'


class QueryParam(BaseModel):
    """One query-parameter NAME with the class of the value it carried.

    There is no `value` field, and that absence is the contract.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    name: str = Field(min_length=1)
    value_class: ValueClass

    @model_validator(mode='after')
    def _validate_name(self) -> QueryParam:
        if any(character in self.name for character in _LOCATOR_RESERVED):
            raise ValueError(f'query parameter name {self.name!r} cannot be expressed in an address')
        return self


def shape_digest(keys: tuple[str, ...]) -> str:
    """Return the stable digest of one JSON key skeleton."""
    canonical = '\n'.join(keys).encode()
    return hashlib.blake2b(canonical, digest_size=_SHAPE_DIGEST_BYTES).hexdigest()


class ShapeSignature(BaseModel):
    """A JSON payload's key skeleton, plus the digest collapse equivalence is measured on.

    Keys, never content. `items[].sku` records that a response is a list of objects carrying a
    `sku`; it records nothing about which SKUs. Shape is the equivalence relation this modality
    collapses on and values are the discriminants that survive it — the same split the DOM pruner
    arrived at, for the same reason: collapsing on content deduplicates away the differences the
    reader was looking for.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    digest: str = Field(pattern=r'^[0-9a-f]{16}$')
    keys: tuple[str, ...] = ()
    truncated: bool = False

    @model_validator(mode='after')
    def _validate_digest(self) -> ShapeSignature:
        if self.digest != shape_digest(self.keys):
            raise ValueError('shape signature digest disagrees with its own key skeleton')
        return self


class RestrictedBody(BaseModel):
    """A pointer to a raw body retained as a SEPARATE restricted artifact.

    Never the bytes. The referenced artifact carries `Sensitivity.RESTRICTED`, so it is reachable
    only through the two gates that already exist — `PruningPolicy.include_restricted` to let a
    reduction mention it and `InspectionBudget.allow_restricted` to read it. No third switch.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    artifact_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)


def duplicate_key(method: str, origin: str, path_template: str, params: tuple[QueryParam, ...]) -> str:
    """Return the digest that groups indistinguishable calls to one endpoint.

    Deliberately computed from the *classed* call signature and nothing else: two calls that
    differ only in which id they fetched share a duplicate key, which is what makes "40 identical
    polls" one countable fact instead of 40 lines. Two calls that differ in the CLASS of a
    parameter do not, because that is a different call being made.
    """
    canonical = '|'.join(
        (
            method,
            origin,
            path_template,
            ','.join(f'{param.name}:{param.value_class.value}' for param in sorted(params, key=lambda p: p.name)),
        )
    ).encode()
    return hashlib.blake2b(canonical, digest_size=_DUPLICATE_DIGEST_BYTES).hexdigest()


class NetworkRequest(BaseModel):
    """One already-normalized, already-redacted request/response pair."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    request_id: str = Field(min_length=1)
    method: str = Field(pattern=r'^[A-Z]+$')
    origin: str
    path_template: str = Field(min_length=1)
    params: tuple[QueryParam, ...] = ()
    status: int | None = Field(default=None, ge=100, le=599)
    resource_type: ResourceType = ResourceType.OTHER
    mime: str | None = None
    timing: TimingBucket = TimingBucket.UNKNOWN
    request_bytes: int | None = Field(default=None, ge=0)
    response_bytes: int | None = Field(default=None, ge=0)
    initiator: InitiatorKind = InitiatorKind.UNKNOWN
    request_shape: ShapeSignature | None = None
    response_shape: ShapeSignature | None = None
    request_header_names: tuple[str, ...] = ()
    response_header_names: tuple[str, ...] = ()
    declared_item_count: int | None = Field(default=None, ge=0)
    """A collection size the response DECLARED, when it declared one. Never inferred."""

    duplicate_key: str = Field(pattern=r'^[0-9a-f]{16}$')
    restricted_body: RestrictedBody | None = None

    @model_validator(mode='after')
    def _validate_request(self) -> NetworkRequest:
        if not ORIGIN.match(self.origin):
            raise ValueError(f'network origin {self.origin!r} must be a scheme and authority with no path')
        self._validate_template()
        self._validate_headers()
        names = [param.name for param in self.params]
        if len(names) != len(set(names)):
            raise ValueError(f'network request {self.request_id!r} repeats a query parameter name')
        expected = duplicate_key(self.method, self.origin, self.path_template, self.params)
        if self.duplicate_key != expected:
            raise ValueError('network duplicate key disagrees with the call signature it claims to group')
        return self

    def _validate_template(self) -> None:
        """Require a path TEMPLATE: rooted, address-expressible, and query-free."""
        if not self.path_template.startswith('/'):
            raise ValueError(f'network path template {self.path_template!r} must start with a slash')
        if '?' in self.path_template:
            raise ValueError('a network path template carries no query string; parameters are classed separately')
        if any(character in self.path_template for character in _LOCATOR_RESERVED):
            raise ValueError(f'network path template {self.path_template!r} cannot be expressed in an address')

    def _validate_headers(self) -> None:
        """Reject anything in a header-NAME slot that is not a lowercased field name."""
        for group in (self.request_header_names, self.response_header_names):
            for name in group:
                if not HEADER_NAME.match(name):
                    raise ValueError(
                        f'{name!r} is not a lowercased HTTP field name; header values never enter this artifact'
                    )
            if len(group) != len(set(group)):
                raise ValueError(f'network request {self.request_id!r} repeats a header name')

    @property
    def status_class(self) -> int | None:
        """Return the RFC 9110 status class (1-5), or None when no response arrived."""
        return None if self.status is None else self.status // 100


class NetworkRedaction(BaseModel):
    """What was removed before these bytes became canonical evidence.

    Every field is a `Literal`, so an unredacted trace is not a trace this schema can express.
    A producer that wanted to carry header values would have to change the type, and a reviewer
    reading a diff sees that rather than a new optional field.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    header_values: Literal['dropped'] = 'dropped'
    credential_header_names: Literal['retained_names_only'] = 'retained_names_only'
    param_values: Literal['classed'] = 'classed'
    urls: Literal['origin_and_template_only'] = 'origin_and_template_only'
    bodies: Literal['dropped', 'restricted_artifact'] = 'dropped'


class NetworkTrace(BaseModel):
    """Self-describing, immutable JSON payload for one normalized network observation."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    schema_version: str = NETWORK_SCHEMA_VERSION
    kind: Literal['network'] = 'network'
    snapshot_id: str = Field(min_length=1)
    requests: tuple[NetworkRequest, ...] = ()
    capabilities: tuple[NetworkCapability, ...] = ()
    redaction: NetworkRedaction = NetworkRedaction()

    @model_validator(mode='after')
    def _validate_trace(self) -> NetworkTrace:
        identifiers = [request.request_id for request in self.requests]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError('network request ids must be unique within a trace')
        kinds = [capability.kind for capability in self.capabilities]
        if len(kinds) != len(set(kinds)):
            raise ValueError('network capabilities must contain at most one entry per kind')
        retained = [request.request_id for request in self.requests if request.restricted_body is not None]
        if retained and self.redaction.bodies != 'restricted_artifact':
            raise ValueError(f'requests {retained!r} point at retained bodies while the trace declares bodies dropped')
        if any(character in self.snapshot_id for character in _LOCATOR_RESERVED):
            raise ValueError(f'snapshot id {self.snapshot_id!r} cannot be expressed in an address')
        return self

    @property
    def observed_request_count(self) -> int:
        """Count the requests this trace actually holds."""
        return len(self.requests)

    def capability(self, kind: NetworkCapabilityKind) -> NetworkCapability | None:
        """Return one declared capability, or None when the producer said nothing about it."""
        return next((capability for capability in self.capabilities if capability.kind is kind), None)

    @property
    def complete(self) -> bool:
        """Whether the producer declared the trace to hold every request the page made.

        Absence of the declaration is not a claim of completeness: an undeclared capability
        yields False, so a capped or late-armed capture cannot read as a whole trace.
        """
        declared = self.capability(NetworkCapabilityKind.COMPLETE_TRACE)
        return declared is not None and declared.available


def serialize_network_trace(trace: NetworkTrace) -> bytes:
    """Encode a network trace with deterministic field order and UTF-8 JSON."""
    return trace.model_dump_json(exclude_none=False).encode('utf-8')


def parse_network_trace(data: bytes) -> NetworkTrace:
    """Validate canonical network JSON before a pruner or inspector consumes it."""
    return NetworkTrace.model_validate_json(data)


__all__ = [
    'HEADER_NAME',
    'NETWORK_SCHEMA_VERSION',
    'ORIGIN',
    'InitiatorKind',
    'NetworkCapability',
    'NetworkCapabilityKind',
    'NetworkRedaction',
    'NetworkRequest',
    'NetworkTrace',
    'QueryParam',
    'ResourceType',
    'RestrictedBody',
    'ShapeSignature',
    'TimingBucket',
    'ValueClass',
    'duplicate_key',
    'parse_network_trace',
    'serialize_network_trace',
    'shape_digest',
]
