"""Verifies that CSS selectors match elements in HTML."""

import logging

from parsel import Selector
from rich.console import Console

logger = logging.getLogger(__name__)

from yosoi.models import FieldSelectors, FieldVerificationResult, SelectorFailure, VerificationResult
from yosoi.models.selectors import SelectorEntry, SelectorLevel, coerce_selector_entry


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
        max_level: SelectorLevel = SelectorLevel.CSS,
    ) -> VerificationResult:
        """Verify all selectors against HTML content.

        Args:
            html: HTML content to verify selectors against
            selectors: Dict mapping field names to FieldSelectors models or raw dicts
            max_level: Maximum selector strategy level to test. Defaults to CSS.

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

    def _verify_field(
        self,
        sel: Selector,
        field_name: str,
        field_data: FieldSelectors | dict[str, str],
        max_level: SelectorLevel = SelectorLevel.CSS,
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
        else:
            entries = [
                ('primary', coerce_selector_entry(field_data.get('primary'))),
                ('fallback', coerce_selector_entry(field_data.get('fallback'))),
                ('tertiary', coerce_selector_entry(field_data.get('tertiary'))),
            ]

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

        if not value or value == 'NA':
            return False, 'na_selector'

        if strategy in ('regex', 'jsonld'):
            return False, 'unsupported_strategy'

        try:
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
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, follow_redirects=True
                )
            sel = Selector(text=response.text)
            elements = sel.css(selector)
            return bool(elements) and bool(' '.join(elements[0].xpath('.//text()').getall()).strip())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning('quick_test failed for selector %r on %r: %s', selector, url, exc)
            return False
