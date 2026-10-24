"""Immutable local evidence storage backed by Rust's validated Archive format."""

from __future__ import annotations

import json
from os import PathLike, fspath
from pathlib import Path
from typing import Any, Literal, Self, overload

from pydantic import Field, StrictStr, field_validator, model_validator

from . import _native
from ._models import ImmutableModel
from .browser import FlowOutcome, Observation, OperationReceipt, SessionPolicy
from .documents import Document
from .locators import Plan

__all__ = [
    "Archive",
    "AutomationContext",
    "AutomationRecord",
    "AutomationRecordRef",
    "DocumentArchiveRef",
    "PlanArchiveRef",
]


def _rust_json(value: ImmutableModel) -> str:
    def wire(item: Any) -> Any:
        if isinstance(item, bytes):
            return list(item)
        if isinstance(item, dict):
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

    value: StrictStr

    @field_validator("value")
    @classmethod
    def _validate_reference(cls, value: str) -> str:
        return _native.validate_archive_ref("document", value)


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
    async def write(self, value: Plan) -> PlanArchiveRef: ...

    @overload
    async def write(self, value: AutomationRecord) -> AutomationRecordRef: ...

    async def write(
        self,
        value: Document | Plan | AutomationRecord,
    ) -> DocumentArchiveRef | PlanArchiveRef | AutomationRecordRef:
        """Save a supported value and return a distinct immutable reference.

        Exact bytes, profiles, coordinates and result certainty are retained.
        Unsupported application objects raise TypeError. Invalid evidence,
        excessive payloads and storage failures raise ArchiveError.
        """
        if isinstance(value, Document):
            return DocumentArchiveRef(
                value=await self._handle.write_document(value._handle)
            )
        if isinstance(value, Plan):
            return PlanArchiveRef(value=await self._handle.write_plan(value._handle))
        if isinstance(value, AutomationRecord):
            return AutomationRecordRef.model_validate_json(
                await self._handle.write_record(_rust_json(value))
            )
        raise TypeError("Archive.write supports Document, Plan and AutomationRecord")

    @overload
    async def read(self, reference: DocumentArchiveRef) -> Document: ...

    @overload
    async def read(self, reference: PlanArchiveRef) -> Plan: ...

    @overload
    async def read(self, reference: AutomationRecordRef) -> AutomationRecord: ...

    async def read(
        self,
        reference: DocumentArchiveRef | PlanArchiveRef | AutomationRecordRef,
    ) -> Document | Plan | AutomationRecord:
        """Read exact saved evidence without launching a browser or fetching URLs.

        References can be serialized with model_dump_json and reconstructed with
        their class's model_validate_json. Missing or corrupt data and unsupported
        versions raise ArchiveError. An unsupported reference type raises TypeError.
        """
        if isinstance(reference, DocumentArchiveRef):
            return Document._from_native(
                await self._handle.read_document(reference.value)
            )
        if isinstance(reference, PlanArchiveRef):
            return Plan.from_compiled(
                json.loads(await self._handle.read_plan(reference.value))
            )
        if isinstance(reference, AutomationRecordRef):
            return AutomationRecord.model_validate_json(
                await self._handle.read_record(reference.model_dump_json())
            )
        raise TypeError("Archive.read requires a typed Archive reference")
