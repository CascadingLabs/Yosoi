"""Bounded evidence navigation over Rust-owned immutable surfaces.

Document and video readers never grant browser control. Native references and
shared references are distinct types; continuations stay bound to their original
observation and operation. Video processing requires the surface-video wheel
feature and local FFmpeg/FFprobe executables.

Shared identity and token types accept 1–1,024 UTF-8 bytes with no control
characters. Their spelling is opaque and does not establish cross-capture entity
identity or permission to act.
"""

from __future__ import annotations

import base64
import hashlib
import json
from builtins import bytes as _Bytes
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import (
    BeforeValidator,
    Field,
    PlainSerializer,
    PrivateAttr,
    StrictBool,
    StrictStr,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from . import _native
from . import browser as _browser
from ._models import ImmutableModel
from .archive import (
    Archive,
    AutomationRecord,
    DocumentArchiveRef,
    FileDocumentArchiveRef,
    PixelArtifactArchiveRef,
    _rust_json,
)
from .documents import (
    Document,
    DocumentProfile,
    FileDocument,
    FileLimits,
    FileMetadata,
    ImageDocument,
    file_from_bytes,
)
from .locators import Plan
from .scalars import DocumentId, ValidatedString

SurfaceError = _native.SurfaceError
"""Rust preparation, reference, budget or authority failure with Rust metadata."""
VideoError = getattr(_native, "VideoError", SurfaceError)
"""Native video I/O, decoder, timeout, bounds or missing-frame failure."""
ExecutionError = getattr(_native, "SurfaceExecutionError", SurfaceError)
"""Shared runtime preparation, execution, retention or cleanup failure."""


def _require_video() -> None:
    if not _native.surface_video_enabled:
        raise SurfaceError("this wheel was built without surface-video")


class SourceId(ValidatedString):
    """Rust-validated opaque source identity, without access or control authority."""

    _kind = "surface_source_id"


class SurfaceId(ValidatedString):
    """Rust-validated identity of a continuing representation of one source."""

    _kind = "surface_id"


class ObservationId(ValidatedString):
    """Rust-validated identity of one immutable interpretation."""

    _kind = "surface_observation_id"


class AddressToken(ValidatedString):
    """Producer-issued opaque address bound to its accompanying observation."""

    _kind = "surface_address"


class ContinuationToken(ValidatedString):
    """Producer-issued opaque continuation bound to a read, scope and observation."""

    _kind = "surface_continuation"


CursorId = Annotated[int, Field(strict=True, ge=0, le=2**64 - 1)]
"""Session-local diagnostic integer. A copied ID never grants cursor authority."""
WatchId = Annotated[int, Field(strict=True, ge=0, le=2**64 - 1)]
"""Session-local subscription integer, checked against the owning Rust cursor."""


class Budget(ImmutableModel):
    """Bounds on the complete Rust JSON result, before a transport envelope."""

    bytes: int = Field(
        default=4096, strict=True, ge=0, description="UTF-8 JSON byte limit."
    )
    items: int = Field(
        default=20, strict=True, ge=0, description="Maximum routing entries."
    )


class Limits(ImmutableModel):
    """Task-independent document preparation bounds, enforced by Rust."""

    input_bytes: int = Field(
        default=8388608, strict=True, ge=0, description="Input byte cap."
    )
    nodes: int = Field(
        default=200000, strict=True, ge=0, description="Indexed node cap."
    )
    depth: int = Field(
        default=96, strict=True, ge=0, description="Source tree depth cap."
    )
    overview_depth: int = Field(
        default=6, strict=True, ge=0, description="Automatic zoom depth."
    )


class DocumentPolicy(ImmutableModel):
    """Independent retained-document, tree and read-response limits.

    Supplied documents exceeding preparation limits are rejected. Native AX
    captures are depth-limited and report partial coverage. Read limits bound
    complete serialized results, independently of retained source bytes.
    """

    max_bytes: int = Field(
        default=8388608,
        strict=True,
        ge=1,
        le=134217728,
        description="Maximum retained serialized document bytes.",
    )
    max_depth: int = Field(
        default=96,
        strict=True,
        ge=1,
        le=256,
        description="Maximum tree depth; root is level zero.",
    )
    max_nodes: int = Field(
        default=100000,
        strict=True,
        ge=1,
        le=200000,
        description="Maximum indexed nodes, including scalars.",
    )
    overview_depth: int = Field(
        default=6,
        strict=True,
        ge=0,
        le=256,
        description="Automatic overview depth, capped to max_depth.",
    )
    response_bytes: int = Field(
        default=65536,
        strict=True,
        ge=512,
        le=65536,
        description="Maximum complete serialized read-result bytes.",
    )

    def limits(self) -> Limits:
        """Return preparation bounds with overview depth capped to tree depth."""
        return Limits(
            input_bytes=self.max_bytes,
            nodes=self.max_nodes,
            depth=self.max_depth,
            overview_depth=min(self.overview_depth, self.max_depth),
        )


class DocumentPolicies(ImmutableModel):
    """Separate SDK capture and response limits per evidence representation."""

    dom: DocumentPolicy = Field(
        default_factory=lambda: DocumentPolicy(max_bytes=33554432, max_nodes=200000),
        description="Rendered DOM retention, tree and read bounds.",
    )
    ax: DocumentPolicy = Field(
        default_factory=lambda: DocumentPolicy(max_nodes=100000),
        description="Native accessibility evidence limits; at most 100000 nodes.",
    )
    html: DocumentPolicy = Field(
        default_factory=DocumentPolicy, description="Source HTML preparation limits."
    )
    xml: DocumentPolicy = Field(
        default_factory=DocumentPolicy, description="Source XML preparation limits."
    )
    json_document: DocumentPolicy = Field(
        default_factory=DocumentPolicy,
        alias="json",
        description="Ordinary JSON preparation limits; serialized as json.",
    )
    text: DocumentPolicy = Field(
        default_factory=DocumentPolicy, description="Plain text preparation limits."
    )
    network: DocumentPolicy = Field(
        default_factory=DocumentPolicy,
        description="Network event-document limits, independent of ordinary JSON.",
    )

    @model_validator(mode="after")
    def _validate_ax_nodes(self) -> Self:
        if self.ax.max_nodes > 100000:
            raise ValueError("AX supports at most 100000 nodes")
        return self


class NetworkObservationPolicy(ImmutableModel):
    """Independent bounds and redaction choices for native Chrome events.

    Attributes:
        max_duration_ms: Maximum subscription lifetime.
        max_events: Lifetime event journal count cap.
        max_buffered_events: Provider queue cap, independent of retained history.
        max_windows: Frozen windows retained for reads.
        max_event_bytes: Event metadata retention cap.
        max_response_bodies: Maximum completed bodies requested per subscription;
            its initial value also caps bodies retained across the live Surface session.
        max_body_bytes: Per-body cap.
        max_total_body_bytes: Subscription-wide body byte cap; its initial value
            also caps bytes retained across the live Surface session.
        retain_bodies: Explicit body opt-in; defaults to false.
        retain_url_path: Explicitly retain URL paths; defaults to false.
        retain_url_query: Explicitly retain URL queries; defaults to false.
        allowed_origins: Exact HTTP(S) origins to retain, or empty for no origin filter.
        allowed_methods: HTTP methods to retain, or empty for no method filter.
        header_allowlist: Header names eligible for retention; credentials and cookies
            are always excluded.
    """

    max_duration_ms: int = Field(default=300000, strict=True, ge=1, le=3600000)
    max_events: int = Field(default=2048, strict=True, ge=1, le=4096)
    max_buffered_events: int = Field(default=256, strict=True, ge=1, le=256)
    max_windows: int = Field(default=32, strict=True, ge=1, le=4096)
    max_event_bytes: int = Field(default=2097152, strict=True, ge=1, le=16777216)
    max_response_bodies: int = Field(default=16, strict=True, ge=0, le=1024)
    max_body_bytes: int = Field(default=1048576, strict=True, ge=1, le=8388608)
    max_total_body_bytes: int = Field(default=8388608, strict=True, ge=1, le=67108864)
    retain_bodies: StrictBool = False
    retain_url_path: StrictBool = False
    retain_url_query: StrictBool = False
    allowed_origins: tuple[StrictStr, ...] = Field(default=(), max_length=256)
    allowed_methods: tuple[StrictStr, ...] = Field(default=(), max_length=64)
    header_allowlist: tuple[StrictStr, ...] = Field(default=(), max_length=64)


class NetworkHeader(ImmutableModel):
    """One retained header after allowlist and sensitive-name filtering."""

    name: StrictStr = Field(description="Lowercase retained header name.")
    value: StrictStr = Field(description="Bounded retained header value.")


NetworkPayloadState = Literal[
    "not_requested", "retained", "truncated", "unavailable", "unsupported"
]
"""Explicit response body retention and projection outcome."""
NetworkPayloadKind = Literal["html", "json", "file"]
"""Projection selected for a separately retained response body."""
NetworkProjectionBasis = Literal[
    "requests_declared",
    "requests_structured_suffix",
    "requests_sniffed",
    "typed_file_magic",
    "opaque_bytes",
]
"""Evidence used to select the retained body projection."""


class NetworkPayloadRef(ImmutableModel):
    """Link from one response event to a separately retained body payload."""

    id: StrictStr = Field(description="Opaque payload id scoped to one subscription.")
    request_id: StrictStr = Field(description="Provider request id scoped to the tab.")
    hop: int = Field(
        strict=True, ge=0, description="Redirect hop producing the response."
    )
    response_sequence: int = Field(
        strict=True, ge=1, description="Linked response event sequence."
    )
    response_window_id: StrictStr = Field(
        description="Frozen window containing the response event."
    )
    body_capture_at_unix_us: int | None = Field(
        default=None,
        strict=True,
        ge=0,
        description="Body request time, separate from event window time.",
    )
    state: NetworkPayloadState = Field(
        description="Body retention or projection result."
    )
    document_kind: NetworkPayloadKind | None = Field(
        default=None, description="Document or FileDocument projection."
    )
    projection_basis: NetworkProjectionBasis | None = Field(
        default=None,
        description="Requests classification or typed file basis for the projection.",
    )
    declared_media_type: StrictStr | None = Field(
        default=None,
        description="Observed raw Content-Type response header, including parameters.",
    )
    browser_effective_mime: StrictStr | None = Field(
        default=None, description="Browser-effective MIME value reported by CDP."
    )
    browser_effective_charset: StrictStr | None = Field(
        default=None,
        description="CDP-effective charset, separate from the response header.",
    )
    detected_media_type: StrictStr | None = Field(
        default=None,
        description="Type detected by shared source sniffing or typed file magic.",
    )
    content_encoding: StrictStr | None = Field(
        default=None, description="Browser-declared content encoding."
    )
    byte_provenance: Literal["cdp_decoded_response_body", "none"] = Field(
        description="Retained bytes are not wire capture."
    )
    provider_base64_encoded: StrictBool = Field(
        description="Whether CDP used base64 transport encoding."
    )
    provider_reported_body_bytes: int | None = Field(
        default=None,
        strict=True,
        ge=0,
        description="Sum of CDP dataReceived.dataLength values; absent if unknown.",
    )
    text_utf8_normalized: StrictBool = Field(
        default=False,
        description=(
            "Whether CDP returned Unicode text retained as a UTF-8 normalized view, "
            "separate from the Content-Type header and browser-effective charset."
        ),
    )
    retained_bytes: int = Field(
        strict=True, ge=0, description="Exact retained body bytes."
    )
    sha256: StrictStr | None = Field(
        default=None, description="SHA-256 of retained response bytes."
    )
    document_id: StrictStr | None = Field(
        default=None,
        description="Document or FileDocument id for offline reconstruction.",
    )
    reason: StrictStr | None = Field(
        default=None, description="Bounded omission or projection reason."
    )


class NetworkCoverage(ImmutableModel):
    """Known gaps and provider limits for one frozen event window."""

    complete: StrictBool = Field(description="Whether provider coverage is complete.")
    reason: StrictStr = Field(
        description="Why the provider cannot claim browser-wide completeness."
    )
    overflow: StrictBool = Field(
        description="Whether an event or byte cap dropped evidence."
    )
    dropped_events: int = Field(
        strict=True, ge=0, description="Known events dropped by bounds."
    )
    disconnected: StrictBool = Field(
        description="Whether the provider stream disconnected."
    )
    expired: StrictBool = Field(
        description="Whether the subscription lifetime elapsed."
    )
    instrumentation_escalated: StrictBool = Field(
        description="Whether this subscription enabled disabled CDP tracking."
    )
    network_was_previously_enabled: StrictBool = Field(
        description="Whether this tab already had Network tracking enabled."
    )
    late_events: int = Field(
        strict=True, ge=0, description="Events delivered with older provider time."
    )
    filtered_events: int = Field(
        strict=True, ge=0, description="Events omitted by selected filters."
    )
    starts_not_observed: int = Field(
        strict=True,
        ge=0,
        description="Events delivered before a request start was known.",
    )
    omitted_payload_links: int = Field(
        strict=True,
        ge=0,
        description="Body links omitted by the network Document bound.",
    )
    start_boundary_unknown: StrictBool = Field(
        description="Whether earlier in-flight requests are unknown."
    )
    end_boundary_in_flight: StrictBool = Field(
        description="Whether requests remain unfinished at window end."
    )


class NetworkGap(ImmutableModel):
    """One explicit gap in the provider sequence or subscription lifetime."""

    after_sequence: int = Field(
        strict=True, ge=0, description="Last retained sequence before the gap."
    )
    reason: StrictStr = Field(description="Bounded gap reason.")
    dropped_events: int | None = Field(
        default=None, strict=True, ge=0, description="Known gap event count."
    )


class NetworkInFlight(ImmutableModel):
    """Request known to cross a frozen event window boundary."""

    request_id: StrictStr = Field(description="Provider request identity.")
    hop: int = Field(strict=True, ge=0, description="Current redirect hop.")
    url: StrictStr = Field(description="URL after the selected redaction policy.")
    method: StrictStr = Field(description="HTTP method.")
    response_seen: StrictBool = Field(
        description="Whether a response event was received."
    )


class NetworkRequestStarted(ImmutableModel):
    """Request start details after URL and header retention policy."""

    kind: Literal["request_started"] = Field(description="Request start discriminator.")
    url: StrictStr = Field(
        description="Retained URL under the selected redaction policy."
    )
    method: StrictStr = Field(description="HTTP method.")
    resource_type: StrictStr | None = Field(
        default=None, description="Browser resource category."
    )
    headers: tuple[NetworkHeader, ...] = Field(
        description="Explicitly allowed non-sensitive headers."
    )


class NetworkRedirect(ImmutableModel):
    """Redirect relationship between two hops of one provider request id."""

    kind: Literal["redirect"] = Field(description="Redirect discriminator.")
    from_url: StrictStr = Field(description="Retained URL for the prior hop.")
    to_url: StrictStr = Field(description="Retained URL for the next hop.")
    status: int = Field(
        strict=True, ge=100, le=599, description="Redirect response status."
    )
    headers: tuple[NetworkHeader, ...] = Field(
        description="Explicitly allowed non-sensitive headers."
    )


class NetworkResponseReceived(ImmutableModel):
    """Response metadata linked to one request hop."""

    kind: Literal["response_received"] = Field(description="Response discriminator.")
    url: StrictStr = Field(description="Retained response URL.")
    status: int | None = Field(
        default=None, strict=True, ge=100, le=599, description="HTTP response status."
    )
    declared_media_type: StrictStr | None = Field(
        default=None,
        description="Observed raw Content-Type response header, including parameters.",
    )
    browser_effective_mime: StrictStr | None = Field(
        default=None, description="Browser-effective MIME value reported by CDP."
    )
    browser_effective_charset: StrictStr | None = Field(
        default=None, description="Browser-effective charset reported by CDP."
    )
    content_encoding: StrictStr | None = Field(
        default=None, description="Declared content encoding."
    )
    headers: tuple[NetworkHeader, ...] = Field(
        description="Explicitly allowed non-sensitive headers."
    )


class NetworkFinished(ImmutableModel):
    """Provider completion metadata for one request hop."""

    kind: Literal["finished"] = Field(description="Completion discriminator.")
    encoded_data_length: int | None = Field(
        default=None,
        strict=True,
        ge=0,
        description="Encoded transfer length when reported.",
    )


class NetworkFailed(ImmutableModel):
    """Provider failure metadata without credentials or raw URL text."""

    kind: Literal["failed"] = Field(description="Failure discriminator.")
    error: StrictStr = Field(description="Bounded safe provider failure label.")
    canceled: StrictBool = Field(description="Whether the request was canceled.")


NetworkEventDetails = Annotated[
    NetworkRequestStarted
    | NetworkRedirect
    | NetworkResponseReceived
    | NetworkFinished
    | NetworkFailed,
    Field(discriminator="kind"),
]
"""Typed, redacted details carried by one NetworkEvent."""


class NetworkEvent(ImmutableModel):
    """One provider event in delivery order, with event-time provenance."""

    sequence: int = Field(
        strict=True, ge=1, description="Monotonic subscription sequence."
    )
    request_id: StrictStr = Field(description="Provider request identity.")
    request_start_observed: StrictBool = Field(
        description="Whether request start was seen before this event."
    )
    hop: int = Field(strict=True, ge=0, description="Redirect hop.")
    observed_at_unix_us: int = Field(
        strict=True, ge=0, description="Local UTC receipt time."
    )
    provider_time_us: int | None = Field(
        default=None, strict=True, ge=0, description="Provider monotonic time."
    )
    provider_clock: Literal["cdp_monotonic"] | None = Field(
        default=None, description="Clock basis for provider time."
    )
    frame_id: StrictStr | None = Field(
        default=None, description="Browser frame id, if supplied."
    )
    loader_id: StrictStr | None = Field(
        default=None, description="Browser loader id, if supplied."
    )
    kind: NetworkEventDetails = Field(
        description="Typed request, redirect, response, finish, or failure details."
    )


class NetworkRetention(ImmutableModel):
    """Caller retention choices and shared Page-lifetime provider caps."""

    max_duration_ms: int = Field(
        strict=True, ge=1, le=3600000, description="Subscription lifetime cap."
    )
    max_events: int = Field(
        strict=True, ge=1, le=4096, description="Lifetime event journal cap."
    )
    max_buffered_events: int = Field(
        strict=True, ge=1, le=256, description="Provider channel queue cap."
    )
    max_event_bytes: int = Field(
        strict=True, ge=1, le=16777216, description="Serialized event metadata cap."
    )
    max_windows: int = Field(
        strict=True, ge=1, le=4096, description="Live frozen-window history cap."
    )
    retain_url_path: StrictBool = Field(description="Whether URL paths were retained.")
    retain_url_query: StrictBool = Field(
        description="Whether URL queries were retained."
    )
    retained_header_names: tuple[StrictStr, ...] = Field(
        description="Retained non-sensitive header allowlist."
    )
    retain_bodies: StrictBool = Field(
        description="Whether response body capture was enabled."
    )
    max_response_bodies: int = Field(
        strict=True, ge=0, le=1024, description="Caller response-body count cap."
    )
    max_body_bytes: int = Field(
        strict=True,
        ge=1,
        le=8388608,
        description="Caller retained-byte cap per response.",
    )
    max_total_body_bytes: int = Field(
        strict=True,
        ge=1,
        le=67108864,
        description="Caller retained-byte cap per subscription.",
    )
    session_max_response_bodies: int | None = Field(
        default=None,
        strict=True,
        ge=0,
        le=1024,
        description="Fixed Surface-session body count cap; absent in older windows.",
    )
    session_max_total_body_bytes: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=67108864,
        description="Fixed Surface-session byte cap; rearming does not reset it.",
    )
    provider_resource_buffer_bytes: int = Field(
        strict=True,
        ge=1,
        description="Shared Page-lifetime CDP per-resource body buffer cap.",
    )
    provider_total_buffer_bytes: int = Field(
        strict=True,
        ge=1,
        description="Shared Page-lifetime CDP aggregate body buffer cap.",
    )
    allowed_origins: tuple[StrictStr, ...] = Field(
        description="Exact origin filter, if selected."
    )
    allowed_methods: tuple[StrictStr, ...] = Field(
        description="Method filter, if selected."
    )


class NetworkWindow(ImmutableModel):
    """Versioned frozen CDP window; event JSON and payload bytes remain separate."""

    schema_id: Literal["yosoi.network.v1"] = Field(
        alias="schema", description="Explicit network observation discriminator."
    )
    schema_version: int = Field(
        strict=True, ge=1, le=1, description="Network schema version."
    )
    session_id: StrictStr = Field(description="Native producer Session.")
    tab_id: StrictStr = Field(description="Native producer tab.")
    subscription_id: StrictStr = Field(
        description="Session-local subscription identity."
    )
    window_id: StrictStr = Field(description="Immutable frozen window identity.")
    first_sequence: int | None = Field(
        default=None, strict=True, ge=1, description="First retained event sequence."
    )
    last_sequence: int | None = Field(
        default=None, strict=True, ge=1, description="Last retained event sequence."
    )
    started_at_unix_us: int = Field(strict=True, ge=0, description="Window start time.")
    ended_at_unix_us: int = Field(strict=True, ge=0, description="Window end time.")
    events: tuple[NetworkEvent, ...] = Field(
        description="Provider events in listener delivery order."
    )
    in_flight_at_start: tuple[NetworkInFlight, ...] = Field(
        description="Known requests at prior freeze boundary."
    )
    in_flight: tuple[NetworkInFlight, ...] = Field(
        description="Requests without a terminal event at window end."
    )
    gaps: tuple[NetworkGap, ...] = Field(
        description="Explicit provider or retention gaps."
    )
    coverage: NetworkCoverage = Field(
        description="Window uncertainty and completeness."
    )
    retention: NetworkRetention = Field(
        description="Effective URL, header, body and filter policy."
    )
    payloads: tuple[NetworkPayloadRef, ...] = Field(
        description="Separate body links, including explicit omissions."
    )

    @model_validator(mode="after")
    def _window_contract(self) -> Self:
        """Check frozen interval, event order and payload identity relationships."""
        if not all(
            (self.session_id, self.tab_id, self.subscription_id, self.window_id)
        ):
            raise ValueError("network window identities must be nonempty")
        if self.ended_at_unix_us < self.started_at_unix_us:
            raise ValueError("network window ends before it starts")
        sequences = tuple(event.sequence for event in self.events)
        if any(
            right <= left for left, right in zip(sequences, sequences[1:], strict=False)
        ):
            raise ValueError("network event sequences must increase")
        expected_first = sequences[0] if sequences else None
        expected_last = sequences[-1] if sequences else None
        if (self.first_sequence, self.last_sequence) != (expected_first, expected_last):
            raise ValueError("network sequence range differs from retained events")
        payload_ids = tuple(payload.id for payload in self.payloads)
        if len(payload_ids) != len(set(payload_ids)):
            raise ValueError("network payload ids must be unique in one window")
        for payload in self.payloads:
            if payload.state in {"retained", "truncated"}:
                if (
                    payload.document_id != payload.id
                    or payload.document_kind is None
                    or payload.projection_basis is None
                    or payload.sha256 is None
                ):
                    raise ValueError(
                        "retained payload requires a source key, projection and digest"
                    )
                if payload.provider_base64_encoded and payload.text_utf8_normalized:
                    raise ValueError(
                        "base64 transport bytes cannot be a normalized text view"
                    )
            elif (
                payload.document_id is not None
                or payload.document_kind is not None
                or payload.projection_basis is not None
                or payload.detected_media_type is not None
                or payload.sha256 is not None
                or payload.text_utf8_normalized
            ):
                raise ValueError("unretained payload cannot claim a source document")
            if payload.response_window_id == self.window_id and not any(
                event.sequence == payload.response_sequence
                and event.request_id == payload.request_id
                and event.hop == payload.hop
                and event.kind.kind == "response_received"
                for event in self.events
            ):
                raise ValueError(
                    "payload reference does not point to its response event"
                )
        return self

    def to_document(self, id: str) -> Document:
        """Create an immutable Document carrying the dedicated network profile."""
        return Document.from_profile(
            id, DocumentProfile.network_observation(), self.model_dump_json()
        )

    @classmethod
    def from_document(cls, document: Document) -> Self:
        """Decode only Documents with the explicit network observation profile."""
        if document.profile.schema_profile != "yosoi_network_observation_v1":
            raise ValueError("document does not carry the network observation profile")
        return cls.model_validate_json(document.data)


NetworkObservation = NetworkWindow
"""Typed spelling for one frozen NetworkWindow."""


class NetworkPayload(ImmutableModel):
    """A payload reference paired with an existing Document or FileDocument."""

    reference: NetworkPayloadRef = Field(
        description="Response relationship and retention metadata."
    )
    value: Document | FileDocument = Field(
        repr=False, exclude=True, description="Retained typed response payload."
    )


class NetworkSubscription(ImmutableModel):
    """Receipt for one explicitly armed native Chrome event subscription."""

    active: StrictBool = Field(description="Whether the subscription is active.")
    subscription_id: StrictStr = Field(
        description="Session-local subscription identity."
    )
    provider: StrictStr = Field(description="Qualified native event provider.")
    body_retention: StrictBool = Field(
        description="Whether response body capture is enabled."
    )
    max_events: int = Field(
        strict=True, ge=1, description="Lifetime event journal cap."
    )
    max_duration_ms: int = Field(
        strict=True, ge=1, description="Subscription lifetime bound."
    )
    session_max_response_bodies: int | None = Field(
        default=None,
        strict=True,
        ge=0,
        description="Fixed Surface-session body count cap; absent in older receipts.",
    )
    session_max_total_body_bytes: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        description="Fixed Surface-session body byte cap; absent in older receipts.",
    )
    session_retained_response_bodies: int | None = Field(
        default=None,
        strict=True,
        ge=0,
        description="Bodies retained by frozen windows when armed.",
    )
    session_retained_body_bytes: int | None = Field(
        default=None, strict=True, ge=0, description="Body bytes retained when armed."
    )


BrowserRepresentation = Literal["dom", "ax", "network"]
"""Native browser evidence view; AX and network addresses are read-only."""


class Coverage(ImmutableModel):
    """Source completeness, independent of how many entries fit on a page."""

    complete: StrictBool = Field(
        description="Whether this representation covers its source."
    )
    reason: StrictStr | None = Field(
        default=None, description="Reason coverage is partial."
    )


class NativeReference(ImmutableModel):
    """Exact document-index address; it does not grant action permission."""

    capture: StrictStr = Field(
        description="Immutable document interpretation identity."
    )
    node: int = Field(strict=True, ge=0, description="Producer-issued node ordinal.")


class Reference(ImmutableModel):
    """Representation-neutral evidence address, scoped to one observation."""

    observation: ObservationId = Field(description="Immutable interpretation identity.")
    address: AddressToken = Field(
        description="Opaque producer address; do not parse it."
    )


class Continuation(ImmutableModel):
    """Opaque native-index continuation. Copy it unchanged into the same read."""

    capture: StrictStr = Field(description="Original immutable capture.")
    operation: StrictStr = Field(description="Original operation binding.")
    scope: int = Field(strict=True, ge=0, description="Original producer scope.")
    query: StrictStr = Field(description="Original literal-search binding.")
    offset: int = Field(
        strict=True, ge=0, description="Next entry or UTF-8 byte offset."
    )


class NativeEntry(ImmutableModel):
    """One structural routing hint backed by document evidence."""

    reference: NativeReference = Field(description="Exact indexed evidence.")
    kind: StrictStr = Field(description="Representation-specific category.")
    label: StrictStr = Field(description="Short source-derived routing label.")
    preview: StrictStr = Field(description="Bounded source preview.")
    members: int | None = Field(default=None, description="Known child count.")
    exemplar: NativeReference | None = Field(
        default=None, description="Repeated-group example."
    )
    shape: StrictStr | None = Field(
        default=None, description="Advisory structural shape."
    )
    view: StrictStr | None = Field(default=None, description="Named constituent view.")


class NativePage(ImmutableModel):
    """A bounded document-index window with explicit paging and coverage."""

    capture: StrictStr = Field(description="Exact immutable interpretation.")
    operation: StrictStr = Field(description="Operation that produced this page.")
    total: int = Field(description="Eligible population before paging.")
    offset: int = Field(description="Starting entry position.")
    entries: tuple[NativeEntry, ...] = Field(description="Returned routing hints.")
    omitted: int = Field(description="Population entries outside this response.")
    next: Continuation | None = Field(
        default=None, description="Next window, if present."
    )
    coverage: Coverage = Field(description="Source completeness independent of paging.")


class NativeInspection(ImmutableModel):
    """Source-backed detail chunk; concatenate all chunks before parsing JSON."""

    reference: NativeReference = Field(description="Exact selected evidence.")
    media_type: StrictStr = Field(description="Interpretation of content.")
    total_bytes: int = Field(description="Complete serialization byte length.")
    offset: int = Field(description="Starting UTF-8 byte position.")
    content: StrictStr = Field(description="This UTF-8-aligned detail chunk.")
    next: Continuation | None = Field(default=None, description="Next detail chunk.")
    coverage: Coverage = Field(description="Source completeness.")


class Coordinate(ImmutableModel):
    """Representation-specific locator coordinates retained by the index."""

    kind: StrictStr = Field(description="Coordinate interpretation.")
    value: StrictStr = Field(description="Producer-derived coordinate value.")


class SourceReference(ImmutableModel):
    """Binding from a combined index to one original independently captured view."""

    view: StrictStr = Field(description="Constituent view name.")
    reference: NativeReference = Field(description="Original view's exact reference.")


class IndexMetadata(ImmutableModel):
    """Preparation summary, not a current live-source status."""

    identity: StrictStr = Field(description="Immutable interpretation identity.")
    representation: StrictStr = Field(description="Document interpretation profile.")
    source_bytes: int = Field(description="Retained source byte count.")
    node_count: int = Field(description="Indexed evidence node count.")
    coverage: Coverage = Field(description="Preparation completeness.")
    root: NativeReference = Field(description="Full structural scope.")


Access = Literal["read", "control"]
"""Whether a capability only reads evidence or may change an external source."""


class Capability(ImmutableModel):
    """Advertised operation with explicit read or control access."""

    id: StrictStr = Field(description="Representation-owned capability name.")
    access: Access = Field(description="Whether the source may change.")
    control_domain: StrictStr | None = Field(
        default=None, description="Control arbitration domain."
    )
    input_schema: StrictStr = Field(description="Versioned input schema identity.")


class Descriptor(ImmutableModel):
    """Continuing source representation and the operations it actually supports."""

    id: SurfaceId = Field(description="Surface identity.")
    source: SourceId = Field(description="Source identity, without authority.")
    representation: StrictStr = Field(description="Interpretation profile.")
    controllable: StrictBool = Field(description="Whether this adapter offers control.")
    capabilities: tuple[Capability, ...] = Field(description="Supported operations.")


class Observation(ImmutableModel):
    """One immutable interpretation of a continuing surface."""

    id: ObservationId = Field(description="Exact observation identity.")
    surface: SurfaceId = Field(description="Surface represented by this observation.")
    coverage: Coverage = Field(description="Evidence completeness.")


class Overview(ImmutableModel):
    """Request a bounded set of routing regions."""

    kind: Literal["overview"] = Field(default="overview", description="Operation tag.")


class Expand(ImmutableModel):
    """Request direct structural or temporal children of exact evidence."""

    kind: Literal["expand"] = Field(default="expand", description="Operation tag.")
    reference: Reference = Field(description="Exact region to explore.")


class Inspect(ImmutableModel):
    """Request source-backed text detail, possibly split across chunks."""

    kind: Literal["inspect"] = Field(default="inspect", description="Operation tag.")
    reference: Reference = Field(description="Exact selected evidence.")


class Search(ImmutableModel):
    """Request literal search when advertised by this representation."""

    kind: Literal["search"] = Field(default="search", description="Operation tag.")
    query: StrictStr = Field(description="Literal source text, not a query language.")


class Parent(ImmutableModel):
    """Request a structural parent where that relation is supported."""

    kind: Literal["parent"] = Field(default="parent", description="Operation tag.")
    reference: Reference = Field(description="Evidence whose parent is requested.")


ReadOperation = Annotated[
    Overview | Expand | Inspect | Search | Parent, Field(discriminator="kind")
]
"""Tagged navigation operation; capabilities determine which variants are supported."""


class ReadRequest(ImmutableModel):
    """One shared request passed unchanged to either Rust-backed reader."""

    operation: ReadOperation = Field(description="Navigation operation.")
    budget: Budget = Field(
        default_factory=Budget, description="Complete Rust result bound."
    )
    continuation: ContinuationToken | None = Field(
        default=None, description="Opaque shared continuation."
    )


class Entry(ImmutableModel):
    """Representation-neutral hint for choosing the next region to inspect."""

    reference: Reference = Field(description="Exact evidence address.")
    kind: StrictStr = Field(description="Representation-specific category.")
    label: StrictStr = Field(description="Short routing label.")
    preview: StrictStr = Field(description="Bounded source-derived preview.")
    members: int | None = Field(default=None, description="Known child count.")


class Page(ImmutableModel):
    """Shared bounded region window; coverage and pagination are independent."""

    observation: ObservationId = Field(description="Exact interpretation identity.")
    total: int = Field(description="Eligible population before paging.")
    offset: int = Field(description="Starting entry position.")
    entries: tuple[Entry, ...] = Field(description="Returned routing entries.")
    next: ContinuationToken | None = Field(
        default=None, description="Opaque next-window token."
    )
    coverage: Coverage = Field(description="Completeness of source evidence.")


class Inspection(ImmutableModel):
    """Shared source-backed text fragment; it may be incomplete serialized JSON."""

    reference: Reference = Field(description="Exact selected evidence.")
    media_type: StrictStr = Field(description="Interpretation of content.")
    total_bytes: int = Field(description="Complete detail length in UTF-8 bytes.")
    offset: int = Field(description="Starting UTF-8 byte position.")
    content: StrictStr = Field(description="This detail fragment.")
    next: ContinuationToken | None = Field(
        default=None, description="Opaque next-chunk token."
    )
    coverage: Coverage = Field(description="Completeness of source evidence.")


class PageResult(ImmutableModel):
    """Tagged shared routing result."""

    kind: Literal["page"] = Field(default="page", description="Result tag.")
    data: Page = Field(description="Bounded routing window.")


class InspectionResult(ImmutableModel):
    """Tagged shared detail result."""

    kind: Literal["inspection"] = Field(default="inspection", description="Result tag.")
    data: Inspection = Field(description="Bounded evidence fragment.")


class ParentResult(ImmutableModel):
    """Tagged parent result; a root has no parent."""

    kind: Literal["parent"] = Field(default="parent", description="Result tag.")
    data: Reference | None = Field(description="Parent reference, absent at root.")


ReadResult = Annotated[
    PageResult | InspectionResult | ParentResult, Field(discriminator="kind")
]
"""Tagged result of a shared read. Contains evidence, never action authority."""
_RESULT = TypeAdapter(ReadResult)


class SurfaceRead(Protocol):
    """Common pure reading contract; frame decoding and effects are capabilities."""

    @property
    def descriptor(self) -> Descriptor:
        """Return supported operations and source identity."""
        ...

    @property
    def observation(self) -> Observation:
        """Return immutable interpretation metadata."""
        ...

    @property
    def root_reference(self) -> Reference:
        """Return the full scope of this representation."""
        ...

    def read(self, request: ReadRequest) -> ReadResult:
        """Read bounded evidence; unsupported or foreign requests raise SurfaceError."""
        ...


class Surface:
    """Reusable immutable index of any supported Document class.

    Args:
        document: Retained source bytes and interpretation profile.
        limits: Preparation bounds, independent of a task or language model.

    Raises:
        SurfaceError: Input interpretation or resource limits fail.
    """

    def __init__(self, document: Document, limits: Limits | None = None) -> None:
        """Prepare document evidence in Rust without network or model calls."""
        self._handle = _native.Surface(
            document._handle, (limits or Limits()).model_dump_json()
        )

    @classmethod
    def with_policy(cls, document: Document, policies: DocumentPolicies) -> Self:
        """Prepare using Rust's policy selection for the declared document type."""
        return cls._from_native(
            _native.Surface.with_policy(document._handle, policies.model_dump_json())
        )

    @classmethod
    def _from_native(cls, handle: _native.Surface) -> Self:
        value = cls.__new__(cls)
        value._handle = handle
        return value

    @property
    def metadata(self) -> IndexMetadata:
        """Return source size, index size, root and preparation coverage."""
        return IndexMetadata.model_validate_json(self._handle.metadata())

    @property
    def identity(self) -> str:
        """Return the immutable document interpretation identity."""
        return self.metadata.identity

    @property
    def representation(self) -> str:
        """Return the indexed document's interpretation profile."""
        return self.metadata.representation

    @property
    def source_bytes(self) -> int:
        """Return retained source size, separate from response budgets."""
        return self.metadata.source_bytes

    @property
    def node_count(self) -> int:
        """Return indexed evidence count, including reduced routing regions."""
        return self.metadata.node_count

    @property
    def coverage(self) -> Coverage:
        """Return preparation coverage, independently of response pagination."""
        return self.metadata.coverage

    @property
    def root(self) -> NativeReference:
        """Return the exact reference covering the complete indexed document."""
        return self.metadata.root

    def _read(
        self,
        operation: str,
        reference: NativeReference | None = None,
        query: str = "",
        continuation: Continuation | None = None,
        budget: Budget | None = None,
    ) -> str:
        return self._handle.read(
            operation,
            reference.model_dump_json() if reference else None,
            query,
            continuation.model_dump_json() if continuation else None,
            (budget or Budget()).model_dump_json(),
        )

    def overview(
        self, *, continuation: Continuation | None = None, budget: Budget | None = None
    ) -> NativePage:
        """Read a reduced overview; omitted evidence remains reachable by paging."""
        return NativePage.model_validate_json(
            self._read("overview", continuation=continuation, budget=budget)
        )

    def find(
        self,
        query: str,
        *,
        continuation: Continuation | None = None,
        budget: Budget | None = None,
    ) -> NativePage:
        """Find literal source text and attributes; Rust rejects empty queries."""
        return NativePage.model_validate_json(
            self._read("find", query=query, continuation=continuation, budget=budget)
        )

    def expand(
        self,
        reference: NativeReference,
        *,
        continuation: Continuation | None = None,
        budget: Budget | None = None,
    ) -> NativePage:
        """Read one region's members; foreign references raise SurfaceError."""
        return NativePage.model_validate_json(
            self._read("expand", reference, continuation=continuation, budget=budget)
        )

    def inspect(
        self,
        reference: NativeReference,
        *,
        continuation: Continuation | None = None,
        budget: Budget | None = None,
    ) -> NativeInspection:
        """Read source detail in UTF-8 chunks bound to the original reference."""
        return NativeInspection.model_validate_json(
            self._read("inspect", reference, continuation=continuation, budget=budget)
        )

    def parent(self, reference: NativeReference) -> NativeReference | None:
        """Return the structural parent, or None at the root."""
        return TypeAdapter(NativeReference | None).validate_json(
            self._read("parent", reference)
        )

    def coordinate(self, reference: NativeReference) -> Coordinate:
        """Return representation-specific source coordinates without live resolution."""
        return Coordinate.model_validate_json(self._read("coordinate", reference))

    def validate(self, reference: NativeReference) -> None:
        """Reject references outside this exact immutable interpretation."""
        self._read("validate", reference)

    def source_reference(self, reference: NativeReference) -> SourceReference | None:
        """Resolve a combined-view reference to its original captured view."""
        return TypeAdapter(SourceReference | None).validate_json(
            self._read("source_reference", reference)
        )

    @classmethod
    def combine(
        cls, scope: str, views: Mapping[str, Surface], limits: Limits | None = None
    ) -> Self:
        """Combine named captures without claiming an atomic observation."""
        return cls._from_native(
            _native.Surface.combine(
                scope,
                [(name, view._handle) for name, view in views.items()],
                (limits or Limits()).model_dump_json(),
            )
        )

    def view(self, name: str) -> Surface | None:
        """Return an original constituent view, or None if the name is absent."""
        handle = self._handle.view(name)
        return self._from_native(handle) if handle is not None else None

    def project(self, name: str, reference: NativeReference) -> NativeReference:
        """Project an original view reference into this combined index."""
        return NativeReference.model_validate_json(
            self._handle.project(name, reference.model_dump_json())
        )

    @classmethod
    def from_image(
        cls,
        content: bytes | ImageDocument,
        tile_side: int = 256,
        limits: Limits | None = None,
        pixel_limits: PixelLimits | None = None,
    ) -> Self:
        """Index a typed image or legacy byte payload without OCR or EXIF rotation."""
        if not hasattr(_native.Surface, "from_image"):
            raise SurfaceError("this wheel has no image support")
        if isinstance(content, ImageDocument):
            return cls.from_image_document(
                content,
                tile_side=tile_side,
                limits=limits,
                pixel_limits=pixel_limits,
            )
        if pixel_limits is None:
            return cls._from_native(
                _native.Surface.from_image(
                    content, tile_side, (limits or Limits()).model_dump_json()
                )
            )
        if not hasattr(_native.Surface, "from_image_with_pixel_limits"):
            raise SurfaceError("this wheel has no image support")
        return cls._from_native(
            _native.Surface.from_image_with_pixel_limits(
                content,
                tile_side,
                (limits or Limits()).model_dump_json(),
                pixel_limits.model_dump_json(),
            )
        )

    @classmethod
    def from_image_document(
        cls,
        document: ImageDocument,
        *,
        tile_side: int = 256,
        limits: Limits | None = None,
        pixel_limits: PixelLimits | None = None,
    ) -> Self:
        """Prepare an exact ImageDocument; source identity excludes Surface options."""
        if not hasattr(_native.Surface, "from_image_document"):
            raise SurfaceError("this wheel has no image support")
        selected_pixels = pixel_limits or PixelLimits()
        return cls._from_native(
            _native.Surface.from_image_document(
                document._handle,
                tile_side,
                (limits or Limits()).model_dump_json(),
                selected_pixels.model_dump_json(),
            )
        )

    def direct_image(self) -> PixelArtifact:
        """Return exact original bytes directly without tree navigation."""
        if not hasattr(self._handle, "direct_image"):
            raise SurfaceError("this wheel has no image support")
        return PixelArtifact._from_native(self._handle.direct_image())

    def overview_image(self, max_side: int) -> PixelArtifact:
        """Return an aspect-preserving overview resized with the triangle filter."""
        if not hasattr(self._handle, "overview_image"):
            raise SurfaceError("this wheel has no image support")
        return PixelArtifact._from_native(self._handle.overview_image(max_side))

    def resize_image(self, width: int, height: int) -> PixelArtifact:
        """Return an explicitly sized resize using the triangle filter."""
        if not hasattr(self._handle, "resize_image"):
            raise SurfaceError("this wheel has no image support")
        return PixelArtifact._from_native(self._handle.resize_image(width, height))

    def crop(
        self, reference: NativeReference, max_png_bytes: int = 8388608
    ) -> ImageCrop:
        """Materialize an indexed image region; binary and text budgets are separate."""
        if not hasattr(self._handle, "crop"):
            raise SurfaceError("this wheel has no image support")
        info, artifact = self._handle.crop(reference.model_dump_json(), max_png_bytes)
        return ImageCrop(
            **json.loads(info), artifact=PixelArtifact._from_native(artifact)
        )

    def crop_rect(self, rect: PixelRect, max_png_bytes: int = 8388608) -> ImageCrop:
        """Crop explicit bounds in the original image raster coordinate space."""
        if not hasattr(self._handle, "crop_rect"):
            raise SurfaceError("this wheel has no image support")
        info, artifact = self._handle.crop_rect(rect.model_dump_json(), max_png_bytes)
        return ImageCrop(
            **json.loads(info), artifact=PixelArtifact._from_native(artifact)
        )


class WebSurface:
    """Shared read protocol over any of the six immutable Document classes.

    Args:
        index: Prepared HTML, XML, JSON, text, rendered DOM or AX evidence.
        source: Nonempty continuing-source identity, without browser authority.
        policy: Optional independent serialized response limits.

    Network-shaped JSON retains partial coverage. Every representation exposes
    only the read capabilities supported by its prepared index.
    """

    def __init__(
        self, index: Surface, source: str, policy: DocumentPolicy | None = None
    ) -> None:
        """Bind a web observation to its source; no browser is opened."""
        self._handle = index._handle.web(
            source, (policy or DocumentPolicy()).model_dump_json()
        )

    @property
    def descriptor(self) -> Descriptor:
        """Return read capabilities; this immutable adapter is not controllable."""
        return Descriptor.model_validate_json(self._handle.descriptor())

    @property
    def observation(self) -> Observation:
        """Return the exact source-bound interpretation identity."""
        return Observation.model_validate_json(self._handle.observation())

    @property
    def root_reference(self) -> Reference:
        """Return the full web observation's shared address."""
        return Reference.model_validate_json(self._handle.root_reference())

    def read(self, request: ReadRequest) -> ReadResult:
        """Read in Rust; the complete tagged result fits the requested byte budget."""
        return _RESULT.validate_json(self._handle.read(request.model_dump_json()))

    def reference(self, reference: NativeReference) -> Reference:
        """Convert an exact index reference into this source-bound shared address."""
        return Reference.model_validate_json(
            self._handle.reference(reference.model_dump_json())
        )

    def native_reference(self, reference: Reference) -> NativeReference:
        """Recover an index reference; foreign observations are rejected by Rust."""
        return NativeReference.model_validate_json(
            self._handle.native_reference(reference.model_dump_json())
        )


class PixelRect(ImmutableModel):
    """Crop in the explicitly declared parent pixel coordinate space."""

    x: int = Field(
        strict=True, ge=0, le=2**32 - 1, description="Left pixel coordinate."
    )
    y: int = Field(strict=True, ge=0, le=2**32 - 1, description="Top pixel coordinate.")
    width: int = Field(strict=True, ge=0, le=2**32 - 1, description="Crop pixel width.")
    height: int = Field(
        strict=True, ge=0, le=2**32 - 1, description="Crop pixel height."
    )


PixelCoordinateKind = Literal["original_raster", "decoded_canvas", "derived_canvas"]
"""Coordinate plane name for one pixel artifact."""
PixelOrientation = Literal[
    "exif_unapplied", "decoder_applied", "not_applicable", "unknown"
]
"""Orientation action already applied before the named coordinate plane."""


class PixelCoordinateSpace(ImmutableModel):
    """Pixel dimensions, coordinate plane and orientation handling."""

    kind: PixelCoordinateKind
    width: int = Field(strict=True, gt=0, le=8192)
    height: int = Field(strict=True, gt=0, le=8192)
    orientation: PixelOrientation


class ImageDocumentPixelSource(ImmutableModel):
    """Identity and exact payload digest for a typed source image."""

    kind: Literal["image_document"]
    document_id: StrictStr
    sha256: StrictStr


class BrowserScreenshotPixelSource(ImmutableModel):
    """Producer identity for one exact screenshot capture."""

    kind: Literal["browser_screenshot"]
    identity: StrictStr


class VideoFramePixelSource(ImmutableModel):
    """Source video and exact frame address with requested and measured time."""

    kind: Literal["video_frame"]
    source_document_id: StrictStr
    source_sha256: StrictStr
    observation: StrictStr
    reference: StrictStr
    requested_us: int = Field(strict=True, ge=0, le=2**64 - 1)
    source_pts_us: int = Field(strict=True, ge=-(2**63), le=2**63 - 1)


class LegacyVideoFramePixelSource(ImmutableModel):
    """Older frame provenance without a typed VideoDocument identity."""

    kind: Literal["legacy_video_frame"]
    source_sha256: StrictStr | None
    observation: StrictStr
    reference: StrictStr
    requested_us: int = Field(strict=True, ge=0, le=2**64 - 1)
    source_pts_us: int = Field(strict=True, ge=-(2**63), le=2**63 - 1)


PixelSource = Annotated[
    ImageDocumentPixelSource
    | BrowserScreenshotPixelSource
    | VideoFramePixelSource
    | LegacyVideoFramePixelSource,
    Field(discriminator="kind"),
]
"""Typed source provenance for an exact root pixel artifact."""


class PixelCropOperation(ImmutableModel):
    """Explicit crop bounds in one parent pixel coordinate space."""

    kind: Literal["crop"]
    rect: PixelRect


class PixelOverviewOperation(ImmutableModel):
    """Aspect-preserving overview resize operation and maximum side."""

    kind: Literal["overview"]
    max_side: int = Field(strict=True, gt=0, le=8192)
    filter: Literal["triangle"]


class PixelResizeOperation(ImmutableModel):
    """Exact output dimensions for an explicit resize."""

    kind: Literal["resize"]
    width: int = Field(strict=True, gt=0, le=8192)
    height: int = Field(strict=True, gt=0, le=8192)
    filter: Literal["triangle"]


class PixelSourceOperation(ImmutableModel):
    """Exact source pixels without a resize or crop."""

    kind: Literal["source"]


PixelOperation = Annotated[
    PixelCropOperation
    | PixelOverviewOperation
    | PixelResizeOperation
    | PixelSourceOperation,
    Field(discriminator="kind"),
]
"""Explicit source, overview, resize or crop operation."""


class PixelEdgeTransform(ImmutableModel):
    """Integer-rational output-pixel-edge map to the parent coordinate plane."""

    scale_x_numerator: int = Field(strict=True, gt=0, le=2**32 - 1)
    scale_x_denominator: int = Field(strict=True, gt=0, le=2**32 - 1)
    scale_y_numerator: int = Field(strict=True, gt=0, le=2**32 - 1)
    scale_y_denominator: int = Field(strict=True, gt=0, le=2**32 - 1)
    translate_x: int = Field(strict=True, ge=0, le=2**32 - 1)
    translate_y: int = Field(strict=True, ge=0, le=2**32 - 1)


class PixelTransform(ImmutableModel):
    """Versioned derivation and exact parent coordinate mapping."""

    version: Literal[1]
    operation: PixelOperation
    parent_identity: StrictStr | None = None
    parent_sha256: StrictStr | None = None
    parent_media_type: Literal["image/png", "image/jpeg"] | None = None
    parent_space: PixelCoordinateSpace | None = None
    output_to_parent: PixelEdgeTransform | None = None


class PixelArtifactInfo(ImmutableModel):
    """Pixel payload digest, source identity, dimensions and coordinate provenance."""

    version: Literal[1]
    identity: StrictStr
    sha256: StrictStr
    media_type: Literal["image/png", "image/jpeg"]
    width: int = Field(strict=True, gt=0, le=8192)
    height: int = Field(strict=True, gt=0, le=8192)
    source: PixelSource
    coordinate_space: PixelCoordinateSpace
    source_space: PixelCoordinateSpace
    transform: PixelTransform


class PixelLimits(ImmutableModel):
    """Decoder, output and retained-artifact limits, separate from text budgets."""

    max_side: int = Field(default=8192, strict=True, ge=1, le=8192)
    max_decoded_bytes: int = Field(default=67108864, strict=True, ge=1, le=67108864)
    max_output_pixels: int = Field(default=16777216, strict=True, ge=1, le=16777216)
    max_output_bytes: int = Field(default=8388608, strict=True, ge=1, le=33554432)
    max_retained_artifacts: int = Field(default=32, strict=True, ge=1, le=1024)


class PixelArtifact(ImmutableModel):
    """Exact PNG/JPEG bytes and validated source/transform metadata."""

    info: PixelArtifactInfo = Field(
        description="Source identity and pixel coordinates."
    )
    content: _Bytes = Field(
        repr=False,
        exclude=True,
        description="Exact encoded image bytes; excluded from metadata dumps.",
    )
    _handle: _native.PixelArtifact = PrivateAttr()

    @classmethod
    def from_image_document(
        cls, document: ImageDocument, limits: PixelLimits | None = None
    ) -> Self:
        """Decode a typed image into a direct pixel artifact without a region index."""
        if not hasattr(_native, "PixelArtifact"):
            raise SurfaceError("this wheel has no image support")
        return cls._from_native(
            _native.PixelArtifact.from_image_document(
                document._handle,
                (limits or PixelLimits()).model_dump_json(),
            )
        )

    def model_post_init(self, context: object) -> None:
        """Bind the immutable Pydantic view to its Rust-owned artifact."""
        if not hasattr(_native, "PixelArtifact") or not isinstance(
            context, _native.PixelArtifact
        ):
            raise ValueError(
                "construct PixelArtifact values through Surface or Archive"
            )
        if not context.matches(self.info.model_dump_json(), self.content):
            raise ValueError("native PixelArtifact value does not match")
        self._handle = context

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Copy this view without allowing metadata or bytes to diverge from Rust."""
        if update:
            unknown = set(update) - {"info", "content"}
            if unknown:
                raise ValueError("PixelArtifact copies cannot update native handles")
            if "info" in update and update["info"] != self.info:
                raise ValueError("PixelArtifact provenance cannot be forged by copying")
            if "content" in update and update["content"] != self.content:
                raise ValueError("PixelArtifact bytes cannot be changed by copying")
        copied = super().model_copy(deep=deep)
        copied._verify_native()
        return copied

    def _verify_native(self) -> None:
        if not self._handle.matches(self.info.model_dump_json(), self.content):
            raise ValueError("native PixelArtifact value does not match")

    @classmethod
    def _from_native(cls, handle: _native.PixelArtifact) -> Self:
        return cls.model_validate(
            {"info": json.loads(handle.info()), "content": handle.bytes()},
            context=handle,
        )

    @property
    def bytes(self) -> _Bytes:
        """Return a copy of exact encoded image bytes."""
        return self.content

    @property
    def document(self) -> ImageDocument:
        """Return the typed immutable ImageDocument owning this payload."""
        self._verify_native()
        return ImageDocument._from_native(self._handle.document())

    def map_rect_to_source(self, rect: PixelRect) -> PixelRect:
        """Map artifact pixel edges back to the root source pixel plane."""
        self._verify_native()
        return PixelRect.model_validate_json(
            self._handle.map_rect_to_source(rect.model_dump_json())
        )

    async def write_to(self, archive: Archive) -> PixelArtifactArchiveRef:
        """Store pixels in Archive with their source and transform metadata."""
        self._verify_native()
        return PixelArtifactArchiveRef.model_validate_json(
            await self._handle.write_to(archive._handle)
        )

    @classmethod
    async def read_from(
        cls, archive: Archive, reference: PixelArtifactArchiveRef
    ) -> Self:
        """Restore verified pixel bytes without a source path or video decoder."""
        if not hasattr(_native, "PixelArtifact"):
            raise SurfaceError("this wheel has no image support")
        handle = await _native.PixelArtifact.read_from(
            archive._handle, reference.model_dump_json()
        )
        return cls._from_native(handle)


class ImageCrop(ImmutableModel):
    """Actual PNG artifact cropped from an indexed source coordinate region."""

    reference: NativeReference = Field(description="Exact selected image evidence.")
    rect: PixelRect = Field(description="Bounds in the original raster pixel space.")
    artifact: PixelArtifact = Field(
        description="Typed crop pixels with parent provenance."
    )

    @property
    def png(self) -> bytes:
        """Return encoded PNG bytes, independent of text response budgets."""
        return self.artifact.content


class ImageSurface:
    """Typed image reader using the shared bounded protocol and pixel artifacts."""

    def __init__(
        self,
        document: ImageDocument,
        *,
        tile_side: int = 256,
        limits: Limits | None = None,
        pixel_limits: PixelLimits | None = None,
    ) -> None:
        """Decode an ImageDocument under explicit index and pixel limits."""
        if not hasattr(_native, "ImageSurface"):
            raise SurfaceError("this wheel has no image support")
        self._handle = _native.ImageSurface.from_image_document(
            document._handle,
            tile_side,
            (limits or Limits()).model_dump_json(),
            (pixel_limits or PixelLimits()).model_dump_json(),
        )

    @classmethod
    def from_pixel_artifact(
        cls,
        artifact: PixelArtifact,
        *,
        tile_side: int = 256,
        limits: Limits | None = None,
        pixel_limits: PixelLimits | None = None,
    ) -> Self:
        """Open a saved root artifact without replacing its source coordinates."""
        if not hasattr(_native, "ImageSurface"):
            raise SurfaceError("this wheel has no image support")
        value = cls.__new__(cls)
        value._handle = _native.ImageSurface.from_pixel_artifact(
            artifact._handle,
            tile_side,
            (limits or Limits()).model_dump_json(),
            (pixel_limits or PixelLimits()).model_dump_json(),
        )
        return value

    @property
    def descriptor(self) -> Descriptor:
        """Return read and pixel capabilities available for this typed image."""
        return Descriptor.model_validate_json(self._handle.descriptor())

    @property
    def observation(self) -> Observation:
        """Return the immutable source-bound image interpretation."""
        return Observation.model_validate_json(self._handle.observation())

    @property
    def root_reference(self) -> Reference:
        """Return the shared reader reference for the complete source raster."""
        return Reference.model_validate_json(self._handle.root_reference())

    @property
    def source_artifact(self) -> PixelArtifact:
        """Return the indexed root PixelArtifact with its source provenance."""
        return PixelArtifact._from_native(self._handle.source_artifact())

    def read(self, request: ReadRequest) -> ReadResult:
        """Read bounded image regions through the existing Surface read contract."""
        return _RESULT.validate_json(self._handle.read(request.model_dump_json()))

    def reference(self, reference: NativeReference) -> Reference:
        """Convert an exact native index reference to this observation."""
        return Reference.model_validate_json(
            self._handle.reference(reference.model_dump_json())
        )

    def native_reference(self, reference: Reference) -> NativeReference:
        """Resolve one shared reference; foreign observations are rejected."""
        return NativeReference.model_validate_json(
            self._handle.native_reference(reference.model_dump_json())
        )

    def direct_image(self) -> PixelArtifact:
        """Return the original encoded bytes without tree navigation."""
        return PixelArtifact._from_native(self._handle.direct_image())

    def overview_image(self, max_side: int) -> PixelArtifact:
        """Return an explicit resized overview under image output bounds."""
        return PixelArtifact._from_native(self._handle.overview_image(max_side))

    def resize_image(self, width: int, height: int) -> PixelArtifact:
        """Return an explicitly sized resize under image output bounds."""
        return PixelArtifact._from_native(self._handle.resize_image(width, height))

    def crop(self, reference: Reference, max_png_bytes: int = 8388608) -> ImageCrop:
        """Crop a shared reference in source-raster coordinates."""
        info, artifact = self._handle.crop(reference.model_dump_json(), max_png_bytes)
        return ImageCrop(
            **json.loads(info), artifact=PixelArtifact._from_native(artifact)
        )

    def crop_rect(self, rect: PixelRect, max_png_bytes: int = 8388608) -> ImageCrop:
        """Crop explicit bounds in the source raster coordinate space."""
        info, artifact = self._handle.crop_rect(rect.model_dump_json(), max_png_bytes)
        return ImageCrop(
            **json.loads(info), artifact=PixelArtifact._from_native(artifact)
        )


class VideoPolicy(ImmutableModel):
    """Snapshot and decoder limits. Rust validates the supported combinations."""

    max_source_bytes: int = Field(
        default=33554432, strict=True, ge=0, description="Source byte cap."
    )
    frame_max_side: int = Field(
        default=1920, strict=True, ge=0, description="Decoded side cap; never upscales."
    )
    max_frame_bytes: int = Field(
        default=8388608, strict=True, ge=0, description="PNG byte cap per artifact."
    )
    min_interval_us: int = Field(
        default=250000,
        strict=True,
        ge=0,
        description="Smallest automatic timeline interval.",
    )
    max_duration_us: int = Field(
        default=21600000000, strict=True, ge=0, description="Primary duration cap."
    )
    tool_timeout_ms: int = Field(
        default=30000,
        strict=True,
        ge=0,
        description="Per-tool timeout in milliseconds.",
    )


class VideoMetadata(ImmutableModel):
    """Primary video stream metadata captured from the frozen source."""

    name: StrictStr = Field(
        description="Original display name, never a reopening address."
    )
    source_sha256: StrictStr = Field(description="Digest of complete frozen bytes.")
    source_bytes: int = Field(description="Original source length.")
    container: StrictStr = Field(description="Demuxer container names.")
    codec: StrictStr = Field(description="Primary stream codec.")
    width: int = Field(description="Original raster width.")
    height: int = Field(description="Original raster height.")
    duration_us: int = Field(description="Primary duration in microseconds.")
    duration_estimated: StrictBool = Field(
        description="Whether container duration was used."
    )
    stream_start_us: int = Field(description="Primary source start timestamp.")
    time_base: StrictStr = Field(description="Demuxer time-base expression.")
    audio_streams: int = Field(description="Audio stream count; audio is not decoded.")
    decoder: StrictStr = Field(description="Decoder version defining interpretation.")


class FrameInfo(ImmutableModel):
    """Actual PNG provenance, separating requested time from measured source PTS."""

    reference: Reference = Field(description="Exact video evidence address.")
    requested_us: int = Field(description="Requested stream-relative microseconds.")
    source_pts_us: int = Field(description="Measured source frame timestamp.")
    position_us: int | None = Field(
        description="Measured stream-relative position, absent for pre-roll."
    )
    canvas_width: int = Field(description="Full decoded-frame width.")
    canvas_height: int = Field(description="Full decoded-frame height.")
    width: int = Field(description="Returned PNG width.")
    height: int = Field(description="Returned PNG height.")
    region: PixelRect | None = Field(
        description="Crop in full decoded-frame coordinates."
    )
    png_sha256: StrictStr = Field(description="Digest of returned PNG bytes.")
    png_bytes: int = Field(description="Encoded PNG byte count.")


_ArchiveDocument = Annotated[
    DocumentArchiveRef,
    BeforeValidator(
        lambda value: (
            DocumentArchiveRef(value=value) if isinstance(value, str) else value
        )
    ),
    PlainSerializer(lambda value: value.value, return_type=str),
]


_ArchiveFileDocument = Annotated[
    FileDocumentArchiveRef,
    BeforeValidator(
        lambda value: (
            TypeAdapter(FileDocumentArchiveRef).validate_python({"value": value})
            if isinstance(value, str)
            else value
        )
    ),
    PlainSerializer(lambda value: value.value, return_type=str),
]


class VideoArchiveRef(ImmutableModel):
    """Normal Archive Document retaining source bytes and interpretation profile."""

    document: _ArchiveDocument = Field(description="Immutable stored document.")
    observation: ObservationId = Field(
        description="Required interpretation identity on restore."
    )


class FrameArchiveRef(ImmutableModel):
    """Normal Archive Document retaining actual PNG bytes and FrameInfo."""

    document: _ArchiveDocument = Field(description="Immutable stored PNG envelope.")


class DecodedFrame:
    """Immutable Rust-owned PNG evidence, restored without a decoder when archived."""

    def __init__(self, handle: _native.DecodedFrame) -> None:
        """Wrap a native artifact returned by frame, crop or read_from."""
        self._handle = handle

    @property
    def info(self) -> FrameInfo:
        """Return measured time, pixel coordinates and PNG integrity metadata."""
        return FrameInfo.model_validate_json(self._handle.info())

    @property
    def png(self) -> bytes:
        """Copy encoded PNG bytes; binary size is separate from text read budgets."""
        return self._handle.png()

    async def write_to(self, archive: Archive) -> FrameArchiveRef:
        """Store verified PNG evidence using the existing Rust Archive backend."""
        return FrameArchiveRef.model_validate_json(
            await self._handle.write_to(archive._handle)
        )

    @classmethod
    async def read_from(cls, archive: Archive, reference: FrameArchiveRef) -> Self:
        """Verify and restore saved PNG pixels without FFmpeg or the original file."""
        _require_video()
        return cls(
            await _native.DecodedFrame.read_from(
                archive._handle, reference.model_dump_json()
            )
        )


class VideoSurface:
    """Frozen local video with a lazy timeline and read-only frame capabilities.

    Open with await VideoSurface.open(path). No OCR, audio transcription, playback,
    live-stream subscription or control is provided. Cancelling the Python await
    leaves Rust finishing bounded cleanup in the background. Snapshot resources
    are released when the owning handle is dropped.
    """

    def __init__(self, handle: _native.VideoSurface) -> None:
        """Wrap a Rust-owned snapshot returned by open or read_from."""
        self._handle = handle

    @classmethod
    async def open(cls, path: str | Path, policy: VideoPolicy | None = None) -> Self:
        """Snapshot and probe a regular local file; failures raise VideoError.

        Requires FFmpeg and FFprobe on PATH or YOSOI_FFMPEG/YOSOI_FFPROBE.
        The original file can be removed once this returns successfully.
        """
        _require_video()
        return cls(
            await _native.VideoSurface.open(
                Path(path), (policy or VideoPolicy()).model_dump_json()
            )
        )

    @property
    def descriptor(self) -> Descriptor:
        """Return read/frame capabilities with controllable false."""
        return Descriptor.model_validate_json(self._handle.descriptor())

    @property
    def observation(self) -> Observation:
        """Return frozen source and decoder-profile interpretation identity."""
        return Observation.model_validate_json(self._handle.observation())

    @property
    def root_reference(self) -> Reference:
        """Return the complete visual timeline scope."""
        return Reference.model_validate_json(self._handle.root_reference())

    @property
    def metadata(self) -> VideoMetadata:
        """Return original video dimensions and primary stream timing."""
        return VideoMetadata.model_validate_json(self._handle.metadata())

    @property
    def policy(self) -> VideoPolicy:
        """Return the processing bounds retained by this observation."""
        return VideoPolicy.model_validate_json(self._handle.policy())

    def read(self, request: ReadRequest) -> ReadResult:
        """Read timeline evidence; search and parent are unsupported."""
        return _RESULT.validate_json(self._handle.read(request.model_dump_json()))

    def at(self, position_us: int) -> Reference:
        """Address stream-relative time for decoding the first frame at or after it."""
        return Reference.model_validate_json(self._handle.at(position_us))

    async def frame(self, reference: Reference) -> DecodedFrame:
        """Decode one frame; the final-frame tail may have no frame at or after it."""
        return DecodedFrame(await self._handle.frame(reference.model_dump_json()))

    async def crop(self, reference: Reference, rect: PixelRect) -> DecodedFrame:
        """Decode/crop a full-frame reference in decoded-canvas coordinates."""
        return DecodedFrame(
            await self._handle.crop(reference.model_dump_json(), rect.model_dump_json())
        )

    async def write_to(self, archive: Archive) -> VideoArchiveRef:
        """Archive the frozen source and interpretation without live authority."""
        return VideoArchiveRef.model_validate_json(
            await self._handle.write_to(archive._handle)
        )

    @classmethod
    async def read_from(cls, archive: Archive, reference: VideoArchiveRef) -> Self:
        """Restore a timeline without probing; new frame decoding still needs FFmpeg."""
        _require_video()
        return cls(
            await _native.VideoSurface.read_from(
                archive._handle, reference.model_dump_json()
            )
        )


ArchivePolicy = Literal["off", "enabled"]
"""Whether a session retains a bounded portable outcome for explicit Archive saving."""


class ArchiveLimits(ImmutableModel):
    """Retention bounds separate from live history and response budgets."""

    bytes: int = Field(
        default=64 * 1024 * 1024,
        strict=True,
        ge=1,
        le=128 * 1024 * 1024,
        description="Combined original evidence byte limit.",
    )
    observations: int = Field(
        default=256,
        strict=True,
        ge=1,
        le=4096,
        description="Maximum retained sources and artifacts.",
    )
    operations: int = Field(
        default=4096,
        strict=True,
        ge=1,
        le=4096,
        description="Maximum retained receipts.",
    )


class SourceInterpretation(ImmutableModel):
    """Interpreter for an exact document, image or named observation bundle."""

    kind: Literal[
        "document",
        "image",
        "image_document",
        "pixel_artifact",
        "file_document",
        "bundle",
    ] = Field(default="document", description="Interpreter category.")
    tile_side: int | None = Field(
        default=None,
        strict=True,
        ge=0,
        le=2**32 - 1,
        description="Original image tile size, used only for images.",
    )

    @model_validator(mode="after")
    def _interpretation(self) -> Self:
        is_image = self.kind in ("image", "image_document", "pixel_artifact")
        if is_image != (self.tile_side is not None):
            raise ValueError("only image interpretations require tile_side")
        return self

    @model_serializer(mode="plain")
    def _wire(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            **(
                {"tile_side": self.tile_side}
                if self.kind in ("image", "image_document", "pixel_artifact")
                else {}
            ),
        }


class ArchivedSource(ImmutableModel):
    """Exact source bytes and interpretation, independent of a source file path."""

    key: StrictStr = Field(description="Unique outcome-local source key.")
    document: DocumentId = Field(description="Original SDK document identity.")
    profile: DocumentProfile | None = Field(
        default=None, description="Document profile, absent for typed images."
    )
    file_kind: Literal["image", "video", "audio", "binary"] | None = Field(
        default=None, description="Concrete typed media family, absent for Documents."
    )
    file_metadata: FileMetadata | None = Field(
        default=None, description="Typed media provenance, absent for Documents."
    )
    pixel_info: PixelArtifactInfo | None = Field(
        default=None,
        description="Pixel provenance when this source is a PixelArtifact.",
    )
    sha256: StrictStr = Field(description="SHA-256 of decoded original bytes.")
    content_base64: StrictStr | None = Field(
        default=None, description="Inline payload for portable or hydrated outcomes."
    )
    document_archive: _ArchiveDocument | None = Field(
        default=None, description="Archive dependency in a stored Outcome record."
    )
    file_archive: _ArchiveFileDocument | None = Field(
        default=None, description="Typed media dependency in a stored Outcome record."
    )
    surface: StrictStr | None = Field(
        default=None,
        description="Prepared identity; absent for raw evidence envelopes.",
    )
    interpretation: SourceInterpretation = Field(
        default_factory=SourceInterpretation,
        description="Interpreter used for restoring this source.",
    )

    @classmethod
    def from_document(
        cls, key: str, document: Document, surface: Surface | None = None
    ) -> Self:
        """Freeze exact document bytes and optionally bind a prepared interpretation."""
        return cls.model_validate_json(
            _native.surface_source_new(
                key, document._handle, None if surface is None else surface._handle
            )
        )

    @classmethod
    def from_file_document(
        cls,
        key: str,
        document: FileDocument,
        surface: Surface | None = None,
    ) -> Self:
        """Freeze typed media bytes and provenance without a text profile."""
        return cls.model_validate_json(
            _native.surface_source_file_document(
                key,
                document._handle,
                None if surface is None else surface._handle,
            )
        )

    @classmethod
    def from_pixel_artifact(
        cls,
        key: str,
        artifact: PixelArtifact,
        *,
        tile_side: int = 256,
        surface: ImageSurface | None = None,
    ) -> Self:
        """Freeze pixel provenance for an ImageSurface Outcome source."""
        if not hasattr(_native, "surface_source_pixel_artifact"):
            raise SurfaceError("this wheel has no image support")
        return cls.model_validate_json(
            _native.surface_source_pixel_artifact(
                key,
                artifact._handle,
                tile_side,
                None if surface is None else surface._handle,
            )
        )

    @classmethod
    def capture(cls, key: str, surface: Surface) -> Self:
        """Retain a prepared document, image or bundle with its exact identity."""
        return cls.model_validate_json(
            _native.surface_source_capture(key, surface._handle)
        )

    def restore(self, maximum: int = 64 * 1024 * 1024) -> Document:
        """Verify and restore original bytes within a byte limit, without source I/O."""
        return Document._from_native(
            _native.surface_source_restore(_rust_json(self), maximum)
        )

    def restore_image(self, maximum: int = 64 * 1024 * 1024) -> ImageDocument:
        """Restore a typed image without assigning it a text Document profile."""
        return ImageDocument._from_native(
            _native.surface_source_restore_image(_rust_json(self), maximum)
        )

    def restore_file_document(self, maximum: int = 64 * 1024 * 1024) -> FileDocument:
        """Verify and restore a typed media payload without source I/O."""
        return ImageDocument._from_native(
            _native.surface_source_restore_file_document(_rust_json(self), maximum)
        )

    def restore_pixel_artifact(self, maximum: int = 64 * 1024 * 1024) -> PixelArtifact:
        """Restore source or derived pixels with their original provenance."""
        if not hasattr(_native, "PixelArtifact"):
            raise SurfaceError("this wheel has no image support")
        return PixelArtifact._from_native(
            _native.surface_source_restore_pixel_artifact(_rust_json(self), maximum)
        )

    def restore_surface(self, limits: Limits | None = None) -> Surface:
        """Restore immutable evidence and reject an interpretation identity mismatch."""
        return Surface._from_native(
            _native.surface_source_restore_surface(
                _rust_json(self), (limits or Limits()).model_dump_json()
            )
        )


class OutcomeRef(ImmutableModel):
    """Typed immutable reference selecting an outcome through Archive.read."""

    document: StrictStr = Field(description="Existing Archive Document reference.")
    version: int = Field(
        default=1,
        strict=True,
        ge=0,
        le=2**32 - 1,
        description="Logical version, checked for support during Archive.read.",
    )

    @field_validator("document")
    @classmethod
    def _reference(cls, value: str) -> str:
        return _native.validate_archive_ref("document", value)


class Outcome(ImmutableModel):
    """Portable evidence and receipts, without live session or action authority."""

    version: Literal[1] = Field(
        default=1, description="Logical outcome schema version."
    )
    record: AutomationRecord = Field(
        description="Ordered original operation certainty and observations."
    )
    sources: tuple[ArchivedSource, ...] = Field(
        default=(), description="Retained original sources and materialized evidence."
    )
    plans: tuple[Plan, ...] = Field(
        default=(), description="Existing compiled locator Plans."
    )
    sealed: StrictBool = Field(
        default=False,
        description="Logical finalization observed; caller owns provider cleanup.",
    )
    complete: StrictBool = Field(
        default=True, description="All evidence requested by policy was retained."
    )
    limits: ArchiveLimits = Field(
        default_factory=ArchiveLimits, description="Limits governing this outcome."
    )

    @classmethod
    def new(cls, id: str, limits: ArchiveLimits | None = None) -> Self:
        """Start a bounded outcome for an adapter-managed execution."""
        return cls.model_validate_json(
            _native.surface_outcome_new(
                id, (limits or ArchiveLimits()).model_dump_json()
            )
        )

    def with_source(self, source: ArchivedSource) -> Self:
        """Return a validated copy retaining one exact source.

        Sealed, conflicting, corrupt or excessive input raises SurfaceError.
        This immutable original remains unchanged when validation fails.
        """
        return type(self).model_validate_json(
            _native.surface_outcome_with_source(_rust_json(self), _rust_json(source))
        )

    def validate_outcome(self) -> None:
        """Check schema, record, source integrity, limits and compiled Plans in Rust."""
        _native.surface_outcome_validate(_rust_json(self))

    @field_validator("plans", mode="before")
    @classmethod
    def _plans(cls, value: object) -> object:
        if isinstance(value, (tuple, list)):
            return tuple(
                item if isinstance(item, Plan) else Plan.from_compiled(item)
                for item in value
            )
        return value

    @field_serializer("plans")
    def _compiled_plans(self, value: tuple[Plan, ...]) -> list[dict[str, object]]:
        return [plan.compiled() for plan in value]

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _native.surface_outcome_validate(_rust_json(self))
        return self

    def surface(self, key: str, limits: Limits | None = None) -> Surface:
        """Restore immutable evidence without opening a browser or granting control."""
        return Surface._from_native(
            _native.surface_outcome_restore(
                _rust_json(self), key, (limits or Limits()).model_dump_json()
            )
        )

    def source_document(self, key: str, maximum: int = 64 * 1024 * 1024) -> Document:
        """Restore a retained source Document by stable key."""
        return Document._from_native(
            _native.surface_outcome_source_document(_rust_json(self), key, maximum)
        )

    def source_file_document(
        self, key: str, maximum: int = 64 * 1024 * 1024
    ) -> FileDocument:
        """Restore a retained typed media file by stable key."""
        return ImageDocument._from_native(
            _native.surface_outcome_source_file_document(_rust_json(self), key, maximum)
        )

    def source_pixel_artifact(
        self, key: str, maximum: int = 64 * 1024 * 1024
    ) -> PixelArtifact:
        """Restore source or derived pixels retained under a stable key."""
        if not hasattr(_native, "PixelArtifact"):
            raise SurfaceError("this wheel has no image support")
        return PixelArtifact._from_native(
            _native.surface_outcome_source_pixel_artifact(
                _rust_json(self), key, maximum
            )
        )

    def network_payload(
        self,
        reference: NetworkPayloadRef,
        maximum: int = 64 * 1024 * 1024,
    ) -> NetworkPayload:
        """Resolve one frozen response-body link from an offline Outcome."""
        if not isinstance(reference, NetworkPayloadRef):
            raise TypeError("reference must be a NetworkPayloadRef")
        belongs_to_outcome = False
        for source in self.sources:
            if (
                source.profile is None
                or source.profile.schema_profile != "yosoi_network_observation_v1"
            ):
                continue
            document = self.source_document(source.key, self.limits.bytes)
            window = NetworkWindow.model_validate_json(document.data)
            if reference in window.payloads:
                belongs_to_outcome = True
                break
        if not belongs_to_outcome:
            raise SurfaceError(
                "network payload reference is not retained by this Outcome"
            )
        if reference.state not in {"retained", "truncated"}:
            raise SurfaceError("network response body was not retained")
        if reference.document_id != reference.id:
            raise SurfaceError("network payload source key does not match its id")
        if reference.document_kind in {"html", "json"}:
            value: Document | FileDocument = self.source_document(reference.id, maximum)
            expected = (
                "source_html" if reference.document_kind == "html" else "source_json"
            )
            if value.document_class != expected:
                raise SurfaceError("network payload Document has the wrong profile")
            digest = hashlib.sha256(value.data).hexdigest()
        elif reference.document_kind == "file":
            value = self.source_file_document(reference.id, maximum)
            digest = value.sha256
        else:
            raise SurfaceError("retained network payload has no projection kind")
        if reference.sha256 != digest:
            raise SurfaceError(
                "network payload digest did not match the Outcome source"
            )
        return NetworkPayload(reference=reference, value=value)

    async def rerun(self, policy: SurfacePolicy, count: int = 1) -> tuple[Outcome, ...]:
        """Execute a supported recipe against fresh isolated live sessions.

        Requires complete, sealed evidence and enabled archive policy. Rust
        preflights supported operations before effects and resolves new targets
        uniquely with live eligibility checks. Each run returns separate evidence.
        Failed attempts remain in the selected policy output directory.
        """
        _require_browser()
        values = json.loads(
            await _native.surface_outcome_rerun(
                _rust_json(self), policy.model_dump_json(), count
            )
        )
        return tuple(Outcome.model_validate(value) for value in values)


def _require_browser() -> None:
    if not _native.surface_browser_enabled:
        raise SurfaceError("this wheel was built without browser surface support")


class SurfacePolicy(ImmutableModel):
    """Evidence retention and output bounds shared across source connections."""

    documents: DocumentPolicies = Field(
        default_factory=DocumentPolicies,
        description="Per-type document bytes, depth, nodes and response bytes.",
    )
    network_observation: NetworkObservationPolicy = Field(
        default_factory=NetworkObservationPolicy,
        description="Native event subscription, redaction, and optional body bounds.",
    )

    archive: ArchivePolicy = Field(
        default="off", description="Portable outcome retention, disabled by default."
    )
    archive_limits: ArchiveLimits = Field(
        default_factory=ArchiveLimits,
        description="Evidence limits independent of response budgets.",
    )
    archive_root: Path | None = Field(
        default=None,
        description="Durable checkpoint store; otherwise owned temporary storage.",
    )
    output: Path | None = Field(
        default=None,
        description="Durable trace directory; otherwise owned temporary files.",
    )


class SurfaceConnection:
    """Shared lifecycle for a source-specific browser or video connection.

    Use a source's open or consume factory, then await close or use async with.
    Cancellation stops waiting; it does not prove that a dispatched effect was
    undone.
    """

    def __init__(self, handle: _native.BrowserSurface | _native.VideoSession) -> None:
        """Wrap a native source connection; prefer its asynchronous factory."""
        self._handle = handle

    async def __aenter__(self) -> Self:
        """Keep source resources alive until context cleanup."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Await source cleanup even when the context body raises."""
        await self.close()

    async def ready(self) -> dict[str, object]:
        """Return capabilities and bounded initial evidence without granting control."""
        return json.loads(await self._handle.ready())

    async def execute(self, command: Mapping[str, object]) -> dict[str, object]:
        """Execute one bounded Surface command through the source implementation.

        Use serialized references from current evidence. Browser effects require
        live attachment, hot ownership and eligibility. An error can follow a
        dispatched effect; inspect retained evidence before retrying.
        """
        return json.loads(await self._handle.execute(json.dumps(dict(command))))

    async def outcome(self) -> Outcome | None:
        """Snapshot retained evidence, including partial attempts, when enabled."""
        value = await self._handle.outcome()
        return None if value == "null" else Outcome.model_validate_json(value)

    async def close(self) -> Outcome | None:
        """Await source cleanup and final retention; repeated calls are harmless.

        Retained certainty and gaps remain available through outcome on failure.
        """
        value = await self._handle.close()
        return None if value == "null" else Outcome.model_validate_json(value)


class BrowserObservation(ImmutableModel):
    """Exact browser evidence identity, capabilities, coverage and root address."""

    descriptor: Descriptor = Field(description="Read capabilities and representation.")
    observation: Observation = Field(description="Immutable identity and coverage.")
    root: Reference = Field(description="Producer-issued root evidence address.")


class BrowserSurface(SurfaceConnection):
    """A live browser surface opened alone or bound to managed browser Work."""

    async def subscribe_network(
        self, *, retain_bodies: bool | None = None
    ) -> NetworkSubscription:
        """Arm native Chrome request events on the consumed Session tab.

        Network capture is opt-in. URL query strings and paths, headers, and
        response bodies follow ``SurfacePolicy.network_observation``. Body
        retention defaults off. Isolated ChromeDriver and BiDi providers return
        an explicit unsupported-capability error.
        """
        command: dict[str, object] = {"op": "network_subscribe"}
        if retain_bodies is not None:
            command["retain_bodies"] = retain_bodies
        return NetworkSubscription.model_validate(await self.execute(command))

    async def cancel_network(self) -> dict[str, object]:
        """Cancel the active native network subscription and release its listeners."""
        return await self.execute({"op": "network_cancel"})

    async def wait_network_event(
        self, after_sequence: int = 0, timeout_ms: int = 5000
    ) -> dict[str, object]:
        """Wait for a provider event without polling or sleeping for readiness."""
        return await self.execute(
            {
                "op": "network_wait",
                "after_sequence": after_sequence,
                "timeout_ms": timeout_ms,
            }
        )

    async def network_payload(
        self,
        reference: NetworkPayloadRef,
        *,
        chunk_bytes: int = 8192,
    ) -> NetworkPayload:
        """Read one live retained response as an existing Document or FileDocument.

        A truncated body keeps its explicit state in ``reference``. Resolve an
        archived payload through ``Outcome.network_payload`` after closing the
        browser connection.
        """
        if not isinstance(reference, NetworkPayloadRef):
            raise TypeError("reference must be a NetworkPayloadRef")
        if reference.state not in {"retained", "truncated"}:
            raise SurfaceError("network response body was not retained")
        if not 1 <= chunk_bytes <= 32768:
            raise ValueError("chunk_bytes must be between 1 and 32768")
        offset = 0
        chunks: list[bytes] = []
        total_bytes: int | None = None
        while total_bytes is None or offset < total_bytes:
            reply = await self.execute(
                {
                    "op": "network_payload",
                    "reference": reference.model_dump(mode="json"),
                    "offset": offset,
                    "max_bytes": chunk_bytes,
                    "budget": 65536,
                }
            )
            current_total = reply.get("total_bytes")
            current_offset = reply.get("offset")
            encoded = reply.get("data_base64")
            if not isinstance(current_total, int) or not isinstance(
                current_offset, int
            ):
                raise SurfaceError("network payload reply omitted byte bounds")
            if current_offset != offset or not isinstance(encoded, str):
                raise SurfaceError("network payload reply has an invalid chunk")
            if total_bytes is not None and total_bytes != current_total:
                raise SurfaceError("network payload length changed during read")
            total_bytes = current_total
            try:
                chunk = base64.b64decode(encoded, validate=True)
            except ValueError as error:
                raise SurfaceError(
                    "network payload chunk was not valid base64"
                ) from error
            if not chunk and offset < total_bytes:
                raise SurfaceError("network payload read made no progress")
            chunks.append(chunk)
            offset += len(chunk)
            if offset > total_bytes:
                raise SurfaceError("network payload exceeded its declared length")
        content = b"".join(chunks)
        if (
            reference.sha256 is not None
            and hashlib.sha256(content).hexdigest() != reference.sha256
        ):
            raise SurfaceError(
                "network payload digest did not match its response reference"
            )
        document_id = reference.document_id or reference.id
        if reference.document_kind == "html":
            value: Document | FileDocument = Document.html(document_id, content)
        elif reference.document_kind == "json":
            value = Document.from_json(document_id, content)
        else:
            metadata = FileMetadata(
                declared_media_type=reference.declared_media_type,
                source=f"native network response {reference.request_id}",
                capture_id=reference.request_id,
            )
            value = file_from_bytes(
                document_id,
                content,
                metadata=metadata,
                limits=FileLimits(max_bytes=max(1, len(content))),
            )
        return NetworkPayload(reference=reference, value=value)

    async def read_network_payload(
        self,
        reference: NetworkPayloadRef,
        *,
        chunk_bytes: int = 8192,
    ) -> NetworkPayload:
        """Alias for :meth:`network_payload` with explicit read wording."""
        return await self.network_payload(reference, chunk_bytes=chunk_bytes)

    async def observe(
        self, representation: BrowserRepresentation
    ) -> BrowserObservation:
        """Capture fresh evidence without acquiring live action authority.

        Native Session bindings support depth-limited AX. The isolated provider
        supports DOM only; unsupported representations raise ExecutionError.
        Views are captured sequentially. Replacing a view invalidates its previous
        addresses.
        """
        return BrowserObservation.model_validate(
            await self.execute({"op": "observe", "representation": representation})
        )

    async def observe_network(self) -> tuple[BrowserObservation, NetworkWindow]:
        """Freeze the native network interval and read its typed contract."""
        observation = await self.observe("network")
        request = ReadRequest(
            operation=Inspect(reference=observation.root),
            budget=Budget(bytes=65280, items=100),
        )
        chunks: list[str] = []
        while True:
            result = await self.read("network", request)
            if not isinstance(result, InspectionResult):
                raise SurfaceError("network root read returned a non-inspection result")
            chunks.append(result.data.content)
            if result.data.next is None:
                break
            request = request.model_copy(update={"continuation": result.data.next})
        window = NetworkWindow.model_validate_json("".join(chunks))
        return observation, window

    async def read(
        self, representation: BrowserRepresentation, request: ReadRequest
    ) -> ReadResult:
        """Read observed evidence under both caller and per-type policy bounds.

        Results are capped at 65280 bytes by the connection envelope. AX and
        network references do not grant live DOM targeting authority.
        """
        request = request.model_copy(
            update={
                "budget": request.budget.model_copy(
                    update={"bytes": min(request.budget.bytes, 65280)}
                )
            }
        )
        return _RESULT.validate_python(
            await self.execute(
                {
                    "op": "read_view",
                    "representation": representation,
                    "budget": max(1024, request.budget.bytes + 256),
                    "request": request.model_dump(mode="json"),
                }
            )
        )

    @classmethod
    async def open(
        cls, url: str, policy: SurfacePolicy | None = None, headless: bool = True
    ) -> Self:
        """Open a supported regular browser, initially detached from live authority."""
        _require_browser()
        return cls(
            await _native.BrowserSurface.open(
                url, (policy or SurfacePolicy()).model_dump_json(), headless
            )
        )

    @classmethod
    async def consume_session(
        cls,
        session: _browser.Session,
        policy: SurfacePolicy | None = None,
    ) -> Self:
        """Bind a Surface connection to a managed Session's initial tab.

        This clones the retained native Session owner under its state guard and
        acquires the initial tab's Work lease. The returned connection releases
        that Work lease on close; it does not close the Session or tab. Keep the
        original Session open while the connection is in use. If Work for the
        initial tab is already held, acquire the connection from that Work with
        :meth:`consume_work` instead of requesting a second controller.

        Args:
            session: Entered managed browser Session whose initial tab is selected.
            policy: Surface capture and retention policy; browser launch policy is
                inherited from the existing Session.

        Returns:
            A Surface connection over the existing tab and Session scheduler.

        Raises:
            TypeError: `session` is not a Yosoi browser Session.
            BrowserError: The Session is not entered, closed, or its native state
                is busy.
            ExecutionError: Initial-tab Work cannot be acquired, or Surface binding
                or initial observation fails.
        """
        if not isinstance(session, _browser.Session):
            raise TypeError("session must be a Yosoi browser.Session")
        if session._handle is None:
            raise _browser.BrowserError("enter the browser Session before consuming it")
        _require_browser()
        handle = await _native.surface_browser_consume_session(
            session._handle, (policy or SurfacePolicy()).model_dump_json()
        )
        return cls(handle)

    @classmethod
    async def consume_work(
        cls,
        work: _browser.Work,
        policy: SurfacePolicy | None = None,
    ) -> Self:
        """Transfer one selected Work lease into a Surface connection.

        The Work wrapper becomes released after the native lease is taken. Closing
        this connection releases Work but leaves its owning Session and tab open.
        A failed transfer before the native take leaves Work usable; a failure
        afterward consumes it because its controller has moved.

        Args:
            work: Yosoi Work lease for the tab to bind. The lease is consumed on
                successful native transfer.
            policy: Surface capture and retention policy; browser policy remains
                bound to the Work's owning Session.

        Returns:
            A Surface connection using the transferred exclusive Work lease.

        Raises:
            TypeError: `work` is not a Yosoi browser Work lease.
            BrowserError: The Work lease is unavailable or already released.
            ExecutionError: Surface binding or initial observation fails. Work
                remains consumed if native transfer already took place.
        """
        if not isinstance(work, _browser.Work):
            raise TypeError("work must be a Yosoi browser.Work")
        _require_browser()
        policy_json = (policy or SurfacePolicy()).model_dump_json()
        async with work._operation_lock:
            if work._released or work._release_task is not None:
                raise _browser.BrowserError("browser Work lease has been released")
            await work._acquire()
            native_work = work._handle
            if native_work is None:
                raise _browser.BrowserError("browser Work lease is unavailable")
            try:
                handle = await _native.surface_browser_consume_work(
                    native_work, policy_json
                )
            finally:
                if native_work.released:
                    if work._handle is native_work:
                        work._handle = None
                    work._released = True
                    work._release_task = None
        return cls(handle)


async def consume_session(
    session: _browser.Session,
    policy: SurfacePolicy | None = None,
) -> BrowserSurface:
    """Bind a Surface connection to the initial tab of a managed browser Session.

    This is the module-level spelling of ``BrowserSurface.consume_session``.
    The Session remains caller-owned and must remain open while the connection
    is active.

    Args:
        session: Entered managed browser Session whose initial tab is selected.
        policy: Surface capture and retention policy; browser policy is inherited.

    Returns:
        A Surface connection using the existing Session scheduler.

    Raises:
        TypeError: `session` is not a Yosoi browser Session.
        BrowserError: The Session is not entered, closed, or its native state is busy.
        ExecutionError: Initial-tab Work cannot be acquired, or Surface binding
            or initial observation fails.
    """
    return await BrowserSurface.consume_session(session, policy)


class VideoSession(SurfaceConnection):
    """Read-only stateful exploration around a frozen VideoSurface."""

    @classmethod
    async def open(
        cls, path: str | Path, policy: SurfacePolicy | None = None, max_side: int = 1920
    ) -> Self:
        """Freeze local video and open a detached reader with bounded frame pixels."""
        _require_video()
        return cls(
            await _native.VideoSession.open(
                str(path), (policy or SurfacePolicy()).model_dump_json(), max_side
            )
        )


async def rerun_browser(
    outcome: Outcome,
    policy: SurfacePolicy,
    count: int = 1,
    headless: bool = True,
) -> tuple[Outcome, ...]:
    """Rerun a sealed browser recipe with explicit source display selection.

    Each iteration resolves fresh references and retains its own outcome.
    Errors preserve partial evidence; they never imply rollback of dispatched effects.
    """
    _require_browser()
    values = json.loads(
        await _native.surface_browser_rerun(
            _rust_json(outcome), policy.model_dump_json(), count, headless
        )
    )
    return tuple(Outcome.model_validate(value) for value in values)


async def replay(
    path: str | Path,
    repeat: int = 1,
    query: str | None = None,
    output: str | Path | None = None,
) -> dict[str, object]:
    """Reconstruct a saved handle or portable file without live source processes.

    Materialized video pixels need no decoder. Incomplete outcomes are rejected.
    """
    if not _native.surface_archive_enabled:
        raise SurfaceError("this wheel was built without Surface archive replay")
    return json.loads(
        await _native.surface_replay(
            str(path), repeat, query, None if output is None else str(output)
        )
    )


async def export(path: str | Path, output: str | Path) -> None:
    """Package a saved handle into one immutable portable flat file through Rust."""
    if not _native.surface_archive_enabled:
        raise SurfaceError("this wheel was built without Surface archive export")
    await _native.surface_export(str(path), str(output))


class SessionPolicy(ImmutableModel):
    """Bounds for in-memory readers, subscriptions, history and one hot owner."""

    archive: ArchivePolicy = Field(
        default="off", description="Explicit evidence retention for Archive saving."
    )
    archive_limits: ArchiveLimits = Field(
        default_factory=ArchiveLimits,
        description="Portable outcome bounds independent of live history.",
    )

    cursors: int = Field(
        default=1, strict=True, ge=0, description="Logical cursor cap."
    )
    watches: int = Field(
        default=8, strict=True, ge=0, description="Total region watch cap."
    )
    captures: int = Field(
        default=2, strict=True, ge=0, description="Retained capture count."
    )
    events: int = Field(
        default=128, strict=True, ge=0, description="Event history capacity."
    )


Freshness = Literal["Unfocused", "Current", "Stale", "Evicted", "Unknown"]
"""Evidence status relative to the session, independent of action eligibility."""
EventKind = Literal[
    "Published",
    "Stale",
    "Changed",
    "Unchanged",
    "Unknown",
    "Detached",
    "ActionFinished",
]
"""Observed session transition; application memory is outside this evidence."""
ActionStatus = Literal["Rejected", "Confirmed", "Unconfirmed"]
"""Adapter-reported outcome, kept distinct from whether dispatch occurred."""


class Position(ImmutableModel):
    """Saved navigation state without granting live access or control."""

    scope: NativeReference | None = Field(default=None, description="Expanded region.")
    focus: NativeReference | None = Field(
        default=None, description="Selected evidence."
    )
    continuation: Continuation | None = Field(
        default=None, description="Saved read position."
    )


class WatchState(ImmutableModel):
    """One explicit subscription to captured regional evidence."""

    id: WatchId = Field(description="Session-local watch identity.")
    reference: NativeReference = Field(description="Last reconciled captured region.")
    needs_reconciliation: StrictBool = Field(
        description="Whether a new capture needs comparison."
    )


class CursorState(ImmutableModel):
    """Observable cursor status, never a transferable control capability."""

    id: CursorId = Field(description="Session-local cursor identity.")
    live: StrictBool = Field(
        description="Whether the adapter has attached the session."
    )
    hot: StrictBool = Field(description="Whether this cursor owns action authority.")
    current_capture: StrictStr = Field(
        description="Current immutable capture identity."
    )
    position: Position = Field(description="Saved region and focus.")
    focus_freshness: Freshness = Field(
        description="Focus status against current evidence."
    )
    scope_freshness: Freshness = Field(
        description="Scope status against current evidence."
    )
    subscriptions: tuple[WatchState, ...] = Field(
        description="This cursor's bounded watches."
    )
    action_in_flight: StrictBool = Field(
        description="Whether this cursor has a pending lease."
    )


class Event(ImmutableModel):
    """One retained event with optional cursor, watch and reference provenance."""

    sequence: int = Field(description="Monotonic session-local sequence.")
    kind: EventKind = Field(description="Transition category.")
    cursor: int | None = Field(description="Affected cursor identity, if any.")
    watch: int | None = Field(description="Affected subscription identity, if any.")
    before: NativeReference | None = Field(
        description="Previous evidence, if available."
    )
    after: NativeReference | None = Field(
        description="Replacement evidence, if available."
    )
    note: StrictStr = Field(description="Recorded explanation of this transition.")


class EventBatch(ImmutableModel):
    """Unread bounded session history with an explicit missed-events flag."""

    events: tuple[Event, ...] = Field(
        description="Retained events since the last read."
    )
    lost: StrictBool = Field(description="Whether older unread events were evicted.")


class ActionReceipt(ImmutableModel):
    """Adapter-reported outcome preserving dispatch uncertainty separately."""

    cursor: int = Field(description="Cursor that owned the lease.")
    target: NativeReference = Field(description="Exact pre-dispatch target evidence.")
    dispatched: StrictBool = Field(description="Whether the adapter marked dispatch.")
    status: ActionStatus = Field(description="Reported postcondition or uncertainty.")
    after_capture: StrictStr | None = Field(
        description="Current capture when finished."
    )
    note: StrictStr = Field(description="Adapter's explanation of the result.")


class Session:
    """In-memory evidence session for an external live adapter.

    Args:
        index: Initial immutable evidence.
        policy: Reader, history and event bounds, defaulting to one cursor.

    Attaching declares that the adapter is observing its source. This class does
    not launch a browser, install a DOM observer or dispatch actions by itself.
    """

    def __init__(self, index: Surface, policy: SessionPolicy | None = None) -> None:
        """Create detached state with no action authority."""
        self._handle = _native.SurfaceSession(
            index._handle, (policy or SessionPolicy()).model_dump_json()
        )

    def cursor(self) -> Cursor:
        """Allocate a reader within policy; Rust rejects capacity exhaustion."""
        return Cursor(self._handle.cursor())

    def attach(self) -> None:
        """Declare the external observer live, without promoting any cursor."""
        self._handle.attach()

    def detach(self) -> None:
        """Detach observation and revoke hot authority and pending leases."""
        self._handle.detach()

    def invalidate(self, reason: str) -> None:
        """Mark observation uncertain until an adapter publishes fresh evidence."""
        self._handle.invalidate(reason)

    def publish(self, index: Surface) -> None:
        """Publish a new immutable capture, invalidating stale focused evidence."""
        self._handle.publish(index._handle)

    def outcome(self) -> Outcome | None:
        """Snapshot retained evidence, or return None when archive policy is off."""
        value = self._handle.outcome()
        return None if value == "null" else Outcome.model_validate_json(value)

    def close(self) -> Outcome | None:
        """Close logical readers and return the final policy outcome.

        This revokes authority and preserves pending effects as unknown. External
        provider cleanup remains caller-owned. Repeated calls return the same data.
        """
        value = self._handle.close()
        return None if value == "null" else Outcome.model_validate_json(value)

    @property
    def current(self) -> Surface:
        """Return an immutable index safe to retain after subsequent publication."""
        return Surface._from_native(self._handle.current())

    @property
    def hot_owner(self) -> int | None:
        """Return the single hot cursor identity, or None."""
        return self._handle.hot_owner()


class Cursor:
    """Owned navigation cursor. Close it to release watches and hot authority."""

    def __init__(self, handle: _native.SurfaceCursor) -> None:
        """Wrap a cursor allocated by Session.cursor."""
        self._handle = handle

    def __enter__(self) -> Self:
        """Use a cursor with deterministic cleanup."""
        return self

    def __exit__(self, *_: object) -> None:
        """Release this cursor even when the body raises."""
        try:
            self.close()
        except SurfaceError as error:
            # An explicit close in the body already released this logical cursor.
            if getattr(error, "variant", None) != "Unknown":
                raise

    @property
    def id(self) -> int:
        """Return a session-local diagnostic identity, without authority."""
        return self._handle.id()

    @property
    def status(self) -> CursorState:
        """Inspect attachment, authority, subscriptions and evidence freshness."""
        return CursorState.model_validate_json(self._handle.status())

    @property
    def position(self) -> Position:
        """Return the saved region, focus and continuation."""
        return Position.model_validate_json(self._handle.position())

    def _read(
        self,
        operation: str,
        reference: NativeReference | None = None,
        query: str = "",
        continuation: Continuation | None = None,
        budget: Budget | None = None,
    ) -> str:
        return self._handle.read(
            operation,
            reference.model_dump_json() if reference else None,
            query,
            continuation.model_dump_json() if continuation else None,
            (budget or Budget()).model_dump_json(),
        )

    def overview(
        self, *, continuation: Continuation | None = None, budget: Budget | None = None
    ) -> NativePage:
        """Read current evidence and save its navigation continuation."""
        return NativePage.model_validate_json(
            self._read("overview", continuation=continuation, budget=budget)
        )

    def find(
        self,
        query: str,
        *,
        continuation: Continuation | None = None,
        budget: Budget | None = None,
    ) -> NativePage:
        """Search current captured evidence without promoting the cursor."""
        return NativePage.model_validate_json(
            self._read("find", query=query, continuation=continuation, budget=budget)
        )

    def expand(
        self,
        reference: NativeReference,
        *,
        continuation: Continuation | None = None,
        budget: Budget | None = None,
    ) -> NativePage:
        """Drill into evidence and save scope without granting action authority."""
        return NativePage.model_validate_json(
            self._read("expand", reference, continuation=continuation, budget=budget)
        )

    def inspect(
        self,
        reference: NativeReference,
        *,
        continuation: Continuation | None = None,
        budget: Budget | None = None,
    ) -> NativeInspection:
        """Read exact captured detail and save focus, preserving its freshness."""
        return NativeInspection.model_validate_json(
            self._read("inspect", reference, continuation=continuation, budget=budget)
        )

    def focus(self, reference: NativeReference) -> None:
        """Select exact evidence; this does not prove current UI eligibility."""
        self._handle.focus(reference.model_dump_json())

    def subscribe(self, reference: NativeReference) -> int:
        """Watch a captured block; an adapter must publish and reconcile updates."""
        return self._handle.subscribe(reference.model_dump_json())

    def reconcile(self, watch: int, replacement: NativeReference) -> EventKind:
        """Compare replacement evidence without asserting durable entity identity."""
        return TypeAdapter(EventKind).validate_json(
            self._handle.reconcile(json.dumps(watch), replacement.model_dump_json())
        )

    def unsubscribe(self, watch: int) -> None:
        """Remove this cursor's subscription without moving its focus."""
        self._handle.unsubscribe(json.dumps(watch))

    def events(self) -> EventBatch:
        """Consume retained events; lost is true when unread history was evicted."""
        return EventBatch.model_validate_json(self._handle.events())

    def promote(self) -> None:
        """Acquire the single hot slot; detached or competing owners are rejected."""
        self._handle.promote()

    def cool(self) -> None:
        """Release hot authority; an in-flight action prevents unsafe handoff."""
        self._handle.cool()

    def begin_action(self) -> ActionLease:
        """Lease focus; the adapter still checks visibility and eligibility."""
        return ActionLease(self._handle.begin_action())

    def close(self) -> None:
        """Release owned cursor state; further cursor operations are rejected."""
        self._handle.close()


class ActionLease:
    """Owned one-action permit. Dropping or closing it preserves uncertain dispatch."""

    def __init__(self, handle: _native.SurfaceActionLease) -> None:
        """Wrap a Rust permit issued by a hot cursor."""
        self._handle = handle

    def __enter__(self) -> Self:
        """Keep the permit scoped to one adapter operation."""
        return self

    def __exit__(self, *_: object) -> None:
        """Release unfinished authority on exceptions, retaining an outcome event."""
        self.close()

    def revalidate(self) -> NativeReference:
        """Recheck live ownership and exact evidence immediately before dispatch."""
        return NativeReference.model_validate_json(self._handle.revalidate())

    def mark_dispatched(self) -> None:
        """Record that a native effect may have begun; this does not confirm success."""
        self._handle.mark_dispatched()

    def finish(self, status: ActionStatus, note: str) -> ActionReceipt:
        """Consume the permit with the adapter's observed outcome.

        Confirmed requires dispatch; Rejected is forbidden after dispatch. Rust
        rejects contradictory outcomes and preserves uncertainty when consumed.
        """
        return ActionReceipt.model_validate_json(
            self._handle.finish(json.dumps(status), note)
        )

    def close(self) -> None:
        """Release an unfinished permit; repeated close is harmless."""
        self._handle.close()
