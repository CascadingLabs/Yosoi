"""Local content-addressed contracts store (CAS-122).

Layout:
  .yosoi/contracts/<fingerprint>.json  — the spec files, keyed by fingerprint
  .yosoi/contracts/names.json          — name → fingerprint alias map

Git-as-registry: the entire `.yosoi/contracts/` tree is diffable/reviewable.
Sharing is git-clone or curl-drop — no service required.

Collision rules:
  - same name + same fingerprint  → idempotent no-op
  - same name + different fp      → refuse (non-fast-forward; show both fps)
  - different name + same fp      → fine; two aliases for one cache entry
"""

from __future__ import annotations

import json
import os
import pathlib

from yosoi.models.spec import CURRENT_SCHEMA_VERSION, ContractSpec


class ContractCollisionError(ValueError):
    """Raised when an alias would silently re-point to a different fingerprint."""

    def __init__(self, name: str, existing_fp: str, new_fp: str) -> None:
        """Initialize with the conflicting name and both fingerprints."""
        self.name = name
        self.existing_fp = existing_fp
        self.new_fp = new_fp
        super().__init__(
            f'Contract name {name!r} already points to fingerprint {existing_fp!r}; '
            f'new spec has fingerprint {new_fp!r}. '
            f'Rename the alias or update it explicitly.'
        )


class ContractStore:
    """Content-addressed local store for ContractSpec objects.

    Typically lives under ``.yosoi/contracts/`` relative to the working directory,
    but the path can be overridden for testing.
    """

    def __init__(self, store_dir: str | None = None) -> None:
        """Initialize the store at the given directory (default: ``.yosoi/contracts``)."""
        self._root = pathlib.Path(store_dir or os.path.join('.yosoi', 'contracts'))

    def _ensure_dir(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    # ── internal paths ────────────────────────────────────────────────────────

    def _spec_path(self, fingerprint: str) -> pathlib.Path:
        return self._root / f'{fingerprint}.json'

    @property
    def _names_path(self) -> pathlib.Path:
        return self._root / 'names.json'

    # ── low-level I/O ─────────────────────────────────────────────────────────

    def _load_names(self) -> dict[str, str]:
        if not self._names_path.exists():
            return {}
        try:
            raw: object = json.loads(self._names_path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                return {str(k): str(v) for k, v in raw.items()}
            return {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_names(self, names: dict[str, str]) -> None:
        self._ensure_dir()
        self._names_path.write_text(
            json.dumps(names, indent=2, sort_keys=True) + '\n',
            encoding='utf-8',
        )

    # ── public API ────────────────────────────────────────────────────────────

    def add(self, spec: ContractSpec, name: str | None = None) -> str:
        """Write a spec to the store and optionally register a name alias.

        Returns the fingerprint.

        Raises:
            ContractCollisionError: If ``name`` is already registered to a
                different fingerprint (git non-fast-forward style).
        """
        self._ensure_dir()
        fp = spec.fingerprint
        alias = name or spec.name

        # Enforce collision rules before touching disk
        names = self._load_names()
        existing_fp = names.get(alias)
        if existing_fp is not None and existing_fp != fp:
            raise ContractCollisionError(alias, existing_fp, fp)

        # Write spec file (content-addressed — idempotent)
        spec_path = self._spec_path(fp)
        if not spec_path.exists():
            spec_path.write_text(spec.model_dump_json(indent=2), encoding='utf-8')

        # Update alias map
        if existing_fp != fp:
            names[alias] = fp
            self._save_names(names)

        return fp

    def get(self, name_or_fp: str) -> ContractSpec:
        """Return a ContractSpec by name alias or raw fingerprint.

        Raises:
            KeyError: If the name or fingerprint is not found.
        """
        # Try as a direct fingerprint first
        direct = self._spec_path(name_or_fp)
        if direct.exists():
            return ContractSpec.model_validate_json(direct.read_text(encoding='utf-8'))

        # Try as a name alias
        names = self._load_names()
        fp = names.get(name_or_fp)
        if fp is None:
            raise KeyError(
                f'Contract {name_or_fp!r} not found. Available names: {", ".join(sorted(names)) or "(none)"}'
            )
        spec_path = self._spec_path(fp)
        if not spec_path.exists():
            raise KeyError(
                f'Alias {name_or_fp!r} → {fp!r} found in names.json but '
                f'spec file {spec_path} is missing. Store may be corrupted.'
            )
        return ContractSpec.model_validate_json(spec_path.read_text(encoding='utf-8'))

    def list_aliases(self) -> list[tuple[str, str]]:
        """Return [(name, fingerprint), ...] for all registered aliases, sorted."""
        return sorted(self._load_names().items())

    def fingerprints(self) -> list[str]:
        """Return all fingerprints currently stored (including un-aliased specs)."""
        if not self._root.exists():
            return []
        return [p.stem for p in sorted(self._root.glob('*.json')) if p.name != 'names.json']

    def lint(self, spec: ContractSpec) -> list[str]:
        """Validate a spec for known governance issues.

        Returns a list of error strings (empty = clean).
        """
        errors: list[str] = []
        if spec.schema_version > CURRENT_SCHEMA_VERSION:
            errors.append(
                f'schema_version {spec.schema_version} is newer than supported '
                f'({CURRENT_SCHEMA_VERSION}). Upgrade yosoi to use this spec.'
            )
        elif spec.schema_version < 1:
            errors.append(f'schema_version {spec.schema_version} is invalid (must be >= 1).')
        return errors

    def migrate(self, spec: ContractSpec) -> ContractSpec:
        """Migrate a spec forward to the current schema version.

        For v1 (the only version), this is a no-op.  When future versions exist,
        this method will apply the upgrade chain.
        """
        if spec.schema_version == CURRENT_SCHEMA_VERSION:
            return spec
        if spec.schema_version < 1:
            raise ValueError(f'Cannot migrate schema_version {spec.schema_version}: too old.')
        # Future upgrade chain goes here.
        return spec.model_copy(update={'schema_version': CURRENT_SCHEMA_VERSION})
