"""Extracts content from web pages using validated selectors."""

from typing import Literal

from parsel import Selector, SelectorList
from rich.console import Console

from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorEntry, SelectorLevel, coerce_selector_entry

FieldMode = Literal['body_text', 'related_content', 'text']


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
        self._field_modes: dict[str, FieldMode] = {}
        if contract is not None:
            for name, fi in contract.model_fields.items():
                extra = fi.json_schema_extra
                raw_ytype = extra.get('yosoi_type') if isinstance(extra, dict) else None
                if raw_ytype == 'body_text':
                    self._field_modes[name] = 'body_text'
                elif raw_ytype == 'related_content':
                    self._field_modes[name] = 'related_content'

    def extract_content_with_html(
        self,
        _url: str,
        html: str,
        validated_selectors: dict[str, dict[str, str]],
        max_level: SelectorLevel = SelectorLevel.CSS,
    ) -> dict[str, str | list[str | dict[str, str]]] | None:
        """Extract content using validated selectors and provided HTML.

        Args:
            _url: URL the content is being extracted from (unused, for API consistency)
            html: Cleaned HTML content to extract from
            validated_selectors: Dictionary of validated selectors (primary, fallback, tertiary)
            max_level: Maximum selector strategy level to use. Defaults to CSS.

        Returns:
            Dictionary of extracted content by field name, or None if extraction failed.
            Each field contains extracted text, list of texts, or list of dicts (for related_content).

        """
        self.console.print(f'  ↻ Extracting {len(self.expected_fields)} fields using validated selectors...')

        sel = Selector(text=html)
        extracted = {}

        for field_name in self.expected_fields:
            if field_name not in validated_selectors:
                self.console.print(f'  ✗ {field_name}: no selector found')
                continue

            field_selectors = validated_selectors[field_name]

            candidates: list[tuple[str, SelectorEntry | None]] = [
                ('primary', coerce_selector_entry(field_selectors.get('primary'))),
                ('fallback', coerce_selector_entry(field_selectors.get('fallback'))),
                ('tertiary', coerce_selector_entry(field_selectors.get('tertiary'))),
            ]

            content = None
            selector_used = None

            for level_name, entry in candidates:
                if entry is None:
                    continue
                content = self._resolve(sel, entry, field_name, max_level)
                if content:
                    selector_used = level_name
                    break

            if content:
                extracted[field_name] = content
                if field_name in self._overridden_fields:
                    self.console.print(f'  - {field_name}: extracted using provided selector')
                else:
                    self.console.print(f'  ✓ {field_name}: extracted using {selector_used} selector')
            else:
                self.console.print(f'  ✗ {field_name}: no content found with any selector')

        total = len(self.expected_fields)
        extracted_count = len(extracted)
        self.console.print(f'  ↻ Summary: {extracted_count}/{total} fields extracted successfully')

        return extracted if extracted else None

    def _resolve(
        self,
        sel: Selector,
        entry: SelectorEntry,
        field_name: str,
        max_level: SelectorLevel,
    ) -> str | list[str | dict[str, str]] | None:
        """Resolve content for a single SelectorEntry, respecting max_level.

        Args:
            sel: Parsel Selector for the parsed HTML
            entry: Selector entry with strategy and value
            field_name: Name of the field (determines extraction strategy)
            max_level: Entries with level > max_level are skipped

        Returns:
            Extracted content, or None if skipped or not found.

        """
        if entry.level > max_level:
            return None
        if entry.type == 'xpath':
            return self._extract_with_xpath_selector(sel, entry.value, field_name)
        if entry.type in ('regex', 'jsonld'):
            return None  # unsupported strategies fail closed
        return self._extract_with_selector(sel, entry.value, field_name)

    def _extract_with_selector(
        self,
        sel: Selector,
        selector: str,
        field_name: str,
    ) -> str | list[str | dict[str, str]] | None:
        """Extract content using a CSS selector.

        Args:
            sel: Parsel Selector for the parsed HTML
            selector: CSS selector string
            field_name: Name of the field being extracted (determines extraction strategy)

        Returns:
            Extracted content as string, list of strings/dicts, or None if extraction failed.
            For related_content, returns list of dicts with 'text' and 'href' keys.

        """
        try:
            elements = sel.css(selector)
            if not elements:
                return None
            return self._extract_from_elements(elements, field_name)
        except Exception as e:  # noqa: BLE001
            self.console.print(f'  ✗ {field_name}: extraction error ({e})')
            return None

    def _extract_with_xpath_selector(
        self,
        sel: Selector,
        xpath: str,
        field_name: str,
    ) -> str | list[str | dict[str, str]] | None:
        """Extract content using an XPath selector.

        Args:
            sel: Parsel Selector for the parsed HTML
            xpath: XPath expression
            field_name: Name of the field being extracted

        Returns:
            Extracted content, or None if not found.

        """
        try:
            elements = sel.xpath(xpath)
            if not elements:
                return None
            return self._extract_from_elements(elements, field_name)
        except Exception as e:  # noqa: BLE001
            self.console.print(f'  ✗ {field_name}: xpath extraction error ({e})')
            return None

    def _extract_from_elements(
        self,
        elements: SelectorList[Selector],
        field_name: str,
    ) -> str | list[str | dict[str, str]] | None:
        """Shared extraction logic given a SelectorList.

        Args:
            elements: Parsel SelectorList of matched elements
            field_name: Name of the field (determines extraction strategy)

        Returns:
            Extracted content, or None if nothing usable found.

        """
        _KNOWN_MODES = ('body_text', 'related_content')
        mode = self._field_modes.get(field_name) or (field_name if field_name in _KNOWN_MODES else 'text')

        if mode == 'body_text':
            paragraphs = [' '.join(el.xpath('.//text()').getall()).strip() for el in elements]
            paragraphs = [p for p in paragraphs if p]
            return '\n\n'.join(paragraphs) if paragraphs else None

        if mode == 'related_content':
            links: list[str | dict[str, str]] = []
            for el in elements:
                text = ' '.join(el.xpath('.//text()').getall()).strip()
                href = el.attrib.get('href', '')
                if text:
                    links.append({'text': text, 'href': href} if href else text)
            return links if links else None

        first_element = elements[0]
        text = ' '.join(first_element.xpath('.//text()').getall()).strip()
        return text if text else None

    def extract_items(
        self,
        _url: str,
        html: str,
        validated_selectors: dict[str, dict[str, str]],
        container_selector: str,
        max_level: SelectorLevel = SelectorLevel.CSS,
    ) -> list[dict[str, str | list[str | dict[str, str]]]] | None:
        """Extract multiple items from HTML using a container selector.

        Each container element is treated as a scoped subtree from which
        per-field selectors are resolved independently.

        Args:
            _url: URL the content is being extracted from (unused, for API consistency)
            html: Cleaned HTML content to extract from
            validated_selectors: Dictionary of validated selectors per field
            container_selector: CSS selector matching each repeating item container
            max_level: Maximum selector strategy level to use. Defaults to CSS.

        Returns:
            List of extracted content dicts (one per container), or None if no items found.

        """
        sel = Selector(text=html)
        containers = sel.css(container_selector)

        if not containers:
            self.console.print(f'  ✗ No containers matched selector: {container_selector}')
            return None

        self.console.print(f'  ↻ Found {len(containers)} items with container selector: {container_selector}')

        items: list[dict[str, str | list[str | dict[str, str]]]] = []
        for container in containers:
            item: dict[str, str | list[str | dict[str, str]]] = {}

            for field_name in self.expected_fields:
                if field_name not in validated_selectors:
                    continue

                field_selectors = validated_selectors[field_name]
                candidates: list[tuple[str, SelectorEntry | None]] = [
                    ('primary', coerce_selector_entry(field_selectors.get('primary'))),
                    ('fallback', coerce_selector_entry(field_selectors.get('fallback'))),
                    ('tertiary', coerce_selector_entry(field_selectors.get('tertiary'))),
                ]

                for _level_name, entry in candidates:
                    if entry is None:
                        continue
                    content = self._resolve(container, entry, field_name, max_level)
                    if content:
                        item[field_name] = content
                        break

            if item:
                items.append(item)

        self.console.print(f'  ↻ Extracted {len(items)} non-empty items')
        return items if items else None

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
