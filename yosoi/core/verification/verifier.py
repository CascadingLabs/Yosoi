"""Verifies that CSS selectors match elements in HTML."""

import logging
from typing import Any

from parsel import Selector
from rich.console import Console

logger = logging.getLogger(__name__)

from yosoi.models import FieldSelectors, FieldVerificationResult, SelectorFailure, VerificationResult
from yosoi.models.selectors import SelectorEntry, SelectorLevel, coerce_selector_entry

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


def _accessible_name(el: Selector) -> str:
    """Best-effort accessible name from static HTML."""
    for attr in ('aria-label', 'alt', 'title', 'value'):
        value = el.attrib.get(attr)
        if value:
            return value.strip()
    return ' '.join(el.xpath('.//text()').getall()).strip()


def _role_matches(sel: Selector, entry: SelectorEntry) -> list[Selector]:
    """Best-effort role/name matching against static HTML.

    Browser AX snapshots are the stronger L2+ signal, but verifier replay only
    sees HTML. Support explicit roles and common implicit-role tags, and require
    the accessible name when the selector provides one.
    """
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


class SelectorVerifier:
    """Verifies selectors by testing them against HTML content.

    Unlike validation (which checks data contracts), verification tests
    whether selectors actually find elements in real HTML.

    Attributes:
        console: Optional Rich console for output

    """

    def __init__(self, console: Console | None = None):
        """Initialize the SelectorVerifier."""
        self.console = console

    def verify(
        self,
        html: str,
        selectors: dict[str, FieldSelectors] | dict[str, dict[str, str]],
        max_level: SelectorLevel = max(SelectorLevel),
    ) -> VerificationResult:
        """Verify all selectors against HTML content.

        Args:
            html: HTML content to verify selectors against
            selectors: Dict mapping field names to FieldSelectors models or raw dicts
            max_level: Maximum selector strategy level to test. Defaults to all.

        Returns:
            VerificationResult with per-field verification status

        """
        sel = Selector(text=html)
        results: dict[str, FieldVerificationResult] = {}

        if self.console:
            self.console.print(f'  → Verifying {len(selectors)} fields against HTML...')

        for field_name, field_data in selectors.items():
            result = self._verify_field(sel, field_name, field_data, max_level)
            results[field_name] = result

            if self.console:
                self._print_field_result(result)

        total = len(selectors)
        verified = sum(1 for r in results.values() if r.status == 'verified')

        if self.console:
            self.console.print(f'  → Summary: {verified}/{total} fields verified')

        return VerificationResult(
            total_fields=total,
            verified_count=verified,
            results=results,
        )

    def _scope_to_root(self, sel: Selector, root: SelectorEntry | None) -> Selector | None:
        """Scope *sel* to a field's root region (first match), or return *sel* when no root.

        Returns ``None`` when a root is set but matches nothing — the field's claimed
        region is absent, so it cannot verify there.
        """
        if root is None:
            return sel
        if root.type == 'xpath':
            matches = sel.xpath(root.value)
        elif root.type == 'css':
            matches = sel.css(root.value)
        else:
            return sel  # non-structural root kinds aren't scopes; ignore rather than fail
        return matches[0] if matches else None

    def _verify_field(
        self,
        sel: Selector,
        field_name: str,
        field_data: FieldSelectors | dict[str, str],
        max_level: SelectorLevel = max(SelectorLevel),
    ) -> FieldVerificationResult:
        """Verify a single field's selectors.

        Args:
            sel: Parsel Selector for the parsed HTML
            field_name: Name of the field
            field_data: FieldSelectors model or raw dict with primary/fallback/tertiary
            max_level: Maximum selector strategy level to test.

        Returns:
            FieldVerificationResult with verification status and failure details

        """
        if isinstance(field_data, FieldSelectors):
            entries: list[tuple[str, SelectorEntry | None]] = field_data.as_entries()
            root = field_data.root
        else:
            entries = [
                ('primary', coerce_selector_entry(field_data.get('primary'))),
                ('fallback', coerce_selector_entry(field_data.get('fallback'))),
                ('tertiary', coerce_selector_entry(field_data.get('tertiary'))),
            ]
            root = coerce_selector_entry(field_data.get('root'))

        # Field-level root: verify the leaf RELATIVE to its parent region, mirroring
        # extraction. A (root, leaf) pair is only trustworthy if the leaf resolves UNDER the
        # root — and the root must match. A root that matches nothing fails the field (the
        # region the field claims to live in is absent), so a wrongly-rooted ad selector
        # can't masquerade as verified against the organic block.
        scoped = self._scope_to_root(sel, root)
        if scoped is None:
            return FieldVerificationResult(
                field_name=field_name,
                status='failed',
                failed_selectors=[
                    SelectorFailure(level='root', selector=root.value if root else '', reason='root matched no element')
                ],
            )
        sel = scoped

        failed_selectors: list[SelectorFailure] = []

        for level, entry in entries:
            if entry is None:
                continue
            if entry.level > max_level:
                continue  # Skip entries above configured ceiling
            success, reason = self._test_selector(sel, entry)
            if success:
                return FieldVerificationResult(
                    field_name=field_name,
                    status='verified',
                    working_level=level,
                    selector=entry.value,
                    selector_level=entry.type,
                    failed_selectors=failed_selectors,
                )
            failed_selectors.append(
                SelectorFailure(
                    level=level,
                    selector=entry.value,
                    reason=reason,
                )
            )

        return FieldVerificationResult(
            field_name=field_name,
            status='failed',
            failed_selectors=failed_selectors,
        )

    def _test_selector(self, sel: Selector, selector: SelectorEntry | str) -> tuple[bool, str]:
        """Test if a selector finds elements in HTML.

        Args:
            sel: Parsel Selector for the parsed HTML
            selector: CSS selector string or SelectorEntry (dispatches on strategy)

        Returns:
            Tuple of (success, reason) where success is True if selector matches
            at least one element, and reason explains the result.

        """
        if isinstance(selector, str):
            value, strategy = selector, 'css'
        else:
            value, strategy = selector.value, selector.type

        if strategy in ('regex', 'jsonld', 'global_id', 'visual'):
            return False, 'unsupported_strategy'

        if not value or value == 'NA':
            return False, 'na_selector'

        try:
            if isinstance(selector, SelectorEntry) and strategy == 'attr':
                elements = sel.css(f'{value}::attr({selector.name})')
            elif isinstance(selector, SelectorEntry) and strategy == 'role':
                elements = _role_matches(sel, selector)
            else:
                elements = sel.xpath(value) if strategy == 'xpath' else sel.css(value)
            if elements:
                return True, 'found'
            return False, 'no_elements_found'
        except Exception as e:  # noqa: BLE001
            return False, f'invalid_syntax: {e}'

    def _print_field_result(self, result: FieldVerificationResult) -> None:
        """Print verification result for a single field."""
        if not self.console:
            return

        if result.status == 'verified' and result.working_level and result.selector:
            if result.working_level == 'primary':
                self.console.print(f'  ✓ {result.field_name}: primary works ({result.selector})')
            else:
                self.console.print(f'  → {result.field_name}: using {result.working_level} ({result.selector})')
        else:
            self.console.print(f'  ✗ {result.field_name}: all selectors failed')
            for failure in result.failed_selectors:
                self.console.print(f'      → {failure.level}: "{failure.selector}" → {failure.reason}')

    async def quick_test(self, url: str, selector: str) -> bool:
        """Quick test if a selector works on a URL.

        Args:
            url: URL to fetch and test
            selector: CSS selector to test

        Returns:
            True if selector finds an element with text content

        """
        import httpx2

        try:
            async with httpx2.AsyncClient() as client:
                response = await client.get(
                    url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, follow_redirects=True
                )
            sel = Selector(text=response.text)
            elements = sel.css(selector)
            return bool(elements) and bool(' '.join(elements[0].xpath('.//text()').getall()).strip())
        except (httpx2.HTTPError, ValueError) as exc:
            logger.warning('quick_test failed for selector %r on %r: %s', selector, url, exc)
            return False

    def verify_root(
        self,
        html: str,
        container_selector: str,
        field_selectors: dict[str, dict[str, Any]],
    ) -> bool:
        """Check that at least one primary field selector matches inside the container.

        Prevents sidebar/related-content containers from being cached as the page
        root. If no primary field selector finds content inside the container,
        it is not a valid root for this page.

        Args:
            html: Cleaned HTML to test against.
            container_selector: The CSS selector for the candidate root container.
            field_selectors: The discovered field selectors (primary/fallback/tertiary dicts).

        Returns:
            True if at least one primary field selector matches inside the container.

        """
        sel = Selector(text=html)

        try:
            containers = sel.css(container_selector)
        except Exception:  # noqa: BLE001
            return False

        if not containers:
            return False

        # Check the first container element — if primary fields match inside it
        # then it's a valid content container, not a sidebar or widget.
        first = containers[0]
        for field_name, field_data in field_selectors.items():
            if field_name in ('root', 'related_content'):
                continue
            primary = field_data.get('primary')
            if not primary:
                continue
            entry = coerce_selector_entry(primary)
            if entry is None:
                continue
            try:
                matches = first.css(entry.value) if entry.type == 'css' else first.xpath(entry.value)
                if matches:
                    return True
            except Exception:  # noqa: BLE001
                continue

        return False
