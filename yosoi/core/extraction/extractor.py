"""Extracts content from web pages using validated selectors."""

from parsel import Selector
from rich.console import Console

from yosoi.models.contract import Contract


class ContentExtractor:
    """Extracts content from HTML using validated selectors.

    Attributes:
        console: Rich console instance for formatted output

    """

    def __init__(self, console: Console | None = None, contract: type[Contract] | None = None):
        """Initialize the extractor.

        Args:
            console: Rich console instance for formatted output. Defaults to None (creates new Console).
            contract: Contract subclass defining expected fields. Defaults to None.

        """
        self.console = console or Console()
        self.expected_fields: tuple[str, ...] = tuple(contract.model_fields.keys()) if contract is not None else ()
        self._overridden_fields: frozenset[str] = (
            frozenset(contract.get_selector_overrides().keys()) if contract is not None else frozenset()
        )

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
        self.console.print(f'  ↻ Extracting {len(self.expected_fields)} fields using validated selectors...')

        sel = Selector(text=html)
        extracted = {}

        for field_name in self.expected_fields:
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
                content = self._extract_with_selector(sel, primary, field_name)
                if content:
                    selector_used = 'primary'

            if not content and fallback:
                content = self._extract_with_selector(sel, fallback, field_name)
                if content:
                    selector_used = 'fallback'

            if not content and tertiary:
                content = self._extract_with_selector(sel, tertiary, field_name)
                if content:
                    selector_used = 'tertiary'

            # Store extracted content
            if content:
                extracted[field_name] = content
                if field_name in self._overridden_fields:
                    self.console.print(f'  - {field_name}: extracted using provided selector')
                else:
                    self.console.print(f'  ✓ {field_name}: extracted using {selector_used} selector')
            else:
                self.console.print(f'  ✗ {field_name}: no content found with any selector')

        # Summary
        total = len(self.expected_fields)
        extracted_count = len(extracted)
        self.console.print(f'  ↻ Summary: {extracted_count}/{total} fields extracted successfully')

        # Return extracted content (or None if nothing extracted)
        if extracted:
            return extracted
        return None

    def _extract_with_selector(
        self,
        sel: Selector,
        selector: str,
        field_name: str,
    ) -> str | list[str | dict[str, str]] | None:
        """Extract content using a single selector.

        Args:
            sel: Parsel Selector for the parsed HTML
            selector: CSS selector to use
            field_name: Name of the field being extracted (determines extraction strategy)

        Returns:
            Extracted content as string, list of strings/dicts, or None if extraction failed.
            For related_content, returns list of dicts with 'text' and 'href' keys.

        """
        try:
            elements = sel.css(selector)
            if not elements:
                return None

            # Different extraction strategies based on field type
            if field_name == 'body_text':
                # Extract all paragraphs and join with newlines
                paragraphs = [' '.join(el.xpath('.//text()').getall()).strip() for el in elements]
                paragraphs = [p for p in paragraphs if p]
                return '\n\n'.join(paragraphs) if paragraphs else None

            if field_name == 'related_content':
                # Extract list of links/titles
                links: list[str | dict[str, str]] = []
                for el in elements:
                    text = ' '.join(el.xpath('.//text()').getall()).strip()
                    href = el.attrib.get('href', '')
                    if text:
                        links.append({'text': text, 'href': href} if href else text)
                return links if links else None

            # For headline, author, date - extract first matching element
            first_element = elements[0]
            text = ' '.join(first_element.xpath('.//text()').getall()).strip()
            return text if text else None

        except Exception as e:  # noqa: BLE001
            self.console.print(f'  ✗ {field_name}: extraction error ({e})')
            return None

    async def quick_extract(
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
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, follow_redirects=True
                )
            sel = Selector(text=response.text)

            return self._extract_with_selector(sel, selector, field_type)

        except (httpx.HTTPError, ValueError):
            return None
