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
"""Rust ordering contracts for discovery sources, provenance, omissions, providers,
rejection codes, and relationships. This is declaration/struct ordering, not
ordinary string sorting.
"""


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
    """Anonymous historical discovery indexes with fixed endpoint shapes.

    Attributes:
        crt_sh: Certificate-transparency names from crt.sh.
        hacker_target: Hostname/address rows from anonymous hostsearch.
        subdomain_center: Names from the anonymous Subdomain Center index.
        wayback_archive: Historical URLs from Wayback CDX. Passive reports do not prove
            current reachability.
    """
    crt_sh = "crt_sh"
    hacker_target = "hacker_target"
    subdomain_center = "subdomain_center"
    wayback_archive = "wayback_archive"

    @classmethod
    def all(cls) -> tuple[PublicProvider, ...]:
        """Return the deterministic catalog order supplied by the Rust SDK."""
        return tuple(cls(value) for value in json.loads(_native.public_providers()))

    @property
    def name(self) -> str:
        """Return the stable Rust catalog key used in outcomes and provenance."""
        return _native.public_provider_name(self.value)

    def endpoint(self, domain: str) -> str:
        """Build a fixed anonymous HTTPS query without network I/O.

        Args:
            domain: DNS domain to validate and encode into the provider query.

        Returns:
            A fixed endpoint; callers cannot override its host or path.

        Raises:
            MapError: The domain is invalid for the provider endpoint shape.
        """
        return _native.public_provider_endpoint(self.value, domain)

    def __lt__(self, other: object) -> bool:
        """Compare this provider with another value using Rust enum order.

        Args:
            other: Provider string or enum value to compare.

        Returns:
            True when this value is less than the other in Rust declaration
            order. Non-string operands return NotImplemented.

        Raises:
            MapError: A supplied string is not a supported provider value.
        """
        if not isinstance(other, str):
            return NotImplemented
        return compare_values("public_provider", self, other) < 0

    def __le__(self, other: object) -> bool:
        """Compare this provider with another value using Rust enum order.

        Args:
            other: Provider string or enum value to compare.

        Returns:
            True when this value is less than or equal to the other in Rust declaration
            order. Non-string operands return NotImplemented.

        Raises:
            MapError: A supplied string is not a supported provider value.
        """
        if not isinstance(other, str):
            return NotImplemented
        return compare_values("public_provider", self, other) <= 0

    def __gt__(self, other: object) -> bool:
        """Compare this provider with another value using Rust enum order.

        Args:
            other: Provider string or enum value to compare.

        Returns:
            True when this value is greater than the other in Rust declaration
            order. Non-string operands return NotImplemented.

        Raises:
            MapError: A supplied string is not a supported provider value.
        """
        if not isinstance(other, str):
            return NotImplemented
        return compare_values("public_provider", self, other) > 0

    def __ge__(self, other: object) -> bool:
        """Compare this provider with another value using Rust enum order.

        Args:
            other: Provider string or enum value to compare.

        Returns:
            True when this value is greater than or equal to the other in Rust
            declaration
            order. Non-string operands return NotImplemented.

        Raises:
            MapError: A supplied string is not a supported provider value.
        """
        if not isinstance(other, str):
            return NotImplemented
        return compare_values("public_provider", self, other) >= 0


SkipReason = Literal["depth", "robots", "non_html", "budget"]
"""Why an inventoried page was skipped: depth, robots rules, non-HTML content, or
resource budget. Discovery alone does not imply exploration.
"""
SourceSkipReason = Literal["not_sitemap"]
"""Source classification for a probe intentionally omitted because it was not a
sitemap; this is not a successful sitemap parse.
"""
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
"""Admission classifications for invalid URLs, credentials, scope exclusions, filters,
and byte/host limits. Rejection is separate from acquisition failure.
"""


def rejection_message(reason: Rejection) -> str:
    """Return the public Rust Display message without changing its wire tag."""
    return _native.rejection_message(reason)


class DiscoverySource(_MapOrderable):
    """Provenance category for a retained hostname or page.

    Attributes:
        kind: seed is caller input; html_link and xml_link are acquired links; sitemap
            and robots are support sources; redirect is observed HTTP routing;
            passive_provider and passive_certificate are historical evidence.
        value: Index provider for passive_provider, otherwise None.
    """
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
        """Return whether provenance is passive index or certificate evidence."""
        return self.kind in ("passive_provider", "passive_certificate")


class Observation(_MapOrderable):
    """One retained provenance observation, without a reachability guarantee.

    Attributes:
        source: Mechanism reporting the host, page, or wildcard.
        source_url: Reporting page or endpoint, or None when no URL applies.
    """
    _ordering_kind: ClassVar[MapOrderingKind] = "observation"

    source: DiscoverySource
    source_url: str | None


class SourceFailure(ImmutableModel):
    """Typed acquisition or parsing failure without raw response excerpts.

    Attributes:
        kind: Classifies transport/status failures, malformed or incomplete content,
            redirect rejection/limits, retention limits, request deadlines, rate limits,
            or unexpected sitemap content.
        value: Unsuccessful HTTP status for http_status, otherwise None.
    """
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
    """Retained page exploration state, independent of discovery provenance.

    Attributes:
        kind: inventoried means retained but unscheduled; pending means queued;
            inspected means supported inspection finished; skipped and failed retain
            their reasons.
        value: Skip reason or typed source failure when applicable, otherwise None.
    """
    kind: Literal["inventoried", "pending", "inspected", "skipped", "failed"]
    value: SkipReason | SourceFailure | None = None


class HostEntry(ImmutableModel):
    """An admitted hostname with explicit reachability evidence.

    Attributes:
        host: Canonical admitted hostname without a scheme or path.
        observations: Retained source evidence, bounded by policy.
        verification: unverified for discovery alone; http_observed for an observed HTTP
            response. Neither proves ownership, application success, or future
            availability.
    """
    host: str
    observations: tuple[Observation, ...]
    verification: Literal["unverified", "http_observed"]


class PageEntry(ImmutableModel):
    """Normalized page URL with discovery and exploration evidence.

    Attributes:
        url: Admitted normalized HTTP(S) URL with fragments removed.
        minimum_link_depth: Smallest known rooted link depth, or None when not
            established.
        observations: Retained provenance observations, bounded by policy.
        exploration: Whether the page was inventoried, inspected, skipped, failed, or
            remains pending.
    """
    url: str
    minimum_link_depth: int | None
    observations: tuple[Observation, ...]
    exploration: Exploration


class WildcardEntry(ImmutableModel):
    """A retained wildcard pattern without expansion into guessed hosts.

    Attributes:
        pattern: Observed wildcard name, not a verified concrete hostname.
        observations: Retained reporting sources, subject to evidence budgets.
    """
    pattern: str
    observations: tuple[Observation, ...]


RelationshipKind = Literal["link", "redirect", "canonical"]
"""Directed link, redirect, or canonical-hint evidence. Links add rooted depth,
redirects preserve depth, and canonical hints do not create traversal parents.
"""


class Relationship(_MapOrderable):
    """Directed discovery evidence without merging the endpoint pages.

    Attributes:
        from_url: Reporting page URL; serialized under the Rust field name from.
        to: Admitted normalized destination URL.
        kind: link increases rooted depth; redirect preserves it; canonical is a hint
            and does not establish a tree parent.
    """
    _ordering_kind: ClassVar[MapOrderingKind] = "relationship"

    from_url: str = Field(alias="from")
    to: str
    kind: RelationshipKind


class FrontierEntry(ImmutableModel):
    """Unfinished page work, without a promise of later execution.

    Attributes:
        page: Normalized URL whose work remains unfinished.
        reason: awaiting_exploration, depth_boundary, operation_stopped, or
            probe_candidate explains why no completed exploration is present.
    """
    page: str
    reason: Literal[
        "awaiting_exploration", "depth_boundary", "operation_stopped", "probe_candidate"
    ]


class SourceStatus(ImmutableModel):
    """Per-source processing state, distinct from operation termination.

    Attributes:
        kind: completed is supported processing within local limits, not whole-site
            completeness; sampled denotes provider-side limits; truncated denotes local
            loss; skipped, disabled, failed, and not_started retain omitted work.
        value: Skip classification or typed source failure when applicable, otherwise
            None.
    """
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
    """Execution facts for one selected discovery source.

    Attributes:
        source: Discovery mechanism occupying the source slot.
        source_url: Reporting endpoint or page, or None when no URL applies.
        status: Terminal processing state, independent of overall exhaustion.
    """
    source: DiscoverySource
    source_url: str | None
    status: SourceStatus


class SupportDocument(ImmutableModel):
    """A robots or sitemap support source and its execution state.

    Attributes:
        url: Normalized support-document URL.
        kind: robots for rules; sitemap for page URLs; sitemap_index for nested sources.
        status: Processing state, including failures and incomplete evidence.
    """
    url: str
    kind: Literal["robots", "sitemap", "sitemap_index"]
    status: SourceStatus


class TreeEntry(ImmutableModel):
    """A page position in the deterministic rooted discovery forest.

    Attributes:
        page: Normalized inventoried page URL.
        parent: Selected rooted predecessor, or None for roots and unattached pages.
        depth: Established link depth; redirects do not increase it, and None means no
            rooted path was found.
    """
    page: str
    parent: str | None
    depth: int | None


class RequestTrace(ImmutableModel):
    """Bounded acquisition accounting retained for a Map request.

    Attributes:
        target: Requested normalized URL; it can contain user-sensitive path or query
            data.
        status: Observed HTTP status, or None when none was recorded.
        charged_response_bytes: Response bytes charged to operation budgets for the
            attempt.
    """
    target: str
    status: int | None
    charged_response_bytes: int


class MapTermination(ImmutableModel):
    """Why discovery stopped, independently of individual source success.

    Attributes:
        kind: exhausted means no runnable work remains under policy, not exhaustive site
            coverage; limit, deadline, and cancelled stop further work while retaining
            evidence.
        value: Resource limit classification for limit, otherwise None.
    """
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
    """Classification of omitted discovery evidence or exploration work.

    Attributes:
        kind: admission, robots, depth, sitemap_depth, pending, inventory, retention,
            wildcard, or other explains the rejection or boundary. Wildcards remain
            patterns rather than expanded concrete hosts.
        value: URL or hostname rejection details for admission, otherwise None.
    """
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
    """Counted omission events, not all undiscovered site items.

    Attributes:
        reason: Boundary or rejection classification causing the omission.
        count: Recorded event count for this category.
    """
    reason: OmissionReason
    count: int


class Summary(ImmutableModel):
    """Recorded resource accounting and concurrency peaks for a discovery run.

    Attributes:
        requests: Charged acquisitions, including support-source requests.
        provider_concurrency_peak: Greatest observed simultaneous public-provider
            acquisitions.
        page_concurrency_peak: Greatest observed simultaneous prefetched page
            acquisitions.
        unused_page_prefetches: Charged speculative page attempts not consumed by
            exploration.
        response_bytes: Aggregate response bytes charged to acquisition budgets.
        inventory_bytes: Bytes charged for retained discovery inventory.
        observations: Count of retained provenance observations.
        omitted: Recorded omission events, not all undiscovered evidence.
        retained_document_bytes: Retained document payload bytes, accounted separately
            from inventory metadata.
    """
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
    """An acquired response kept alive with its owning Map outcome.

    Attributes:
        url: Normalized page or support-source URL associated with the response.
        response: Typed acquired response retaining native capture ownership and
            document access.
    """
    url: str
    response: Response


class MapOutcome(ImmutableModel):
    """Bounded discovery evidence with retained acquisition owners.

    Attributes:
        policy_snapshot: Resolved policy snapshot used for execution.
        hosts: Admitted hostnames with explicit reachability evidence.
        pages: Retained normalized pages and exploration states.
        relationships: Directed links, redirects, and canonical hints retained as
            evidence.
        frontier: Unfinished work, not a promise of later execution.
        support_documents: Robots and sitemap sources with processing states.
        sources: Selected sources, including disabled, failed, sampled, and unstarted
            slots.
        tree: Deterministic rooted forest; unattached evidence has unknown depth.
        captures: Retained acquisition responses keeping native document owners alive.
        wildcard_names: Observed wildcard patterns, without concrete-host expansion.
        wildcards: Wildcard patterns with retained provenance observations.
        request_trace: Acquisition accounting; target strings can contain user-sensitive
            data.
        termination: Why execution stopped; exhaustion alone does not prove complete
            coverage.
        omissions: Counted omission categories, not all undiscovered site items.
        summary: Charged resources, retained evidence counts, and concurrency peaks.
    """
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
    """Authored seed intent with validation deferred to checking or sending.

    Attributes:
        seed: Caller seed text; creating this model does not send network requests.
    """
    seed: str = Field(repr=False)
    _handle: _native.MapRequest = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        """Retain authored seed intent natively without acquiring pages."""
        self._handle = _native.MapRequest(self.seed)

    def check(self) -> None:
        """Validate seed and package-default policy without network I/O.

        Raises:
            MapError: The seed, scope, policy, or acquisition setup is invalid.
        """
        self._handle.validate()

    def bind(self, policy: Policy) -> BoundMapRequest:
        """Snapshot a complete policy declaration for later discovery.

        Args:
            policy: Complete declaration to serialize at binding time.

        Returns:
            A binding unaffected by later edits to the caller policy.
        """
        return BoundMapRequest(self, policy)

    async def send(
        self, *, cancellation: CancellationToken | None = None
    ) -> MapOutcome:
        """Discover within package defaults while retaining typed evidence.

        Args:
            cancellation: Optional cooperative token shared with other operations.
                Observed cancellation stops further work and retains existing outcomes.

        Returns:
            Discovery evidence and acquisition owners. Inspect source states, frontier,
            omissions, and termination before claiming completeness.

        Raises:
            MapError: Seed validation, policy resolution, or execution setup fails.
            pydantic.ValidationError: Native data cannot form a typed result.
        """
        handle = await self._handle.send(cancellation=_token(cancellation))
        return MapOutcome._from_native(handle)


class BoundMapRequest:
    """A discovery request bound to a serialized policy snapshot.

    Attributes:
        request: Retained authored seed request. Later caller-policy edits do not change
            the snapshot.
    """
    def __init__(self, request: MapRequest, policy: Policy) -> None:
        """Retain the request and snapshot its policy without network I/O.

        Args:
            request: Authored seed request to retain.
            policy: Complete declaration to serialize for later checks and sends.
        """
        self.request = request
        self._policy_json = policy.to_json()

    @property
    def policy(self) -> Policy:
        """Return a policy copy whose edits do not change this binding."""
        return Policy.model_validate_json(self._policy_json)

    def check(self) -> None:
        """Validate seed and bound-policy admission without network I/O.

        Raises:
            MapError: The seed, scope, policy, or acquisition setup is invalid.
        """
        self.request._handle.validate(self._policy_json)

    async def send(
        self, *, cancellation: CancellationToken | None = None
    ) -> MapOutcome:
        """Discover with the bound policy and retain evidence on cancellation.

        Args:
            cancellation: Optional cooperative token shared with other operations.

        Returns:
            Typed inventory and acquisition owners, including failed or sampled sources
            and unfinished work. Exhaustion is not proof of exhaustive site coverage.

        Raises:
            MapError: Seed validation, policy resolution, or execution setup fails.
            pydantic.ValidationError: Native data cannot form a typed result.
        """
        handle = await self.request._handle.send(
            self._policy_json, _token(cancellation)
        )
        return MapOutcome._from_native(handle)


def new(seed: str) -> MapRequest:
    """Author seed intent without URL validation or network I/O.

    Args:
        seed: URL text to validate when the request is checked or sent.

    Returns:
        A request using package defaults until bound to a policy.

    Raises:
        pydantic.ValidationError: The seed is not a string.
    """
    return MapRequest(seed=seed)
