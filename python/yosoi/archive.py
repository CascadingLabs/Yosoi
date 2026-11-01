"""Immutable local evidence storage backed by Rust's validated Archive format."""

from __future__ import annotations

import json
from collections.abc import Mapping
from os import PathLike, fspath
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal, Self, overload

from pydantic import (
    BeforeValidator,
    Field,
    PlainSerializer,
    StrictStr,
    field_validator,
    model_validator,
)

from . import _native
from ._models import ImmutableModel
from .browser import FlowOutcome, Observation, OperationReceipt, SessionPolicy
from .documents import (
    AudioDocument,
    BinaryDocument,
    Document,
    FileDocument,
    ImageDocument,
    VideoDocument,
    _FileDocument,
)
from .locators import Plan

if TYPE_CHECKING:
    from .surface import (
        Outcome,
        OutcomeRef,
        PixelArtifact,
    )

__all__ = [
    "Archive",
    "AutomationContext",
    "AutomationRecord",
    "AutomationRecordRef",
    "DocumentArchiveRef",
    "PixelArtifactArchiveRef",
    "FileDocumentArchiveRef",
    "ImageDocumentArchiveRef",
    "VideoDocumentArchiveRef",
    "AudioDocumentArchiveRef",
    "BinaryDocumentArchiveRef",
    "PlanArchiveRef",
]


def _rust_json(value: ImmutableModel) -> str:
    def wire(item: Any) -> Any:
        if isinstance(item, bytes):
            return list(item)
        if isinstance(item, Mapping):
            return {key: wire(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [wire(child) for child in item]
        return item

    return json.dumps(wire(value.model_dump(mode="python")))


class DocumentArchiveRef(ImmutableModel):
    """Immutable reference to one exact Document occurrence.

    Attributes:
        value: Rust-validated kind, format version and UUID reference.
    """

    value: StrictStr = Field(description="Rust-validated Document Archive reference.")

    @field_validator("value")
    @classmethod
    def _validate_reference(cls, value: str) -> str:
        return _native.validate_archive_ref("document", value)


_DocumentArchiveRefWire = Annotated[
    DocumentArchiveRef,
    BeforeValidator(
        lambda value: (
            DocumentArchiveRef(value=value) if isinstance(value, str) else value
        )
    ),
    PlainSerializer(lambda value: value.value, return_type=str),
]


class PixelArtifactArchiveRef(ImmutableModel):
    """Metadata Document selecting a typed raw image payload and pixel provenance."""

    document: _DocumentArchiveRefWire = Field(
        description="Existing Archive metadata Document reference."
    )


class _MediaDocumentArchiveRef(ImmutableModel):
    """Shared validation for references whose kind names one media document."""

    value: StrictStr = Field(
        description="Rust-validated typed media Archive reference."
    )
    _kind: ClassVar[str]

    @field_validator("value")
    @classmethod
    def _validate_reference(cls, value: str) -> str:
        try:
            return _native.validate_archive_ref(cls._kind, value)
        except _native.ArchiveError as error:
            raise ValueError(str(error)) from error


class ImageDocumentArchiveRef(_MediaDocumentArchiveRef):
    """Immutable typed reference to one archived image document."""

    _kind = "image_document"


class VideoDocumentArchiveRef(_MediaDocumentArchiveRef):
    """Immutable typed reference to one archived video document."""

    _kind = "video_document"


class AudioDocumentArchiveRef(_MediaDocumentArchiveRef):
    """Immutable typed reference to one archived audio document."""

    _kind = "audio_document"


class BinaryDocumentArchiveRef(_MediaDocumentArchiveRef):
    """Immutable typed reference to one archived opaque binary document."""

    _kind = "binary_document"


FileDocumentArchiveRef = (
    ImageDocumentArchiveRef
    | VideoDocumentArchiveRef
    | AudioDocumentArchiveRef
    | BinaryDocumentArchiveRef
)
"""Typed file-reference union; TypeAdapter restores its concrete kind from JSON."""


class PlanArchiveRef(ImmutableModel):
    """Immutable reference to one compiled locator Plan.

    Attributes:
        value: Rust-validated kind, format version and UUID reference.
    """

    value: StrictStr

    @field_validator("value")
    @classmethod
    def _validate_reference(cls, value: str) -> str:
        return _native.validate_archive_ref("plan", value)


class AutomationRecordRef(ImmutableModel):
    """Portable handle naming one immutable automation record Document.

    Attributes:
        version: Logical record version, validated during read.
        document: Exact immutable Document reference in the Rust wire format.
    """

    version: int = Field(strict=True, ge=1, le=2**32 - 1)
    document: StrictStr

    @field_validator("document")
    @classmethod
    def _validate_reference(cls, value: str) -> str:
        return _native.validate_archive_ref("document", value)


class AutomationContext(ImmutableModel):
    """Recorded provenance supplied by the application, without live authority.

    Attributes:
        effective_policy_identity: Resolved Policy identity recorded for the run.
        session_policy: Browser settings used by the owner.
        provider: Recorded browser provider label.
        browser_identity: Optional browser identity claimed by the caller.
        source_revision: Optional source revision claimed by the caller.
        parent: Optional immutable parent record reference.
    """

    effective_policy_identity: StrictStr
    session_policy: SessionPolicy
    provider: StrictStr
    browser_identity: StrictStr | None = None
    source_revision: StrictStr | None = None
    parent: AutomationRecordRef | None = None


class AutomationRecord(ImmutableModel):
    """Bounded observations and receipts validated by the Rust record contract.

    This stores evidence, not executable Python objects or resumed Sessions.
    Pydantic Contract instances are outside the portable Archive contract.

    Attributes:
        version: Logical record schema version.
        id: Application-authored record identity.
        observations: Captured evidence with original Session, tab and epoch.
        operations: Ordered operation receipts with effect certainty preserved.
        flow_outcome: Optional original Flow declaration and observed outcome.
        context: Optional application-supplied provenance.
    """

    version: Literal[1] = 1
    id: StrictStr
    observations: tuple[Observation, ...] = ()
    operations: tuple[OperationReceipt, ...] = ()
    flow_outcome: FlowOutcome | None = None
    context: AutomationContext | None = None

    @model_validator(mode="after")
    def _validate_record(self) -> Self:
        _native.validate_automation_record(_rust_json(self))
        return self

    @classmethod
    def from_flow(cls, id: str, outcome: FlowOutcome) -> Self:
        """Retain a Flow's receipts, cleanup, failure capture and unique observations.

        Rejected and unknown results remain intact. Inconsistent observations,
        unsupported outcomes and excessive evidence raise ArchiveError.
        """
        return cls.model_validate_json(
            _native.automation_record_from_flow(id, _rust_json(outcome))
        )


class Archive:
    """Local Unix Archive handle with no open files between operations.

    Use ``await Archive.open(path)``. No close method is needed: each asynchronous
    read or write owns its filesystem resources. Cancelling an await stops waiting;
    the Rust operation still settles, and a write may already have committed.
    A cancelled write returns no reference and can leave unreferenced data.
    """

    def __init__(self, handle: _native.Archive) -> None:
        """Wrap a native handle; applications should use Archive.open."""
        self._handle = handle

    @classmethod
    async def open(cls, root: str | PathLike[str]) -> Self:
        """Open or create an Archive root with private filesystem permissions.

        Raises:
            ArchiveError: Platform, path safety, permissions or filesystem I/O fails.
        """
        path = fspath(root)
        if not isinstance(path, str):
            raise TypeError("Archive root must be a text filesystem path")
        return cls(await _native.Archive.open(path))

    @property
    def root(self) -> Path:
        """Return the canonical absolute root without opening a file."""
        return Path(self._handle.root)

    @overload
    async def write(self, value: Document) -> DocumentArchiveRef: ...

    @overload
    async def write(self, value: ImageDocument) -> ImageDocumentArchiveRef: ...

    @overload
    async def write(self, value: VideoDocument) -> VideoDocumentArchiveRef: ...

    @overload
    async def write(self, value: AudioDocument) -> AudioDocumentArchiveRef: ...

    @overload
    async def write(self, value: BinaryDocument) -> BinaryDocumentArchiveRef: ...

    @overload
    async def write(
        self, value: FileDocument
    ) -> (
        ImageDocumentArchiveRef
        | VideoDocumentArchiveRef
        | AudioDocumentArchiveRef
        | BinaryDocumentArchiveRef
    ): ...

    @overload
    async def write(self, value: Plan) -> PlanArchiveRef: ...

    @overload
    async def write(self, value: AutomationRecord) -> AutomationRecordRef: ...

    @overload
    async def write(self, value: Outcome) -> OutcomeRef: ...

    @overload
    async def write(self, value: PixelArtifact) -> PixelArtifactArchiveRef: ...

    async def write(
        self,
        value: Document
        | FileDocument
        | Plan
        | AutomationRecord
        | Outcome
        | PixelArtifact,
    ) -> (
        DocumentArchiveRef
        | ImageDocumentArchiveRef
        | VideoDocumentArchiveRef
        | AudioDocumentArchiveRef
        | BinaryDocumentArchiveRef
        | PlanArchiveRef
        | AutomationRecordRef
        | OutcomeRef
        | PixelArtifactArchiveRef
    ):
        """Save a supported value and return a distinct immutable reference.

        Exact bytes, profiles, coordinates, file metadata and result certainty are
        retained.
        Unsupported application objects raise TypeError. Invalid evidence,
        excessive payloads and storage failures raise ArchiveError.
        """
        from .surface import Outcome, OutcomeRef, PixelArtifact

        if isinstance(value, PixelArtifact):
            return await value.write_to(self)

        if isinstance(value, Outcome):
            return OutcomeRef.model_validate_json(
                await self._handle.write_surface(_rust_json(value))
            )
        if isinstance(value, Document):
            return DocumentArchiveRef(
                value=await self._handle.write_document(value._handle)
            )
        if isinstance(value, _FileDocument):
            value._handle.validate_input(
                str(value.id), value._kind, value.metadata.model_dump_json()
            )
            kind, raw_reference = await self._handle.write_file_document(value._handle)
            reference_type = {
                "image": ImageDocumentArchiveRef,
                "video": VideoDocumentArchiveRef,
                "audio": AudioDocumentArchiveRef,
                "binary": BinaryDocumentArchiveRef,
            }.get(kind)
            if reference_type is None:
                raise _native.ArchiveError(f"unknown native file document kind: {kind}")
            return reference_type(value=raw_reference)
        if isinstance(value, Plan):
            return PlanArchiveRef(value=await self._handle.write_plan(value._handle))
        if isinstance(value, AutomationRecord):
            return AutomationRecordRef.model_validate_json(
                await self._handle.write_record(_rust_json(value))
            )
        raise TypeError(
            "Archive.write supports Document, media file documents, Plan, "
            "AutomationRecord, Outcome and PixelArtifact"
        )

    @overload
    async def read(self, reference: DocumentArchiveRef) -> Document: ...

    @overload
    async def read(self, reference: ImageDocumentArchiveRef) -> ImageDocument: ...

    @overload
    async def read(self, reference: VideoDocumentArchiveRef) -> VideoDocument: ...

    @overload
    async def read(self, reference: AudioDocumentArchiveRef) -> AudioDocument: ...

    @overload
    async def read(self, reference: BinaryDocumentArchiveRef) -> BinaryDocument: ...

    @overload
    async def read(self, reference: PlanArchiveRef) -> Plan: ...

    @overload
    async def read(self, reference: AutomationRecordRef) -> AutomationRecord: ...

    @overload
    async def read(self, reference: OutcomeRef) -> Outcome: ...

    @overload
    async def read(self, reference: PixelArtifactArchiveRef) -> PixelArtifact: ...

    async def read(
        self,
        reference: DocumentArchiveRef
        | ImageDocumentArchiveRef
        | VideoDocumentArchiveRef
        | AudioDocumentArchiveRef
        | BinaryDocumentArchiveRef
        | PlanArchiveRef
        | AutomationRecordRef
        | OutcomeRef
        | PixelArtifactArchiveRef,
    ) -> FileDocument | Document | Plan | AutomationRecord | Outcome | PixelArtifact:
        """Read exact saved evidence without launching a browser or fetching URLs.

        References can be serialized with model_dump_json and reconstructed with
        their class's model_validate_json. Missing or corrupt data and unsupported
        versions raise ArchiveError. A typed media reference restores the same concrete
        image, video, audio, or binary class. An unsupported reference type raises
        TypeError.
        """
        from .surface import Outcome, OutcomeRef, PixelArtifact

        if isinstance(reference, PixelArtifactArchiveRef):
            return await PixelArtifact.read_from(self, reference)

        if isinstance(reference, OutcomeRef):
            return Outcome.model_validate_json(
                await self._handle.read_surface(reference.model_dump_json())
            )
        if isinstance(reference, DocumentArchiveRef):
            return Document._from_native(
                await self._handle.read_document(reference.value)
            )
        file_reference_kinds = (
            (ImageDocumentArchiveRef, "image_document", ImageDocument),
            (VideoDocumentArchiveRef, "video_document", VideoDocument),
            (AudioDocumentArchiveRef, "audio_document", AudioDocument),
            (BinaryDocumentArchiveRef, "binary_document", BinaryDocument),
        )
        for reference_type, kind, document_type in file_reference_kinds:
            if isinstance(reference, reference_type):
                document = _FileDocument._from_native(
                    await self._handle.read_file_document(kind, reference.value)
                )
                if not isinstance(document, document_type):
                    raise _native.ArchiveError(
                        "archived file document kind does not match its typed reference"
                    )
                return document
        if isinstance(reference, PlanArchiveRef):
            return Plan.from_compiled(
                json.loads(await self._handle.read_plan(reference.value))
            )
        if isinstance(reference, AutomationRecordRef):
            return AutomationRecord.model_validate_json(
                await self._handle.read_record(reference.model_dump_json())
            )
        raise TypeError("Archive.read requires a typed Archive reference")

    async def export_file(
        self, reference: OutcomeRef, path: str | PathLike[str]
    ) -> None:
        """Export a Surface outcome as one immutable, self-contained file.

        The destination must not exist. Atomic publication requires hard links.
        A sync error can leave a complete destination; cancellation stops waiting,
        while native publication can finish. No unrelated Archive values are copied.
        """
        from .surface import OutcomeRef

        if not isinstance(reference, OutcomeRef):
            raise TypeError("export_file requires a Surface OutcomeRef")
        await self._handle.export_file(reference.model_dump_json(), fspath(path))

    async def import_file(self, path: str | PathLike[str]) -> OutcomeRef:
        """Validate and import one portable outcome without its original store.

        Version, size, digest and outcome checks precede persistence. Corruption
        raises ArchiveError. Import restores evidence and never action authority.
        """
        from .surface import OutcomeRef

        return OutcomeRef.model_validate_json(
            await self._handle.import_file(fspath(path))
        )
