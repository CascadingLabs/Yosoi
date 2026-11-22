"""Immutable image, video, audio, and binary payload ownership backed by Rust."""

from __future__ import annotations

import builtins
import json
from collections.abc import Mapping
from os import PathLike, fspath
from typing import Any, ClassVar, Literal, Self, cast

from pydantic import Field, PrivateAttr, StrictStr

from . import _native
from ._models import ImmutableModel
from .scalars import DocumentId

FileDocumentError = _native.FileDocumentError
"""Rust-native identity, metadata, media-signature, and file-size failure."""

DEFAULT_FILE_LIMIT_BYTES = 64 * 1024 * 1024
"""Default retained file payload limit in bytes."""
MAX_FILE_LIMIT_BYTES = 256 * 1024 * 1024
"""Absolute retained file payload limit in bytes."""
MAX_SOURCE_BYTES = 1_048_576
"""Maximum source provenance size in UTF-8 bytes, enforced by Rust."""
DEFAULT_FILE_MAX_BYTES = DEFAULT_FILE_LIMIT_BYTES
"""Rust-compatible alias for the default retained file payload limit."""
MAX_FILE_BYTES = MAX_FILE_LIMIT_BYTES
"""Rust-compatible alias for the absolute retained file payload limit."""


class FileLimits(ImmutableModel):
    """Byte bound for file reads and file-document construction.

    Attributes:
        max_bytes: Maximum exact payload size accepted by Rust. The default is 64 MiB
            and no value can exceed the 256 MiB SDK hard limit.
    """

    max_bytes: int = Field(
        default=DEFAULT_FILE_LIMIT_BYTES,
        strict=True,
        ge=0,
        le=MAX_FILE_LIMIT_BYTES,
        description="Maximum retained file bytes; at most 256 MiB.",
    )


class FileMetadata(ImmutableModel):
    """Declared and detected media information with capture provenance.

    Attributes:
        filename: Optional source filename; it is not a filesystem path guarantee.
        declared_media_type: Optional MIME value supplied by a source or caller. It is
            retained separately from format detection.
        detected_media_type: MIME value inferred from payload signatures when known.
        source: Optional description of the source or acquisition mechanism.
        capture_id: Optional originating capture identity.
        session_id: Optional browser Session identity for captured downloads.
        tab_id: Optional browser tab identity for captured downloads.
        download_id: Optional provider download identity.
        probe_validated_video_container: Container confirmed by FFprobe when a generic
            signature required decoder-side validation. The original detected MIME
            remains separate and may still be audio/ogg or absent.
        sha256: Lowercase SHA-256 hex digest of the exact payload, populated by Rust.
    """

    filename: StrictStr | None = Field(
        default=None,
        max_length=1024,
        description="Source filename, limited to 1 KiB of UTF-8 bytes by Rust.",
    )
    declared_media_type: StrictStr | None = Field(
        default=None,
        max_length=4096,
        description="Source-declared MIME type, if known; Rust enforces a 4 KiB bound.",
    )
    detected_media_type: StrictStr | None = Field(
        default=None,
        max_length=4096,
        description="MIME type inferred from retained payload bytes by Rust.",
    )
    source: StrictStr | None = Field(
        default=None,
        max_length=MAX_SOURCE_BYTES,
        description=(
            "Exact acquisition source or URL, bounded by Rust to 1 MiB of UTF-8 bytes."
        ),
    )
    capture_id: StrictStr | None = Field(
        default=None, max_length=4096, description="Originating capture ID."
    )
    session_id: StrictStr | None = Field(
        default=None, max_length=4096, description="Originating browser Session ID."
    )
    tab_id: StrictStr | None = Field(
        default=None, max_length=4096, description="Originating browser tab ID."
    )
    download_id: StrictStr | None = Field(
        default=None, max_length=4096, description="Provider download ID."
    )
    probe_validated_video_container: StrictStr | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        max_length=4096,
        description=(
            "FFprobe-confirmed self-contained container for signature-ambiguous video. "
            "Rust populates this field; caller-authored values are ignored by file "
            "constructors."
        ),
    )
    sha256: StrictStr | None = Field(
        default=None,
        max_length=64,
        description="Digest of exact payload bytes, computed by Rust.",
    )

    def _native_input(self) -> str:
        """Serialize caller-authored fields without detector or probe evidence."""
        return self.model_dump_json(
            exclude_none=True,
            exclude={
                "detected_media_type",
                "sha256",
                "probe_validated_video_container",
            },
        )

    def _with_value(self, field: str, value: str) -> Self:
        """Return a native-validated immutable copy with one field changed."""
        metadata_json = _native.file_metadata_with(
            self.model_dump_json(exclude_none=True), field, value
        )
        return type(self).model_validate_json(metadata_json)

    def with_filename(self, value: str) -> Self:
        """Return a copy with a caller-provided filename.

        Rust checks the UTF-8 byte bound while creating this copy.

        Args:
            value: Filename to retain.

        Returns:
            New metadata preserving all other fields.

        Raises:
            FileDocumentError: The filename exceeds the native UTF-8 byte bound.
        """
        return self._with_value("filename", value)

    def with_declared_media_type(self, value: str) -> Self:
        """Return a copy with a caller-declared MIME value.

        Args:
            value: MIME value to retain separately from detected type.

        Returns:
            New metadata preserving all other fields.

        Raises:
            FileDocumentError: The value exceeds the native UTF-8 byte bound.
        """
        return self._with_value("declared_media_type", value)

    def with_source(self, value: str) -> Self:
        """Return a copy with a source label.

        Args:
            value: Source or acquisition label to retain.

        Returns:
            New metadata preserving all other fields.

        Raises:
            FileDocumentError: The value exceeds the native UTF-8 byte bound.
        """
        return self._with_value("source", value)

    def with_capture_id(self, value: str) -> Self:
        """Return a copy with an originating capture identity.

        Args:
            value: Capture identity to retain.

        Returns:
            New metadata preserving all other fields.

        Raises:
            FileDocumentError: The value exceeds the native UTF-8 byte bound.
        """
        return self._with_value("capture_id", value)

    def with_session_id(self, value: str) -> Self:
        """Return a copy with an originating browser Session identity.

        Args:
            value: Session identity to retain.

        Returns:
            New metadata preserving all other fields.

        Raises:
            FileDocumentError: The value exceeds the native UTF-8 byte bound.
        """
        return self._with_value("session_id", value)

    def with_tab_id(self, value: str) -> Self:
        """Return a copy with an originating browser tab identity.

        Args:
            value: Tab identity to retain.

        Returns:
            New metadata preserving all other fields.

        Raises:
            FileDocumentError: The value exceeds the native UTF-8 byte bound.
        """
        return self._with_value("tab_id", value)

    def with_download_id(self, value: str) -> Self:
        """Return a copy with an originating provider download identity.

        Args:
            value: Download identity to retain.

        Returns:
            New metadata preserving all other fields.

        Raises:
            FileDocumentError: The value exceeds the native UTF-8 byte bound.
        """
        return self._with_value("download_id", value)


class _FileDocument(ImmutableModel):
    """Shared immutable metadata view over one Rust-owned file payload."""

    id: DocumentId = Field(
        description="Validated identity independent of any source URL."
    )
    metadata: FileMetadata = Field(
        description="Declared, detected, and source metadata."
    )
    _handle: _native.FileDocument = PrivateAttr()
    _limits: FileLimits = PrivateAttr(default_factory=FileLimits)
    _kind: ClassVar[Literal["image", "video", "audio", "binary"]]

    def model_post_init(self, context: object) -> None:
        """Bind the immutable Python view to the matching Rust-owned value."""
        if not isinstance(context, _native.FileDocument):
            raise ValueError(
                "construct file documents with from_bytes or file_from_bytes"
            )
        if context.id != self.id or context.kind() != self._kind:
            raise ValueError(
                "native file document identity or media kind does not match"
            )
        context.validate_input(
            str(self.id), self._kind, self.metadata.model_dump_json()
        )
        self._handle = context

    @classmethod
    def _from_native(cls, handle: _native.FileDocument) -> FileDocument:
        """Build the concrete Python media type selected by the Rust enum."""
        kind = handle.kind()
        concrete = {
            "image": ImageDocument,
            "video": VideoDocument,
            "audio": AudioDocument,
            "binary": BinaryDocument,
        }.get(kind)
        if concrete is None:
            raise ValueError(f"unknown native file document kind: {kind}")
        return concrete.model_validate(
            {"id": handle.id, "metadata": json.loads(handle.metadata())},
            context=handle,
        )

    @classmethod
    def _construct(
        cls,
        id: str,
        content: builtins.bytes,
        metadata: FileMetadata | None,
        limits: FileLimits | None,
        *,
        infer: bool = False,
    ) -> _FileDocument:
        """Create a native payload owner with authored or inferred classification."""
        if not isinstance(content, builtins.bytes):
            raise TypeError("file content must be bytes")
        selected_metadata = FileMetadata() if metadata is None else metadata
        if not isinstance(selected_metadata, FileMetadata):
            raise TypeError("metadata must be FileMetadata")
        selected_limits = FileLimits() if limits is None else limits
        if not isinstance(selected_limits, FileLimits):
            raise TypeError("limits must be FileLimits")
        kind = "infer" if infer else cls._kind
        handle = _native.FileDocument(
            id,
            content,
            kind,
            selected_metadata._native_input(),
            selected_limits.model_dump_json(),
        )
        document = _FileDocument._from_native(handle)
        if not infer and not isinstance(document, cls):
            raise ValueError("native file constructor returned a different media kind")
        document._limits = selected_limits
        return document

    @classmethod
    def from_bytes(
        cls,
        id: str,
        content: builtins.bytes,
        *,
        metadata: FileMetadata | None = None,
        limits: FileLimits | None = None,
    ) -> Self:
        """Retain exact bytes as this explicitly selected media family.

        The requested media family must match a known byte signature. This validates
        the file family only; no complete image, video, or audio decoder runs. A
        BinaryDocument can retain arbitrary bytes.

        Args:
            id: Stable document identity independent of the original URL or path.
            content: Exact payload bytes to retain without decoding.
            metadata: Optional source declarations and provenance. Rust computes the
                detected media type and digest from the payload.
            limits: Maximum payload size; defaults to 64 MiB and cannot exceed 256 MiB.

        Returns:
            An immutable concrete media document backed by Rust-owned bytes.

        Raises:
            TypeError: Content, metadata, or limits have the wrong type.
            pydantic.ValidationError: Identity or limit fields are invalid.
            FileDocumentError: Rust rejects the identity, metadata, or payload size.
        """
        return cast(Self, cls._construct(id, content, metadata, limits))

    @property
    def bytes(self) -> builtins.bytes:
        """Return a copy of the exact retained payload bytes."""
        return self._handle.bytes()

    @property
    def byte_len(self) -> int:
        """Return the exact retained payload length in bytes."""
        return self._handle.byte_len

    @property
    def sha256(self) -> str:
        """Return lowercase SHA-256 hex for the exact retained payload."""
        return self._handle.sha256

    def __eq__(self, other: object) -> bool:
        """Compare the concrete family, identity, metadata and exact retained bytes.

        Args:
            other: File document to compare with this immutable source.

        Returns:
            Value equality independent of native handle and acquisition limits.
            Other operand types return NotImplemented.
        """
        if not isinstance(other, _FileDocument):
            return NotImplemented
        return (
            type(self) is type(other)
            and self.id == other.id
            and self.metadata == other.metadata
            and self._handle.value_equals(other._handle)
        )

    def __repr__(self) -> str:
        """Describe identity and media metadata without including payload bytes."""
        return f"{type(self).__name__}(id={str(self.id)!r}, metadata={self.metadata!r})"

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy this document while keeping its Rust metadata and bytes consistent.

        Args:
            update: Optional replacement identity or authored metadata.
            deep: Copy Python metadata deeply while sharing the immutable native source.

        Returns:
            A copy that retains the same concrete family and exact payload bytes.

        Raises:
            TypeError: An unsupported field is updated or metadata has the wrong type.
            pydantic.ValidationError: Updated identity or metadata fields are invalid.
            FileDocumentError: Rust rejects the reconstructed payload or media family.
        """
        if not update:
            return super().model_copy(deep=deep)
        values: dict[str, object] = {
            "id": str(self.id),
            "metadata": self.metadata,
            **(update or {}),
        }
        if set(values) - {"id", "metadata"}:
            raise TypeError("file document copies can update only id or metadata")
        metadata = values["metadata"]
        if not isinstance(metadata, FileMetadata):
            raise TypeError("metadata must be FileMetadata")
        identity = values["id"]
        if not isinstance(identity, str):
            raise TypeError("file document identity must be a string")
        limits = FileLimits(max_bytes=max(self._limits.max_bytes, self.byte_len))
        result = cast(
            Self,
            _FileDocument._from_native(
                self._handle.copy_with(
                    identity,
                    metadata._native_input(),
                    limits.model_dump_json(),
                )
            ),
        )
        result._limits = limits
        return result


class ImageDocument(_FileDocument):
    """Immutable image bytes with native MIME detection and retained provenance."""

    _kind = "image"


class VideoDocument(_FileDocument):
    """Immutable video bytes with native MIME detection and retained provenance."""

    _kind = "video"

    def copy_with_metadata(
        self,
        id: str,
        metadata: FileMetadata | None = None,
        limits: FileLimits | None = None,
    ) -> Self:
        """Copy exact bytes under a new identity without authoring detector evidence.

        For a signature-ambiguous video created by `VideoSurface.open`, Rust keeps
        the existing probe-validated container basis because the payload is unchanged.
        Caller-supplied metadata cannot create or replace that basis, detected MIME,
        or digest. Omitted metadata keeps the current value; omitted limits use the
        default file limit.
        """
        if not isinstance(id, str):
            raise TypeError("id must be a string")
        selected_metadata = self.metadata if metadata is None else metadata
        if not isinstance(selected_metadata, FileMetadata):
            raise TypeError("metadata must be FileMetadata")
        selected_limits = FileLimits() if limits is None else limits
        if not isinstance(selected_limits, FileLimits):
            raise TypeError("limits must be FileLimits")
        result = cast(
            Self,
            _FileDocument._from_native(
                self._handle.copy_with(
                    id,
                    selected_metadata._native_input(),
                    selected_limits.model_dump_json(),
                )
            ),
        )
        result._limits = selected_limits
        return result


class AudioDocument(_FileDocument):
    """Immutable audio bytes with native MIME detection and retained provenance."""

    _kind = "audio"


class BinaryDocument(_FileDocument):
    """Opaque immutable bytes retained without format or decoder assumptions."""

    _kind = "binary"


FileDocument = ImageDocument | VideoDocument | AudioDocument | BinaryDocument
"""Concrete immutable image, video, audio, or opaque binary file documents."""


def file_from_bytes(
    id: str,
    content: builtins.bytes,
    *,
    metadata: FileMetadata | None = None,
    limits: FileLimits | None = None,
) -> FileDocument:
    """Infer a media family from exact bytes, using BinaryDocument as the fallback.

    Args:
        id: Stable document identity independent of any source URL or path.
        content: Exact payload bytes. No character or media decoder runs.
        metadata: Optional source declarations and provenance; detected type and SHA-256
            are computed by Rust and remain distinct from the declared MIME type.
        limits: Maximum payload size, defaulting to 64 MiB with a 256 MiB hard cap.

    Returns:
        A concrete ImageDocument, VideoDocument, AudioDocument, or BinaryDocument.

    Raises:
        TypeError: Content, metadata, or limits have the wrong type.
        pydantic.ValidationError: Identity or limit fields are invalid.
        FileDocumentError: Rust rejects the identity, metadata, or payload size.
    """
    return cast(
        FileDocument,
        _FileDocument._construct(id, content, metadata, limits, infer=True),
    )


async def read_file(
    id: str,
    path: str | PathLike[str],
    *,
    limits: FileLimits | None = None,
) -> FileDocument:
    """Read and classify a local file through the Rust SDK.

    Args:
        id: Stable document identity independent of the filesystem path.
        path: Local path to read; the filename is retained as source metadata.
        limits: Maximum payload size, defaulting to 64 MiB with a 256 MiB hard cap.

    Returns:
        A concrete media document with exact bytes and detected metadata when known.

    Raises:
        TypeError: The path or limits have the wrong type.
        FileDocumentError: The payload exceeds configured bounds or cannot be retained.
    """
    selected_limits = FileLimits() if limits is None else limits
    if not isinstance(selected_limits, FileLimits):
        raise TypeError("limits must be FileLimits")
    native_path = fspath(path)
    if not isinstance(native_path, str):
        raise TypeError("file path must be a text filesystem path")
    handle = await _native.read_file(id, native_path, selected_limits.model_dump_json())
    document = _FileDocument._from_native(handle)
    document._limits = selected_limits
    return document
