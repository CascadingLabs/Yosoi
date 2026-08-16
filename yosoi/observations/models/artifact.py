"""Exact identities and safety labels for canonical observation artifacts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

OBSERVATION_SCHEMA_VERSION = 'obs1'


class EvidenceKind(str, Enum):
    """A modality captured for one exact page state."""

    SOURCE_HTML = 'source_html'
    RENDERED_DOM = 'rendered_dom'
    AX_TREE = 'ax_tree'
    NETWORK = 'network'
    HEALTH = 'health'
    VISUAL = 'visual'


class Sensitivity(str, Enum):
    """Access class assigned before captured bytes become canonical evidence."""

    PUBLIC = 'public'
    MODEL_SAFE = 'model_safe'
    RESTRICTED = 'restricted'
    EPHEMERAL_SECRET = 'ephemeral_secret'


class ArtifactRef(BaseModel):
    """Immutable identity and provenance for one policy-safe captured artifact."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = OBSERVATION_SCHEMA_VERSION
    snapshot_id: str = Field(min_length=1)
    kind: EvidenceKind
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sensitivity: Sensitivity = Sensitivity.MODEL_SAFE
    redactions: tuple[str, ...] = ()


__all__ = ['OBSERVATION_SCHEMA_VERSION', 'ArtifactRef', 'EvidenceKind', 'Sensitivity']
