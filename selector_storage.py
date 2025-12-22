"""
selector_storage.py
===================
Handles saving and loading selector data to/from JSON files.
"""

import json
import os
from datetime import datetime
from urllib.parse import urlparse


class SelectorStorage:
    """Manages selector storage in JSON files."""

    def __init__(self, storage_dir: str = 'selectors'):
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

    def save_selectors(self, url: str, selectors: dict) -> str:
        """
        Save selectors to a JSON file.

        Args:
            url: URL the selectors were discovered from
            selectors: Dict of validated selectors

        Returns:
            Path to saved file
        """
        domain = self._extract_domain(url)
        filepath = self._get_filepath(domain)

        # Create structured data
        data = {
            'domain': domain,
            'source_url': url,
            'discovered_at': datetime.now().isoformat(),
            'version': '1.0',
            'selectors': self._format_selectors(selectors),
        }

        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f'\n✓ Saved selectors to: {filepath}')
        return filepath

    def load_selectors(self, domain: str) -> dict | None:
        """
        Load selectors from a JSON file.

        Args:
            domain: Domain name (e.g., 'example.com')

        Returns:
            Dict of selectors or None if not found
        """
        filepath = self._get_filepath(domain)

        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                data = json.load(f)
            return data.get('selectors')
        except Exception as e:
            print(f'Error loading selectors: {e}')
            return None

    def selector_exists(self, domain: str) -> bool:
        """Check if selectors exist for a domain."""
        filepath = self._get_filepath(domain)
        return os.path.exists(filepath)

    def list_domains(self) -> list:
        """List all domains with saved selectors."""
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

    def get_summary(self) -> dict:
        """Get summary of all saved selectors."""
        domains = self.list_domains()

        summary = {'total_domains': len(domains), 'domains': []}

        for domain in domains:
            data = self._load_file_data(domain)
            if data:
                summary['domains'].append(
                    {
                        'domain': domain,
                        'discovered_at': data.get('discovered_at'),
                        'fields': list(data.get('selectors', {}).keys()),
                    }
                )

        return summary

    def _format_selectors(self, selectors: dict) -> dict:
        """Format selectors for storage."""
        formatted = {}

        for field, field_data in selectors.items():
            if isinstance(field_data, dict):
                formatted[field] = {
                    'primary': field_data.get('primary'),
                    'fallback': field_data.get('fallback'),
                    'tertiary': field_data.get('tertiary'),
                    'working_priority': field_data.get('working_priority'),
                    'tested': True,
                }
            else:
                # Simple string selector
                formatted[field] = {
                    'primary': field_data,
                    'fallback': None,
                    'tertiary': None,
                    'working_priority': 'primary',
                    'tested': False,
                }

        return formatted

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return 'unknown'

    def _get_filepath(self, domain: str) -> str:
        """Get filepath for a domain's selectors."""
        safe_domain = domain.replace('.', '_').replace('/', '_')
        return os.path.join(self.storage_dir, f'selectors_{safe_domain}.json')

    def _load_file_data(self, domain: str) -> dict | None:
        """Load complete file data for a domain."""
        filepath = self._get_filepath(domain)

        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def export_summary(self, output_file: str = 'selectors_summary.json'):
        """Export a summary of all selectors to a file."""
        summary = self.get_summary()

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f'✓ Exported summary to: {output_file}')
        return output_file
