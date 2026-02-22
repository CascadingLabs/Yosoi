"""Extracts content from web pages using validated selectors."""

from typing import ClassVar

from bs4 import BeautifulSoup
from rich.console import Console


class ContentExtractor:
    """Extracts content from HTML using validated selectors.

    Attributes:
        console: Rich console instance for formatted output
        EXPECTED_FIELDS: List of field names that should be extracted

    """

    EXPECTED_FIELDS: ClassVar[tuple[str, ...]] = (
        'headline',
        'author',
        'date',
        'body_text',
        'related_content',
    )

    def __init__(self, console: Console | None = None):
        """Initialize the extractor.

        Args:
            console: Rich console instance for formatted output. Defaults to None (creates new Console).

        """
        self.console = console or Console()

    def extract_content_with_html(
        self,
        _url: str,
        html: str,
        validated_selectors: dict[str, dict[str, str]],
    ) -> dict[str, str | list[str | dict[str, str]]] | None:
        """Extract content using validated selectors and provided HTML.

        Args:
            _url: URL the content is being extracted from (unused, for API consistency)
            html: Cleaned HTML content to extract from
            validated_selectors: Dictionary of validated selectors (primary, fallback, tertiary)

        Returns:
            Dictionary of extracted content by field name, or None if extraction failed.
            Each field contains extracted text, list of texts, or list of dicts (for related_content).

        """
        self.console.print(f'  ↻ Extracting {len(self.EXPECTED_FIELDS)} fields using validated selectors...')

        soup = BeautifulSoup(html, 'lxml')
        extracted = {}

        # Extract each expected field
        for field_name in self.EXPECTED_FIELDS:
            # Check if selector exists for this field
            if field_name not in validated_selectors:
                self.console.print(f'  ✗ {field_name}: no selector found')
                continue

            field_selectors = validated_selectors[field_name]

            # Get selectors in priority order
            primary = field_selectors.get('primary')
            fallback = field_selectors.get('fallback')
            tertiary = field_selectors.get('tertiary')

            # Try each selector in priority order
            content = None
            selector_used = None

            if primary:
                content = self._extract_with_selector(soup, primary, field_name)
                if content:
                    selector_used = 'primary'

            if not content and fallback:
                content = self._extract_with_selector(soup, fallback, field_name)
                if content:
                    selector_used = 'fallback'

            if not content and tertiary:
                content = self._extract_with_selector(soup, tertiary, field_name)
                if content:
                    selector_used = 'tertiary'

            # Store extracted content
            if content:
                extracted[field_name] = content
                self.console.print(f'  ✓ {field_name}: extracted using {selector_used} selector')
            else:
                self.console.print(f'  ✗ {field_name}: no content found with any selector')

        # Summary
        total = len(self.EXPECTED_FIELDS)
        extracted_count = len(extracted)
        self.console.print(f'  ↻ Summary: {extracted_count}/{total} fields extracted successfully')

        # Return extracted content (or None if nothing extracted)
        if extracted:
            return extracted
        return None

    def _extract_with_selector(
        self,
        soup: BeautifulSoup,
        selector: str,
        field_name: str,
    ) -> str | list[str | dict[str, str]] | None:
        """Extract content using a single selector.

        Args:
            soup: BeautifulSoup parsed HTML
            selector: CSS selector to use
            field_name: Name of the field being extracted (determines extraction strategy)

        Returns:
            Extracted content as string, list of strings/dicts, or None if extraction failed.
            For related_content, returns list of dicts with 'text' and 'href' keys.

        """
        try:
            elements = soup.select(selector)
            if not elements:
                return None

            # Different extraction strategies based on field type
            if field_name == 'body_text':
                # Extract all paragraphs and join with newlines
                paragraphs = [elem.get_text(strip=True) for elem in elements if elem.get_text(strip=True)]
                return '\n\n'.join(paragraphs) if paragraphs else None

            if field_name == 'related_content':
                # Extract list of links/titles
                links = []
                for elem in elements:
                    text = elem.get_text(strip=True)
                    href_value = elem.get('href', '')
                    # BeautifulSoup can return list for some attributes, ensure it's a string
                    href: str = ' '.join(href_value) if isinstance(href_value, list) else (href_value or '')
                    if text:
                        links.append({'text': text, 'href': href} if href else text)
                return links if links else None

            # For headline, author, date - extract first matching element
            first_element = elements[0]
            text = first_element.get_text(strip=True)
            return text if text else None

        except Exception as e:
            self.console.print(f'  ✗ {field_name}: extraction error ({e})')
            return None

    def quick_extract(
        self, url: str, selector: str, field_type: str = 'text'
    ) -> str | list[str | dict[str, str]] | None:
        """Quick extraction of a single field from a URL.

        Fetches the URL and extracts content using the provided selector.

        Args:
            url: URL to fetch and extract from
            selector: CSS selector to use
            field_type: Type of field ('text', 'body_text', or 'related_content'). Defaults to 'text'.

        Returns:
            Extracted content (string, list of strings/dicts), or None if extraction failed.

        """
        import requests

        try:
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            soup = BeautifulSoup(response.text, 'lxml')

            return self._extract_with_selector(soup, selector, field_type)

        except Exception:
            return None
