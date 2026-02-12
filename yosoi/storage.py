"""Handles saving and loading selector data to/from JSON files."""

import json
import os
from typing import Any
from urllib.parse import urlparse

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

    def save_selectors(self, url: str, selectors: dict) -> str:
        """Save selectors to a JSON file.

        Selectors are always saved as JSON for machine readability and reuse.

        Args:
            url: URL the selectors were discovered from
            selectors: Dictionary of validated selectors

        Returns:
            Path to the saved file.

        """
        from yosoi.outputs.utils import save_formatted_selectors

        domain = self._extract_domain(url)
        filepath = self._get_selector_filepath(domain)

        # Format selectors
        formatted_selectors = self._format_selectors(selectors)

        # Use output module to format and save (always JSON)
        save_formatted_selectors(filepath, url, domain, formatted_selectors)

        print(f'\n✓ Saved selectors to: {filepath}')
        return filepath

    def load_selectors(self, domain: str) -> dict | None:
        """Load selectors from a JSON file.

        Args:
            domain: Domain name (e.g., 'example.com')

        Returns:
            Dictionary of selectors, or None if not found or error occurred.

        """
        filepath = self._get_filepath(domain)

        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                data: dict[str, Any] = json.load(f)
                return data
        except Exception as e:
            print(f'Error loading selectors: {e}')
            return None

    def selector_exists(self, domain: str) -> bool:
        """Check if selectors exist for a domain.

        Args:
            domain: Domain name to check

        Returns:
            True if selector file exists for the domain, False otherwise.

        """
        filepath = self._get_filepath(domain)
        return os.path.exists(filepath)

    def save_content(self, url: str, content: dict, output_format: str = 'json') -> str:
        """Save extracted content to a file in the specified format.

        Args:
            url: URL the content was extracted from
            content: Dictionary of extracted content by field
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

    def load_content(self, url: str) -> dict | None:
        """Load extracted content from a JSON file.

        Args:
            url: URL to load content for

        Returns:
            Dictionary of extracted content, or None if not found or error occurred.

        """
        filepath = self._get_content_filepath(url)

        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                data: dict[str, Any] = json.load(f)
                return data
        except Exception as e:
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

    def _format_selectors(self, selectors: dict) -> dict[str, dict[str, str]]:
        """Format selectors for storage.

        Args:
            selectors: Raw selectors dictionary

        Returns:
            Formatted selectors with primary, fallback, and tertiary keys.

        """
        formatted: dict[str, dict[str, str]] = {}

        for field, field_data in selectors.items():
            if isinstance(field_data, dict):
                formatted[field] = {
                    'primary': field_data.get('primary', 'NA'),
                    'fallback': field_data.get('fallback', 'NA'),
                    'tertiary': field_data.get('tertiary', 'NA'),
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
        except Exception:
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

        Creates a safe filename from the full URL including path.

        Args:
            url: Full URL
            output_format: Output format ('json' or 'markdown'). Defaults to 'json'.

        Returns:
            Full file path for the URL's content file.

        """
        import hashlib

        # Parse URL
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')

        # Create safe domain directory
        safe_domain = domain.replace('.', '_').replace('/', '_')
        domain_dir = os.path.join(self.content_dir, safe_domain)

        # Determine file extension
        extension = 'md' if output_format == 'markdown' else 'json'

        # Create filename from URL path or use hash for homepage
        if parsed.path and parsed.path != '/':
            # Use path for filename (sanitized)
            path_parts = parsed.path.strip('/').replace('/', '_')
            filename = f'{path_parts[:100]}.{extension}'
        else:
            # Homepage - use a hash of the full URL
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f'homepage_{url_hash}.{extension}'

        return os.path.join(domain_dir, filename)

    def _load_file_data(self, domain: str) -> dict[str, Any] | None:
        """Load complete file data for a domain.

        Args:
            domain: Domain name

        Returns:
            Dictionary with 'selectors' key, or None if not found or error occurred.

        """
        filepath = self._get_filepath(domain)

        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                selectors = json.load(f)
                return {'selectors': selectors}
        except Exception:
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
