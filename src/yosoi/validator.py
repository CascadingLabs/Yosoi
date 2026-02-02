"""
selector_validator.py
======================
Validates that CSS selectors actually work on web pages.
"""

import requests
from bs4 import BeautifulSoup
from rich.console import Console


class SelectorValidator:
    """Validates CSS selectors by testing them on actual pages."""

    EXPECTED_FIELDS = ['headline', 'author', 'date', 'body_text', 'related_content']

    def __init__(self, user_agent: str = 'Mozilla/5.0', console: Console | None = None):
        self.user_agent = user_agent
        self.console = console or Console()

    def validate_selectors_with_html(
        self,
        _url: str,
        html: str,
        selectors: dict[str, dict[str, str]],  # Prefix url with _
    ) -> dict[str, dict[str, str]]:
        """
        Validate selectors using provided HTML (no re-fetch needed).
        """
        self.console.print(f'  → Validating {len(self.EXPECTED_FIELDS)} fields using fetched HTML...')

        soup = BeautifulSoup(html, 'html.parser')
        validated = {}

        # Validate each expected field
        for field_name in self.EXPECTED_FIELDS:
            # Check if selector exists for this field
            if field_name not in selectors:
                self.console.print(f'  ✗ {field_name}: no selector found')
                continue

            field_selectors = selectors[field_name]

            # Get selectors
            primary = field_selectors.get('primary', 'NA')
            fallback = field_selectors.get('fallback', 'NA')
            tertiary = field_selectors.get('tertiary', 'NA')

            if self._handle_selector(soup, primary, field_name):
                self.console.print(f'  ✓ {field_name}: primary selector works ({primary})')
                validated[field_name] = field_selectors
            elif self._handle_selector(soup, fallback, field_name):
                self.console.print(f'  ✗ {field_name}: primary failed')
                self.console.print(f'  ✓ {field_name}: fallback selector works ({fallback})')
                validated[field_name] = field_selectors
            elif self._handle_selector(soup, tertiary, field_name):
                self.console.print(f'  ✗ {field_name}: primary & fallback failed')
                self.console.print(f'  ✓ {field_name}: fallback selector works ({tertiary})')
                validated[field_name] = field_selectors
            else:
                self.console.print(f'  ✗ {field_name}: ALL selectors failed validation')

        # Summary
        total = len(self.EXPECTED_FIELDS)
        validated_count = len(validated)
        self.console.print(f'  → Summary: {validated_count}/{total} fields validated successfully')

        # Return validated fields (or None if none validated)
        return validated if validated else None

    def _handle_selector(self, soup: BeautifulSoup, selector: str, field_name: str) -> bool:
        if selector == 'NA':
            return False
        try:
            elements = soup.select(selector)
            return bool(elements)
        except Exception as e:
            self.console.print(f'  ✗ {field_name}: validation error ({e})')
            return False

    def quick_test(self, url: str, selector: str) -> bool:
        """
        Quick test if a single selector works.
        """
        try:
            response = requests.get(url, headers={'User-Agent': self.user_agent}, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')

            element = soup.select_one(selector)
            return element is not None and bool(element.get_text(strip=True))

        except Exception:
            return False
