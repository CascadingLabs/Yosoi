"""Multi-shot observation diff contracts and scaffold."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from yosoi.observations.models.index import ObservationIndex
from yosoi.observations.models.view import RegionRef


class ChangeKind(str, Enum):
    """Structural change classification between indexed snapshots."""

    ADDED = 'added'
    REMOVED = 'removed'
    CHANGED = 'changed'


class IndexChange(BaseModel):
    """One addressable change between two observation indexes."""

    model_config = ConfigDict(frozen=True)

    kind: ChangeKind
    before: RegionRef | None = None
    after: RegionRef | None = None
    summary: str


class ObservationDiff(BaseModel):
    """Bounded structural comparison between two exact snapshot indexes."""

    model_config = ConfigDict(frozen=True)

    before_snapshot_id: str
    after_snapshot_id: str
    changes: tuple[IndexChange, ...] = ()
    truncated: bool = False


def diff_indexes(before: ObservationIndex, after: ObservationIndex) -> ObservationDiff:
    """Compare two indexes after action-episode semantics are specified."""
    raise NotImplementedError('observation index diffing is not implemented; see observations/ROADMAP.md')


__all__ = ['ChangeKind', 'IndexChange', 'ObservationDiff', 'diff_indexes']
