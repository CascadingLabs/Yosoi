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

    def validate_selectors(self, url: str, selectors: dict) -> dict:
        """
        Test each selector to see if it finds elements on the page.

        Args:
            url: URL to test selectors on
            selectors: Dict of selectors organized by field

        Returns:
            Dict of validated selectors with working ones marked
        """
        try:
            # Fetch the page
            response = requests.get(url, headers={'User-Agent': self.user_agent}, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')

            validated = {}

            # Test each field
            for field, field_selectors in selectors.items():
                self.console.print(f'\n  Testing {field}:')

                working_selector = self._find_working_selector(soup, field, field_selectors)

                if working_selector:
                    validated[field] = working_selector

            return validated

        except Exception as e:
            self.console.print(f'[danger]  ✗ Validation error: {e}[/danger]')
            return {}

    def _find_working_selector(self, soup: BeautifulSoup, field: str, field_selectors: dict) -> dict | None:
        """Find the first working selector for a field."""

        best_selector = None
        best_priority = None

        # Try primary, fallback, tertiary in order
        for priority in ['primary', 'fallback', 'tertiary']:
            selector = field_selectors.get(priority)

            if not selector or selector == 'NA':
                self.console.print(f'    [dim]{priority}: NA[/dim]')
                continue

            # Test the selector
            works, sample_text = self._test_selector(soup, field, selector)

            if works:
                self.console.print(f'    [success]✓ {priority}: \'{selector}\'[/success] → [dim]"{sample_text}..."[/dim]')

                # Keep first working selector
                if not best_selector:
                    best_selector = selector
                    best_priority = priority
            else:
                self.console.print(f"    [danger]✗ {priority}: '{selector}' (no elements found)[/danger]")

        # Return the best working selector
        if best_selector:
            result = {
                'primary': best_selector,
                'fallback': field_selectors.get('fallback'),
                'tertiary': field_selectors.get('tertiary'),
                'working_priority': best_priority,
            }
            self.console.print(f"  → Using {best_priority} selector: '[cyan]{best_selector}[/cyan]'")
            return result
        self.console.print(f'[danger]  → No working selectors for {field}[/danger]')
        return None

    def _test_selector(self, soup: BeautifulSoup, field: str, selector: str) -> tuple[bool, str]:
        """
        Test if a selector finds elements with content.

        Returns:
            (success: bool, sample_text: str)
        """
        try:
            # For body_text, select multiple elements
            if field == 'body_text':
                elements = soup.select(selector)
            else:
                element = soup.select_one(selector)
                elements = [element] if element else []

            # Check if we found elements with text
            if not elements or not any(el and el.get_text(strip=True) for el in elements):
                return False, ''

            # Get sample text
            sample_text = elements[0].get_text(strip=True)[:60]

            # For headline: reject if it's too short or looks like navigation
            if field == 'headline':
                text_full = elements[0].get_text(strip=True)

                # Reject navigation-like text
                nav_patterns = [
                    'select region',
                    'menu',
                    'navigation',
                    'search',
                    'subscribe',
                    'sign in',
                    'log in',
                    'home',
                ]

                if any(pattern in text_full.lower() for pattern in nav_patterns):
                    return False, 'navigation element'

                # Reject if too short (likely not a headline)
                if len(text_full) < 15:
                    return False, 'too short'

            # For body_text: reject if it's event/sidebar content
            if field == 'body_text':
                text_full = elements[0].get_text(strip=True)

                # Reject sidebar-like text
                sidebar_patterns = [
                    'upcoming event',
                    'advertisement',
                    'newsletter',
                    'subscribe now',
                    'follow us',
                ]

                if any(pattern in text_full.lower() for pattern in sidebar_patterns):
                    return False, 'sidebar element'

            return True, sample_text

        except Exception as e:
            return False, f'error: {e}'

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
