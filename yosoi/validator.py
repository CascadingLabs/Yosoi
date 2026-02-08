"""Validates that selectors actually work on web pages."""

import requests
from bs4 import BeautifulSoup
from rich.console import Console

from yosoi.models import DEFAULT_BLUEPRINT, BluePrint


class SelectorValidator:
    """Validates selectors by testing them on actual pages.

    Attributes:
        user_agent: User agent string for HTTP requests
        console: Rich console instance for formatted output
        blueprint: BluePrint defining expected fields

    """

    def __init__(
        self, user_agent: str = 'Mozilla/5.0', console: Console | None = None, blueprint: type[BluePrint] | None = None
    ):
        """Initialize the validator.

        Args:
            user_agent: User agent string for HTTP requests. Defaults to 'Mozilla/5.0'.
            console: Rich console instance for formatted output. Defaults to None (creates new Console).
            blueprint: BluePrint class defining fields to validate (uses ArticleBluePrint if None)

        """
        self.user_agent = user_agent
        self.console = console or Console()
        self.blueprint = blueprint or DEFAULT_BLUEPRINT

    def validate_selectors_with_html(
        self,
        _url: str,
        html: str,
        selectors: dict[str, dict[str, str]],
    ) -> dict[str, dict[str, str]] | None:
        """Validate selectors using provided HTML (no re-fetch needed).

        Args:
            _url: URL the selectors were discovered from (unused, for API consistency)
            html: HTML content to validate selectors against
            selectors: Dictionary of field names to selector dictionaries (primary, fallback, tertiary)

        Returns:
            Dictionary of validated selectors, or None if no selectors validated successfully.
            Each field contains {'primary': str, 'fallback': str, 'tertiary': str}.

        """
        # Get expected fields from blueprint
        all_fields = self.blueprint.get_all_fields()
        expected_fields = list(all_fields.keys())

        self.console.print(f'  → Validating {len(expected_fields)} fields using fetched HTML...')

        soup = BeautifulSoup(html, 'lxml')
        validated = {}

        # Validate each expected field
        for field_name in expected_fields:
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
                self.console.print(f'  ✓ {field_name}: tertiary selector works ({tertiary})')
                validated[field_name] = field_selectors
            else:
                self.console.print(f'  ✗ {field_name}: ALL selectors failed validation')

        # Summary
        total = len(expected_fields)
        validated_count = len(validated)
        self.console.print(f'  → Summary: {validated_count}/{total} fields validated successfully')

        # Return validated fields (or None if none validated)
        if validated:
            return validated
        return None

    def _handle_selector(self, soup: BeautifulSoup, selector: str, field_name: str) -> bool:
        """Test if a single selector finds elements in the HTML.

        Args:
            soup: BeautifulSoup parsed HTML
            selector: Selector string to test
            field_name: Name of the field being validated (for error reporting)

        Returns:
            True if the selector finds at least one element, False otherwise.

        """
        if selector == 'NA':
            return False
        try:
            elements = soup.select(selector)
            return bool(elements)
        except Exception as e:
            self.console.print(f'  ✗ {field_name}: validation error ({e})')
            return False

    def quick_test(self, url: str, selector: str) -> bool:
        """Quick test if a single selector works on a URL.

        Fetches the URL and tests if the selector finds any content.

        Args:
            url: URL to fetch and test against
            selector: Selector string to test

        Returns:
            True if the selector finds an element with text content, False otherwise.

        """
        try:
            response = requests.get(url, headers={'User-Agent': self.user_agent}, timeout=10)
            soup = BeautifulSoup(response.text, 'lxml')

            element = soup.select_one(selector)
            return element is not None and bool(element.get_text(strip=True))

        except Exception:
            return False
