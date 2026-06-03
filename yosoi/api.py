"""Small programmatic API for in-memory Yosoi scraping."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from yosoi.core.configs import YosoiConfig, auto_config
from yosoi.core.discovery import LLMConfig
from yosoi.core.pipeline import ContentMap, Pipeline
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.utils import observability as obs
from yosoi.utils.contracts import resolve_contract


async def scrape(
    url: str | Sequence[str],
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | str | None = None,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'simple',
    selector_level: SelectorLevel = SelectorLevel.CSS,
    save_formats: Sequence[str] = (),
    quiet: bool = True,
    allow_downloads: bool = False,
    allowed_download_types: Sequence[str] = (),
    download_dir: str | None = None,
    max_download_bytes: int | None = None,
    keep_downloads: bool = True,
    max_concurrency: int = 8,
) -> list[ContentMap]:
    """Scrape one URL and return validated native Python dictionaries.

    By default this API does not write JSON/CSV/etc. files. Pass
    ``save_formats=('json',)`` when file output is wanted.

    For ``ys.File()`` download fields, set ``allow_downloads=True`` and use a browser
    ``fetcher_type`` (``'headless'``/``'headful'``/``'waterfall'``). ``allowed_download_types``
    is an optional run-wide file-type allowlist intersected with each field's own.
    ``download_dir`` overrides the quarantine root (default ``.yosoi/downloads/``) and
    ``max_download_bytes`` sets a run-wide per-file cap (used when a field sets no ``max_bytes``).
    ``keep_downloads=False`` purges the downloaded bytes at run end (provenance is retained).

    Pass a list of URLs to scrape them with automatic concurrency: the recipe is
    discovered once per domain (serially), then the rest fan out concurrently as
    cache hits. Returns the items flattened in input order. [SPIKE — see CAS ticket]
    """
    if not isinstance(url, str):
        urls = list(url)
        if not urls:
            return []
        # Concurrency only engages for MORE THAN ONE URL; a single-element list is
        # a plain scrape (no domain-seeding, no semaphore, no fan-out).
        if len(urls) > 1:
            return await _scrape_urls(
                urls,
                contract,
                model,
                max_concurrency=max_concurrency,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=fetcher_type,
                selector_level=selector_level,
                save_formats=save_formats,
                quiet=quiet,
                allow_downloads=allow_downloads,
                allowed_download_types=allowed_download_types,
                download_dir=download_dir,
                max_download_bytes=max_download_bytes,
                keep_downloads=keep_downloads,
            )
        url = urls[0]

    contract_cls = resolve_contract(contract) if isinstance(contract, str) else contract
    llm_config = _resolve_model(model)
    save_format_list = list(save_formats)
    with obs.span(
        'api.scrape',
        url=url,
        contract=contract_cls.__name__,
        model=_model_label(llm_config),
        fetcher_type=fetcher_type,
        selector_level=selector_level.value,
        save_formats=','.join(save_format_list),
    ):
        try:
            async with Pipeline(
                llm_config=llm_config,
                contract=contract_cls,
                output_format=save_format_list,
                force=force,
                quiet=quiet,
                selector_level=selector_level,
                allow_downloads=allow_downloads,
                allowed_download_types=tuple(allowed_download_types),
                download_dir=download_dir,
                max_download_bytes=max_download_bytes,
                keep_downloads=keep_downloads,
            ) as pipeline:
                return [
                    item
                    async for item in pipeline.scrape(
                        url,
                        force=force,
                        skip_verification=skip_verification,
                        fetcher_type=fetcher_type,
                        output_format=save_format_list,
                    )
                ]
        except Exception as e:
            obs.warning('API scrape failed', url=url, contract=contract_cls.__name__, error=str(e))
            raise


async def _scrape_urls(
    urls: list[str],
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | str | None,
    *,
    max_concurrency: int,
    **kwargs: Any,
) -> list[ContentMap]:
    """Concurrent multi-URL scrape: discover once per domain, replay the rest in parallel.

    Seeding each domain serially warms its per-domain selector cache before the
    concurrent replays, so a list of same-domain URLs costs ONE discovery, not N.
    """
    if not urls:
        return []
    by_domain: dict[str, list[str]] = {}
    for u in urls:
        by_domain.setdefault(urlsplit(u).netloc, []).append(u)

    results: dict[str, list[ContentMap]] = {}
    deferred: list[str] = []
    for members in by_domain.values():
        results[members[0]] = await scrape(members[0], contract, model, **kwargs)
        deferred.extend(members[1:])

    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _one(u: str) -> tuple[str, list[ContentMap]]:
        async with semaphore:
            return u, await scrape(u, contract, model, **kwargs)

    results.update(dict(await asyncio.gather(*(_one(u) for u in deferred))))
    return [item for u in urls for item in results.get(u, [])]


async def scrape_many(
    urls: Sequence[str],
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | str | None = None,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'simple',
    selector_level: SelectorLevel = SelectorLevel.CSS,
    save_formats: Sequence[str] = (),
    quiet: bool = True,
) -> dict[str, list[ContentMap]]:
    """Scrape multiple URLs and return items keyed by URL."""
    url_list = list(urls)
    with obs.span(
        'api.scrape_many', urls=len(url_list), contract=contract if isinstance(contract, str) else contract.__name__
    ):
        results: dict[str, list[ContentMap]] = {}
        current_url: str | None = None
        try:
            for url in url_list:
                current_url = url
                results[url] = await scrape(
                    url,
                    contract,
                    model,
                    force=force,
                    skip_verification=skip_verification,
                    fetcher_type=fetcher_type,
                    selector_level=selector_level,
                    save_formats=save_formats,
                    quiet=quiet,
                )
        except Exception as e:
            obs.warning('API scrape_many URL failed', url=current_url, error=str(e))
            raise
        return results


def scrape_sync(
    url: str,
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | str | None = None,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'simple',
    selector_level: SelectorLevel = SelectorLevel.CSS,
    save_formats: Sequence[str] = (),
    quiet: bool = True,
) -> list[ContentMap]:
    """Synchronous wrapper around :func:`scrape`."""
    with obs.span('api.scrape_sync', url=url, contract=contract if isinstance(contract, str) else contract.__name__):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                scrape(
                    url,
                    contract,
                    model,
                    force=force,
                    skip_verification=skip_verification,
                    fetcher_type=fetcher_type,
                    selector_level=selector_level,
                    save_formats=save_formats,
                    quiet=quiet,
                )
            )
        error = 'scrape_sync() cannot run inside an active event loop; await scrape() instead.'
        obs.warning('API scrape_sync called inside active event loop', url=url)
        raise RuntimeError(error)


def _resolve_model(model: YosoiConfig | LLMConfig | str | None) -> YosoiConfig | LLMConfig:
    if model is None:
        return auto_config()
    if isinstance(model, str):
        return auto_config(model=model)
    return model


def _model_label(model: YosoiConfig | LLMConfig) -> str:
    llm = model.llm if isinstance(model, YosoiConfig) else model
    return f'{llm.provider}:{llm.model_name}'
