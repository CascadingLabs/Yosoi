"""Taskiq broker and task definitions for concurrent URL processing.

Uses InMemoryBroker with SmartRetryMiddleware for in-process async concurrency.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from taskiq import InMemoryBroker
from taskiq.middlewares import SmartRetryMiddleware

from yosoi.core.configs import YosoiConfig
from yosoi.core.discovery.config import LLMConfig
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel

logger = logging.getLogger(__name__)

broker = InMemoryBroker().with_middlewares(
    SmartRetryMiddleware(
        default_retry_count=3,
        use_jitter=True,
        use_delay_exponent=True,
        default_delay=1,
        max_delay_exponent=30,
    ),
)

# Module-level state injected at startup
_pipeline_config: dict[str, Any] = {}
_semaphore: asyncio.Semaphore | None = None


async def configure_broker(
    llm_config: LLMConfig | YosoiConfig,
    contract: type[Contract],
    output_format: str | list[str] = 'json',
    max_workers: int = 5,
    selector_level: SelectorLevel | None = None,
) -> None:
    """Configure the broker with pipeline settings and start it.

    Args:
        llm_config: LLM or full Yosoi configuration.
        contract: Contract subclass for scraping fields.
        output_format: Output format(s): json, markdown, jsonl, ndjson, csv, xlsx, parquet.
        max_workers: Maximum concurrent tasks.
        selector_level: Maximum selector strategy level. Defaults to CSS.

    """
    global _semaphore
    _pipeline_config['llm_config'] = llm_config
    _pipeline_config['contract'] = contract
    _pipeline_config['output_format'] = output_format
    _pipeline_config['max_workers'] = max_workers
    _pipeline_config['selector_level'] = selector_level or SelectorLevel.CSS
    _semaphore = asyncio.Semaphore(max_workers)
    await broker.startup()


async def shutdown_broker() -> None:
    """Shut down the broker cleanly."""
    global _semaphore
    await broker.shutdown()
    _pipeline_config.clear()
    _semaphore = None


def get_pipeline_config() -> dict[str, Any]:
    """Return the current pipeline configuration.

    Returns:
        Dictionary with llm_config, contract, output_format, max_workers.

    Raises:
        RuntimeError: If broker has not been configured.

    """
    if not _pipeline_config:
        raise RuntimeError('Broker not configured. Call configure_broker() first.')
    return _pipeline_config


@broker.task(retry_on_error=True, max_retries=2)
async def process_url_task(
    url: str,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'simple',
    max_fetch_retries: int = 2,
    max_discovery_retries: int = 3,
) -> dict[str, Any]:
    """Process a single URL as a taskiq task.

    Creates a fresh Pipeline instance per task to avoid shared mutable state.

    Args:
        url: URL to process.
        force: Force re-discovery.
        skip_verification: Skip verification step.
        fetcher_type: Fetcher type to use.
        max_fetch_retries: Max fetch retry attempts.
        max_discovery_retries: Max AI discovery retry attempts.

    Returns:
        Dictionary with 'url', 'success', and optionally 'error'.

    """
    from yosoi.core.pipeline import Pipeline

    config = get_pipeline_config()
    sem = _semaphore or asyncio.Semaphore(5)

    async with sem:
        pipeline = Pipeline(
            config['llm_config'],
            contract=config['contract'],
            output_format=config['output_format'],
            quiet=True,
            selector_level=config.get('selector_level', SelectorLevel.CSS),
        )

        start = time.monotonic()
        try:
            success = await pipeline.process_url(
                url,
                force=force,
                max_fetch_retries=max_fetch_retries,
                max_discovery_retries=max_discovery_retries,
                skip_verification=skip_verification,
                fetcher_type=fetcher_type,
            )
            elapsed = time.monotonic() - start
            return {'url': url, 'success': success, 'elapsed': elapsed}
        except Exception:
            logger.exception('Task failed for %s', url)
            # We reraise so that taskiq can do its job of handling retries w/ its middleware
            raise


class DomainDedup:
    """Track which domains have been enqueued to prevent duplicate processing.

    Attributes:
        _seen: Set of domains already enqueued.

    """

    def __init__(self) -> None:
        """Initialize with empty set."""
        self._seen: set[str] = set()

    def should_process(self, domain: str) -> bool:
        """Check if domain should be processed (not yet seen).

        Args:
            domain: Domain string to check.

        Returns:
            True if domain has not been seen before.

        """
        if domain in self._seen:
            return False
        self._seen.add(domain)
        return True

    def reset(self) -> None:
        """Clear all tracked domains."""
        self._seen.clear()


async def enqueue_urls(
    urls: list[str],
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'simple',
    max_fetch_retries: int = 2,
    max_discovery_retries: int = 3,
    dedup_by_domain: bool = True,
    on_complete: Callable[[str, bool, float], Awaitable[None]] | None = None,
) -> dict[str, list]:
    """Enqueue URLs as tasks and collect results.

    Args:
        urls: List of URLs to process.
        force: Force re-discovery.
        skip_verification: Skip verification step.
        fetcher_type: Fetcher type to use.
        max_fetch_retries: Max fetch retry attempts.
        max_discovery_retries: Max AI discovery retry attempts.
        dedup_by_domain: Skip duplicate domains. Defaults to True.
        on_complete: Optional async callback ``(url, success, elapsed)`` called
            when each task finishes. Used by the CLI progress display.

    Returns:
        Dictionary with 'successful' and 'failed' URL lists,
        plus 'skipped' for deduped URLs.

    """
    results: dict[str, list] = {'successful': [], 'failed': [], 'skipped': []}
    dedup = DomainDedup()

    # Enqueue all tasks
    handles = []
    enqueued_urls = []

    for url in urls:
        if dedup_by_domain:
            parse_url = url if url.startswith(('http://', 'https://')) else f'https://{url}'
            domain = urlparse(parse_url).netloc.replace('www.', '')
            if not dedup.should_process(domain):
                logger.info('Skipping duplicate domain: %s (url: %s)', domain, url)
                results['skipped'].append(url)
                continue

        handle = await process_url_task.kiq(
            url,
            force=force,
            skip_verification=skip_verification,
            fetcher_type=fetcher_type,
            max_fetch_retries=max_fetch_retries,
            max_discovery_retries=max_discovery_retries,
        )
        handles.append(handle)
        enqueued_urls.append(url)

    # Collect results
    for handle, url in zip(handles, enqueued_urls, strict=True):
        task_result = await _wait_for_handle(handle, url)
        _collect_single_result(results, handle, url, task_result)
        if on_complete is not None:
            rv = task_result.return_value if task_result and not task_result.is_err else None
            success = rv.get('success', False) if rv else False
            elapsed = rv.get('elapsed', 0.0) if rv else 0.0
            await on_complete(url, success, elapsed)

    return results


async def _wait_for_handle(handle, url: str):
    """Await a single task handle, returning the result or None on error.

    Args:
        handle: Taskiq async result handle.
        url: URL for logging on failure.

    Returns:
        The TaskiqResult, or None if waiting failed.

    """
    try:
        return await handle.wait_result(timeout=120)
    except Exception:
        logger.exception('Failed to get result for %s', url)
        return None


def _collect_single_result(results: dict[str, list], handle, url: str, result) -> None:
    """Classify a single task result into successful or failed.

    Args:
        results: Accumulator dict with 'successful' and 'failed' lists.
        handle: The task handle (unused, kept for interface consistency).
        url: The URL that was processed.
        result: The TaskiqResult or None.

    """
    if result is None or result.is_err:
        results['failed'].append(url)
    elif result.return_value and result.return_value.get('success'):
        results['successful'].append(url)
    else:
        results['failed'].append(url)
