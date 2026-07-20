"""Long-term fingerprint cache and classification audit trail.

Storage root defaults to ``.yosoi/fingerprint/`` and is deliberately separate from
crawler storage. Crawlers, scrape flows, demos, and future classifier modules can all
share the same reference/page/field/classification evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from yosoi.fingerprints.models import (
    FingerprintClassificationRecord,
    FingerprintFieldReferenceRecord,
    FingerprintPageRecord,
    FingerprintReferenceRecord,
)
from yosoi.utils.files import atomic_write_text, init_yosoi

_SAFE_TOKEN_RE = re.compile(r'[^A-Za-z0-9_.-]+')


def fingerprint_store_path() -> Path:
    """Return the default ``.yosoi/fingerprint`` cache directory, creating it if needed."""
    return init_yosoi('fingerprint')


def url_key(url: str) -> str:
    """Stable short cache key for a URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def safe_token(value: str) -> str:
    """Return a filesystem-safe token while preserving readable labels where possible."""
    token = _SAFE_TOKEN_RE.sub('_', value).strip('._-')
    return token or hashlib.sha256(value.encode()).hexdigest()[:16]


class FingerprintStore:
    """Filesystem-backed cache for fingerprints and append-only classification audit records."""

    def __init__(self, root: str | Path | None = None) -> None:
        """Initialise the store under ``root`` or the default ``.yosoi/fingerprint`` path."""
        self.root = Path(root) if root is not None else fingerprint_store_path()
        self.pages_dir = self.root / 'pages'
        self.references_dir = self.root / 'references'
        self.classifications_dir = self.root / 'classifications'
        for directory in (self.pages_dir, self.references_dir, self.classifications_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def save_page(self, record: FingerprintPageRecord) -> Path:
        """Persist a fetched page fingerprint, keyed by URL hash."""
        path = self.page_path(record.url)
        _write_model(path, record)
        return path

    def load_page(self, url: str) -> FingerprintPageRecord | None:
        """Load a page fingerprint by URL, or ``None`` when absent."""
        path = self.page_path(url)
        if not path.exists():
            return None
        return FingerprintPageRecord.model_validate_json(path.read_text(encoding='utf-8'))

    def page_path(self, url: str) -> Path:
        """Return the cache path for a page URL."""
        return self.pages_dir / f'{url_key(url)}.json'

    def save_reference(self, record: FingerprintReferenceRecord) -> Path:
        """Persist a named page-level reference fingerprint under its contract namespace."""
        path = self.reference_path(record.reference_id, contract_fingerprint=record.contract_fingerprint)
        _write_model(path, record)
        return path

    def load_reference(
        self,
        reference_id: str,
        *,
        contract_fingerprint: str | None = None,
    ) -> FingerprintReferenceRecord | None:
        """Load a named page-level reference, optionally scoped to a contract fingerprint."""
        path = self.reference_path(reference_id, contract_fingerprint=contract_fingerprint)
        if path.exists():
            return FingerprintReferenceRecord.model_validate_json(path.read_text(encoding='utf-8'))
        if contract_fingerprint is not None:
            return None
        matches = list(self.references_dir.glob(f'*/{safe_token(reference_id)}.json'))
        if len(matches) != 1:
            return None
        return FingerprintReferenceRecord.model_validate_json(matches[0].read_text(encoding='utf-8'))

    def list_references(self, *, contract_fingerprint: str | None = None) -> list[FingerprintReferenceRecord]:
        """Return all stored page-level references, optionally filtered to one contract fingerprint."""
        base = (
            self.references_dir / safe_token(contract_fingerprint or 'unscoped')
            if contract_fingerprint
            else self.references_dir
        )
        paths = sorted(base.glob('*.json') if contract_fingerprint else base.glob('*/*.json'))
        return [FingerprintReferenceRecord.model_validate_json(path.read_text(encoding='utf-8')) for path in paths]

    def save_field_reference(self, record: FingerprintFieldReferenceRecord) -> Path:
        """Persist a field/root-scoped reference without overwriting extractor conflicts."""
        path = self.field_reference_path(
            record.reference_id,
            field_name=record.field_name,
            contract_fingerprint=record.contract_fingerprint,
        )
        if path.exists():
            existing = FingerprintFieldReferenceRecord.model_validate_json(path.read_text(encoding='utf-8'))
            if (existing.extractor is not None or record.extractor is not None) and (
                existing.extractor != record.extractor or existing.selector != record.selector
            ):
                raise ValueError(
                    f'conflicting extractor strategy for reference {record.reference_id!r}; use a distinct reference id'
                )
        _write_model(path, record)
        return path

    def load_field_reference(
        self,
        reference_id: str,
        *,
        field_name: str,
        contract_fingerprint: str | None = None,
    ) -> FingerprintFieldReferenceRecord | None:
        """Load a field/root-scoped reference by id, field, and optional contract namespace."""
        path = self.field_reference_path(reference_id, field_name=field_name, contract_fingerprint=contract_fingerprint)
        if not path.exists():
            return None
        return FingerprintFieldReferenceRecord.model_validate_json(path.read_text(encoding='utf-8'))

    def list_field_references(
        self,
        *,
        field_name: str | None = None,
        contract_fingerprint: str | None = None,
    ) -> list[FingerprintFieldReferenceRecord]:
        """Return stored field/root references, optionally filtered by contract and field."""
        if contract_fingerprint is None:
            base = self.references_dir
            pattern = f'*/fields/{safe_token(field_name)}/*.json' if field_name else '*/fields/*/*.json'
        else:
            base = self.references_dir / safe_token(contract_fingerprint or 'unscoped')
            pattern = f'fields/{safe_token(field_name)}/*.json' if field_name else 'fields/*/*.json'
        paths = sorted(base.glob(pattern))
        return [FingerprintFieldReferenceRecord.model_validate_json(path.read_text(encoding='utf-8')) for path in paths]

    def append_classification(self, record: FingerprintClassificationRecord) -> Path:
        """Append one classification audit event to ``classifications/<run_id>.jsonl``.

        Uses ``O_APPEND`` plus ``fsync`` so concurrent writers do not read/rewrite and lose
        each other's audit events. A crash can lose the current line, but cannot truncate the
        existing audit trail.
        """
        path = self.classification_path(record.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (record.model_dump_json() + '\n').encode('utf-8')
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        return path

    def load_classifications(self, run_id: str) -> list[FingerprintClassificationRecord]:
        """Load every classification audit event for a run id."""
        path = self.classification_path(run_id)
        if not path.exists():
            return []
        return [
            FingerprintClassificationRecord.model_validate_json(line)
            for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()
        ]

    def classification_path(self, run_id: str) -> Path:
        """Return the JSONL audit path for a run id."""
        return self.classifications_dir / f'{safe_token(run_id)}.jsonl'

    def reference_path(self, reference_id: str, *, contract_fingerprint: str | None = None) -> Path:
        """Return the cache path for a named page-level reference."""
        namespace = safe_token(contract_fingerprint or 'unscoped')
        return self.references_dir / namespace / f'{safe_token(reference_id)}.json'

    def field_reference_path(
        self,
        reference_id: str,
        *,
        field_name: str,
        contract_fingerprint: str | None = None,
    ) -> Path:
        """Return the cache path for a field/root-scoped reference."""
        namespace = safe_token(contract_fingerprint or 'unscoped')
        return self.references_dir / namespace / 'fields' / safe_token(field_name) / f'{safe_token(reference_id)}.json'


def _write_model(
    path: Path,
    record: FingerprintPageRecord | FingerprintReferenceRecord | FingerprintFieldReferenceRecord,
) -> None:
    payload = record.model_dump(mode='json')
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + '\n')


__all__ = ['FingerprintStore', 'fingerprint_store_path', 'safe_token', 'url_key']
