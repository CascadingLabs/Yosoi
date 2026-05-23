"""Small programmatic API for in-memory Yosoi scraping."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from yosoi.core.configs import YosoiConfig, auto_config
from yosoi.core.discovery import LLMConfig
from yosoi.core.pipeline import ContentMap, Pipeline
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.utils.contracts import resolve_contract


async def scrape(
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
    """Scrape one URL and return validated native Python dictionaries.

    By default this API does not write JSON/CSV/etc. files. Pass
    ``save_formats=('json',)`` when file output is wanted.
    """
    contract_cls = resolve_contract(contract) if isinstance(contract, str) else contract
    llm_config = _resolve_model(model)
    async with Pipeline(
        llm_config=llm_config,
        contract=contract_cls,
        output_format=list(save_formats),
        force=force,
        quiet=quiet,
        selector_level=selector_level,
    ) as pipeline:
        return [
            item
            async for item in pipeline.scrape(
                url,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=fetcher_type,
                output_format=list(save_formats),
            )
        ]


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
    results: dict[str, list[ContentMap]] = {}
    for url in urls:
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
    raise RuntimeError('scrape_sync() cannot run inside an active event loop; await scrape() instead.')


def _resolve_model(model: YosoiConfig | LLMConfig | str | None) -> YosoiConfig | LLMConfig:
    if model is None:
        return auto_config()
    if isinstance(model, str):
        return auto_config(model=model)
    return model
