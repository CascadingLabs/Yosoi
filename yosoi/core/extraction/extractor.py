"""Extracts content from web pages using validated selectors."""

from typing import Any, Literal

from parsel import Selector
from rich.console import Console

from yosoi.models.contract import Contract, _unwrap_list_annotation
from yosoi.models.selectors import SelectorEntry, SelectorLevel, coerce_selector_entry

FieldMode = Literal['body_text', 'related_content', 'text', 'list']

_ROLE_SELECTORS: dict[str, tuple[str, ...]] = {
    'button': ('button', 'input[type="button"]', 'input[type="submit"]'),
    'link': ('a[href]',),
    'textbox': ('input:not([type])', 'input[type="text"]', 'textarea'),
    'searchbox': ('input[type="search"]',),
    'heading': ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'),
    'article': ('article',),
    'main': ('main',),
    'navigation': ('nav',),
    'list': ('ul', 'ol'),
    'listitem': ('li',),
    'table': ('table',),
    'row': ('tr',),
    'cell': ('td', 'th'),
    'img': ('img',),
}


def _node_text(el: Selector) -> str:
    """Return the text value of a matched node.

    A CSS ``::attr(name)``/``::text`` pseudo-element or an XPath ``/@attr``
    selection resolves to a string node (``el.root`` is a ``str``) — its value
    is already the thing we want, so return it directly. Anything else is an
    element, so gather its descendant text. Without this, attribute-encoded
    values (e.g. ``<p class="star-rating Three">``) extract as empty because
    the element carries no text node.
    """
    if isinstance(el.root, str):
        return (el.get() or '').strip()
    return ' '.join(el.xpath('.//text()').getall()).strip()


def _accessible_name(el: Selector) -> str:
    """Best-effort accessible name from static HTML."""
    for attr in ('aria-label', 'alt', 'title', 'value'):
        value = el.attrib.get(attr)
        if value:
            return value.strip()
    return _node_text(el)


def _role_matches(sel: Selector, entry: SelectorEntry) -> list[Selector]:
    """Best-effort role/name matching against static HTML."""
    role = entry.value.strip().lower()
    selectors = [f'[role="{role}"]', *_ROLE_SELECTORS.get(role, ())]
    candidates: list[Selector] = []
    seen: set[int] = set()
    for css in selectors:
        for match in sel.css(css):
            key = id(match.root)
            if key not in seen:
                candidates.append(match)
                seen.add(key)

    name = (entry.name or '').strip().lower()
    if name:
        candidates = [match for match in candidates if name in _accessible_name(match).lower()]

    if entry.nth is not None:
        return [candidates[entry.nth]] if 0 <= entry.nth < len(candidates) else []
    return candidates


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
        self._field_modes: dict[str, FieldMode] = {}
        self._nested_prefixes: frozenset[str] = frozenset()
        if contract is not None:
            fields: list[str] = []
            for name, fi in contract.model_fields.items():
                ann = fi.annotation
                if isinstance(ann, type) and issubclass(ann, Contract):
                    for child_name, child_fi in ann.model_fields.items():
                        flat_name = f'{name}_{child_name}'
                        fields.append(flat_name)
                        child_extra = child_fi.json_schema_extra
                        raw_ytype = child_extra.get('yosoi_type') if isinstance(child_extra, dict) else None
                        if raw_ytype == 'body_text':
                            self._field_modes[flat_name] = 'body_text'
                        elif raw_ytype == 'related_content':
                            self._field_modes[flat_name] = 'related_content'
                else:
                    fields.append(name)
                    extra = fi.json_schema_extra
                    raw_ytype = extra.get('yosoi_type') if isinstance(extra, dict) else None
                    if raw_ytype == 'body_text':
                        self._field_modes[name] = 'body_text'
                    elif raw_ytype == 'related_content':
                        self._field_modes[name] = 'related_content'
                    elif name not in self._field_modes and _unwrap_list_annotation(fi.annotation) is not None:
                        self._field_modes[name] = 'list'
            self.expected_fields = tuple(fields)
            self._nested_prefixes = frozenset(contract.nested_contracts().keys())
        else:
            self.expected_fields = ()
        self._overridden_fields: frozenset[str] = (
            frozenset(contract.get_selector_overrides().keys()) if contract is not None else frozenset()
        )

    @staticmethod
    def _unflatten(
        flat: dict[str, Any],
        nested_prefixes: frozenset[str],
    ) -> dict[str, Any]:
        """Reassemble ``{parent}_{child}`` keys into nested dicts.

        Uses *nested_prefixes* (the set of parent field names that map to child
        contracts) so that literal underscores in non-nested field names are
        never accidentally split.
        """
        if not nested_prefixes:
            return flat
        result: dict[str, Any] = {}
        for key, value in flat.items():
            matched = False
            for prefix in nested_prefixes:
                if key.startswith(f'{prefix}_'):
                    child = key[len(prefix) + 1 :]
                    if prefix not in result:
                        result[prefix] = {}
                    result[prefix][child] = value
                    matched = True
                    break
            if not matched:
                result[key] = value
        return result

    def extract_content_with_html(
        self,
        _url: str,
        html: str,
        validated_selectors: dict[str, dict[str, str]],
        max_level: SelectorLevel = max(SelectorLevel),
    ) -> dict[str, str | list[str | dict[str, str]]] | None:
        """Extract content using validated selectors and provided HTML.

        Args:
            _url: URL the content is being extracted from (unused, for API consistency)
            html: Cleaned HTML content to extract from
            validated_selectors: Dictionary of validated selectors (primary, fallback, tertiary)
            max_level: Maximum selector strategy level to use. Defaults to all.

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

            # Field-level root: scope this field's resolution to its parent region. A field
            # rooted under one region (e.g. a sponsored ad block) cannot latch onto another
            # (the organic list), and its leaf selector can stay simple. If a root is set but
            # matches nothing, the field has no value IN that region — we do NOT silently fall
            # back to the whole document (that would defeat the discrimination root buys).
            root_entry = coerce_selector_entry(field_selectors.get('root'))
            scope = self._scope_to_root(sel, root_entry)
            if scope is None:
                self.console.print(f'  ✗ {field_name}: root selector matched no region')
                continue

            content = None
            selector_used = None

            for level_name, entry in candidates:
                if entry is None:
                    continue
                content = self._resolve(scope, entry, field_name, max_level)
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

        if not extracted:
            return None
        return self._unflatten(extracted, self._nested_prefixes)

    def _scope_to_root(self, sel: Selector, root_entry: SelectorEntry | None) -> Selector | None:
        """Scope *sel* to a field's root region, or return *sel* unchanged when no root.

        Returns the FIRST element matched by the root (single-record semantics), the
        unscoped selector when no root is set, or ``None`` when a root is set but matches
        nothing — the signal that this field simply has no value in its region.
        """
        if root_entry is None:
            return sel
        if root_entry.type == 'xpath':
            matches = sel.xpath(root_entry.value)
        elif root_entry.type == 'css':
            matches = sel.css(root_entry.value)
        else:
            return sel  # non-structural root kinds aren't scopes; ignore rather than fail
        return matches[0] if matches else None

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
        if entry.type == 'attr':
            return self._extract_with_selector(sel, f'{entry.value}::attr({entry.name})', field_name)
        if entry.type == 'role':
            elements = _role_matches(sel, entry)
            return self._extract_from_elements(elements, field_name) if elements else None
        if entry.type in ('regex', 'jsonld', 'global_id', 'visual'):
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
        elements: Any,
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
            paragraphs = [_node_text(el) for el in elements]
            paragraphs = [p for p in paragraphs if p]
            return '\n\n'.join(paragraphs) if paragraphs else None

        if mode == 'related_content':
            links: list[str | dict[str, str]] = []
            for el in elements:
                text = _node_text(el)
                # Attribute/text selections (el.root is a str) have no .attrib.
                href = el.attrib.get('href', '') if not isinstance(el.root, str) else ''
                if text:
                    links.append({'text': text, 'href': href} if href else text)
            return links if links else None

        if mode == 'list':
            items: list[str | dict[str, str]] = [_node_text(el) for el in elements]
            items = [t for t in items if t]
            return items if items else None

        text = _node_text(elements[0])
        return text if text else None

    def _resolve_container_selector(
        self, sel: Selector, container_selector: str | dict[str, Any] | SelectorEntry
    ) -> Any:
        """Return containers for a repeated-item selector without inferring its type from text."""
        if isinstance(container_selector, str):
            return sel.xpath(container_selector) if container_selector.startswith('/') else sel.css(container_selector)
        entry = coerce_selector_entry(container_selector)
        if entry is None:
            return []
        if entry.type == 'xpath':
            return sel.xpath(entry.value)
        if entry.type == 'css':
            return sel.css(entry.value)
        return []

    def extract_items(
        self,
        _url: str,
        html: str,
        validated_selectors: dict[str, dict[str, str]],
        container_selector: str | dict[str, Any] | SelectorEntry,
        max_level: SelectorLevel = max(SelectorLevel),
    ) -> list[dict[str, str | list[str | dict[str, str]]]] | None:
        """Extract multiple items from HTML using a container selector.

        Each container element is treated as a scoped subtree from which
        per-field selectors are resolved independently.

        Args:
            _url: URL the content is being extracted from (unused, for API consistency)
            html: Cleaned HTML content to extract from
            validated_selectors: Dictionary of validated selectors per field
            container_selector: CSS selector matching each repeating item container
            max_level: Maximum selector strategy level to use. Defaults to all.

        Returns:
            List of extracted content dicts (one per container), or None if no items found.

        """
        sel = Selector(text=html)
        try:
            containers = self._resolve_container_selector(sel, container_selector)
        except Exception as exc:  # noqa: BLE001
            self.console.print(f'  ✗ Container selector failed ({exc}): {container_selector}')
            return None

        if not containers:
            self.console.print(f'  ✗ No containers matched selector: {container_selector}')
            return None

        self.console.print(f'  ↻ Found {len(containers)} items with container selector: {container_selector}')

        items: list[dict[str, str | list[str | dict[str, str]]]] = []
        seen_items: set[tuple[tuple[str, str], ...]] = set()
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
                unflattened = self._unflatten(item, self._nested_prefixes)
                key = tuple(sorted((name, repr(value)) for name, value in unflattened.items()))
                if key in seen_items:
                    continue
                seen_items.add(key)
                items.append(unflattened)

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
        import httpx2

        try:
            async with httpx2.AsyncClient() as client:
                response = await client.get(
                    url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, follow_redirects=True
                )
            sel = Selector(text=response.text)
            return self._extract_with_selector(sel, selector, field_type)
        except (httpx2.HTTPError, ValueError):
            return None
