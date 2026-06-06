"""Small programmatic API for in-memory Yosoi scraping."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from yosoi.core.configs import YosoiConfig, auto_config
from yosoi.core.discovery import LLMConfig
from yosoi.core.pipeline import ContentMap, Pipeline
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.utils import observability as obs
from yosoi.utils.contracts import resolve_contract


async def scrape(
    url: str,
    contract: type[Contract] | str | Sequence[type[Contract] | str],
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
) -> list[ContentMap] | dict[str, list[ContentMap]]:
    """Scrape one URL and return validated native Python dictionaries.

    ``contract`` is ONE contract — returning ``list[record]`` — or a LIST of contracts for
    the same page (separate data contracts, e.g. an ad-result and an organic-result block),
    returning ``{contract_name: [records]}``. The multi-contract form discovers concurrently
    (the contracts do not block one another); see :func:`_scrape_multi`.

    By default this API does not write JSON/CSV/etc. files. Pass
    ``save_formats=('json',)`` when file output is wanted.

    For ``ys.File()`` download fields, set ``allow_downloads=True`` and use a browser
    ``fetcher_type`` (``'headless'``/``'headful'``/``'waterfall'``). ``allowed_download_types``
    is an optional run-wide file-type allowlist intersected with each field's own.
    ``download_dir`` overrides the quarantine root (default ``.yosoi/downloads/``) and
    ``max_download_bytes`` sets a run-wide per-file cap (used when a field sets no ``max_bytes``).
    ``keep_downloads=False`` purges the downloaded bytes at run end (provenance is retained).
    """
    if not isinstance(contract, (str, type)):  # a list/sequence of contracts
        return await _scrape_multi(
            url,
            contract,
            model,
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
    return await _scrape_one(
        url,
        contract,
        model,
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


async def _scrape_one(
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
    allow_downloads: bool = False,
    allowed_download_types: Sequence[str] = (),
    download_dir: str | None = None,
    max_download_bytes: int | None = None,
    keep_downloads: bool = True,
) -> list[ContentMap]:
    """Single-contract scrape — the original ``scrape`` body (returns ``list[record]``)."""
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


async def _scrape_multi(
    url: str,
    contracts: Sequence[type[Contract] | str],
    model: YosoiConfig | LLMConfig | str | None,
    *,
    force: bool,
    skip_verification: bool,
    fetcher_type: str,
    selector_level: SelectorLevel,
    save_formats: Sequence[str],
    quiet: bool,
    allow_downloads: bool,
    allowed_download_types: Sequence[str],
    download_dir: str | None,
    max_download_bytes: int | None,
    keep_downloads: bool,
) -> dict[str, list[ContentMap]]:
    """Scrape one URL with MANY contracts — separate data contracts for the same page.

    Discovery is CONCURRENT: the contracts discover at once and do not block one another
    (``asyncio.gather``), sharing a write-lock so their per-domain selector writes don't
    race. Returns ``{contract_name: [records]}``.

    Deliberately does NOT share a ``DiscoveryBus`` across contracts: the bus dedupes on
    ``field_signature`` (field name + description + type), so sharing it would force e.g. an
    ``Ad`` and an ``Organic`` contract's ``url`` to the SAME selector — the opposite of
    discrimination. Related contracts must learn to DIVERGE, not dedup.

    FUTURE: fetch-once — today each contract's pipeline fetches the URL, so N contracts means
    N fetches (bad for anti-bot SERPs); share one fetched+cleaned HTML across contracts.
    FUTURE: cross-contract discrimination "path-planning" — when two contracts' selectors
    overlap, coordinate them apart (the Tier-1 region gate + a re-discover divergence loop in
    ``yosoi.core.discovery.discrimination``). Today field-level root + per-contract intent
    discriminate by construction, but nothing ENFORCES disjointness here yet.
    FUTURE: concurrent page SELECTION/extraction (joint planning) — not worked out yet.
    """
    contract_clss = [resolve_contract(c) if isinstance(c, str) else c for c in contracts]
    llm_config = _resolve_model(model)
    save_format_list = list(save_formats)
    write_lock = asyncio.Lock()

    async def _one(contract_cls: type[Contract]) -> list[ContentMap]:
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
            write_lock=write_lock,
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

    with obs.span('api.scrape_multi', url=url, contracts=len(contract_clss), model=_model_label(llm_config)):
        results = await asyncio.gather(*(_one(c) for c in contract_clss))
    return {c.__name__: r for c, r in zip(contract_clss, results, strict=True)}


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
                results[url] = await _scrape_one(
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
                _scrape_one(
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
