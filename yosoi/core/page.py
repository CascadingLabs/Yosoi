"""Generic page acquisition runtime shared by crawl, scrape, and scripts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from rich.console import Console
from tenacity import RetryError

from yosoi.core.cleaning import HTMLCleaner
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import PageFingerprint, PageObservation
from yosoi.models.results import FetchResult
from yosoi.policy.page import PageRuntimeConfig
from yosoi.utils import observability
from yosoi.utils.exceptions import BotDetectionError, DownloadError
from yosoi.utils.retry import get_async_retryer

if TYPE_CHECKING:
    from yosoi.models.download import DownloadSpec

DebugSaveHtml = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True)
class PageSnapshot:
    """Acquired page data before crawl/scrape-specific interpretation."""

    url: str
    final_url: str
    raw_html: str
    cleaned_html: str | None
    fetch_result: FetchResult
    fingerprint: PageFingerprint | None = None
    observation: PageObservation | None = None

    @property
    def html_for_discovery(self) -> str:
        """Return the normalized HTML if present, else the raw page HTML."""
        return self.cleaned_html or self.raw_html


class PageAcquisitionError(RuntimeError):
    """Raised when a page cannot be acquired under the configured policy."""


class PageAcquisition:
    """Fetch, clean, and observe a page without owning crawl or scrape semantics."""

    def __init__(
        self,
        config: PageRuntimeConfig,
        *,
        cleaner: HTMLCleaner | None = None,
        console: Console | None = None,
        save_debug_html: DebugSaveHtml | None = None,
        fingerprint: bool = True,
    ) -> None:
        """Create a reusable acquisition runtime."""
        self.config = config
        self.console = console or Console(quiet=True)
        self.cleaner = cleaner or HTMLCleaner(console=self.console)
        self.save_debug_html = save_debug_html
        self.fingerprint = fingerprint

    async def acquire(
        self,
        url: str,
        *,
        fetcher: Any,
        action_scripts: Mapping[str, str] | None = None,
        download_specs: Mapping[str, DownloadSpec] | None = None,
    ) -> PageSnapshot:
        """Acquire one page through the provided fetcher."""
        result = await self._fetch(
            url,
            fetcher=fetcher,
            action_scripts=dict(action_scripts) if action_scripts else None,
            download_specs=dict(download_specs) if download_specs else None,
        )
        raw_html = result.html
        if raw_html is None:
            raise PageAcquisitionError(f'No HTML content received for {url}')

        headers = getattr(result, 'headers', None)
        cleaned_html: str | None = None
        if self.config.clean_html and self.config.cleaner_profile == 'discovery' and _should_clean_html(headers):
            cleaned_html = self.cleaner.clean_html(raw_html)
            if not cleaned_html:
                raise PageAcquisitionError(f'HTML cleaning failed for {url}')
            if self.save_debug_html is not None:
                await self.save_debug_html(url, cleaned_html)

        page_fingerprint: PageFingerprint | None = None
        observation: PageObservation | None = None
        if self.fingerprint:
            page_fingerprint, observation = self._observe(
                str(getattr(result, 'url', url)),
                raw_html,
                ax_snapshot=getattr(result, 'ax_snapshot', None),
                headers=headers,
                endpoints=getattr(result, 'endpoints', None),
            )

        return PageSnapshot(
            url=url,
            final_url=str(getattr(result, 'url', url)),
            raw_html=raw_html,
            cleaned_html=cleaned_html,
            fetch_result=result,
            fingerprint=page_fingerprint,
            observation=observation,
        )

    async def _fetch(
        self,
        url: str,
        *,
        fetcher: Any,
        action_scripts: dict[str, str] | None,
        download_specs: dict[str, DownloadSpec] | None,
    ) -> FetchResult:
        def before_sleep_log(retry_state: Any) -> None:
            exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
            reason = type(exc).__name__ if exc is not None else 'unknown'
            observability.warning(
                f'Retrying fetch url={url} attempt={retry_state.attempt_number} reason={reason}',
                url=url,
                attempt=retry_state.attempt_number,
                reason=reason,
            )

        try:
            retryer = get_async_retryer(
                max_attempts=self.config.max_fetch_retries,
                wait_min=1,
                wait_max=10,
                exceptions=(BotDetectionError, Exception),
                log_callback=before_sleep_log,
                reraise=False,
                non_retry_exceptions=(DownloadError,),
            )

            async for attempt in retryer:
                with attempt:
                    kwargs: dict[str, Any] = {}
                    if action_scripts is not None:
                        kwargs['action_scripts'] = action_scripts
                    if download_specs is not None:
                        kwargs['download_specs'] = download_specs
                    result = cast(FetchResult, await fetcher.fetch(url, **kwargs))
                    if not result.success:
                        raise PageAcquisitionError(f'Fetch failed: {result.block_reason or "unknown error"}')
                    if result.html is None:
                        raise PageAcquisitionError('No HTML content received')
                    return result
        except RetryError as exc:
            last = exc.last_attempt.exception()
            message = str(last) if last is not None else f'All fetch attempts failed for {url}'
            raise PageAcquisitionError(message) from exc

        raise PageAcquisitionError(f'Fetch failed for {url}')

    @staticmethod
    def _observe(
        url: str,
        html: str,
        *,
        ax_snapshot: Any = None,
        headers: Mapping[str, str] | None = None,
        endpoints: Any = None,
    ) -> tuple[PageFingerprint | None, PageObservation | None]:
        try:
            fingerprint = PageFingerprint.of(html, ax_snapshot=ax_snapshot, headers=headers, endpoints=endpoints)
            observation = observe_html(url, html, row_selector='')
        except (AttributeError, TypeError, ValueError):
            return None, None
        return fingerprint, observation


def _should_clean_html(headers: Mapping[str, str] | None) -> bool:
    if not headers:
        return True
    content_type = ''
    for key, value in headers.items():
        if key.lower() == 'content-type':
            content_type = value.lower()
            break
    if not content_type:
        return True
    return 'html' in content_type or content_type.startswith('text/plain')


__all__ = ['PageAcquisition', 'PageAcquisitionError', 'PageSnapshot']
