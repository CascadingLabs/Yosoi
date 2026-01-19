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

    def __init__(self, user_agent: str = 'Mozilla/5.0', console: Console = None):
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

        This is the NEW method that eliminates re-fetching the URL for validation.

        Args:
            url: URL being validated (for logging only)
            html: HTML content to validate against
            selectors: Selectors to validate

        Returns:
            Dictionary of validated selectors (only selectors that worked)
        """
        from bs4 import BeautifulSoup

        self.console.print(f'[dim]  → Validating {len(selectors)} fields using fetched HTML...[/dim]')

        soup = BeautifulSoup(html, 'html.parser')
        validated = {}

        for field, field_selectors in selectors.items():
            # Try primary selector
            try:
                elements = soup.select(field_selectors['primary'])
                if elements and elements[0].get_text(strip=True):
                    validated[field] = field_selectors
                    self.console.print(
                        f'[success]  ✓ {field}: primary selector works ({field_selectors["primary"]})[/success]'
                    )
                    continue
            except Exception as e:
                self.console.print(f'[dim]    {field}: primary failed ({str(e)[:50]})[/dim]')

            # Try fallback selector
            try:
                elements = soup.select(field_selectors['fallback'])
                if elements and elements[0].get_text(strip=True):
                    validated[field] = field_selectors
                    self.console.print(
                        f'[success]  ✓ {field}: fallback selector works ({field_selectors["fallback"]})[/success]'
                    )
                    continue
            except Exception as e:
                self.console.print(f'[dim]    {field}: fallback failed ({str(e)[:50]})[/dim]')

            # Try tertiary selector
            try:
                if field_selectors['tertiary'] != 'NA':
                    elements = soup.select(field_selectors['tertiary'])
                    if elements and elements[0].get_text(strip=True):
                        validated[field] = field_selectors
                        self.console.print(
                            f'[success]  ✓ {field}: tertiary selector works ({field_selectors["tertiary"]})[/success]'
                        )
                        continue
            except Exception as e:
                self.console.print(f'[dim]    {field}: tertiary failed ({str(e)[:50]})[/dim]')

            # All selectors failed for this field
            self.console.print(f'[danger]  ✗ {field}: ALL selectors failed validation[/danger]')

        if validated:
            self.console.print(
                f'[dim]  → Summary: {len(validated)}/{len(selectors)} fields validated successfully[/dim]'
            )

        return validated

    def quick_test(self, url: str, selector: str) -> bool:
        """
        Quick test if a single selector works.

        Args:
            url: URL to test on
            selector: CSS selector to test

        Returns:
            True if selector finds elements, False otherwise
        """
        try:
            response = requests.get(url, headers={'User-Agent': self.user_agent}, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')

            element = soup.select_one(selector)
            return element is not None and bool(element.get_text(strip=True))

        except Exception:
            return False
