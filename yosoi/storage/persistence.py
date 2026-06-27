"""Handles selector and extracted-content state in SQLite."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from yosoi.models.snapshot import (
    CacheVerdict,
    SelectorSnapshot,
    SnapshotStatus,
    selector_dict_to_snapshot,
    snapshot_to_selector_dict,
)
from yosoi.utils.files import atomic_write_json_async, init_yosoi, safe_domain
from yosoi.utils.urls import extract_domain

if TYPE_CHECKING:
    from yosoi.models.contract import Contract


class SelectorStorage:
    """Manages selector and content state in `.yosoi/yosoi.sqlite3`.

    Attributes:
        content_dir: Directory path where opt-in extracted-content flat files are stored.

    """

    def __init__(self, content_dir: str | Path = 'content', *, flat_files: bool = False):
        """Initialize the storage manager.

        Args:
            content_dir: Directory path for opt-in extracted-content flat files. Defaults to 'content'.
            flat_files: Also write extracted content as files. SQLite remains the source of truth.

        """
        yosoi_dir = init_yosoi()
        self.content_dir = str(yosoi_dir / Path(content_dir))
        self.database_path = yosoi_dir / 'yosoi.sqlite3'
        self.flat_files = flat_files

    async def save_selectors(
        self,
        url: str,
        selectors: dict[str, Any],
        *,
        verified: bool = False,
        contract_sig: str | None = None,
        contract: type[Contract] | None = None,
    ) -> str:
        """Save selectors as snapshot format.

        Wraps each field's selector dict in a SelectorSnapshot with a
        ``discovered_at`` timestamp, then writes the snapshots to SQLite.

        Args:
            url: URL the selectors were discovered from
            selectors: Dictionary of validated selectors
            verified: When True, stamp each snapshot with ``last_verified_at=now``.
            contract_sig: Optional contract signature for isolated selector cache files.
            contract: Optional Contract class used to persist normalized contract/field entities.

        Returns:
            Path to the saved file.

        """
        now = datetime.now(timezone.utc)
        formatted = self._format_selectors(selectors)
        snapshots: dict[str, SelectorSnapshot] = {}
        for field_name, field_data in formatted.items():
            snapshots[field_name] = selector_dict_to_snapshot(
                field_data, discovered_at=now, last_verified_at=now if verified else None
            )
        return await self.save_snapshots(url, snapshots, contract_sig=contract_sig, contract=contract)

    async def load_selectors(self, domain: str, contract_sig: str | None = None) -> dict[str, Any] | None:
        """Load selectors from the SQLite snapshot store.

        Strips audit metadata — callers receive
        ``{field: {primary, fallback, tertiary}}`` shape.

        Args:
            domain: Domain name (e.g., 'example.com')
            contract_sig: Optional contract signature for isolated selector cache files.

        Returns:
            Dictionary of selectors, or None if not found or error occurred.

        """
        snapshots = await self.load_snapshots(domain, contract_sig=contract_sig)
        if snapshots is None:
            return None
        return {name: data for name, snap in snapshots.items() if (data := snapshot_to_selector_dict(snap))}

    async def load_field_selector(
        self, domain: str, field_name: str, contract_sig: str | None = None
    ) -> dict[str, Any] | None:
        """Return raw selector dict for a single field, or None if not cached.

        Args:
            domain: Domain name (e.g., 'example.com')
            field_name: Field name to look up
            contract_sig: Optional contract signature for isolated selector cache files.

        Returns:
            Dict with primary/fallback/tertiary keys, or None if not found.

        """
        data = await self.load_selectors(domain, contract_sig=contract_sig)
        if data is None:
            return None
        entry = data.get(field_name)
        return entry if isinstance(entry, dict) else None

    async def selector_exists(self, domain: str, contract_sig: str | None = None) -> bool:
        """Check if selectors exist for a domain.

        Args:
            domain: Domain name to check
            contract_sig: Optional contract signature for isolated selector cache files.

        Returns:
            True if selector file exists for the domain, False otherwise.

        """
        from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore

        async with LibSQLCacheMetricsStore(self.database_path) as metrics_store:
            return await metrics_store.selector_exists(domain, contract_fingerprint=contract_sig)

    async def save_content(
        self,
        url: str,
        content: dict[str, Any] | list[dict[str, Any]],
        output_format: str = 'json',
        contract_sig: str | None = None,
    ) -> str:
        """Save extracted content to SQLite, optionally mirroring to a flat file.

        Args:
            url: URL the content was extracted from
            content: Dictionary of extracted content or list of dicts for multi-item pages
            output_format: Output format ('json' or 'markdown'). Defaults to 'json'.
            contract_sig: Optional contract signature for stable, unique filenames.

        Returns:
            Path to the saved file.

        """
        domain = self._extract_domain(url)
        self._save_content_sqlite(url, domain, content, output_format, contract_sig)

        filepath = self._get_content_filepath(url, output_format, contract_sig)
        if self.flat_files:
            from yosoi.outputs.utils import save_formatted_content

            # Output savers include binary/tabular writers (pandas, pyarrow, openpyxl)
            # that have no async API; keep one synchronous dispatch path for every format.
            save_formatted_content(filepath, url, domain, content, output_format)
            logger.info('Saved content flat file to: %s', filepath)

        logger.info('Saved content to SQLite: %s', self.database_path)
        return str(self.database_path)

    async def load_content(
        self, url: str, contract_sig: str | None = None
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Load extracted content from SQLite, with legacy JSON-file fallback.

        Args:
            url: URL to load content for
            contract_sig: Optional contract signature (must match the one used when saving).

        Returns:
            Single content dict, list of item dicts for multi-item pages, or None.

        """
        row = self._load_content_sqlite(url, contract_sig=contract_sig)
        if row is not None:
            return row

        filepath = self._get_content_filepath(url, contract_sig=contract_sig)
        return self._load_content_sync(filepath)

    async def content_exists(self, url: str, contract_sig: str | None = None) -> bool:
        """Check if extracted content exists for a URL.

        Args:
            url: URL to check
            contract_sig: Optional contract signature (must match the one used when saving).

        Returns:
            True if content file exists for the URL, False otherwise.

        """
        if self._content_exists_sqlite(url, contract_sig=contract_sig):
            return True
        filepath = self._get_content_filepath(url, contract_sig=contract_sig)
        return self._file_exists_sync(filepath)

    async def list_domains(self) -> list[str]:
        """List all domains with saved selectors.

        Reads the current selector snapshot rows from the local SQLite database.

        Returns:
            Sorted list of domain names with saved selectors.

        """
        from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore

        async with LibSQLCacheMetricsStore(self.database_path) as metrics_store:
            return await metrics_store.list_domains()

    async def get_summary(self) -> dict[str, Any]:
        """Get summary of all saved selectors.

        Returns:
            Dictionary containing 'total_domains' count and list of domain details.
            Each domain includes 'domain', 'discovered_at', and 'fields' keys.

        """
        domains = await self.list_domains()

        summary: dict[str, Any] = {'total_domains': len(domains), 'domains': []}

        for domain in domains:
            snapshots = await self.load_snapshots(domain)
            if snapshots:
                # Use earliest discovered_at as the domain-level timestamp
                earliest = min((s.discovered_at for s in snapshots.values()), default=None)
                health_counts = {status.value: 0 for status in SnapshotStatus}
                for snap in snapshots.values():
                    health_counts[snap.status.value] += 1
                summary['domains'].append(
                    {
                        'domain': domain,
                        'discovered_at': earliest.isoformat() if earliest else None,
                        'fields': list(snapshots.keys()),
                        'health': health_counts,
                    }
                )

        return summary

    # ------------------------------------------------------------------
    # Snapshot API (v2)
    # ------------------------------------------------------------------

    async def load_snapshots(self, domain: str, contract_sig: str | None = None) -> dict[str, SelectorSnapshot] | None:
        """Load full SQLite snapshots with audit metadata for a domain.

        Args:
            domain: Domain name (e.g., 'example.com')
            contract_sig: Optional contract signature for isolated selector cache files.

        Returns:
            Dict mapping field names to SelectorSnapshot, or None if not found.

        """
        from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore

        async with LibSQLCacheMetricsStore(self.database_path) as metrics_store:
            return await metrics_store.load_snapshots(domain, contract_fingerprint=contract_sig)

    async def save_snapshots(
        self,
        url: str,
        snapshots: dict[str, SelectorSnapshot],
        contract_sig: str | None = None,
        contract: type[Contract] | None = None,
    ) -> str:
        """Write current selector snapshots to the local SQLite database.

        Args:
            url: URL the selectors were discovered from
            snapshots: Dict mapping field names to SelectorSnapshot
            contract_sig: Optional contract signature for isolated selector cache files.
            contract: Optional Contract class used to persist normalized contract/field entities.

        Returns:
            Path to the saved file.

        """
        domain = self._extract_domain(url)
        from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore
        from yosoi.utils.signatures import contract_signature

        contract_fp = contract_sig or (contract_signature(contract) if contract is not None else None)
        async with LibSQLCacheMetricsStore(self.database_path) as metrics_store:
            await metrics_store.upsert_snapshots(
                url=url,
                domain=domain,
                snapshots=snapshots,
                contract_fingerprint=contract_fp,
                contract=contract,
            )

        logger.info('Saved snapshots for %s to: %s', domain, self.database_path)
        return str(self.database_path)

    async def record_verdict(
        self, domain: str, field_name: str, verdict: CacheVerdict, contract_sig: str | None = None
    ) -> None:
        """Update the audit trail for a single field after verification.

        Args:
            domain: Domain name
            field_name: Field whose verdict to record
            verdict: FRESH, STALE, or DEGRADED
            contract_sig: Optional contract signature for isolated selector cache files.

        """
        from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore

        async with LibSQLCacheMetricsStore(self.database_path) as metrics_store:
            await metrics_store.record_verdict(
                domain=domain,
                field_name=field_name,
                verdict=verdict,
                contract_fingerprint=contract_sig,
            )

    def _format_selectors(self, selectors: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Format selectors for storage.

        Args:
            selectors: Raw selectors dictionary

        Returns:
            Formatted selectors with primary, fallback, and tertiary keys.

        """
        formatted: dict[str, dict[str, Any]] = {}

        for field, field_data in selectors.items():
            if isinstance(field_data, dict):
                formatted[field] = {
                    'primary': field_data.get('primary'),
                    'fallback': field_data.get('fallback'),
                    'tertiary': field_data.get('tertiary'),
                }
                if field_data.get('root') is not None:
                    formatted[field]['root'] = field_data.get('root')

        return formatted

    def _extract_domain(self, url: str) -> str:
        """Extract the normalized domain from a URL (single source of truth)."""
        return extract_domain(url)

    def _get_content_filepath(self, url: str, output_format: str = 'json', contract_sig: str | None = None) -> str:
        """Get filepath for a URL's extracted content.

        Accumulating formats (jsonl, csv, xlsx, parquet) share a single results file
        per domain. Per-URL formats (json, markdown) produce one file per URL.

        Args:
            url: Full URL
            output_format: Output format. Defaults to 'json'.
            contract_sig: Optional contract signature hash. When provided, filenames
                embed both the contract signature and a URL hash so multiple URLs with
                the same path but different query strings produce distinct files.

        Returns:
            Full file path for the URL's content file.

        """
        import hashlib

        _ACCUMULATING = {'jsonl', 'ndjson', 'csv', 'xlsx', 'parquet'}
        _EXTENSIONS = {
            'json': 'json',
            'markdown': 'md',
            'jsonl': 'jsonl',
            'ndjson': 'jsonl',
            'csv': 'csv',
            'xlsx': 'xlsx',
            'parquet': 'parquet',
        }

        parsed = urlparse(url)
        domain = extract_domain(url)
        safe = safe_domain(domain)
        ext = _EXTENSIONS.get(output_format, 'json')
        domain_dir = os.path.join(self.content_dir, safe)

        if output_format in _ACCUMULATING:
            return os.path.join(domain_dir, f'results.{ext}')

        # Per-URL (json, markdown) — derive filename from URL path or contract+hash
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        if contract_sig:
            filename = f'{contract_sig}_{url_hash}.{ext}'
        elif parsed.path and parsed.path != '/':
            path_parts = parsed.path.strip('/').replace('/', '_')
            filename = f'{path_parts[:100]}.{ext}'
        else:
            filename = f'homepage_{url_hash}.{ext}'

        return os.path.join(domain_dir, filename)

    def _save_content_sqlite(
        self,
        url: str,
        domain: str,
        content: dict[str, Any] | list[dict[str, Any]],
        output_format: str,
        contract_sig: str | None,
    ) -> None:
        from yosoi.outputs.json import format_json

        payload = format_json(url, domain, content)
        now = str(payload['extracted_at'])
        url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
        contract_fp = contract_sig or ''
        self._ensure_content_table()
        with sqlite3.connect(self.database_path) as conn:
            conn.execute(
                """
                INSERT INTO fetch_outputs (
                    contract_fingerprint, url_hash, output_format, url, domain, extracted_at, content_json, fetch_json, downloads_path
                )
                VALUES (?, ?, ?, ?, ?, ?, json(?), json(?), ?)
                ON CONFLICT(contract_fingerprint, url_hash, output_format) DO UPDATE SET
                    url = excluded.url,
                    domain = excluded.domain,
                    extracted_at = excluded.extracted_at,
                    content_json = excluded.content_json,
                    fetch_json = excluded.fetch_json,
                    downloads_path = excluded.downloads_path
                """,
                (
                    contract_fp,
                    url_hash,
                    output_format,
                    url,
                    domain,
                    now,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    json.dumps({}, sort_keys=True),
                    None,
                ),
            )

    def _load_content_sqlite(
        self, url: str, contract_sig: str | None = None
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        self._ensure_content_table()
        url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
        contract_fp = contract_sig or ''
        with sqlite3.connect(self.database_path) as conn:
            row = conn.execute(
                """
                SELECT content_json FROM fetch_outputs
                WHERE contract_fingerprint = ? AND url_hash = ? AND output_format = 'json'
                """,
                (contract_fp, url_hash),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(str(row[0]))
        if 'items' in data and isinstance(data['items'], list):
            items: list[dict[str, Any]] = data['items']
            return items
        content: dict[str, Any] = data.get('content', data)
        return content

    def _content_exists_sqlite(self, url: str, contract_sig: str | None = None) -> bool:
        self._ensure_content_table()
        url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
        contract_fp = contract_sig or ''
        with sqlite3.connect(self.database_path) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM fetch_outputs
                WHERE contract_fingerprint = ? AND url_hash = ?
                LIMIT 1
                """,
                (contract_fp, url_hash),
            ).fetchone()
        return row is not None

    def _ensure_content_table(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fetch_outputs (
                    contract_fingerprint TEXT NOT NULL,
                    url_hash TEXT NOT NULL,
                    output_format TEXT NOT NULL,
                    url TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    extracted_at TEXT NOT NULL,
                    content_json JSON NOT NULL,
                    fetch_json JSON NOT NULL DEFAULT '{}',
                    downloads_path TEXT,
                    PRIMARY KEY(contract_fingerprint, url_hash, output_format)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fetch_outputs_contract_domain
                ON fetch_outputs(contract_fingerprint, domain)
                """
            )

    def _load_content_sync(self, filepath: str) -> dict[str, Any] | list[dict[str, Any]] | None:
        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                data: dict[str, Any] = json.loads(f.read())
                # Multi-item format uses 'items' key
                if 'items' in data and isinstance(data['items'], list):
                    items: list[dict[str, Any]] = data['items']
                    return items
                # Single-item format uses 'content' key
                content: dict[str, Any] = data.get('content', data)
                return content
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.error('Error loading content: %s', e)
            return None

    @staticmethod
    def _file_exists_sync(filepath: str) -> bool:
        return os.path.exists(filepath)

    async def export_summary(self, output_file: str = 'selectors_summary.json') -> str:
        """Export a summary of all selectors to a file.

        Args:
            output_file: Path to output file. Defaults to 'selectors_summary.json'.

        Returns:
            Path to the exported file.

        """
        summary = await self.get_summary()

        await atomic_write_json_async(output_file, summary, ensure_ascii=False)

        logger.info('Exported summary to: %s', output_file)
        return output_file
