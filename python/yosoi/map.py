"""Bounded discovery uses the Rust SDK's frontier, budgets and outcomes."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import ClassVar, Literal

from pydantic import Field, PrivateAttr

from . import _native
from ._models import ImmutableModel, NativeAuthoringModel
from .cancellation import CancellationToken
from .outcomes import U32, U64
from .policy import Policy, PolicySnapshot
from .request import Response, _token

MapOrderingKind = Literal[
    "discovery_source",
    "observation",
    "omission_reason",
    "public_provider",
    "rejection",
    "relationship",
    "relationship_kind",
]


def _ordering_json(kind: MapOrderingKind, value: object) -> str:
    if isinstance(value, _MapOrderable):
        if value._ordering_kind != kind:
            raise TypeError(f"{type(value).__name__} cannot be compared as {kind!r}")
        return value.model_dump_json(by_alias=True)
    if kind in {"public_provider", "rejection", "relationship_kind"}:
        if not isinstance(value, str):
            raise TypeError(f"{kind} ordering values must be strings or SDK values")
        return json.dumps(str(value))
    raise TypeError(f"{kind} ordering values must be SDK models")


def compare_values(kind: MapOrderingKind, left: object, right: object) -> int:
    """Compare typed Map values with the public Rust `Ord` implementation.

    String-backed Literal aliases remain ordinary strings; pass their kind to
    this function when their Rust enum declaration order is needed.
    """
    if kind not in {
        "discovery_source",
        "observation",
        "omission_reason",
        "public_provider",
        "rejection",
        "relationship",
        "relationship_kind",
    }:
        raise ValueError(f"unknown Map ordering kind: {kind!r}")
    return _native.map_value_compare(
        kind, _ordering_json(kind, left), _ordering_json(kind, right)
    )


class _MapOrderable(ImmutableModel):
    _ordering_kind: ClassVar[MapOrderingKind]

    def __lt__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return compare_values(self._ordering_kind, self, other) < 0

    def __le__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return compare_values(self._ordering_kind, self, other) <= 0

    def __gt__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return compare_values(self._ordering_kind, self, other) > 0

    def __ge__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return compare_values(self._ordering_kind, self, other) >= 0


class PublicProvider(StrEnum):
    crt_sh = "crt_sh"
    hacker_target = "hacker_target"
    subdomain_center = "subdomain_center"
    wayback_archive = "wayback_archive"

    @classmethod
    def all(cls) -> tuple[PublicProvider, ...]:
        return tuple(cls(value) for value in json.loads(_native.public_providers()))

    @property
    def name(self) -> str:
        return _native.public_provider_name(self.value)

    def endpoint(self, domain: str) -> str:
        return _native.public_provider_endpoint(self.value, domain)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return compare_values("public_provider", self, other) < 0

    def __le__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return compare_values("public_provider", self, other) <= 0

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return compare_values("public_provider", self, other) > 0

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return compare_values("public_provider", self, other) >= 0


SkipReason = Literal["depth", "robots", "non_html", "budget"]
SourceSkipReason = Literal["not_sitemap"]
Rejection = Literal[
    "invalid_url",
    "unsupported_scheme",
    "credentials",
    "host_scope",
    "origin_scope",
    "path_scope",
    "filtered",
    "url_length",
    "invalid_host",
    "unsupported_domain_scope",
    "hostname_length",
]


def rejection_message(reason: Rejection) -> str:
    """Return the public Rust Display message without changing its wire tag."""
    return _native.rejection_message(reason)


class DiscoverySource(_MapOrderable):
    _ordering_kind: ClassVar[MapOrderingKind] = "discovery_source"

    kind: Literal[
        "seed",
        "html_link",
        "xml_link",
        "passive_provider",
        "sitemap",
        "robots",
        "redirect",
        "passive_certificate",
    ]
    value: PublicProvider | None = None

    @property
    def is_passive(self) -> bool:
        return self.kind in ("passive_provider", "passive_certificate")


class Observation(_MapOrderable):
    _ordering_kind: ClassVar[MapOrderingKind] = "observation"

    source: DiscoverySource
    source_url: str | None


class SourceFailure(ImmutableModel):
    kind: Literal[
        "transport",
        "http_status",
        "parse",
        "incomplete_document",
        "redirect_rejected",
        "redirect_limit",
        "retention_limit",
        "request_deadline",
        "rate_limited",
        "unexpected_sitemap_content",
    ]
    value: int | None = None


class Exploration(ImmutableModel):
    kind: Literal["inventoried", "pending", "inspected", "skipped", "failed"]
    value: SkipReason | SourceFailure | None = None


class HostEntry(ImmutableModel):
    host: str
    observations: tuple[Observation, ...]
    verification: Literal["unverified", "http_observed"]


class PageEntry(ImmutableModel):
    url: str
    minimum_link_depth: int | None
    observations: tuple[Observation, ...]
    exploration: Exploration


class WildcardEntry(ImmutableModel):
    pattern: str
    observations: tuple[Observation, ...]


RelationshipKind = Literal["link", "redirect", "canonical"]


class Relationship(_MapOrderable):
    _ordering_kind: ClassVar[MapOrderingKind] = "relationship"

    from_url: str = Field(alias="from")
    to: str
    kind: RelationshipKind


class FrontierEntry(ImmutableModel):
    page: str
    reason: Literal[
        "awaiting_exploration", "depth_boundary", "operation_stopped", "probe_candidate"
    ]


class SourceStatus(ImmutableModel):
    kind: Literal[
        "completed",
        "sampled",
        "skipped",
        "disabled",
        "failed",
        "truncated",
        "not_started",
    ]
    value: SourceSkipReason | SourceFailure | None = None


class SourceOutcome(ImmutableModel):
    source: DiscoverySource
    source_url: str | None
    status: SourceStatus


class SupportDocument(ImmutableModel):
    url: str
    kind: Literal["robots", "sitemap", "sitemap_index"]
    status: SourceStatus


class TreeEntry(ImmutableModel):
    page: str
    parent: str | None
    depth: int | None


class RequestTrace(ImmutableModel):
    target: str
    status: int | None
    charged_response_bytes: int


class MapTermination(ImmutableModel):
    kind: Literal["exhausted", "limit", "deadline", "cancelled"]
    value: (
        Literal[
            "hosts",
            "urls",
            "relationships",
            "observations",
            "pending",
            "requests",
            "sitemaps",
            "sitemap_depth",
            "response_bytes",
            "total_response_bytes",
            "inventory_bytes",
            "parser_entries",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)


class OmissionReason(_MapOrderable):
    _ordering_kind: ClassVar[MapOrderingKind] = "omission_reason"

    kind: Literal[
        "admission",
        "robots",
        "depth",
        "sitemap_depth",
        "pending",
        "inventory",
        "retention",
        "wildcard",
        "other",
    ]
    value: Rejection | None = None


class Omission(ImmutableModel):
    reason: OmissionReason
    count: int


class Summary(ImmutableModel):
    requests: U32 = 0
    provider_concurrency_peak: U32 = 0
    page_concurrency_peak: U32 = 0
    unused_page_prefetches: U32 = 0
    response_bytes: U64 = 0
    inventory_bytes: U64 = 0
    observations: U32 = 0
    omitted: U64 = 0
    retained_document_bytes: U64 = 0


class RetainedCapture(ImmutableModel):
    url: str
    response: Response


class MapOutcome(ImmutableModel):
    policy_snapshot: PolicySnapshot
    hosts: tuple[HostEntry, ...]
    pages: tuple[PageEntry, ...]
    relationships: tuple[Relationship, ...]
    frontier: tuple[FrontierEntry, ...]
    support_documents: tuple[SupportDocument, ...]
    sources: tuple[SourceOutcome, ...]
    tree: tuple[TreeEntry, ...]
    captures: tuple[RetainedCapture, ...]
    wildcard_names: tuple[str, ...]
    wildcards: tuple[WildcardEntry, ...]
    request_trace: tuple[RequestTrace, ...]
    termination: MapTermination
    omissions: tuple[Omission, ...]
    summary: Summary
    _handle: _native.MapOutcome = PrivateAttr()

    @classmethod
    def _from_native(cls, handle: _native.MapOutcome) -> MapOutcome:
        value = json.loads(handle.to_json())
        for index, capture in enumerate(value["captures"]):
            capture["response"] = Response._from_native(handle.response(index))
        result = cls.model_validate(value)
        result._handle = handle
        return result


class MapRequest(NativeAuthoringModel):
    seed: str = Field(repr=False)
    _handle: _native.MapRequest = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        self._handle = _native.MapRequest(self.seed)

    def check(self) -> None:
        self._handle.validate()

    def bind(self, policy: Policy) -> BoundMapRequest:
        return BoundMapRequest(self, policy)

    async def send(
        self, *, cancellation: CancellationToken | None = None
    ) -> MapOutcome:
        handle = await self._handle.send(cancellation=_token(cancellation))
        return MapOutcome._from_native(handle)


class BoundMapRequest:
    def __init__(self, request: MapRequest, policy: Policy) -> None:
        self.request = request
        self._policy_json = policy.to_json()

    @property
    def policy(self) -> Policy:
        return Policy.model_validate_json(self._policy_json)

    def check(self) -> None:
        self.request._handle.validate(self._policy_json)

    async def send(
        self, *, cancellation: CancellationToken | None = None
    ) -> MapOutcome:
        handle = await self.request._handle.send(
            self._policy_json, _token(cancellation)
        )
        return MapOutcome._from_native(handle)


def new(seed: str) -> MapRequest:
    return MapRequest(seed=seed)
