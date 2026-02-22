"""Verifies that CSS selectors match elements in HTML."""

from bs4 import BeautifulSoup
from rich.console import Console

from yosoi.models import FieldSelectors, FieldVerificationResult, SelectorFailure, VerificationResult


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
    ) -> VerificationResult:
        """Verify all selectors against HTML content.

        Args:
            html: HTML content to verify selectors against
            selectors: Dict mapping field names to FieldSelectors models or raw dicts

        Returns:
            VerificationResult with per-field verification status

        """
        soup = BeautifulSoup(html, 'lxml')
        results: dict[str, FieldVerificationResult] = {}

        if self.console:
            self.console.print(f'  → Verifying {len(selectors)} fields against HTML...')

        for field_name, field_data in selectors.items():
            result = self._verify_field(soup, field_name, field_data)
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
        soup: BeautifulSoup,
        field_name: str,
        field_data: FieldSelectors | dict[str, str],
    ) -> FieldVerificationResult:
        """Verify a single field's selectors.

        Args:
            soup: Parsed HTML
            field_name: Name of the field
            field_data: FieldSelectors model or raw dict with primary/fallback/tertiary

        Returns:
            FieldVerificationResult with verification status and failure details

        """
        if isinstance(field_data, FieldSelectors):
            selectors = field_data.as_tuples()
        else:
            selectors = [
                ('primary', field_data.get('primary')),
                ('fallback', field_data.get('fallback')),
                ('tertiary', field_data.get('tertiary')),
            ]

        failed_selectors: list[SelectorFailure] = []

        for level, selector in selectors:
            success, reason = self._test_selector(soup, selector)
            if success:
                return FieldVerificationResult(
                    field_name=field_name,
                    status='verified',
                    working_level=level,
                    selector=selector,
                    failed_selectors=failed_selectors,
                )
            failed_selectors.append(
                SelectorFailure(
                    level=level,
                    selector=selector,
                    reason=reason,
                )
            )

        return FieldVerificationResult(
            field_name=field_name,
            status='failed',
            failed_selectors=failed_selectors,
        )

    def _test_selector(self, soup: BeautifulSoup, selector: str) -> tuple[bool, str]:
        """Test if a selector finds elements in HTML.

        Args:
            soup: Parsed HTML
            selector: CSS selector string

        Returns:
            Tuple of (success, reason) where success is True if selector matches
            at least one element, and reason explains the result.

        """
        if not selector or selector == 'NA':
            return False, 'na_selector'

        try:
            elements = soup.select(selector)
            if elements:
                return True, 'found'
            return False, 'no_elements_found'
        except Exception as e:
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

    def verify_selectors_with_html(
        self,
        _url: str,
        html: str,
        selectors: dict[str, dict[str, str]],
    ) -> dict[str, dict[str, str]] | None:
        """Backward-compatible method for legacy callers.

        Args:
            _url: URL (unused, kept for API compatibility)
            html: HTML content to verify against
            selectors: Dict of field names to selector dicts

        Returns:
            Dict of verified selectors, or None if none verified

        Deprecated:
            Use verify() instead for structured results.

        """
        result = self.verify(html, selectors)

        if not result.success:
            return None

        return {name: selectors[name] for name in result.results if result.results[name].status == 'verified'}

    def quick_test(self, url: str, selector: str) -> bool:
        """Quick test if a selector works on a URL.

        Args:
            url: URL to fetch and test
            selector: CSS selector to test

        Returns:
            True if selector finds an element with text content

        """
        import requests

        try:
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            soup = BeautifulSoup(response.text, 'lxml')
            element = soup.select_one(selector)
            return element is not None and bool(element.get_text(strip=True))
        except Exception:
            return False
