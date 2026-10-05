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
from .scalars import DocumentEpoch, DocumentId, RUST_DOMAIN_VALIDATED

SourceFormat = Literal["html", "xml", "json", "text"]
DocumentClass = Literal[
    "source_html",
    "source_xml",
    "source_json",
    "source_text",
    "rendered_dom",
    "accessibility_tree",
]
_RUST_PROFILE_VALIDATED = RUST_DOMAIN_VALIDATED


class DocumentProfile(ImmutableModel):
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
        return cls(
            representation="source", source_format="html", schema_profile="html5"
        )

    @classmethod
    def source_xml(cls) -> Self:
        return cls(representation="source", source_format="xml", schema_profile="xml10")

    @classmethod
    def source_json(cls) -> Self:
        return cls(
            representation="source",
            source_format="json",
            schema_profile="json_rfc8259",
        )

    @classmethod
    def source_text(cls) -> Self:
        return cls(
            representation="source", source_format="text", schema_profile="utf8_text"
        )

    @classmethod
    def rendered_dom(cls, epoch: int | DocumentEpoch) -> Self:
        return cls(
            representation="rendered_dom",
            source_format="json",
            schema_profile="yosoi_rendered_dom_v1",
            epoch=epoch,
        )

    @classmethod
    def accessibility_tree(cls, epoch: int | DocumentEpoch) -> Self:
        return cls(
            representation="accessibility_tree",
            source_format="json",
            schema_profile="yosoi_accessibility_tree_v1",
            epoch=epoch,
        )

    @property
    def document_class(self) -> DocumentClass:
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
    id: DocumentId
    profile: DocumentProfile
    data: bytes = Field(repr=False, exclude=True)
    _handle: _native.Document = PrivateAttr()

    def model_post_init(self, context: object) -> None:
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
        return cls.from_profile(id, DocumentProfile.source_html(), content)

    @classmethod
    def xml(cls, id: str, content: str | bytes) -> Self:
        return cls.from_profile(id, DocumentProfile.source_xml(), content)

    @classmethod
    def from_json(cls, id: str, content: str | bytes) -> Self:
        return cls.from_profile(id, DocumentProfile.source_json(), content)

    @classmethod
    def text(cls, id: str, content: str | bytes) -> Self:
        return cls.from_profile(id, DocumentProfile.source_text(), content)

    @classmethod
    def from_profile(
        cls, id: str, profile: DocumentProfile, content: str | bytes
    ) -> Self:
        return cls(id=id, profile=profile, data=_bytes(content))

    @classmethod
    def rendered_dom(
        cls, id: str, epoch: int | DocumentEpoch, content: str | bytes
    ) -> Self:
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
        return self._handle.byte_len

    @property
    def document_class(self) -> DocumentClass:
        return json.loads(self._handle.document_class())

    def bind(self, policy: Policy) -> BoundDocument:
        return BoundDocument(self, policy)

    def locate(self, plan: Plan) -> LocateOutcome:
        return _read(self._handle.locate(plan._handle))

    def parse(self) -> ParsedDocument:
        return ParsedDocument(self._handle.parse())

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        if update or deep:
            values = {**self.model_dump(), "data": self.data, **(update or {})}
            return type(self).model_validate(values)
        return super().model_copy()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            return NotImplemented
        return (self.id, self.profile, self.data) == (
            other.id,
            other.profile,
            other.data,
        )


class BoundDocument:
    def __init__(self, document: Document, policy: Policy) -> None:
        self.document = document
        self._policy_json = policy.to_json()

    @property
    def policy(self) -> Policy:
        return Policy.model_validate_json(self._policy_json)

    def locate(self, plan: Plan) -> LocateOutcome:
        return _read(self.document._handle.locate(plan._handle, self._policy_json))

    def parse(self) -> ParsedDocument:
        return ParsedDocument(self.document._handle.parse(self._policy_json))


class ParsedDocument:
    """A reusable Rust parse; close explicitly or use it as a context manager."""

    def __init__(self, handle: _native.ParsedDocument) -> None:
        self._handle = handle

    def locate(self, plan: Plan) -> LocateOutcome:
        return _read(self._handle.locate(plan._handle))

    @property
    def closed(self) -> bool:
        return self._handle.closed

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> Self:
        if self.closed:
            raise _native.ClosedResourceError("parsed document is closed")
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _bytes(content: str | bytes) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else content
