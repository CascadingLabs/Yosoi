"""Portable flat recipe artifacts for deterministic Yosoi replay."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from yosoi.models.snapshot import SnapshotMap
from yosoi.models.spec import ContractSpec

RECIPE_SCHEMA_VERSION: Literal['v1'] = 'v1'
RECIPE_ID_PREFIX = 'v1:sha256:'


class RecipeMetadata(BaseModel):
    """Human and compatibility metadata for a recipe artifact."""

    name: str | None = None
    domain_scope: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
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


class RecipeA3Scope(BaseModel):
    """Portable A3Node replay scope keyed before navigation."""

    schema_version: Literal['yosoi.a3node.scope.v1'] = 'yosoi.a3node.scope.v1'
    scope_key: str
    domain: str
    page_profile: str
    intent: str = 'fetch'
    browser_fingerprint: str = 'default'
    route_signature: str = ''
    query_signature: str = ''


class RecipeA3Act(BaseModel):
    """Portable DOM stabilization action."""

    kind: str
    cycles: int = 1
    target: dict[str, Any] | None = None
    timeout_ms: int | None = None
    retry: dict[str, Any] = Field(default_factory=dict)
    assert_: dict[str, Any] = Field(default_factory=dict, alias='assert')


class RecipeA3Node(BaseModel):
    """Stable A3Node export embedded in a flat recipe."""

    schema_version: Literal['yosoi.a3node.v1'] = 'yosoi.a3node.v1'
    scope: RecipeA3Scope
    acts: list[RecipeA3Act] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(
        default_factory=lambda: {
            'no_cookies': True,
            'no_local_paths': True,
            'no_secrets': True,
            'no_screenshots': True,
        }
    )

    @model_validator(mode='before')
    @classmethod
    def _migrate_legacy_node(cls, data: Any) -> Any:
        if not isinstance(data, dict) or 'scope' in data:
            return data
        if {'scope_key', 'domain', 'acts'} & set(data):
            return {
                'scope': {
                    'scope_key': str(data.get('scope_key') or data.get('domain') or 'legacy'),
                    'domain': str(data.get('domain') or ''),
                    'page_profile': str(data.get('page_profile') or 'legacy-domain'),
                    'intent': str(data.get('intent') or 'legacy-domain'),
                    'browser_fingerprint': str(data.get('browser_fingerprint') or 'legacy-domain'),
                    'route_signature': str(data.get('route_signature') or ''),
                    'query_signature': str(data.get('query_signature') or ''),
                },
                'acts': data.get('acts') or [],
                'provenance': {
                    key: value
                    for key, value in data.items()
                    if key in {'discovered_at', 'replay_count', 'last_replayed_at'}
                },
            }
        return data


class Recipe(BaseModel):
    """Flat shareable recipe: contract + selectors + optional actions + evidence.

    ``recipe_id`` is the sha256 of a deep-canonical JSON payload excluding the
    ``recipe_id`` field itself. Duplicate content therefore mints the same ID.
    """

    recipe_id: str = ''
    instructions: list[str] = Field(default_factory=list)
    contract: ContractSpec
    selectors: dict[str, SnapshotMap] = Field(default_factory=dict)
    a3nodes: list[RecipeA3Node] = Field(default_factory=list)
    validation: RecipeValidation = Field(default_factory=RecipeValidation)
    metadata: RecipeMetadata = Field(default_factory=RecipeMetadata)

    @model_validator(mode='before')
    @classmethod
    def _fill_selector_domains(cls, data: Any) -> Any:
        """Allow compact recipe JSON where selector domain is implied by key."""
        if not isinstance(data, dict):
            return data
        selectors = data.get('selectors')
        if not isinstance(selectors, dict):
            return data
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
        source_urls = metadata.get('source_urls') if isinstance(metadata, dict) else []
        url_patterns = metadata.get('url_patterns') if isinstance(metadata, dict) else []
        updated = dict(data)
        updated_selectors = {}
        for domain, value in selectors.items():
            if isinstance(value, dict):
                value = dict(value)
                value.setdefault('domain', domain)
                value.setdefault('url', _source_url_for_domain(domain, source_urls, url_patterns))
            updated_selectors[domain] = value
        updated['selectors'] = updated_selectors
        return updated

    @model_validator(mode='after')
    def _fill_recipe_id(self) -> Recipe:
        """Compute identity and human runbook instructions when absent."""
        if not self.recipe_id:
            object.__setattr__(self, 'recipe_id', self.compute_id())
        elif not self.recipe_id.startswith(RECIPE_ID_PREFIX):
            raise ValueError(f'recipe_id must start with {RECIPE_ID_PREFIX!r}')
        if not self.instructions:
            object.__setattr__(self, 'instructions', self.default_instructions())
        return self

    def identity_payload(self) -> dict[str, Any]:
        """Return the portable semantic payload that participates in identity.

        Provenance metadata is intentionally excluded so re-minting the same
        contract/selectors/evidence later produces the same ``recipe_id``.
        """
        payload = self.model_dump(mode='json', by_alias=True)
        payload.pop('recipe_id', None)
        payload.pop('instructions', None)
        metadata = payload.get('metadata')
        if isinstance(metadata, dict):
            metadata.pop('created_at', None)
            metadata.pop('created_by', None)
            metadata.pop('notes', None)
        _strip_selector_provenance(payload.get('selectors'))
        _strip_a3node_provenance(payload.get('a3nodes'))
        return payload

    def compute_id(self) -> str:
        """Return the stable sha256 recipe identity for this artifact."""
        encoded = canonical_json_bytes(self.identity_payload())
        return RECIPE_ID_PREFIX + hashlib.sha256(encoded).hexdigest()

    def verify_integrity(self) -> None:
        """Fail if ``recipe_id`` does not match the canonical payload."""
        expected = self.compute_id()
        if self.recipe_id != expected:
            raise ValueError(f'Recipe integrity check failed: stored {self.recipe_id!r}, computed {expected!r}')

    def canonical_json(self) -> str:
        """Return stable pretty JSON for storage and review.

        JSON has no comments, so recipes carry a top-level ``instructions``
        runbook instead. It is emitted first for humans and excluded from the
        identity hash so operational guidance can evolve without changing the
        recipe's semantic identity.
        """
        return _recipe_review_json(_compact_recipe_payload(self.model_dump(mode='json', by_alias=True))) + '\n'

    def default_instructions(self) -> list[str]:
        """Return human instructions embedded at the top of minted recipes."""
        return [
            'Yosoi recipe JSON. JSON does not support comments; these instructions are data, not identity.',
            'Inspect: yosoi recipe inspect <this-file>',
            f'Verify: yosoi recipe check <this-file> --recipe-id {self.recipe_id}',
            'Install locally: yosoi recipe install <this-file>',
            'Publish to GitHub: yosoi recipe publish <this-file> -r OWNER/REPO',
            'Publish to secret/unlisted Gist: yosoi recipe publish <this-file> --gist',
            f'Remote install: yosoi recipe install <raw-url-or-gh-ref> --recipe-id {self.recipe_id}',
        ]

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


def _source_url_for_domain(domain: str, source_urls: Any, url_patterns: Any) -> str:
    """Pick a source URL for legacy SnapshotMap compatibility."""
    if isinstance(source_urls, list):
        for url in source_urls:
            if isinstance(url, str) and domain in url:
                return url
    if isinstance(url_patterns, list):
        for pattern in url_patterns:
            if isinstance(pattern, str) and domain in pattern:
                return pattern.replace('*', '').rstrip('/') or f'https://{domain}/'
    return f'https://{domain}/'


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
        snap_map.pop('domain', None)
        snap_map.pop('url', None)
        snapshots = snap_map.get('snapshots')
        if not isinstance(snapshots, dict):
            continue
        for snapshot in snapshots.values():
            if isinstance(snapshot, dict):
                for key in volatile:
                    snapshot.pop(key, None)


def _strip_a3node_provenance(value: Any) -> None:
    """Remove volatile A3Node audit fields from identity in place."""
    if not isinstance(value, list):
        return
    for node in value:
        if isinstance(node, dict):
            node.pop('provenance', None)


def _deep_canonical(value: Any) -> Any:
    """Recursively sort JSON object keys while preserving list order."""
    if isinstance(value, dict):
        return {k: _deep_canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_deep_canonical(item) for item in value]
    return value


def _compact_recipe_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Remove fields that are redundant in recipe JSON but restorable on load."""
    compact = dict(value)
    selectors = compact.get('selectors')
    if isinstance(selectors, dict):
        compact_selectors = {}
        for domain, snap_map in selectors.items():
            if isinstance(snap_map, dict):
                snap_map = dict(snap_map)
                if snap_map.get('domain') == domain:
                    snap_map.pop('domain', None)
                snap_map.pop('url', None)
            compact_selectors[domain] = snap_map
        compact['selectors'] = compact_selectors
    return compact


def _recipe_review_json(value: dict[str, Any]) -> str:
    """Serialize a recipe for human review with instructions first."""
    order = (
        'instructions',
        'recipe_id',
        'contract',
        'selectors',
        'a3nodes',
        'validation',
        'metadata',
    )
    ordered = {key: _deep_canonical(value[key]) for key in order if key in value}
    for key in sorted(value):
        if key not in ordered:
            ordered[key] = _deep_canonical(value[key])
    return json.dumps(ordered, ensure_ascii=False, indent=2)


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
