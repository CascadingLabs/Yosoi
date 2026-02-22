"""Debug logic abstraction for Yosoi.

Handles saving of HTML and selectors for debugging purposes.
"""

import json
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console

from yosoi.utils.files import get_debug_path


class DebugManager:
    """Manages debug output for the pipeline.

    Handles saving HTML and selector information when debug mode is enabled.
    """

    def __init__(self, console: Console | None = None, enabled: bool = False):
        """Initialize DebugManager.

        Args:
            console: Rich console instance for output.
            enabled: Whether debug mode is enabled.

        """
        self.console = console or Console()
        self.enabled = enabled
        self.debug_dir = self._ensure_debug_dir() if enabled else None

    def _ensure_debug_dir(self) -> Path:
        """Ensure debug directory exists and return it."""
        debug_dir = get_debug_path()
        debug_dir.mkdir(parents=True, exist_ok=True)
        return debug_dir

    def _get_safe_filename(self, url: str, suffix: str) -> str:
        """Create a safe filename from URL.

        Args:
            url: The URL to create a filename from.
            suffix: Suffix for the filename (e.g., 'html', 'selectors.json').

        Returns:
            A safe filename string.

        """
        parsed = urlparse(url)
        # Combine netloc and path, replacing slashes and limiting length
        safe_path = parsed.path.replace('/', '_')[:50]
        base = f'{parsed.netloc}{safe_path}'
        return f'{base}.{suffix}'

    def save_debug_html(self, url: str, html: str):
        """Save cleaned HTML to file for debugging.

        Args:
            url: URL from which the HTML was obtained.
            html: Cleaned HTML content to save.

        """
        if not self.enabled or not self.debug_dir:
            return

        filename = self._get_safe_filename(url, 'html')
        filepath = self.debug_dir / filename

        try:
            # Save HTML with metadata comment
            filepath.write_text(
                f'<!-- URL: {url} -->\n<!-- Cleaned HTML length: {len(html)} chars -->\n\n{html}',
                encoding='utf-8',
            )
            self.console.print(f'  [dim]↻ Debug HTML saved to: {filepath}[/dim]')
        except Exception as e:
            self.console.print(f'[warning]Failed to save debug HTML: {e}[/warning]')

    def save_debug_selectors(self, url: str, selectors: dict):
        """Save discovered selectors to file for debugging.

        Args:
            url: URL for which selectors were discovered.
            selectors: The discovered selectors.

        """
        if not self.enabled or not self.debug_dir:
            return

        filename = self._get_safe_filename(url, 'selectors.json')
        filepath = self.debug_dir / filename

        debug_data = {'url': url, 'selectors': selectors}

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(debug_data, f, indent=2)
            self.console.print(f'  [dim]↻ Debug selectors saved to: {filepath}[/dim]')
        except Exception as e:
            self.console.print(f'[warning]Failed to save debug selectors: {e}[/warning]')
