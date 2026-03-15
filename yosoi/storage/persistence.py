"""Handles saving and loading selector data to/from JSON files."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from yosoi.models.snapshot import (
    CacheVerdict,
    SelectorSnapshot,
    SnapshotMap,
    selector_dict_to_snapshot,
    snapshot_to_selector_dict,
)
from yosoi.utils.files import init_yosoi


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

    def save_selectors(self, url: str, selectors: dict[str, Any], *, verified: bool = False) -> str:
        """Save selectors as snapshot format.

        Wraps each field's selector dict in a SelectorSnapshot with a
        ``discovered_at`` timestamp, then writes the SnapshotMap to disk.

        Args:
            url: URL the selectors were discovered from
            selectors: Dictionary of validated selectors
            verified: When True, stamp each snapshot with ``last_verified_at=now``.

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
        return self.save_snapshots(url, snapshots)

    def load_selectors(self, domain: str) -> dict[str, Any] | None:
        """Load selectors from a snapshot file.

        Strips audit metadata — callers receive
        ``{field: {primary, fallback, tertiary}}`` shape.

        Args:
            domain: Domain name (e.g., 'example.com')

        Returns:
            Dictionary of selectors, or None if not found or error occurred.

        """
        snapshots = self.load_snapshots(domain)
        if snapshots is None:
            return None
        return {name: snapshot_to_selector_dict(snap) for name, snap in snapshots.items()}

    def load_field_selector(self, domain: str, field_name: str) -> dict[str, Any] | None:
        """Return raw selector dict for a single field, or None if not cached.

        Args:
            domain: Domain name (e.g., 'example.com')
            field_name: Field name to look up

        Returns:
            Dict with primary/fallback/tertiary keys, or None if not found.

        """
        data = self.load_selectors(domain)
        if data is None:
            return None
        entry = data.get(field_name)
        return entry if isinstance(entry, dict) else None

    def selector_exists(self, domain: str) -> bool:
        """Check if selectors exist for a domain.

        Args:
            domain: Domain name to check

        Returns:
            True if selector file exists for the domain, False otherwise.

        """
        filepath = self._get_filepath(domain)
        return os.path.exists(filepath)

    def save_content(
        self, url: str, content: dict[str, Any] | list[dict[str, Any]], output_format: str = 'json'
    ) -> str:
        """Save extracted content to a file in the specified format.

        Args:
            url: URL the content was extracted from
            content: Dictionary of extracted content or list of dicts for multi-item pages
            output_format: Output format ('json' or 'markdown'). Defaults to 'json'.

        Returns:
            Path to the saved file.

        """
        from yosoi.outputs.utils import save_formatted_content

        domain = self._extract_domain(url)
        filepath = self._get_content_filepath(url, output_format)

        # Use output module to format and save
        save_formatted_content(filepath, url, domain, content, output_format)

        print(f'✓ Saved content to: {filepath}')
        return filepath

    def load_content(self, url: str) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Load extracted content from a JSON file.

        Args:
            url: URL to load content for

        Returns:
            Single content dict, list of item dicts for multi-item pages, or None.

        """
        filepath = self._get_content_filepath(url)

        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                data: dict[str, Any] = json.load(f)
                # Multi-item format uses 'items' key
                if 'items' in data and isinstance(data['items'], list):
                    items: list[dict[str, Any]] = data['items']
                    return items
                # Single-item format uses 'content' key
                content: dict[str, Any] = data.get('content', data)
                return content
        except (OSError, json.JSONDecodeError, ValueError) as e:
            print(f'Error loading content: {e}')
            return None

    def content_exists(self, url: str) -> bool:
        """Check if extracted content exists for a URL.

        Args:
            url: URL to check

        Returns:
            True if content file exists for the URL, False otherwise.

        """
        filepath = self._get_content_filepath(url)
        return os.path.exists(filepath)

    def list_domains(self) -> list[str]:
        """List all domains with saved selectors.

        Returns:
            Sorted list of domain names with saved selectors.

        """
        if not os.path.exists(self.storage_dir):
            return []

        files = os.listdir(self.storage_dir)
        domains = []

        for filename in files:
            if filename.startswith('selectors_') and filename.endswith('.json'):
                # Extract domain from filename
                domain = filename[10:-5].replace('_', '.')
                domains.append(domain)

        return sorted(domains)

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all saved selectors.

        Returns:
            Dictionary containing 'total_domains' count and list of domain details.
            Each domain includes 'domain', 'discovered_at', and 'fields' keys.

        """
        domains = self.list_domains()

        summary: dict[str, Any] = {'total_domains': len(domains), 'domains': []}

        for domain in domains:
            snapshots = self.load_snapshots(domain)
            if snapshots:
                # Use earliest discovered_at as the domain-level timestamp
                earliest = min((s.discovered_at for s in snapshots.values()), default=None)
                summary['domains'].append(
                    {
                        'domain': domain,
                        'discovered_at': earliest.isoformat() if earliest else None,
                        'fields': list(snapshots.keys()),
                    }
                )

        return summary

    # ------------------------------------------------------------------
    # Snapshot API (v2)
    # ------------------------------------------------------------------

    def load_snapshots(self, domain: str) -> dict[str, SelectorSnapshot] | None:
        """Load full snapshots with audit metadata for a domain.

        Args:
            domain: Domain name (e.g., 'example.com')

        Returns:
            Dict mapping field names to SelectorSnapshot, or None if not found.

        """
        data = self._load_file_data(domain)
        if data is None:
            return None

        if 'snapshots' not in data:
            return None

        try:
            snap_map = SnapshotMap.model_validate(data)
            return dict(snap_map.snapshots) if snap_map.snapshots else None
        except (ValueError, TypeError):
            return None

    def save_snapshots(self, url: str, snapshots: dict[str, SelectorSnapshot]) -> str:
        """Write v2 snapshot format to disk.

        Args:
            url: URL the selectors were discovered from
            snapshots: Dict mapping field names to SelectorSnapshot

        Returns:
            Path to the saved file.

        """
        domain = self._extract_domain(url)
        filepath = self._get_selector_filepath(domain)

        snap_map = SnapshotMap(url=url, domain=domain, snapshots=snapshots)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(snap_map.model_dump(mode='json'), f, indent=2, ensure_ascii=False)

        print(f'\n✓ Saved snapshots to: {filepath}')
        return filepath

    def record_verdict(self, domain: str, field_name: str, verdict: CacheVerdict) -> None:
        """Update the audit trail for a single field after verification.

        Args:
            domain: Domain name
            field_name: Field whose verdict to record
            verdict: FRESH, STALE, or DEGRADED

        """
        data = self._load_file_data(domain)
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

        filepath = self._get_filepath(domain)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(snap_map.model_dump(mode='json'), f, indent=2, ensure_ascii=False)

    def _format_selectors(self, selectors: dict[str, Any]) -> dict[str, dict[str, str | None]]:
        """Format selectors for storage.

        Args:
            selectors: Raw selectors dictionary

        Returns:
            Formatted selectors with primary, fallback, and tertiary keys.

        """
        formatted: dict[str, dict[str, str | None]] = {}

        for field, field_data in selectors.items():
            if isinstance(field_data, dict):
                formatted[field] = {
                    'primary': field_data.get('primary'),
                    'fallback': field_data.get('fallback'),
                    'tertiary': field_data.get('tertiary'),
                }

        return formatted

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL.

        Removes 'www.' prefix if present.

        Args:
            url: URL to extract domain from

        Returns:
            Domain name without 'www.' prefix, or 'unknown' if URL is invalid.

        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except ValueError:
            return 'unknown'

    def _get_filepath(self, domain: str) -> str:
        """Get filepath for a domain's selectors (always JSON).

        Args:
            domain: Domain name

        Returns:
            Full file path for the domain's selector file (JSON).

        """
        return self._get_selector_filepath(domain)

    def _get_selector_filepath(self, domain: str) -> str:
        """Get filepath for a domain's selectors (always JSON).

        Args:
            domain: Domain name

        Returns:
            Full file path for the domain's selector file.

        """
        safe_domain = domain.replace('.', '_').replace('/', '_')
        return os.path.join(self.storage_dir, f'selectors_{safe_domain}.json')

    def _get_content_filepath(self, url: str, output_format: str = 'json') -> str:
        """Get filepath for a URL's extracted content.

        Accumulating formats (jsonl, csv, xlsx, parquet) share a single results file
        per domain. Per-URL formats (json, markdown) produce one file per URL.

        Args:
            url: Full URL
            output_format: Output format. Defaults to 'json'.

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
        domain = parsed.netloc.replace('www.', '')
        safe_domain = domain.replace('.', '_').replace('/', '_')
        ext = _EXTENSIONS.get(output_format, 'json')
        domain_dir = os.path.join(self.content_dir, safe_domain)

        if output_format in _ACCUMULATING:
            return os.path.join(domain_dir, f'results.{ext}')

        # Per-URL (json, markdown) — derive filename from URL path
        if parsed.path and parsed.path != '/':
            path_parts = parsed.path.strip('/').replace('/', '_')
            filename = f'{path_parts[:100]}.{ext}'
        else:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f'homepage_{url_hash}.{ext}'

        return os.path.join(domain_dir, filename)

    def _load_file_data(self, domain: str) -> dict[str, Any] | None:
        """Load complete file data for a domain.

        Args:
            domain: Domain name

        Returns:
            Dictionary with full JSON structure (url, domain, discovered_at, selectors),
            or None if not found or error occurred.

        """
        filepath = self._get_filepath(domain)

        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                file_data: dict[str, Any] = json.load(f)
                return file_data
        except (OSError, json.JSONDecodeError):
            return None

    def export_summary(self, output_file: str = 'selectors_summary.json') -> str:
        """Export a summary of all selectors to a file.

        Args:
            output_file: Path to output file. Defaults to 'selectors_summary.json'.

        Returns:
            Path to the exported file.

        """
        summary = self.get_summary()

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f'✓ Exported summary to: {output_file}')
        return output_file
