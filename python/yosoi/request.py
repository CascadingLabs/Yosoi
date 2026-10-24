"""Async requests expose typed SDK results and retained immutable documents."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, PrivateAttr

from . import _native
from ._models import ImmutableModel, NativeAuthoringModel
from .cancellation import CancellationToken
from .diagnostics import AttemptDiagnostic as AttemptDiagnostic
from .diagnostics import (
    AttemptFailureKind as AttemptFailureKind,
)
from .diagnostics import (
    Diagnostic as Diagnostic,
)
from .diagnostics import (
    NotStartedReason as NotStartedReason,
)
from .diagnostics import PartialReason as PartialReason
from .diagnostics import (
    ProjectionReason as ProjectionReason,
)
from .diagnostics import (
    TransportDiagnostic as TransportDiagnostic,
)
from .diagnostics import UnavailableReason as UnavailableReason
from .diagnostics import UnprojectableReason as UnprojectableReason
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
from .scalars import ValidatedString

if TYPE_CHECKING:
    from .browser import Session, Work

DocumentRequest = Literal[
    "response_document", "rendered_dom", "accessibility_tree", "network_tree"
]
"""Requested evidence families for an acquisition. A selected family can still be
partial, unavailable, or unprojectable in the returned outcome.
"""


class WebTarget(ValidatedString):
    """Authored request target; Rust defers URL validation until preparation."""

    _kind = "web_target"

    @classmethod
    def new(cls, value: str) -> WebTarget:
        """Retain target text without URL validation or network I/O.

        Args:
            value: Original target text to validate during request preparation.

        Returns:
            A string value whose construction does not prove that the URL is usable.
        """
        return cls(value)

    def __repr__(self) -> str:
        """Return a representation that redacts the authored target."""
        return "WebTarget(<redacted>)"


class DocumentMetadata(ImmutableModel):
    """Source document identity, representation, and byte accounting.

    Attributes:
        id: Identity allocated to the document, not its source URL.
        profile: Declared representation profile used to interpret retained bytes.
        document_class: Native document capability class.
        byte_len: Number of bytes in the retained document payload.
    """

    id: str
    profile: DocumentProfile
    document_class: str
    byte_len: int


class Produced(ImmutableModel):
    """Requested document representation was produced with retained ownership.

    Attributes:
        status: Discriminator fixed to produced for tagged decoding.
        document: Retained immutable document; inspect its locator evidence for
            scope-specific completeness.
    """

    status: Literal["produced"]
    document: Document


class PartialDocument(ImmutableModel):
    """Document production retained incomplete evidence or omitted a document.

    Attributes:
        status: Discriminator fixed to partial for tagged decoding.
        document: Retained partial document, or None when no usable document was
            retained.
        reasons: Typed reasons limiting production completeness. Partial is not complete
            absence.
    """

    status: Literal["partial"]
    document: Document | None
    reasons: tuple[ProjectionReason, ...]


class Unavailable(ImmutableModel):
    """Requested evidence was unavailable from the acquisition.

    Attributes:
        status: Discriminator fixed to unavailable for tagged decoding.
        reason: Typed explanation for absent evidence, distinct from projection
            incompatibility.
    """

    status: Literal["unavailable"]
    reason: ProjectionReason

    @property
    def document(self) -> None:
        """Return None without treating unavailable evidence as complete absence."""
        return None


class Unprojectable(ImmutableModel):
    """Available acquisition evidence cannot produce the requested representation.

    Attributes:
        status: Discriminator fixed to unprojectable for tagged decoding.
        reason: Typed projection incompatibility or unsupported representation
            explanation.
    """

    status: Literal["unprojectable"]
    reason: ProjectionReason

    @property
    def document(self) -> None:
        """Return None because the requested representation cannot be projected."""
        return None


DocumentOutcome = Annotated[
    Produced | PartialDocument | Unavailable | Unprojectable,
    Field(discriminator="status"),
]
"""Tagged document production states. Produced, partial, unavailable, and unprojectable
retain distinct evidence and absence meanings.
"""


class AttemptDocument(ImmutableModel):
    """One authored document request and its typed production outcome.

    Attributes:
        requested: Requested response, rendered DOM, accessibility, or network
            representation.
        outcome: Produced, partial, unavailable, or unprojectable evidence, without
            collapsing these states.
    """

    requested: DocumentRequest
    outcome: DocumentOutcome


class Attempt(ImmutableModel):
    """Typed acquisition outcome retained in authored policy order.

    Attributes:
        capture_id: Identity allocated to this capture occurrence.
        acquisition: Direct HTTP or browser mechanism selected by the policy.
        authored_selection: current resolves package defaults; exact retains explicitly
            authored selection.
        requested_target: Original request target; it can contain user-sensitive path or
            query text.
        http_status: Observed HTTP status, or None when no status was recorded.
        content_type: Bounded declared Direct HTTP Content-Type, including parameters.
            None when absent, invalid, duplicated, oversized, or unavailable; this
            declaration does not verify the file format.
        body: Complete retained Direct HTTP representation bytes after content
            decoding, before character decoding. Includes binary images without
            requiring a Document. None for incomplete/unavailable bodies,
            browser acquisitions, or omitted response-document selection. An empty
            retained body is b"". HTTP errors can still have bodies; inspect status.
            Payload bytes are excluded from repr and model dumps.
        state: completed, failed, or not_started describes acquisition execution, not
            HTTP business success or completeness of every document.
        failure_kind: Typed failure classification when an attempt failed.
        not_started_reason: Reason acquisition did not start, when applicable.
        diagnostic: Typed structural diagnostics without substituting them for document
            evidence.
        documents: One outcome per authored document representation in acquisition
            order.
    """

    capture_id: str
    acquisition: AcquisitionKind
    authored_selection: Literal["current", "exact"]
    requested_target: str
    http_status: int | None
    content_type: str | None = None
    body: bytes | None = Field(default=None, repr=False, exclude=True)
    state: Literal["completed", "failed", "not_started"]
    failure_kind: AttemptFailureKind | None
    not_started_reason: NotStartedReason | None
    diagnostic: Diagnostic | None
    documents: tuple[AttemptDocument, ...]


class Response(ImmutableModel):
    """Completed and failed acquisition evidence with retained native ownership.

    Attributes:
        request_id: Identity of the prepared request producing these outcomes.
        requested_target: Requested target text; repr redacts it but direct access can
            expose user content.
        policy_snapshot: Resolved immutable policy snapshot fixed during preparation.
        termination: completed means execution did not observe caller cancellation, not
            that every acquisition succeeded. cancelled retains prior outcomes and later
            unstarted attempts.
        attempts: One typed outcome per authored acquisition in policy order, including
            failures and work that never started.
    """

    request_id: str
    requested_target: str = Field(repr=False)
    policy_snapshot: PolicySnapshot
    termination: Literal["completed", "cancelled"]
    attempts: tuple[Attempt, ...] = Field(repr=False)
    _handle: _native.Response = PrivateAttr()

    def __repr__(self) -> str:
        """Return request identity and counts with target and attempts redacted."""
        return (
            "Response("
            f"request_id={self.request_id!r}, "
            "requested_target='<redacted>', "
            f"attempt_count={len(self.attempts)}, "
            f"termination={self.termination!r})"
        )

    __str__ = __repr__

    @classmethod
    def _from_native(cls, handle: _native.Response) -> Response:
        value = json.loads(handle.to_json())
        for attempt_index, attempt in enumerate(value["attempts"]):
            attempt["body"] = handle.body(attempt_index)
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
        """Collect all retained documents in acquisition and request order.

        Includes documents from partial outcomes when present. Inspect attempts to
        retain requested representation, failure, and completeness distinctions;
        this convenience tuple alone cannot establish success or complete absence.
        """
        return tuple(
            item.outcome.document
            for attempt in self.attempts
            for item in attempt.documents
            if item.outcome.document is not None
        )


class PageRequest(NativeAuthoringModel):
    """Authored page acquisition intent, independent of policy binding.

    Attributes:
        target: Original target text. URL validation is deferred until checking or
            sending; construction does not perform I/O.
    """

    target: WebTarget = Field(repr=False)
    _handle: _native.PageRequest = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        """Create a native request handle without acquiring or validating a URL."""
        self._handle = _native.PageRequest(self.target)

    @property
    def id(self) -> RequestId:
        """Return the request identity retained across policy bindings and sends."""
        return RequestId(self._handle.id)

    def check(self) -> None:
        """Validate target and package-default policy without acquisition I/O.

        Raises:
            RequestError: Request preparation or policy resolution fails.
        """
        self._handle.validate()

    def bind(self, policy: Policy) -> BoundPageRequest:
        """Snapshot a complete policy declaration for subsequent acquisition.

        Args:
            policy: Complete declaration to serialize at binding time.

        Returns:
            A binding unaffected by later edits to the caller policy.
        """
        return BoundPageRequest(self, policy)

    def in_session(self, session: Session) -> BoundSessionRequest:
        """Bind this request to the caller-owned browser Session."""
        return BoundSessionRequest(self, session=session)

    def with_work(self, work: Work) -> BoundSessionRequest:
        """Bind this request to the caller-owned Work lease."""
        return BoundSessionRequest(self, work=work)

    async def send(self, *, cancellation: CancellationToken | None = None) -> Response:
        """Acquire document representations with defaults.

        Args:
            cancellation: Optional cooperative token shared with other operations.
                Observed cancellation retains prior attempts and marks later attempts
                not started; external effects are not rolled back.

        Returns:
            Typed response retaining document owners. Completed termination does not
            imply that every attempt succeeded; inspect attempts and document outcomes.

        Raises:
            RequestError: Preparation or adapter setup fails before execution.
            pydantic.ValidationError: Native response data cannot form a typed result.
        """
        handle = await self._handle.send(cancellation=_token(cancellation))
        return Response._from_native(handle)


class BoundPageRequest:
    """A page request bound to a serialized policy snapshot.

    Attributes:
        request: Retained authored request. Later edits to the caller policy do not
            affect this binding.
    """

    def __init__(self, request: PageRequest, policy: Policy) -> None:
        """Retain the request and snapshot its policy without acquisition I/O.

        Args:
            request: Authored acquisition request to retain.
            policy: Complete declaration to serialize for subsequent checks and sends.
        """
        self.request = request
        self._policy_json = policy.to_json()

    @property
    def id(self) -> RequestId:
        """Return the identity of the retained authored request."""
        return self.request.id

    @property
    def target(self) -> WebTarget:
        """Return original target text without validating it or performing I/O."""
        return self.request.target

    @property
    def policy(self) -> Policy:
        """Return a policy copy whose edits do not change this binding."""
        return Policy.model_validate_json(self._policy_json)

    def check(self) -> None:
        """Validate target and bound-policy snapshot without acquisition I/O.

        Raises:
            RequestError: Request preparation or policy resolution fails.
        """
        self.request._handle.validate(self._policy_json)

    def in_session(self, session: Session) -> BoundSessionRequest:
        """Use this bound Policy while borrowing the caller-owned Session."""
        return BoundSessionRequest(self, session=session)

    def with_work(self, work: Work) -> BoundSessionRequest:
        """Use this bound Policy while borrowing the caller-owned Work lease."""
        return BoundSessionRequest(self, work=work)

    async def send(self, *, cancellation: CancellationToken | None = None) -> Response:
        """Acquire document representations with the bound policy.

        Args:
            cancellation: Optional cooperative token shared with other operations.
                Observed cancellation retains prior attempts and marks later attempts
                not started; external effects are not rolled back.

        Returns:
            Typed response retaining document owners. Completed termination does not
            imply that every attempt succeeded; inspect attempts and document outcomes.

        Raises:
            RequestError: Preparation or adapter setup fails before execution.
            pydantic.ValidationError: Native response data cannot form a typed result.
        """
        handle = await self.request._handle.send(
            self._policy_json, _token(cancellation)
        )
        return Response._from_native(handle)


class BoundSessionRequest:
    """A page request retaining a caller-owned browser Session or Work.

    Attributes:
        request: Authored or policy-bound page request to send through the retained
            owner.
    """

    request: PageRequest | BoundPageRequest
    _session: Session | None
    _work: Work | None

    def __init__(
        self,
        request: PageRequest | BoundPageRequest,
        *,
        session: Session | None = None,
        work: Work | None = None,
    ) -> None:
        """Retain exactly one caller-owned browser execution owner.

        Args:
            request: Authored or policy-bound acquisition request.
            session: Browser Session to reuse, mutually exclusive with work.
            work: Browser Work lease to reuse, mutually exclusive with session.

        Raises:
            TypeError: Both or neither owners are supplied, or an owner has the wrong
                type.

        The caller controls the owner's lifetime. Construction starts no acquisition
        and does not transfer responsibility for closing the Session or Work lease.
        """
        if (session is None) == (work is None):
            raise TypeError("provide exactly one browser Session or Work owner")
        from .browser import Session as BrowserSession
        from .browser import Work as BrowserWork

        if session is not None and not isinstance(session, BrowserSession):
            raise TypeError("session must be a Yosoi browser Session")
        if work is not None and not isinstance(work, BrowserWork):
            raise TypeError("work must be a Yosoi browser Work lease")
        self.request = request
        self._session = session
        self._work = work

    @property
    def id(self) -> RequestId:
        """Return the identity of the retained authored request."""
        return self.request.id

    @property
    def target(self) -> WebTarget:
        """Return original target text, which can contain user-sensitive data."""
        return self.request.target

    @property
    def policy(self) -> Policy | None:
        """Return a policy copy when explicitly bound, otherwise None."""
        if isinstance(self.request, BoundPageRequest):
            return self.request.policy
        return None

    async def send(self, *, cancellation: CancellationToken | None = None) -> Response:
        """Acquire documents through the retained Session or Work owner.

        Args:
            cancellation: Optional cooperative token. When omitted, the owner applies
                its existing cancellation behavior. Observed cancellation preserves
                completed outcomes and does not undo external effects.

        Returns:
            A typed response without closing the Session or releasing the Work lease.
            Inspect individual attempts rather than treating completion as success.

        Raises:
            BrowserError: The Session has not been entered or Work is unavailable.
            RequestError: Request preparation or acquisition setup cannot begin.
            RuntimeError: The binding has lost both execution owners.
        """
        if self._session is not None:
            return await self._session.send(self.request, cancellation=cancellation)
        if self._work is not None:
            return await self._work.send(self.request, cancellation=cancellation)
        raise RuntimeError("browser request has no owner")


def new(target: str | WebTarget) -> PageRequest:
    """Author a page acquisition without URL validation or network I/O.

    Args:
        target: Original string or WebTarget to validate during preparation.

    Returns:
        A request with a fresh identity, using defaults until explicitly bound.

    Raises:
        pydantic.ValidationError: The supplied target cannot form the authoring model.
    """
    return PageRequest(target=WebTarget.new(target))


def _token(value: CancellationToken | None) -> _native.CancellationToken | None:
    return None if value is None else value._handle
