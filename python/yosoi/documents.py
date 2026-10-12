"""Immutable Pydantic documents with Rust-owned parse and locate operations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import Field, PrivateAttr, ValidationInfo, model_validator

from . import _native
from ._models import ImmutableModel
from .locators import Plan
from .outcomes import LocateOutcome, _read
from .policy import Policy
from .scalars import RUST_DOMAIN_VALIDATED, DocumentEpoch, DocumentId

SourceFormat = Literal["html", "xml", "json", "text"]
"""Payload syntax accepted by source profiles: HTML, XML, JSON, or UTF-8 text."""
DocumentClass = Literal[
    "source_html",
    "source_xml",
    "source_json",
    "source_text",
    "rendered_dom",
    "accessibility_tree",
]
"""Native capability classes; source, rendered DOM, and accessibility evidence are not
interchangeable.
"""
_RUST_PROFILE_VALIDATED = RUST_DOMAIN_VALIDATED


class DocumentProfile(ImmutableModel):
    """Validated representation and schema for retained payload bytes.

    Attributes:
        representation: source, rendered_dom, or accessibility_tree selects
            capabilities.
        source_format: Owned payload syntax: html, xml, json, or text.
        schema_profile: Exact parser/schema profile, serialized under the field name
            schema.
        epoch: Positive generation for rendered DOM and accessibility snapshots; source
            profiles omit it.
    """

    representation: Literal["source", "rendered_dom", "accessibility_tree"]
    source_format: SourceFormat
    schema_profile: Literal[
        "html5",
        "xml10",
        "json_rfc8259",
        "utf8_text",
        "yosoi_rendered_dom_v1",
        "yosoi_accessibility_tree_v1",
    ] = Field(alias="schema")
    epoch: DocumentEpoch | None = None

    @model_validator(mode="after")
    def _validate_in_rust(self, info: ValidationInfo) -> Self:
        if info.context is _RUST_PROFILE_VALIDATED:
            return self
        try:
            _native.validate_profile(self.model_dump_json(exclude_none=True))
        except _native.DocumentError as error:
            raise ValueError(str(error)) from error
        return self

    @classmethod
    def source_html(cls) -> Self:
        """Return a source HTML5 profile without a snapshot epoch."""
        return cls(
            representation="source", source_format="html", schema_profile="html5"
        )

    @classmethod
    def source_xml(cls) -> Self:
        """Return a source XML 1.0 profile without a snapshot epoch."""
        return cls(representation="source", source_format="xml", schema_profile="xml10")

    @classmethod
    def source_json(cls) -> Self:
        """Return a source RFC 8259 JSON profile without a snapshot epoch."""
        return cls(
            representation="source",
            source_format="json",
            schema_profile="json_rfc8259",
        )

    @classmethod
    def source_text(cls) -> Self:
        """Return a source UTF-8 text profile without a snapshot epoch."""
        return cls(
            representation="source", source_format="text", schema_profile="utf8_text"
        )

    @classmethod
    def rendered_dom(cls, epoch: int | DocumentEpoch) -> Self:
        """Declare retained rendered DOM snapshot interpretation.

        Args:
            epoch: Positive immutable browser snapshot generation.

        Returns:
            A validated profile without capturing a live browser.

        Raises:
            pydantic.ValidationError: Epoch or authoring fields are invalid.
            DocumentError: Native profile or document validation rejects the inputs.
        """
        return cls(
            representation="rendered_dom",
            source_format="json",
            schema_profile="yosoi_rendered_dom_v1",
            epoch=epoch,
        )

    @classmethod
    def accessibility_tree(cls, epoch: int | DocumentEpoch) -> Self:
        """Declare retained accessibility snapshot interpretation.

        Args:
            epoch: Positive immutable browser snapshot generation.

        Returns:
            A validated profile without capturing a live browser.

        Raises:
            pydantic.ValidationError: Epoch or authoring fields are invalid.
            DocumentError: Native profile or document validation rejects the inputs.
        """
        return cls(
            representation="accessibility_tree",
            source_format="json",
            schema_profile="yosoi_accessibility_tree_v1",
            epoch=epoch,
        )

    @property
    def document_class(self) -> DocumentClass:
        """Return the native capability class for this validated profile."""
        return json.loads(
            _native.profile_class(self.model_dump_json(exclude_none=True))
        )


def _document_profile(values: dict[str, object]) -> DocumentProfile:
    """Validate a convenience profile before building its Pydantic view."""
    profile_json = _native.validate_profile(json.dumps(values))
    return DocumentProfile.model_validate_json(
        profile_json, context=_RUST_PROFILE_VALIDATED
    )


class Document(ImmutableModel):
    """Immutable document bytes with retained native parse ownership.

    Attributes:
        id: Validated document identity, independent of any source URL.
        profile: Representation and schema interpretation of the retained bytes.
        data: Exact owned bytes; text inputs are UTF-8 encoded. Model dumps omit payload
            data by default.
    """

    id: DocumentId
    profile: DocumentProfile
    data: bytes = Field(repr=False, exclude=True)
    _handle: _native.Document = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        """Create or validate native ownership of these exact document inputs."""
        if isinstance(context, _native.Document):
            context.validate_input(self.id, self.data, self.profile.model_dump_json())
            self._handle = context
        else:
            self._handle = _native.Document(
                self.id, self.data, self.profile.model_dump_json()
            )

    @classmethod
    def _from_native(cls, handle: _native.Document) -> Self:
        return cls.model_validate(
            {
                "id": handle.id,
                "profile": json.loads(handle.profile()),
                "data": handle.bytes(),
            },
            context=handle,
        )

    @classmethod
    def html(cls, id: str, content: str | bytes) -> Self:
        """Retain source bytes using the HTML5 interpretation.

        Args:
            id: Authored document identity, independent of any acquisition URL.
            content: Exact bytes, or text to encode as UTF-8.

        Returns:
            A document owning its payload without external acquisition.

        Raises:
            pydantic.ValidationError: Identity or authoring fields are invalid.
            DocumentError: Native construction rejects the supplied inputs.
        """
        return cls.from_profile(id, DocumentProfile.source_html(), content)

    @classmethod
    def xml(cls, id: str, content: str | bytes) -> Self:
        """Retain source bytes using the XML 1.0 interpretation.

        Args:
            id: Authored document identity, independent of any acquisition URL.
            content: Exact bytes, or text to encode as UTF-8.

        Returns:
            A document owning its payload without external acquisition.

        Raises:
            pydantic.ValidationError: Identity or authoring fields are invalid.
            DocumentError: Native construction rejects the supplied inputs.
        """
        return cls.from_profile(id, DocumentProfile.source_xml(), content)

    @classmethod
    def from_json(cls, id: str, content: str | bytes) -> Self:
        """Retain source bytes using the RFC 8259 JSON interpretation.

        Args:
            id: Authored document identity, independent of any acquisition URL.
            content: Exact bytes, or text to encode as UTF-8.

        Returns:
            A document owning its payload without external acquisition.

        Raises:
            pydantic.ValidationError: Identity or authoring fields are invalid.
            DocumentError: Native construction rejects the supplied inputs.
        """
        return cls.from_profile(id, DocumentProfile.source_json(), content)

    @classmethod
    def text(cls, id: str, content: str | bytes) -> Self:
        """Retain source bytes using the UTF-8 text interpretation.

        Args:
            id: Authored document identity, independent of any acquisition URL.
            content: Exact bytes, or text to encode as UTF-8.

        Returns:
            A document owning its payload without external acquisition.

        Raises:
            pydantic.ValidationError: Identity or authoring fields are invalid.
            DocumentError: Native construction rejects the supplied inputs.
        """
        return cls.from_profile(id, DocumentProfile.source_text(), content)

    @classmethod
    def from_profile(
        cls, id: str, profile: DocumentProfile, content: str | bytes
    ) -> Self:
        """Retain content using an explicit interpretation profile.

        Args:
            id: Authored document identity.
            profile: Validated representation, syntax, schema, and epoch declaration.
            content: Exact bytes, or text to encode as UTF-8.

        Returns:
            Immutable payload ownership without external acquisition.

        Raises:
            pydantic.ValidationError: Identity or authoring fields are invalid.
            DocumentError: Native construction rejects the supplied inputs.
        """
        return cls(id=id, profile=profile, data=_bytes(content))

    @classmethod
    def rendered_dom(
        cls, id: str, epoch: int | DocumentEpoch, content: str | bytes
    ) -> Self:
        """Declare retained rendered DOM snapshot interpretation.

        Args:
            id: Authored document identity.
            epoch: Positive immutable browser snapshot generation.
            content: JSON snapshot bytes or text in the supported version-1 schema.

        Returns:
            A retained snapshot document without querying a live browser.

        Raises:
            pydantic.ValidationError: Epoch or authoring fields are invalid.
            DocumentError: Native profile or document validation rejects the inputs.
        """
        profile = _document_profile(
            {
                "representation": "rendered_dom",
                "source_format": "json",
                "schema": "yosoi_rendered_dom_v1",
                "epoch": epoch,
            }
        )
        return cls.from_profile(id, profile, content)

    @classmethod
    def accessibility_tree(
        cls, id: str, epoch: int | DocumentEpoch, content: str | bytes
    ) -> Self:
        """Declare retained accessibility snapshot interpretation.

        Args:
            id: Authored document identity.
            epoch: Positive immutable browser snapshot generation.
            content: JSON snapshot bytes or text in the supported version-1 schema.

        Returns:
            A retained snapshot document without querying a live browser.

        Raises:
            pydantic.ValidationError: Epoch or authoring fields are invalid.
            DocumentError: Native profile or document validation rejects the inputs.
        """
        profile = _document_profile(
            {
                "representation": "accessibility_tree",
                "source_format": "json",
                "schema": "yosoi_accessibility_tree_v1",
                "epoch": epoch,
            }
        )
        return cls.from_profile(id, profile, content)

    @property
    def byte_len(self) -> int:
        """Return retained payload bytes, not decoded character count."""
        return self._handle.byte_len

    @property
    def document_class(self) -> DocumentClass:
        """Return the native capability class of the retained payload."""
        return json.loads(self._handle.document_class())

    def bind(self, policy: Policy) -> BoundDocument:
        """Snapshot a complete policy without acquiring new data.

        Args:
            policy: Complete declaration to serialize now.

        Returns:
            A document binding unaffected by later caller-policy edits.
        """
        return BoundDocument(self, policy)

    def locate(self, plan: Plan) -> LocateOutcome:
        """Execute a bounded locator plan against retained payload bytes.

        Args:
            plan: Authored outputs, projections, and repeated regions.

        Returns:
            Typed matches, complete absence, indeterminate evidence, or failure.
            No network acquisition occurs; empty convenience collections alone do
            not establish complete absence.
        """
        return _read(self._handle.locate(plan._handle))

    def parse(self) -> ParsedDocument:
        """Create a reusable native parse using default resource policy.

        Returns:
            A parse owner to close explicitly or use as a context manager.

        Raises:
            ParseError: Parsing or resource checks reject the retained payload.
        """
        return ParsedDocument(self._handle.parse())

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Copy authoring values while preserving valid native ownership.

        Args:
            update: Optional replacement fields to revalidate.
            deep: Reconstruct through the public constructor when True.

        Returns:
            A document copy. Unchanged shallow copies retain the native handle;
            updated or deep copies are reconstructed and revalidated.

        Raises:
            pydantic.ValidationError: Updated authoring fields are invalid.
            DocumentError: Native reconstruction rejects the supplied inputs.
        """
        if update or deep:
            values = {**self.model_dump(), "data": self.data, **(update or {})}
            return type(self).model_validate(values)
        return super().model_copy()

    def __eq__(self, other: object) -> bool:
        """Compare identity, interpretation profile, and exact payload bytes.

        Args:
            other: Document to compare.

        Returns:
            Retained-input equality, not native-handle identity. Other operand types
            return NotImplemented.
        """
        if not isinstance(other, Document):
            return NotImplemented
        return (self.id, self.profile, self.data) == (
            other.id,
            other.profile,
            other.data,
        )


class BoundDocument:
    """Retained document paired with a serialized policy snapshot.

    Attributes:
        document: Immutable document owner; later caller-policy edits do not change the
            binding.
    """

    def __init__(self, document: Document, policy: Policy) -> None:
        """Retain a document and snapshot a policy without acquisition I/O.

        Args:
            document: Immutable payload owner to retain.
            policy: Complete declaration to serialize for parsing and locating.
        """
        self.document = document
        self._policy_json = policy.to_json()

    @property
    def policy(self) -> Policy:
        """Return a policy copy whose edits do not change this binding."""
        return Policy.model_validate_json(self._policy_json)

    def locate(self, plan: Plan) -> LocateOutcome:
        """Execute the authored plan using the bound policy.

        Args:
            plan: Outputs and projections to evaluate against retained bytes.

        Returns:
            Typed outcome preserving matches, absence, incompleteness, or failure.
        """
        return _read(self.document._handle.locate(plan._handle, self._policy_json))

    def parse(self) -> ParsedDocument:
        """Create a reusable parse using the bound resource limits.

        Returns:
            A parse owner to close explicitly or use as a context manager.

        Raises:
            ParseError: Parsing or configured resource checks reject the payload.
        """
        return ParsedDocument(self.document._handle.parse(self._policy_json))


class ParsedDocument:
    """A reusable Rust parse; close explicitly or use it as a context manager."""

    def __init__(self, handle: _native.ParsedDocument) -> None:
        """Retain a native parse handle without acquiring or reparsing data.

        Args:
            handle: Native owner returned by a supported parse operation.
        """
        self._handle = handle

    def locate(self, plan: Plan) -> LocateOutcome:
        """Reuse retained parse evidence for an authored locator plan.

        Args:
            plan: Outputs and projections to evaluate against the parse.

        Returns:
            Typed matches, absence, incomplete evidence, or failure.

        Raises:
            ClosedResourceError: The parse has already been closed.
        """
        return _read(self._handle.locate(plan._handle))

    @property
    def closed(self) -> bool:
        """Return whether native parse ownership has been explicitly closed."""
        return self._handle.closed

    def close(self) -> None:
        """Close native parse ownership; repeated closes are harmless."""
        self._handle.close()

    def __enter__(self) -> Self:
        """Return this parse owner for context-managed use.

        Raises:
            ClosedResourceError: The parse was closed before context entry.
        """
        if self.closed:
            raise _native.ClosedResourceError("parsed document is closed")
        return self

    def __exit__(self, *args: object) -> None:
        """Close native parse ownership on context exit, including on errors."""
        self.close()


def _bytes(content: str | bytes) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else content
