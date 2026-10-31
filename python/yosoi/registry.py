"""Transactional registry DTOs and shared memory/JSONL handles backed by Rust.

Read a snapshot, evaluate a decision, then commit against its exact revision.
A Conflict requires reevaluation before retrying. Perform external work only
after a successful commit. Operations are synchronous; async callers should
offload them to a worker thread. Native file I/O releases the Python interpreter.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from os import PathLike, fspath
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, StrictStr

from . import _native
from ._models import ImmutableModel
from .errors import RegistryError as RegistryError

__all__ = [
    "Change",
    "Coordination",
    "Put",
    "Registry",
    "RegistryError",
    "Remove",
    "Revision",
    "Snapshot",
]

Coordination = Literal["instance", "local_processes", "distributed"]
"""Actual backend sharing scope; this alone does not identify a registry."""


class Revision(ImmutableModel):
    """Portable identity and commit sequence used to reject stale decisions."""

    registry_id: StrictStr = Field(
        description="Logical registry UUID, stable across compaction."
    )
    sequence: int = Field(
        ge=0, le=2**64 - 1, strict=True, description="Commit sequence starting at zero."
    )


class Snapshot(ImmutableModel):
    """Owned state at one revision; mutating its DTOs cannot change the registry."""

    revision: Revision = Field(description="Exact token required by commit.")
    entries: dict[str, JsonValue] = Field(
        description="Application DTOs indexed by stable keys."
    )


class Put(ImmutableModel):
    """Create or replace one entry as part of an atomic ordered batch."""

    kind: Literal["put"] = Field(
        default="put", description="Wire mutation discriminator."
    )
    key: StrictStr = Field(
        description="Nonempty key, at most 256 UTF-8 bytes, without controls."
    )
    value: JsonValue = Field(
        description="JSON DTO bounded to 64 KiB serialized and 32 nesting levels."
    )


class Remove(ImmutableModel):
    """Remove an entry, allowing already absent entries."""

    kind: Literal["remove"] = Field(
        default="remove", description="Wire mutation discriminator."
    )
    key: StrictStr = Field(description="Stable entry key under the same bounds as Put.")


Change = Annotated[Put | Remove, Field(discriminator="kind")]
"""One mutation in a batch committed atomically by the backend."""


def _wire_changes(changes: Sequence[Change]) -> str:
    wire = [change.model_dump(mode="json") for change in changes]
    # Rust JSON numbers store signed/unsigned 64-bit integers or binary64
    # floats. Reject larger Python integers before decoding could round them.
    pending: list[object] = [wire]
    while pending:
        value = pending.pop()
        if isinstance(value, int) and not -(2**63) <= value <= 2**64 - 1:
            raise ValueError("registry JSON integers must fit i64 or u64")
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return json.dumps(wire, allow_nan=False)


class Registry:
    """Cloneable runtime handle, separate from portable Policy and registry DTOs.

    A default instance is isolated in memory. Clones share state. JSONL handles
    sharing a canonical file coordinate across local processes and survive exit.
    """

    def __init__(self) -> None:
        """Create an isolated in-memory registry; no filesystem is accessed."""
        self._handle = _native.NativeRegistry()

    @classmethod
    def jsonl(cls, path: str | PathLike[str]) -> Self:
        """Open/create a journal, creating parents and retaining a stable identity.

        Args:
            path: File to share. Symlink aliases are canonicalized; hard-link
                aliases and network filesystems are unsupported for coordination.

        Returns:
            A handle using persistent local-process coordination.

        Raises:
            RegistryError: Lock contention, malformed state, capacity or I/O failure.
        """
        instance = cls.__new__(cls)
        instance._handle = _native.NativeRegistry.jsonl(fspath(path))
        return instance

    @classmethod
    def global_jsonl(cls) -> Self:
        """Opt into the standard per-user persistent journal.

        Uses XDG_STATE_HOME or HOME/.local/state on Unix, LOCALAPPDATA on Windows.
        Raises RegistryError if no absolute state location exists or opening fails.
        This never changes the default backend of independently created registries.
        """
        instance = cls.__new__(cls)
        instance._handle = _native.NativeRegistry.global_jsonl()
        return instance

    @property
    def coordination(self) -> Coordination:
        """Return the actual backend coordination boundary."""
        return self._handle.coordination()

    def clone(self) -> Self:
        """Share this backend without copying its state or changing its lifetime."""
        instance = type(self).__new__(type(self))
        instance._handle = self._handle.clone_handle()
        return instance

    def snapshot(self) -> Snapshot:
        """Read consistent state; raise RegistryError on backend/lock failure."""
        return Snapshot.model_validate_json(self._handle.snapshot_json())

    def commit(self, expected: Revision, changes: Sequence[Change]) -> Snapshot:
        """Apply a batch only when identity and sequence still match.

        Args:
            expected: Revision from the snapshot used to evaluate the decision.
            changes: Ordered mutations applied together. Empty batches validate
                the revision without advancing it.

        Returns:
            Committed snapshot, including the new revision.

        Raises:
            RegistryError: Conflict, Busy, invalid state/keys or capacity/I/O failure.
                A write/sync error can leave the commit outcome indeterminate;
                inspect state before deciding whether to retry. No retries occur here.
            ValueError: JSON numbers are non-finite or integers exceed the Rust
                signed/unsigned 64-bit range. No commit is attempted.
        """
        return Snapshot.model_validate_json(
            self._handle.commit_json(expected.model_dump_json(), _wire_changes(changes))
        )

    def compact(self) -> None:
        """Compact history without changing identity/state/revision.

        A no-op in memory. JSONL uses the same process lock as transactions and
        atomically replaces the journal. Raises RegistryError on backend failure.
        """
        self._handle.compact()
