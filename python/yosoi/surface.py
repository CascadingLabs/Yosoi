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

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self

from pydantic import (
    BeforeValidator,
    Field,
    PlainSerializer,
    StrictBool,
    StrictStr,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from . import _native
from ._models import ImmutableModel
from .archive import Archive, AutomationRecord, DocumentArchiveRef, _rust_json
from .documents import Document, DocumentProfile
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
        cls, content: bytes, tile_side: int = 256, limits: Limits | None = None
    ) -> Self:
        """Index PNG/JPEG pixels as bounded regions without OCR or EXIF rotation."""
        if not hasattr(_native.Surface, "from_image"):
            raise SurfaceError("this wheel has no image support")
        return cls._from_native(
            _native.Surface.from_image(
                content, tile_side, (limits or Limits()).model_dump_json()
            )
        )

    def crop(
        self, reference: NativeReference, max_png_bytes: int = 8388608
    ) -> ImageCrop:
        """Materialize an indexed image region; binary and text budgets are separate."""
        if not hasattr(self._handle, "crop"):
            raise SurfaceError("this wheel has no image support")
        info, png = self._handle.crop(reference.model_dump_json(), max_png_bytes)
        return ImageCrop(**json.loads(info), png=png)


class WebSurface:
    """Shared read protocol over immutable HTML, DOM, AX or network evidence.

    Args:
        index: Prepared document index; other document classes are rejected.
        source: Nonempty continuing-source identity, without browser authority.
        policy: Optional independent serialized response limits.
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
    """Crop in full decoded-frame pixels; source-video dimensions may differ."""

    x: int = Field(
        strict=True, ge=0, le=2**32 - 1, description="Left pixel coordinate."
    )
    y: int = Field(strict=True, ge=0, le=2**32 - 1, description="Top pixel coordinate.")
    width: int = Field(strict=True, ge=0, le=2**32 - 1, description="Crop pixel width.")
    height: int = Field(
        strict=True, ge=0, le=2**32 - 1, description="Crop pixel height."
    )


class ImageCrop(ImmutableModel):
    """Actual PNG evidence cropped from an indexed immutable image region."""

    reference: NativeReference = Field(description="Exact selected image evidence.")
    rect: PixelRect = Field(description="Bounds in original decoded image pixels.")
    png: bytes = Field(description="Encoded PNG bytes, independent of text budgets.")


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

    kind: Literal["document", "image", "bundle"] = Field(
        default="document", description="Interpreter category."
    )
    tile_side: int | None = Field(
        default=None,
        strict=True,
        ge=0,
        le=2**32 - 1,
        description="Original image tile size, used only for images.",
    )

    @model_validator(mode="after")
    def _interpretation(self) -> Self:
        if (self.kind == "image") != (self.tile_side is not None):
            raise ValueError("only image interpretations require tile_side")
        return self

    @model_serializer(mode="plain")
    def _wire(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            **({"tile_side": self.tile_side} if self.kind == "image" else {}),
        }


class ArchivedSource(ImmutableModel):
    """Exact source bytes and interpretation, independent of a source file path."""

    key: StrictStr = Field(description="Unique outcome-local source key.")
    document: DocumentId = Field(description="Original SDK document identity.")
    profile: DocumentProfile = Field(description="Exact document profile and epoch.")
    sha256: StrictStr = Field(description="SHA-256 of decoded original bytes.")
    content_base64: StrictStr = Field(description="Retained original bytes as base64.")
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

    Use a source's open factory, then await close or use async with. Cancellation
    stops waiting; it does not prove that a dispatched effect was undone.
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
    """An isolated live browser with source-specific actions and archive support."""

    async def observe(
        self, representation: BrowserRepresentation
    ) -> BrowserObservation:
        """Capture fresh evidence without acquiring live action authority.

        AX is native and depth-limited. Network covers a best-effort log window
        since session open or the last network observation. Views are captured
        sequentially. Replacing a view invalidates its previous addresses.
        """
        return BrowserObservation.model_validate(
            await self.execute({"op": "observe", "representation": representation})
        )

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
