"""Shareable recipe artifact: ContractSpec + domain selectors bundled together.

A RecipeBundle is the unit of sharing in Yosoi's recipe registry. It contains
everything needed to scrape a known web surface with zero LLM calls:

- The contract definition (field names, yosoi types, root selector)
- The verified selector snapshots, keyed by domain

Usage::

    # Producer: mint a recipe after discovery
    bundle = RecipeBundle.from_parts(contract_cls, {"example.com": snapshot_map})
    bundle.save("/path/to/recipe.json")

    # Consumer: load and scrape
    items = await ys.scrape(url, contract="https://raw.github.com/.../recipe.json")

File format::

    {
        "schema_version": "yosoi.recipe.v1",
        "recipe_id": "<sha256 of canonical content>",
        "created_at": "2026-06-03T00:00:00Z",
        "contract": { ...ContractSpec... },
        "selectors": {
            "example.com": { ...SnapshotMap... }
        }
    }

The ``recipe_id`` is a sha256 of the canonical JSON (keys sorted, no
whitespace) of the ``contract`` + ``selectors`` fields. It is verified on
load so a truncated download or accidental edit is caught immediately.

Future: the ``selectors`` dict key will become a structured
``(domain, contract_sig, page_shape)`` triple once the page fingerprint is
threaded through the storage layer. For now it is a bare domain string.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from yosoi.models.snapshot import SnapshotMap
from yosoi.models.spec import ContractSpec

RECIPE_SCHEMA_VERSION = 'yosoi.recipe.v1'
SUPPORTED_SCHEMA_VERSIONS = frozenset({'yosoi.recipe.v1'})


class RecipeBundle(BaseModel):
    """Shareable artifact: contract definition + verified selector snapshots.

    Attributes:
        schema_version: Format identifier. Bump when the shape changes.
        recipe_id: sha256 of the canonical content for integrity checking.
        created_at: UTC timestamp when the recipe was minted.
        created_by: Optional free-text provenance (tool name, username, etc.).
        contract: The serialised contract definition.
        selectors: Per-domain verified selector snapshots.
            Key is the bare domain string (e.g. ``'example.com'``).
            Future: will become a ``(domain, contract_sig, page_shape)``
            structured key once page fingerprinting is threaded through.
    """

    schema_version: str = RECIPE_SCHEMA_VERSION
    recipe_id: str = ''
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = 'yosoi'
    contract: ContractSpec
    selectors: dict[str, SnapshotMap] = Field(default_factory=dict)

    @model_validator(mode='after')
    def _ensure_recipe_id(self) -> RecipeBundle:
        """Compute recipe_id if not already set."""
        if not self.recipe_id:
            object.__setattr__(self, 'recipe_id', self._compute_id())
        return self

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_parts(
        cls,
        contract: type,  # type[Contract] — avoid circular import
        snapshots: dict[str, SnapshotMap],
        *,
        created_by: str = 'yosoi',
    ) -> RecipeBundle:
        """Build a RecipeBundle from a live Contract class and snapshot maps.

        Args:
            contract: The Contract subclass used for discovery.
            snapshots: Mapping of domain → SnapshotMap from the selector store.
            created_by: Optional provenance string.

        Returns:
            A new RecipeBundle ready to save or publish.
        """
        spec = ContractSpec.from_contract(contract)
        return cls(
            contract=spec,
            selectors=snapshots,
            created_by=created_by,
        )

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    def _compute_id(self) -> str:
        """sha256 of canonical JSON of contract + selectors."""
        payload = json.dumps(
            {
                'contract': self.contract.model_dump(mode='json'),
                'selectors': {domain: snap_map.model_dump(mode='json') for domain, snap_map in self.selectors.items()},
            },
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
        )
        return 'sha256:' + hashlib.sha256(payload.encode()).hexdigest()

    def verify_integrity(self) -> None:
        """Raise ValueError if the recipe_id does not match the content.

        Call this after loading a recipe from an external source.

        Raises:
            ValueError: When the computed id does not match the stored id,
                indicating corruption or tampering.
        """
        if not self.recipe_id:
            raise ValueError('Recipe has no recipe_id — cannot verify integrity.')
        expected = self._compute_id()
        if self.recipe_id != expected:
            raise ValueError(
                f'Recipe integrity check failed.\n'
                f'  stored:   {self.recipe_id}\n'
                f'  computed: {expected}\n'
                'The file may be corrupted or was modified after minting.'
            )

    # ------------------------------------------------------------------
    # Schema validation
    # ------------------------------------------------------------------

    def verify_schema(self) -> None:
        """Raise ValueError if the schema_version is not supported.

        Raises:
            ValueError: When the schema_version is unknown or newer than
                this version of Yosoi supports.
        """
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f'Unsupported recipe schema_version {self.schema_version!r}. '
                f'This version of Yosoi supports: {sorted(SUPPORTED_SCHEMA_VERSIONS)}. '
                'Upgrade yosoi to use this recipe.'
            )

    # ------------------------------------------------------------------
    # Field / selector alignment check
    # ------------------------------------------------------------------

    def verify_alignment(self) -> list[str]:
        """Check that contract fields are present in the selector snapshots.

        Returns a list of warning strings (empty = fully aligned). Does NOT
        raise — alignment issues are warnings, not hard failures, because a
        recipe may intentionally cover only a subset of domains.

        A field is considered covered when it appears in at least one
        domain's snapshot map with ACTIVE status.
        """
        contract_fields = set(self.contract.fields.keys())
        covered: set[str] = set()
        for snap_map in self.selectors.values():
            for field_name, snap in snap_map.snapshots.items():
                if snap.is_active:
                    covered.add(field_name)

        missing = contract_fields - covered
        if not missing:
            return []
        return [f'Contract field {f!r} has no active selector in any bundled domain.' for f in sorted(missing)]

    # ------------------------------------------------------------------
    # Selector lookup
    # ------------------------------------------------------------------

    def snapshots_for_domain(self, domain: str) -> SnapshotMap | None:
        """Return the SnapshotMap for a domain, or None if not in the bundle.

        Tries an exact match first, then a bare-domain (no subdomain) fallback
        so ``www.example.com`` can match an ``example.com`` entry.

        Args:
            domain: Bare domain string (e.g. ``'qscrape.dev'``).

        Returns:
            SnapshotMap or None.
        """
        if domain in self.selectors:
            return self.selectors[domain]
        # Subdomain fallback: strip one leading label
        parts = domain.split('.', 1)
        if len(parts) == 2:
            return self.selectors.get(parts[1])
        return None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialise the bundle to a JSON string."""
        return self.model_dump_json(indent=indent)

    def save(self, path: str) -> None:
        """Write the bundle to a local file atomically.

        Uses :func:`~yosoi.utils.files.atomic_write_text` so a crash or kill
        mid-write never leaves a truncated file.

        Args:
            path: Destination file path (should end in ``.json``).
        """
        from yosoi.utils.files import atomic_write_text

        atomic_write_text(path, self.to_json())

    @classmethod
    def load(cls, path: str) -> RecipeBundle:
        """Read and validate a bundle from a local file.

        Performs schema check and integrity verification.

        Args:
            path: Local file path.

        Returns:
            Validated RecipeBundle.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: On schema or integrity failure.
        """
        with open(path, encoding='utf-8') as f:
            raw = f.read()
        bundle = cls.model_validate_json(raw)
        bundle.verify_schema()
        bundle.verify_integrity()
        return bundle

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a compact summary dict for display / logging."""
        return {
            'schema_version': self.schema_version,
            'recipe_id': self.recipe_id,
            'created_at': self.created_at.isoformat(),
            'created_by': self.created_by,
            'contract': self.contract.name,
            'fields': list(self.contract.fields.keys()),
            'domains': list(self.selectors.keys()),
        }
