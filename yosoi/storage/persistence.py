"""Handles saving and loading selector data to/from JSON files."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import aiofiles
import aiofiles.os

logger = logging.getLogger(__name__)

from yosoi.models.snapshot import (
    CacheVerdict,
    SelectorSnapshot,
    SnapshotMap,
    SnapshotStatus,
    selector_dict_to_snapshot,
    snapshot_to_selector_dict,
)
from yosoi.utils.files import atomic_write_json_async, init_yosoi, safe_domain
from yosoi.utils.urls import extract_domain


class SelectorStorage:
    """Manages selector storage in JSON files.

    Attributes:
        storage_dir: Directory path where selector files are stored
        content_dir: Directory path where extracted content is stored

    """

    def __init__(self, storage_dir: str = 'selectors', content_dir: str = 'content'):
        """Initialize the storage manager.

        Args:
            storage_dir: Directory path for storing selector files. Defaults to 'selectors'.
            content_dir: Directory path for storing extracted content. Defaults to 'content'.

        """
        self.storage_dir = str(init_yosoi(storage_dir))
        self.content_dir = str(init_yosoi(content_dir))

    async def save_selectors(
        self, url: str, selectors: dict[str, Any], *, verified: bool = False, contract_sig: str | None = None
    ) -> str:
        """Save selectors as snapshot format.

        Wraps each field's selector dict in a SelectorSnapshot with a
        ``discovered_at`` timestamp, then writes the SnapshotMap to disk.

        Args:
            url: URL the selectors were discovered from
            selectors: Dictionary of validated selectors
            verified: When True, stamp each snapshot with ``last_verified_at=now``.
            contract_sig: Optional contract signature for isolated selector cache files.

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
        return await self.save_snapshots(url, snapshots, contract_sig=contract_sig)

    async def load_selectors(self, domain: str, contract_sig: str | None = None) -> dict[str, Any] | None:
        """Load selectors from a snapshot file.

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
        filepath = self._get_filepath(domain, contract_sig=contract_sig)
        return await aiofiles.os.path.exists(filepath)

    async def save_content(
        self,
        url: str,
        content: dict[str, Any] | list[dict[str, Any]],
        output_format: str = 'json',
        contract_sig: str | None = None,
    ) -> str:
        """Save extracted content to a file in the specified format.

        Args:
            url: URL the content was extracted from
            content: Dictionary of extracted content or list of dicts for multi-item pages
            output_format: Output format ('json' or 'markdown'). Defaults to 'json'.
            contract_sig: Optional contract signature for stable, unique filenames.

        Returns:
            Path to the saved file.

        """
        from yosoi.outputs.utils import save_formatted_content

        domain = self._extract_domain(url)
        filepath = self._get_content_filepath(url, output_format, contract_sig)

        # Output savers include binary/tabular writers (pandas, pyarrow, openpyxl)
        # that have no async API; offload to a thread so the event loop is never
        # blocked while keeping a single dispatch path for every format.
        await asyncio.to_thread(save_formatted_content, filepath, url, domain, content, output_format)

        logger.info('Saved content to: %s', filepath)
        return filepath

    async def load_content(
        self, url: str, contract_sig: str | None = None
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Load extracted content from a JSON file.

        Args:
            url: URL to load content for
            contract_sig: Optional contract signature (must match the one used when saving).

        Returns:
            Single content dict, list of item dicts for multi-item pages, or None.

        """
        filepath = self._get_content_filepath(url, contract_sig=contract_sig)

        if not await aiofiles.os.path.exists(filepath):
            return None

        try:
            async with aiofiles.open(filepath, encoding='utf-8') as f:
                data: dict[str, Any] = json.loads(await f.read())
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

    async def content_exists(self, url: str, contract_sig: str | None = None) -> bool:
        """Check if extracted content exists for a URL.

        Args:
            url: URL to check
            contract_sig: Optional contract signature (must match the one used when saving).

        Returns:
            True if content file exists for the URL, False otherwise.

        """
        filepath = self._get_content_filepath(url, contract_sig=contract_sig)
        return await aiofiles.os.path.exists(filepath)

    async def list_domains(self) -> list[str]:
        """List all domains with saved selectors.

        Reads the ``domain`` field from each snapshot file rather than
        reversing filename mangling, so domains with underscores round-trip
        correctly.

        Returns:
            Sorted list of domain names with saved selectors.

        """
        if not await aiofiles.os.path.exists(self.storage_dir):
            return []

        domains = []
        for filename in await aiofiles.os.listdir(self.storage_dir):
            if not (filename.startswith('selectors_') and filename.endswith('.json')):
                continue
            filepath = os.path.join(self.storage_dir, filename)
            try:
                async with aiofiles.open(filepath, encoding='utf-8') as f:
                    data = json.loads(await f.read())
                domain = data.get('domain')
                if isinstance(domain, str) and domain:
                    domains.append(domain)
            except (OSError, json.JSONDecodeError):
                pass

        return sorted(set(domains))

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
        """Load full snapshots with audit metadata for a domain.

        Args:
            domain: Domain name (e.g., 'example.com')
            contract_sig: Optional contract signature for isolated selector cache files.

        Returns:
            Dict mapping field names to SelectorSnapshot, or None if not found.

        """
        data = await self._load_file_data(domain, contract_sig=contract_sig)
        if data is None:
            return None

        if 'snapshots' not in data:
            return None

        try:
            snap_map = SnapshotMap.model_validate(data)
            return dict(snap_map.snapshots) if snap_map.snapshots else None
        except (ValueError, TypeError):
            return None

    async def save_snapshots(
        self, url: str, snapshots: dict[str, SelectorSnapshot], contract_sig: str | None = None
    ) -> str:
        """Write v2 snapshot format to disk.

        Args:
            url: URL the selectors were discovered from
            snapshots: Dict mapping field names to SelectorSnapshot
            contract_sig: Optional contract signature for isolated selector cache files.

        Returns:
            Path to the saved file.

        """
        domain = self._extract_domain(url)
        filepath = self._get_selector_filepath(domain, contract_sig=contract_sig)

        snap_map = SnapshotMap(url=url, domain=domain, snapshots=snapshots)
        payload = snap_map.model_dump(mode='json')
        if contract_sig:
            payload['contract_sig'] = contract_sig
        await atomic_write_json_async(filepath, payload, ensure_ascii=False)

        logger.info('Saved snapshots to: %s', filepath)
        return filepath

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
        data = await self._load_file_data(domain, contract_sig=contract_sig)
        if data is None or 'snapshots' not in data:
            return

        snap_map = SnapshotMap.model_validate(data)
        snap = snap_map.snapshots.get(field_name)
        if snap is None:
            return

        now = datetime.now(timezone.utc)
        if verdict == CacheVerdict.FRESH:
            snap.last_verified_at = now
            snap.failure_count = 0
        else:  # STALE or DEGRADED
            snap.last_failed_at = now
            snap.failure_count += 1

        filepath = self._get_filepath(domain, contract_sig=contract_sig)
        payload = snap_map.model_dump(mode='json')
        if contract_sig:
            payload['contract_sig'] = contract_sig
        await atomic_write_json_async(filepath, payload, ensure_ascii=False)

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

    def _get_filepath(self, domain: str, contract_sig: str | None = None) -> str:
        """Get filepath for a domain's selectors (always JSON).

        Args:
            domain: Domain name
            contract_sig: Optional contract signature for isolated selector cache files.

        Returns:
            Full file path for the domain's selector file (JSON).

        """
        return self._get_selector_filepath(domain, contract_sig=contract_sig)

    def _get_selector_filepath(self, domain: str, contract_sig: str | None = None) -> str:
        """Get filepath for a domain's selectors (always JSON).

        Args:
            domain: Domain name
            contract_sig: Optional contract signature for isolated selector cache files.

        Returns:
            Full file path for the domain's selector file.

        """
        safe = safe_domain(domain)
        if contract_sig:
            safe = f'{safe}_{contract_sig}'
        return os.path.join(self.storage_dir, f'selectors_{safe}.json')

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

    async def _load_file_data(self, domain: str, contract_sig: str | None = None) -> dict[str, Any] | None:
        """Load complete file data for a domain.

        Args:
            domain: Domain name
            contract_sig: Optional contract signature for isolated selector cache files.

        Returns:
            Dictionary with full JSON structure (url, domain, discovered_at, selectors),
            or None if not found or error occurred.

        """
        filepath = self._get_filepath(domain, contract_sig=contract_sig)

        if not await aiofiles.os.path.exists(filepath):
            return None

        try:
            async with aiofiles.open(filepath, encoding='utf-8') as f:
                file_data: dict[str, Any] = json.loads(await f.read())
                return file_data
        except (OSError, json.JSONDecodeError):
            return None

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
