"""Async requests expose typed SDK results and retained immutable documents."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import Field, PrivateAttr

from . import _native
from ._models import ImmutableModel, NativeAuthoringModel
from .cancellation import CancellationToken
from .documents import Document, DocumentProfile
from .identities import (
    ActivityId as ActivityId,
)
from .identities import (
    CaptureId as CaptureId,
)
from .identities import (
    RequestId as RequestId,
)
from .policy import AcquisitionKind, Policy, PolicySnapshot

DocumentRequest = Literal[
    "response_document", "rendered_dom", "accessibility_tree", "network_tree"
]


class ProjectionReason(ImmutableModel):
    kind: str
    family: str | None = None
    reason: str | None = None
    code: str | None = None


class Diagnostic(ImmutableModel):
    kind: str
    value: TransportDiagnostic | None = None


class TransportDiagnostic(ImmutableModel):
    kind: str
    value: str | None = None


class DocumentMetadata(ImmutableModel):
    id: str
    profile: DocumentProfile
    document_class: str
    byte_len: int


class Produced(ImmutableModel):
    status: Literal["produced"]
    document: Document


class PartialDocument(ImmutableModel):
    status: Literal["partial"]
    document: Document | None
    reasons: tuple[ProjectionReason, ...]


class Unavailable(ImmutableModel):
    status: Literal["unavailable"]
    reason: ProjectionReason

    @property
    def document(self) -> None:
        return None


class Unprojectable(ImmutableModel):
    status: Literal["unprojectable"]
    reason: ProjectionReason

    @property
    def document(self) -> None:
        return None


DocumentOutcome = Annotated[
    Produced | PartialDocument | Unavailable | Unprojectable,
    Field(discriminator="status"),
]


class AttemptDocument(ImmutableModel):
    requested: DocumentRequest
    outcome: DocumentOutcome


class Attempt(ImmutableModel):
    capture_id: str
    acquisition: AcquisitionKind
    authored_selection: Literal["current", "exact"]
    requested_target: str
    http_status: int | None
    state: Literal["completed", "failed", "not_started"]
    failure_kind: str | None
    not_started_reason: Literal["cancelled"] | None
    diagnostic: Diagnostic | None
    documents: tuple[AttemptDocument, ...]


class Response(ImmutableModel):
    request_id: str
    requested_target: str
    policy_snapshot: PolicySnapshot
    termination: Literal["completed", "cancelled"]
    attempts: tuple[Attempt, ...]
    _handle: _native.Response = PrivateAttr()

    @classmethod
    def _from_native(cls, handle: _native.Response) -> Response:
        value = json.loads(handle.to_json())
        for attempt_index, attempt in enumerate(value["attempts"]):
            for document_index, item in enumerate(attempt["documents"]):
                metadata = item["outcome"].get("document")
                if metadata is not None:
                    item["outcome"]["document"] = Document._from_native(
                        handle.document(attempt_index, document_index)
                    )
        response = cls.model_validate(value)
        response._handle = handle
        return response

    @property
    def documents(self) -> tuple[Document, ...]:
        return tuple(
            item.outcome.document
            for attempt in self.attempts
            for item in attempt.documents
            if item.outcome.document is not None
        )


class PageRequest(NativeAuthoringModel):
    target: str = Field(repr=False)
    _handle: _native.PageRequest = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        self._handle = _native.PageRequest(self.target)

    @property
    def id(self) -> RequestId:
        return RequestId(self._handle.id)

    def check(self) -> None:
        self._handle.validate()

    def bind(self, policy: Policy) -> BoundPageRequest:
        return BoundPageRequest(self, policy)

    async def send(self, *, cancellation: CancellationToken | None = None) -> Response:
        handle = await self._handle.send(cancellation=_token(cancellation))
        return Response._from_native(handle)


class BoundPageRequest:
    def __init__(self, request: PageRequest, policy: Policy) -> None:
        self.request = request
        self._policy_json = policy.to_json()

    @property
    def id(self) -> RequestId:
        return self.request.id

    @property
    def target(self) -> str:
        return self.request.target

    @property
    def policy(self) -> Policy:
        return Policy.model_validate_json(self._policy_json)

    def check(self) -> None:
        self.request._handle.validate(self._policy_json)

    async def send(self, *, cancellation: CancellationToken | None = None) -> Response:
        handle = await self.request._handle.send(
            self._policy_json, _token(cancellation)
        )
        return Response._from_native(handle)


def new(target: str) -> PageRequest:
    return PageRequest(target=target)


def _token(value: CancellationToken | None) -> _native.CancellationToken | None:
    return None if value is None else value._handle


Diagnostic.model_rebuild()
