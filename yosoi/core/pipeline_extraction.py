"""Extraction mixin — page data retrieval: fetch, clean, extract, JS outputs, downloads.

Contains: _fetch, _clean, _extract, _extract_with_cached, _merge_fetch_outputs,
_merge_js_outputs, _merge_downloads, _record_downloads, _finalize_downloads.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from tenacity import RetryCallState, RetryError

from yosoi.models.results import JsOutputs, VerificationResult
from yosoi.models.selectors import SelectorLevel
from yosoi.utils import observability
from yosoi.utils.exceptions import BotDetectionError, DownloadError
from yosoi.utils.retry import get_async_retryer

if TYPE_CHECKING:
    from yosoi.core.fetcher import HTMLFetcher
    from yosoi.models.contract import Contract
    from yosoi.models.download import DownloadResult, DownloadSpec
    from yosoi.models.results import FetchResult

# Type aliases — defined at module level so they exist at runtime (used in cast() calls)
ContentMap = dict[str, object]
ContentItems = list[dict[str, object]]

logger = logging.getLogger(__name__)


class PipelineExtractionMixin:
    """Methods for fetching HTML, cleaning it, and extracting field content."""

    # Pipeline attributes referenced here (set in __init__)
    console: Console
    cleaner: Any
    extractor: Any
    verifier: Any
    debug: Any
    selector_level: SelectorLevel
    contract: type[Contract]
    _allow_downloads: bool
    _download_log: list[tuple[str, DownloadResult]]
    _keep_downloads: bool
    _download_dir: str | None
    _url_start: float

    async def _fetch(
        self,
        url: str,
        fetcher: HTMLFetcher,
        max_retries: int = 2,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, DownloadSpec] | None = None,
    ) -> FetchResult | None:
        """Fetch HTML with automatic retry logic for bot detection."""
        self.console.print(Panel(f'Processing: {url}', style='bold blue'))
        self.console.print('[step]Step 1: Fetching HTML...[/step]')

        def before_sleep_log(retry_state: RetryCallState) -> None:
            attempt = retry_state.attempt_number
            if attempt >= 1:
                self.console.print(f'[warning]Fetch retry attempt {attempt}/{max_retries}...[/warning]')
                observability.warning('Retrying fetch', url=url, attempt=attempt)

        try:
            retryer = get_async_retryer(
                max_attempts=max_retries,
                wait_min=1,
                wait_max=10,
                exceptions=(BotDetectionError, Exception),
                log_callback=before_sleep_log,
                reraise=False,
                non_retry_exceptions=(DownloadError,),
            )

            async for attempt in retryer:
                with attempt:
                    result = None
                    try:
                        result = await fetcher.fetch(url, action_scripts=action_scripts, download_specs=download_specs)

                        if not result.success:
                            self.console.print(
                                f'[danger]Fetch failed: {result.block_reason or "Unknown error"}[/danger]'
                            )
                            raise Exception(f'Fetch failed: {result.block_reason}')

                        if result.html is None:
                            self.console.print('[danger]No HTML content received[/danger]')
                            raise Exception('No HTML content received')

                        self.console.print(
                            f'[success]Fetched {len(result.html):,} characters of HTML ({result.fetch_time:.2f}s)[/success]'
                        )
                        return result

                    except BotDetectionError as e:
                        self._handle_bot_detection(e, attempt.retry_state.attempt_number, max_retries)
                        raise

                    except (httpx.HTTPError, OSError, ValueError, RuntimeError) as e:
                        if str(e) not in [
                            'No HTML content received',
                            f'Fetch failed: {getattr(result, "block_reason", "Unknown")}',
                        ]:
                            self.console.print(f'[danger]Unexpected error: {e}[/danger]')
                            logger.exception('Fetch error for %s', url)
                            observability.warning(
                                'Fetch error', url=url, error=str(e), attempt=attempt.retry_state.attempt_number
                            )
                        raise

        except RetryError:
            self.console.print(f'[danger]All {max_retries} attempts failed[/danger]')
            return None
        except (httpx.HTTPError, OSError, ValueError, RuntimeError):
            return None

        return None

    async def _clean(self, url: str, result: FetchResult) -> str | None:
        """Clean HTML by removing noise and extracting main content."""
        assert result.html is not None, 'result.html should not be None in _clean'

        self.console.print('[step]Step 1.5: Cleaning HTML...[/step]')
        cleaned_html: str = self.cleaner.clean_html(result.html)

        if not cleaned_html:
            self.console.print('[danger]HTML cleaning produced empty result[/danger]')
            return None

        await self.debug.save_debug_html(url, cleaned_html)
        self.console.print(f'[success]Cleaned HTML ready ({len(cleaned_html):,} chars)[/success]')
        return cleaned_html

    def _extract(
        self,
        url: str,
        html: str,
        verified_selectors: dict[str, Any],
        container_selector: str | None = None,
    ) -> ContentMap | ContentItems | None:
        """Extract content from HTML using verified selectors."""
        self.console.print('[step]Step 4: Extracting content using verified selectors...[/step]')

        if container_selector:
            items = self.extractor.extract_items(
                url, html, verified_selectors, container_selector, max_level=self.selector_level
            )
            if not items:
                self.console.print('[danger]Content extraction failed - no items extracted[/danger]')
                return None
            self.console.print(f'[success]Extracted {len(items)} items successfully[/success]')
            return items

        extracted = self.extractor.extract_content_with_html(
            url, html, verified_selectors, max_level=self.selector_level
        )

        if not extracted:
            self.console.print('[danger]Content extraction failed - no content extracted[/danger]')
            return None

        self.console.print(f'[success]Extracted content from {len(extracted)} fields successfully[/success]')
        return extracted

    async def _extract_with_cached(
        self,
        url: str,
        fetcher: HTMLFetcher,
        existing_selectors: dict[str, Any],
        skip_verification: bool,
    ) -> tuple[ContentItems | None, bool]:
        """Fetch, optionally verify, and extract content using cached selectors."""
        step = (
            'Fetching HTML for extraction with cached selectors...'
            if skip_verification
            else 'Fetching HTML to verify cached selectors...'
        )
        self.console.print(f'[step]{step}[/step]')

        domain = self._extract_domain(url)  # type: ignore[attr-defined]
        await self._discover_js_actions(url, domain, fetcher)  # type: ignore[attr-defined]
        js_scripts = await self._resolve_js_scripts(domain)  # type: ignore[attr-defined]
        download_specs = self._resolve_download_specs(fetcher)  # type: ignore[attr-defined]
        try:
            result = await fetcher.fetch(url, action_scripts=js_scripts or None, download_specs=download_specs)

            if not result.success or result.html is None:
                self.console.print('[warning]⚠ Could not fetch HTML, skipping extraction[/warning]')
                return None, True

            self.console.print('[step]Cleaning HTML...[/step]')
            cleaned_html: str = self.cleaner.clean_html(result.html)
            await self.debug.save_debug_html(url, cleaned_html)

            root_entry = self._resolve_root(existing_selectors)  # type: ignore[attr-defined]
            container_selector = self._root_value(root_entry)  # type: ignore[attr-defined]

            if root_entry and not skip_verification:
                from parsel import Selector as _PS

                from yosoi.models.selectors import coerce_selector_entry

                primary = root_entry.get('primary')
                _entry = coerce_selector_entry(primary) if primary else None
                if _entry is not None:
                    _ok, _ = self.verifier._test_selector(_PS(text=cleaned_html), _entry)
                    if not _ok:
                        self.console.print(
                            '[warning]⚠ Cached container selector failed — forcing re-discovery[/warning]'
                        )
                        return None, False

            if not skip_verification:
                verification = self.verifier.verify(cleaned_html, existing_selectors, max_level=self.selector_level)
                if not verification.success:
                    self.console.print(
                        '[warning]⚠ Cached selectors failed verification - forcing re-discovery[/warning]'
                    )
                    return None, False
                selectors_to_use = {
                    name: existing_selectors[name]
                    for name in verification.results
                    if verification.results[name].status == 'verified'
                }
                self.console.print(
                    f'[success]✓ Verified {len(selectors_to_use)}/{len(self.contract.discovery_field_names())} cached selectors[/success]'
                )
                overridden = set(self.contract.get_selector_overrides())
                required_fields = self.contract.discovery_field_names() - overridden
                missing = required_fields - set(selectors_to_use)
                if missing:
                    self.console.print(
                        f'[warning]⚠ New contract fields not in cache: {", ".join(sorted(missing))} — re-discovering[/warning]'
                    )
                    return None, False
            else:
                selectors_to_use = existing_selectors

            extracted = self._extract(url, cleaned_html, selectors_to_use, container_selector)
            extracted = self._merge_fetch_outputs(extracted, result)
            self._record_downloads(result.downloads)
            if extracted:
                if isinstance(extracted, list):
                    return extracted, True
                return [extracted], True

            self.console.print('[warning]⚠ Extraction failed with cached selectors[/warning]')
            return None, True

        except (BotDetectionError, DownloadError):
            raise
        except Exception as e:
            logger.exception('Cached selector handling failed for %s', url)
            self.console.print(f'[warning]⚠ Error: {e}, skipping extraction[/warning]')
            return None, True

    @staticmethod
    def _merge_js_outputs(
        extracted: ContentMap | ContentItems | None,
        js_outputs: JsOutputs | None,
    ) -> ContentMap | ContentItems | None:
        """Merge js_outputs from action scripts into extracted content."""
        from typing import cast

        if not js_outputs:
            return extracted
        if extracted is None:
            return cast(ContentMap, dict(js_outputs))
        if isinstance(extracted, list):
            return cast(ContentItems, [{**item, **js_outputs} for item in extracted])
        return cast(ContentMap, {**extracted, **js_outputs})

    @staticmethod
    def _merge_downloads(
        extracted: ContentMap | ContentItems | None,
        downloads: dict[str, DownloadResult] | None,
    ) -> ContentMap | ContentItems | None:
        """Merge ys.File() download results into extracted content."""
        from typing import cast

        if not downloads:
            return extracted
        values: dict[str, Any] = {field: result.value for field, result in downloads.items()}
        if extracted is None:
            return cast(ContentMap, dict(values))
        if isinstance(extracted, list):
            return cast(ContentItems, [{**item, **values} for item in extracted])
        return cast(ContentMap, {**extracted, **values})

    @classmethod
    def _merge_fetch_outputs(
        cls,
        extracted: ContentMap | ContentItems | None,
        result: FetchResult,
    ) -> ContentMap | ContentItems | None:
        """Merge live-tab action outputs (ys.js() and ys.File()) into extracted content."""
        if result.js_outputs:
            extracted = cls._merge_js_outputs(extracted, result.js_outputs)
        if result.downloads:
            extracted = cls._merge_downloads(extracted, result.downloads)
        return extracted

    def _record_downloads(self, downloads: dict[str, DownloadResult] | None) -> None:
        """Log each ys.File() download and accumulate it for the run-end manifest."""
        if not downloads:
            return
        for field, result in downloads.items():
            self._download_log.append((field, result))
            rec = result.record
            logger.info(
                'download field=%s path=%s sha256=%s size=%d content_type=%s changed=%s',
                field,
                rec.path,
                rec.sha256[:12],
                rec.size_bytes,
                rec.content_type,
                result.changed,
            )

    def _finalize_downloads(self) -> None:
        """At run end: print a download manifest and, unless keeping them, purge the bytes."""
        import contextlib

        if not getattr(self, '_download_log', None):
            return

        table = Table(title='Downloads', expand=False)
        table.add_column('field', style='cyan')
        table.add_column('type', style='dim')
        table.add_column('size', justify='right')
        table.add_column('changed', justify='center')
        table.add_column('path', style='dim', overflow='fold')
        total_bytes = 0
        for field, result in self._download_log:
            rec = result.record
            total_bytes += rec.size_bytes
            table.add_row(
                field,
                rec.content_type or '?',
                f'{rec.size_bytes / 1024:.1f} KiB',
                '✓' if result.changed else '·',
                rec.path,
            )
        self.console.print(table)
        self.console.print(f'[dim]{len(self._download_log)} download(s), {total_bytes / 1024:.1f} KiB total[/dim]')

        if not self._keep_downloads:
            purged = 0
            for _field, result in self._download_log:
                with contextlib.suppress(OSError):
                    Path(result.record.path).unlink(missing_ok=True)
                    purged += 1
            self.console.print(f'[dim]purged {purged} download blob(s); provenance retained in index.json[/dim]')

    def _handle_bot_detection(self, error: BotDetectionError, attempt: int, max_retries: int) -> None:
        """Handle bot detection error."""
        self.console.print(f'[danger]BOT DETECTION (Attempt {attempt}/{max_retries})[/danger]')
        self.console.print(f'[danger]URL: {error.url}[/danger]')
        self.console.print(f'[danger]Status Code: {error.status_code}[/danger]')
        self.console.print(f'[danger]Indicators: {", ".join(error.indicators)}[/danger]')

        logger.warning(
            'Bot detection (attempt %d/%d) for %s (status=%d): %s',
            attempt,
            max_retries,
            error.url,
            error.status_code,
            ', '.join(error.indicators),
        )
        observability.warning(
            'Bot detection triggered',
            url=error.url,
            status_code=error.status_code,
            indicators=','.join(error.indicators),
            attempt=attempt,
            max_retries=max_retries,
        )

        if attempt >= max_retries:
            self.console.print('[danger]ABORTING - All fetch attempts exhausted[/danger]')
            self.console.print('[info]All fetch attempts exhausted for this URL[/info]')

    def _verify(
        self, _url: str, html: str, selectors: dict[str, Any], skip_verification: bool
    ) -> dict[str, Any] | None:
        """Verify discovered selectors against HTML."""
        if skip_verification:
            self.console.print('[warning]Skipping verification (--skip-verification enabled)[/warning]')
            return selectors

        self.console.print('[step]Step 3: Verifying selectors against actual HTML...[/step]')

        result = self.verifier.verify(html, selectors, max_level=self.selector_level)
        self._last_level_distribution = result.level_distribution

        if not result.success:
            self._print_verification_failure(result)
            return None

        verified = {name: selectors[name] for name in result.results if result.results[name].status == 'verified'}
        failed_count = len(selectors) - len(verified)
        self.console.print(f'[success]Verified {len(verified)}/{result.total_fields} fields successfully[/success]')

        if failed_count >= 1:
            self._print_partial_failure(result)

        return verified

    def _print_verification_failure(self, result: VerificationResult) -> None:
        """Print detailed failure summary when all selectors fail."""
        self.console.print('[danger]Verification failed - no selectors matched![/danger]')
        self.console.print('')
        for field_name, field_result in result.results.items():
            self.console.print(f'  [danger]✗ {field_name}[/danger]')
            for failure in field_result.failed_selectors:
                self.console.print(
                    f'      [dim]→ {failure.level}:[/dim] "{failure.selector}" [warning]→ {failure.reason}[/warning]'
                )
        self.console.print('')

    def _print_partial_failure(self, result: VerificationResult) -> None:
        """Print summary of partial failures."""
        failed_fields = [name for name in result.results if result.results[name].status == 'failed']
        self.console.print(f'[warning]  ⚠ {len(failed_fields)} field(s) failed verification:[/warning]')
        for field_name in failed_fields:
            field_result = result.results[field_name]
            reasons = [f.reason for f in field_result.failed_selectors if f.reason != 'na_selector']
            primary_reason = reasons[0] if reasons else 'all_na'
            self.console.print(f'      [dim]• {field_name}:[/dim] {primary_reason}')

    async def _record_fetch_strategy_selector_level(self, fetcher: Any, domain: str) -> None:
        """Cache the highest selector level that worked with the domain loading strategy."""
        from yosoi.core.fetcher.waterfall import JSFetcher

        if not isinstance(fetcher, JSFetcher):
            return
        level_dist = getattr(self, '_last_level_distribution', None)
        if not level_dist:
            return
        order = [level.name.lower() for level in sorted(SelectorLevel)]
        highest = next((level for level in reversed(order) if level_dist.get(level)), None)
        if highest is not None:
            await fetcher.update_selector_level(domain, highest)
