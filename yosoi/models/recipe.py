"""Portable flat recipe artifacts for deterministic Yosoi replay."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from yosoi.models.snapshot import SnapshotMap
from yosoi.models.spec import ContractSpec

RECIPE_SCHEMA_VERSION: Literal['yosoi.recipe.v1'] = 'yosoi.recipe.v1'
RecipeArtifactKind = Literal['flat-json']


class RecipeMetadata(BaseModel):
    """Human and compatibility metadata for a recipe artifact."""

    name: str | None = None
    domain_scope: list[str] = Field(default_factory=list)
    url_patterns: list[str] = Field(default_factory=list)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = 'yosoi recipe mint'
    yosoi_min: str | None = None
    notes: str | None = None


class RecipeValidation(BaseModel):
    """Portable validation evidence for a minted recipe."""

    fixture_urls: list[str] = Field(default_factory=list)
    expected_shape: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


class Recipe(BaseModel):
    """Flat shareable recipe: contract + selectors + optional actions + evidence.

    ``recipe_id`` is the sha256 of a deep-canonical JSON payload excluding the
    ``recipe_id`` field itself. Duplicate content therefore mints the same ID.
    """

    schema_version: Literal['yosoi.recipe.v1'] = RECIPE_SCHEMA_VERSION
    artifact_kind: RecipeArtifactKind = 'flat-json'
    recipe_id: str = ''
    contract: ContractSpec
    selectors: dict[str, SnapshotMap] = Field(default_factory=dict)
    a3nodes: list[dict[str, Any]] = Field(default_factory=list)
    validation: RecipeValidation = Field(default_factory=RecipeValidation)
    metadata: RecipeMetadata = Field(default_factory=RecipeMetadata)

    @model_validator(mode='after')
    def _fill_recipe_id(self) -> Recipe:
        """Compute identity on construction when absent."""
        if not self.recipe_id:
            object.__setattr__(self, 'recipe_id', self.compute_id())
        return self

    def identity_payload(self) -> dict[str, Any]:
        """Return the portable semantic payload that participates in identity.

        Provenance metadata is intentionally excluded so re-minting the same
        contract/selectors/evidence later produces the same ``recipe_id``.
        """
        payload = self.model_dump(mode='json')
        payload.pop('recipe_id', None)
        metadata = payload.get('metadata')
        if isinstance(metadata, dict):
            metadata.pop('created_at', None)
            metadata.pop('created_by', None)
            metadata.pop('notes', None)
        _strip_selector_provenance(payload.get('selectors'))
        return payload

    def compute_id(self) -> str:
        """Return the stable sha256 recipe identity for this artifact."""
        encoded = canonical_json_bytes(self.identity_payload())
        return 'sha256:' + hashlib.sha256(encoded).hexdigest()

    def verify_integrity(self) -> None:
        """Fail if ``recipe_id`` does not match the canonical payload."""
        expected = self.compute_id()
        if self.recipe_id != expected:
            raise ValueError(f'Recipe integrity check failed: stored {self.recipe_id!r}, computed {expected!r}')

    def canonical_json(self) -> str:
        """Return stable pretty JSON for storage and review."""
        return canonical_json_text(self.model_dump(mode='json'), indent=2) + '\n'

    def to_contract(self) -> type[Any]:
        """Return this recipe's contract as a live ``ys.Contract`` subclass."""
        return self.contract.to_contract()

    def selectors_for(self, domain: str) -> SnapshotMap | None:
        """Return selectors for a domain, with one-label subdomain fallback."""
        if domain in self.selectors:
            return self.selectors[domain]
        parts = domain.split('.', 1)
        if len(parts) == 2:
            return self.selectors.get(parts[1])
        return None

    def fixture_urls(self) -> list[str]:
        """Return validation fixture URLs carried by the recipe."""
        return list(self.validation.fixture_urls)

    def selector_domains(self) -> list[str]:
        """Return domains covered by bundled selectors."""
        return sorted(self.selectors)


def _strip_selector_provenance(value: Any) -> None:
    """Remove volatile selector audit fields from an identity payload in place."""
    if not isinstance(value, dict):
        return
    volatile = {
        'discovered_at',
        'last_verified_at',
        'last_failed_at',
        'failure_count',
        'source',
        'status_reason',
        'discovery_record_count',
        'discovery_field_coverage',
    }
    for snap_map in value.values():
        if not isinstance(snap_map, dict):
            continue
        snapshots = snap_map.get('snapshots')
        if not isinstance(snapshots, dict):
            continue
        for snapshot in snapshots.values():
            if isinstance(snapshot, dict):
                for key in volatile:
                    snapshot.pop(key, None)


def _deep_canonical(value: Any) -> Any:
    """Recursively sort JSON object keys while preserving list order."""
    if isinstance(value, dict):
        return {k: _deep_canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_deep_canonical(item) for item in value]
    return value


def canonical_json_text(value: Any, *, indent: int | None = None) -> str:
    """Serialize JSON-compatible data deterministically."""
    return json.dumps(
        _deep_canonical(value),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
        separators=None if indent else (',', ':'),
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return compact deterministic UTF-8 JSON bytes."""
    return canonical_json_text(value).encode('utf-8')
