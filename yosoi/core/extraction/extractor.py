"""Extracts selector-backed and deterministic fields within one row boundary."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

from parsel import Selector
from rich.console import Console

from yosoi.models.contract import Contract, _unwrap_list_annotation
from yosoi.models.extraction import (
    ExtractionEvidence,
    ExtractionRow,
    ExtractorBinding,
    ExtractorFieldError,
    ExtractorFingerprint,
    ExtractorNoMatch,
    annotation_identity,
    extractor_spec_for_callable,
    resolve_extractor_bindings,
    runtime_fingerprint,
)
from yosoi.models.selectors import SelectorEntry, SelectorLevel, coerce_selector_entry

if TYPE_CHECKING:
    from yosoi.fingerprints.models import FingerprintFieldReferenceRecord
    from yosoi.fingerprints.store import FingerprintStore
    from yosoi.policy import Policy

FieldMode = Literal['body_text', 'related_content', 'text', 'list']

logger = logging.getLogger(__name__)

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

    def __init__(  # noqa: C901
        self,
        console: Console | None = None,
        contract: type[Contract] | None = None,
        *,
        policy: Policy | None = None,
        fingerprint_store: FingerprintStore | None = None,
    ):
        """Initialize selector and deterministic extraction coordination.

        Fingerprint reference I/O is opt-in through ``policy.extractor``. Callers
        that need an otherwise pure boundary should pass an explicit store.
        """
        from yosoi.policy import Policy

        self.console = console or Console()
        self.contract = contract
        self._policy = policy or Policy()
        extractor_policy = self._policy.extractor
        self._reference_writes = bool(extractor_policy and extractor_policy.reference_writes)
        self._generalized_reads = bool(
            extractor_policy and extractor_policy.generalized_reads and self._policy.allows_source('fingerprint')
        )
        self._allow_opaque_generalization = bool(extractor_policy and extractor_policy.allow_opaque)
        self._allowed_extractor_references = frozenset(extractor_policy.allowed_references if extractor_policy else ())
        self._fingerprint_store = fingerprint_store
        if self._fingerprint_store is None and (self._reference_writes or self._generalized_reads):
            from yosoi.fingerprints.store import FingerprintStore

            self._fingerprint_store = FingerprintStore()
        self._field_modes: dict[str, FieldMode] = {}
        self._nested_prefixes: frozenset[str] = frozenset()
        self._extractor_bindings = (
            resolve_extractor_bindings(contract, fail_required=not self._generalized_reads)
            if contract is not None
            else {}
        )
        self.last_extractor_fingerprints: list[ExtractorFingerprint] = []
        self.last_extractor_diagnostics: list[dict[str, str | int]] = []
        self._pending_extractor_references: list[FingerprintFieldReferenceRecord] = []
        self._field_fingerprints: dict[str, str] = {}
        if contract is not None:
            fields = contract.discovery_field_names()
            ordered_fields: list[str] = []
            for name, fi in contract.model_fields.items():
                ann = fi.annotation
                if isinstance(ann, type) and issubclass(ann, Contract):
                    for child_name, child_fi in ann.model_fields.items():
                        flat_name = f'{name}_{child_name}'
                        if flat_name not in fields:
                            continue
                        ordered_fields.append(flat_name)
                        child_extra = child_fi.json_schema_extra
                        raw_ytype = child_extra.get('yosoi_type') if isinstance(child_extra, dict) else None
                        if raw_ytype == 'body_text':
                            self._field_modes[flat_name] = 'body_text'
                        elif raw_ytype == 'related_content':
                            self._field_modes[flat_name] = 'related_content'
                elif name in fields:
                    ordered_fields.append(name)
                    extra = fi.json_schema_extra
                    raw_ytype = extra.get('yosoi_type') if isinstance(extra, dict) else None
                    if raw_ytype == 'body_text':
                        self._field_modes[name] = 'body_text'
                    elif raw_ytype == 'related_content':
                        self._field_modes[name] = 'related_content'
                    elif _unwrap_list_annotation(fi.annotation) is not None:
                        self._field_modes[name] = 'list'
            self.expected_fields = tuple(ordered_fields)
            self._nested_prefixes = frozenset(contract.nested_contracts().keys())
            spec = contract.to_spec()
            self._contract_fingerprint = spec.fingerprint
            self._field_fingerprints = {
                name: spec.fields[name].fingerprint for name in contract.extractor_fields() if name in spec.fields
            }
        else:
            self.expected_fields = ()
            self._contract_fingerprint = ''
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
        *,
        runtime_evidence: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, str | list[str | dict[str, str]]] | None:
        """Synchronous convenience wrapper; async callers must use the async variant."""
        from yosoi.models.extraction import run_extraction_sync

        return run_extraction_sync(
            self.extract_content_with_html_async(
                _url,
                html,
                validated_selectors,
                max_level,
                runtime_evidence=runtime_evidence,
            ),
            async_name='ContentExtractor.extract_content_with_html_async(...)',
        )

    async def extract_content_with_html_async(
        self,
        _url: str,
        html: str,
        validated_selectors: dict[str, dict[str, str]],
        max_level: SelectorLevel = max(SelectorLevel),
        *,
        runtime_evidence: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, str | list[str | dict[str, str]]] | None:
        """Extract content using validated selectors and provided HTML.

        Args:
            _url: URL the content is being extracted from (unused, for API consistency)
            html: Cleaned HTML content to extract from
            validated_selectors: Dictionary of validated selectors (primary, fallback, tertiary)
            max_level: Maximum selector strategy level to use. Defaults to all.
            runtime_evidence: Named values observed during the existing page acquisition.

        Returns:
            Dictionary of extracted content by field name, or None if extraction failed.
            Each field contains extracted text, list of texts, or list of dicts (for related_content).

        """
        self.last_extractor_fingerprints.clear()
        self.last_extractor_diagnostics.clear()
        self._pending_extractor_references.clear()
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

        extracted.update(
            await self._extract_deterministic_fields(
                row_html=html,
                page_html=html,
                url=_url,
                row_index=0,
                root_scope='rootless',
                runtime_evidence=runtime_evidence,
            )
        )
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

    @staticmethod
    def _root_scope_fingerprint(container_selector: str | dict[str, Any] | SelectorEntry) -> str:
        """Hash one canonical root identity consistently across extraction entry points."""
        entry: SelectorEntry | None
        if isinstance(container_selector, str):
            entry = SelectorEntry(
                type='xpath' if container_selector.startswith('/') else 'css',
                value=container_selector,
            )
        else:
            entry = coerce_selector_entry(container_selector)
        payload = entry.model_dump_json() if entry is not None else repr(container_selector)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def extract_items(
        self,
        _url: str,
        html: str,
        validated_selectors: dict[str, dict[str, str]],
        container_selector: str | dict[str, Any] | SelectorEntry,
        max_level: SelectorLevel = max(SelectorLevel),
        *,
        runtime_evidence: Mapping[str, Sequence[str]] | None = None,
    ) -> list[dict[str, str | list[str | dict[str, str]]]] | None:
        """Synchronous convenience wrapper; async callers must use the async variant."""
        from yosoi.models.extraction import run_extraction_sync

        return run_extraction_sync(
            self.extract_items_async(
                _url,
                html,
                validated_selectors,
                container_selector,
                max_level,
                runtime_evidence=runtime_evidence,
            ),
            async_name='ContentExtractor.extract_items_async(...)',
        )

    async def extract_items_async(
        self,
        _url: str,
        html: str,
        validated_selectors: dict[str, dict[str, str]],
        container_selector: str | dict[str, Any] | SelectorEntry,
        max_level: SelectorLevel = max(SelectorLevel),
        *,
        runtime_evidence: Mapping[str, Sequence[str]] | None = None,
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
            runtime_evidence: Named values observed during the existing page acquisition.

        Returns:
            List of extracted content dicts (one per container), or None if no items found.

        """
        self.last_extractor_fingerprints.clear()
        self.last_extractor_diagnostics.clear()
        self._pending_extractor_references.clear()
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
        root_scope = self._root_scope_fingerprint(container_selector)
        for row_index, container in enumerate(containers):
            item: dict[str, Any] = {}

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

            item.update(
                await self._extract_deterministic_fields(
                    row_html=container.get(),
                    page_html=html,
                    url=_url,
                    row_index=row_index,
                    root_scope=root_scope,
                    runtime_evidence=runtime_evidence,
                )
            )

            if item:
                unflattened = self._unflatten(item, self._nested_prefixes)
                key = tuple(sorted((name, repr(value)) for name, value in unflattened.items()))
                if key in seen_items:
                    continue
                seen_items.add(key)
                items.append(unflattened)

        self.console.print(f'  ↻ Extracted {len(items)} non-empty items')
        return items if items else None

    async def _extract_deterministic_fields(  # noqa: C901
        self,
        *,
        row_html: str,
        page_html: str,
        url: str,
        row_index: int,
        root_scope: str,
        runtime_evidence: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, Any]:
        """Run extractor fields once for this row and validate before acceptance."""
        if self.contract is None or not self._extractor_bindings:
            return {}
        row = ExtractionRow(
            row_html,
            url=url,
            index=row_index,
            root_scope=root_scope,
            runtime_evidence=runtime_evidence,
        )
        values: dict[str, Any] = {}
        batch_cache: dict[str, tuple[Any, tuple[ExtractionEvidence, ...]] | BaseException] = {}
        for field_name, local_binding in self._extractor_bindings.items():
            field_info = self.contract.model_fields[field_name]
            generalized_reference: FingerprintFieldReferenceRecord | None = None
            binding = local_binding
            if binding is None:
                binding, generalized_reference = self._generalized_binding(
                    field_name=field_name,
                    page_html=page_html,
                    row_html=row_html,
                    url=url,
                    root_scope=root_scope,
                    row_index=row_index,
                )
            if binding is None:
                self.last_extractor_diagnostics.append(
                    {
                        'row': row_index,
                        'field': field_name,
                        'resolver_id': 'none',
                        'category': 'unresolved',
                    }
                )
                if field_info.is_required():
                    raise ExtractorFieldError(
                        field_name,
                        row_index,
                        'none',
                        'unresolved',
                        'no trusted deterministic extractor strategy matched this row',
                    )
                values[field_name] = self.contract.field_default(field_name)
                continue
            try:
                raw_value, evidence = await binding.execute(row, batch_cache=batch_cache)
            except ExtractorNoMatch as exc:
                self.last_extractor_diagnostics.append(
                    {
                        'row': row_index,
                        'field': field_name,
                        'resolver_id': binding.spec.resolver_id,
                        'category': 'no_match',
                    }
                )
                if field_info.is_required():
                    raise ExtractorFieldError(
                        field_name,
                        row_index,
                        binding.spec.resolver_id,
                        'no_match',
                        'extractor reported no match',
                    ) from exc
                values[field_name] = self.contract.field_default(field_name)
                continue
            try:
                value = self.contract.coerce_field(field_name, raw_value, source_url=url)
            except (TypeError, ValueError) as exc:
                self.last_extractor_diagnostics.append(
                    {
                        'row': row_index,
                        'field': field_name,
                        'resolver_id': binding.spec.resolver_id,
                        'category': 'validation_failure',
                    }
                )
                if field_info.is_required():
                    raise ExtractorFieldError(
                        field_name,
                        row_index,
                        binding.spec.resolver_id,
                        'validation_failure',
                        f'output did not satisfy the field annotation ({type(exc).__name__})',
                    ) from None
                values[field_name] = self.contract.field_default(field_name)
                continue

            fingerprint = runtime_fingerprint(
                page_html=page_html,
                row_html=row_html,
                url=url,
                root_scope=root_scope,
                field_fingerprint=self._field_fingerprints[field_name],
                binding=binding,
                evidence=evidence,
                validation_result='valid',
                value=value,
            )
            if generalized_reference is not None:
                strategy = generalized_reference.extractor
                if strategy is None or fingerprint.operations != strategy.operations:
                    self.last_extractor_diagnostics.append(
                        {
                            'row': row_index,
                            'field': field_name,
                            'resolver_id': binding.spec.resolver_id,
                            'category': 'generalization_mismatch',
                        }
                    )
                    if field_info.is_required():
                        raise ExtractorFieldError(
                            field_name,
                            row_index,
                            binding.spec.resolver_id,
                            'generalization_mismatch',
                            'current-row evidence did not match the proposed strategy',
                        )
                    values[field_name] = self.contract.field_default(field_name)
                    continue

            values[field_name] = value
            self.last_extractor_diagnostics.append(
                {
                    'row': row_index,
                    'field': field_name,
                    'resolver_id': binding.spec.resolver_id,
                    'category': 'success',
                }
            )
            self.last_extractor_fingerprints.append(fingerprint)
            if local_binding is not None:
                self._persist_extractor_reference(
                    field_name=field_name,
                    binding=binding,
                    fingerprint=fingerprint,
                    page_html=page_html,
                    url=url,
                    root_scope=root_scope,
                )
        return values

    def _generalized_binding(  # noqa: C901
        self,
        *,
        field_name: str,
        page_html: str,
        row_html: str,
        url: str,
        root_scope: str,
        row_index: int,
    ) -> tuple[ExtractorBinding | None, FingerprintFieldReferenceRecord | None]:
        """Resolve one exact, trusted stored strategy or abstain on conflict."""
        if not self._generalized_reads or self._fingerprint_store is None or self.contract is None:
            return None, None

        from yosoi.fingerprints.generalization import route_template
        from yosoi.generalization.fingerprint import PageFingerprint
        from yosoi.models.extraction import RowFingerprint

        annotation = annotation_identity(self.contract.model_fields[field_name].annotation)
        extra = self.contract.model_fields[field_name].json_schema_extra
        yosoi_type = extra.get('yosoi_type') if isinstance(extra, dict) else None
        page_fingerprint = PageFingerprint.of(page_html)
        row_fingerprint = RowFingerprint.of(row_html)
        route = route_template(url)
        candidates: list[FingerprintFieldReferenceRecord] = []
        for reference in self._fingerprint_store.list_field_references(field_name=field_name):
            strategy = reference.extractor
            if strategy is None or not strategy.extractor.portable or strategy.extractor.plan is not None:
                continue
            if strategy.extractor.reference not in self._allowed_extractor_references:
                continue
            if strategy.opaque and not self._allow_opaque_generalization:
                continue
            if strategy.output_annotation != annotation:
                continue
            if (reference.yosoi_type or None) != (yosoi_type or None):
                continue
            if reference.route_template != route or reference.root.signature != root_scope:
                continue
            if strategy.row.similarity(row_fingerprint) != 1.0:
                continue
            if not page_fingerprint.similarity(reference.fingerprint).same_shape:
                continue
            candidates.append(reference)

        strategy_ids = {
            (reference.extractor.extractor.fingerprint, reference.extractor.operations)
            for reference in candidates
            if reference.extractor is not None
        }
        if len(strategy_ids) != 1:
            if candidates:
                self.last_extractor_diagnostics.append(
                    {
                        'row': row_index,
                        'field': field_name,
                        'resolver_id': 'fingerprint',
                        'category': 'generalization_conflict',
                    }
                )
            return None, None

        reference = candidates[0]
        strategy = reference.extractor
        if strategy is None:  # pragma: no cover - narrowed above
            return None, None
        try:
            spec, fn = extractor_spec_for_callable(
                strategy.extractor.reference,
                source='generalized',
                key=strategy.extractor.resolver_id,
                version=strategy.extractor.version,
                config=strategy.extractor.config,
            )
        except (TypeError, ValueError) as exc:
            logger.debug('stored extractor strategy could not be loaded: %s', exc)
            return None, None
        spec = spec.model_copy(
            update={
                'opaque': strategy.opaque,
                'batch_fields': strategy.extractor.batch_fields,
            }
        )
        return ExtractorBinding(
            field_name=field_name,
            fn=fn,
            spec=spec,
            batch_fields=strategy.extractor.batch_fields,
        ), reference

    def _persist_extractor_reference(
        self,
        *,
        field_name: str,
        binding: ExtractorBinding,
        fingerprint: ExtractorFingerprint,
        page_html: str,
        url: str,
        root_scope: str,
    ) -> None:
        """Persist validated local strategy evidence without extracted values."""
        if (
            not self._reference_writes
            or self._fingerprint_store is None
            or self.contract is None
            or not binding.spec.portable
            or binding.spec.source == 'generalized'
        ):
            return

        from yosoi.fingerprints.generalization import extractor_strategy_from_fingerprint, route_template
        from yosoi.fingerprints.models import FingerprintFieldReferenceRecord, RootScopeRecord
        from yosoi.generalization.fingerprint import PageFingerprint

        annotation = annotation_identity(self.contract.model_fields[field_name].annotation)
        extra = self.contract.model_fields[field_name].json_schema_extra
        yosoi_type = extra.get('yosoi_type') if isinstance(extra, dict) else None
        route = route_template(url)
        reference_material = '\x1f'.join(
            (
                field_name,
                binding.spec.fingerprint,
                route,
                root_scope,
                fingerprint.page_structure,
                fingerprint.row.structure,
                fingerprint.field_fingerprint,
                *fingerprint.operations,
            )
        )
        reference_id = 'extractor-' + hashlib.sha256(reference_material.encode()).hexdigest()[:24]
        record = FingerprintFieldReferenceRecord(
            reference_id=reference_id,
            label=f'{self.contract.__name__}.{field_name}:{binding.spec.resolver_id}',
            url=route,
            route_template=route,
            fingerprint=PageFingerprint.of(page_html),
            contract_name=self.contract.__name__,
            contract_fingerprint=self._contract_fingerprint,
            field_name=field_name,
            yosoi_type=yosoi_type if isinstance(yosoi_type, str) else None,
            root=RootScopeRecord(
                kind='rootless' if root_scope == 'rootless' else 'dom',
                signature=root_scope,
            ),
            extractor=extractor_strategy_from_fingerprint(
                fingerprint,
                spec=binding.spec,
                output_annotation=annotation,
            ),
        )
        self._pending_extractor_references.append(record)

    def persist_validated_references(self) -> None:
        """Persist queued strategy references only after full-contract validation succeeds."""
        pending = tuple(self._pending_extractor_references)
        self._pending_extractor_references.clear()
        if self._fingerprint_store is None:
            return
        for record in pending:
            self._save_extractor_reference(record)

    def _save_extractor_reference(self, record: FingerprintFieldReferenceRecord) -> None:
        """Persist one queued reference while keeping storage failure non-fatal."""
        assert self._fingerprint_store is not None
        try:
            self._fingerprint_store.save_field_reference(record)
        except (OSError, ValueError) as exc:
            logger.warning('could not persist extractor fingerprint reference: %s', exc)

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
