"""Small programmatic API for in-memory Yosoi scraping."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence

from yosoi.core.configs import YosoiConfig, auto_config
from yosoi.core.discovery import LLMConfig
from yosoi.core.fetcher.identity import BrowserIdentity
from yosoi.core.pipeline import ContentMap, Pipeline
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.utils import observability as obs
from yosoi.utils.contracts import resolve_contract


async def scrape(
    url: str | Sequence[str],
    contract: type[Contract] | str | Sequence[type[Contract] | str],
    model: YosoiConfig | LLMConfig | str | None = None,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str | Mapping[str, str] | Callable[[str], str] = 'simple',
    selector_level: SelectorLevel = SelectorLevel.CSS,
    save_formats: Sequence[str] = (),
    quiet: bool = True,
    allow_downloads: bool = False,
    allowed_download_types: Sequence[str] = (),
    download_dir: str | None = None,
    max_download_bytes: int | None = None,
    keep_downloads: bool = True,
    identities: Mapping[str, BrowserIdentity] | Callable[[str], BrowserIdentity | None] | None = None,
    max_concurrency: int | None = None,
) -> list[ContentMap] | dict[str, list[ContentMap]] | dict[str, dict[str, list[ContentMap]]]:
    """Scrape one-or-many URLs with one-or-many contracts — the single blessed path.

    ``url`` and ``contract`` each take a scalar OR a list; the return shape follows which axes
    are lists, and every ``(url, contract)`` unit runs CONCURRENTLY under one shared
    write-lock (so per-domain selector writes don't race):

      * ``scrape(url, Contract)``      -> ``list[record]``
      * ``scrape(url, [A, B])``        -> ``{contract_name: [records]}``
      * ``scrape([u1, u2], Contract)`` -> ``{url: [records]}``
      * ``scrape([u1, u2], [A, B])``   -> ``{url: {contract_name: [records]}}``

    Multiple data contracts for the SAME page (an ad-result vs an organic-result block)
    discover concurrently and do not block one another. NOTE: no ``DiscoveryBus`` is shared
    across distinct contracts — the bus dedupes on ``field_signature`` (name + description +
    type, NOT the contract intent), so sharing it would force e.g. ``Ad.url == Organic.url``,
    the opposite of discrimination. Related contracts must learn to DIVERGE, not dedup.

    ``fetcher_type`` is a scalar OR a per-URL ``{url: tier}`` map / ``url -> tier`` callable, so
    different engines get different tiers in ONE concurrent call (e.g. ``google: 'headful'``,
    ``bing``/``brave``: ``'headless'``). ``max_concurrency`` (opt-in) caps how many
    ``(url, contract)`` units run at once — set it on big SERP grids so you don't open hundreds
    of tabs and trip anti-bot; default ``None`` is unbounded (today's behavior).

    ``identities`` is an OPT-IN, per-URL :class:`~yosoi.core.fetcher.identity.BrowserIdentity`
    (a dict ``{url: identity}`` or a ``url -> identity | None`` callable). It is how you opt
    into the *sensitive* choices a SERP scrape needs — a trusted Chromium ``profile_dir``,
    ``headful``, a ``geo`` teleport, ``proxy``/``locale``/``timezone_id`` — PER URL, so e.g. a
    google tab runs headful+profile while bing/brave tabs run plain headless, all concurrently.
    Default ``None`` keeps today's behavior exactly. An identity needs a browser
    ``fetcher_type`` (``headless``/``headful``); the ``simple`` fetcher ignores it (and warns).

    By default this API does not write files. Pass ``save_formats=('json',)`` for file output.
    ``ys.File()`` download fields need ``allow_downloads=True`` + a browser ``fetcher_type``;
    ``allowed_download_types``/``download_dir``/``max_download_bytes``/``keep_downloads`` tune
    the download lane (see :func:`_scrape_one`).

    FUTURE: fetch-once — each ``(url, contract)`` unit fetches independently, so N contracts on
    one URL = N fetches (bad for anti-bot SERPs); share one fetched+cleaned HTML per URL.
    FUTURE: cross-contract discrimination "path-planning" — when two contracts' selectors
    overlap, coordinate them apart (Tier-1 region gate + a re-discover divergence loop in
    ``yosoi.core.discovery.discrimination``); today field-level root + per-contract intent
    discriminate by construction, but nothing ENFORCES disjointness here yet.
    FUTURE: bound URL-axis concurrency (a semaphore) and concurrent page SELECTION.
    """
    urls: list[str] = [url] if isinstance(url, str) else list(url)
    raw_contracts = [contract] if isinstance(contract, (str, type)) else list(contract)
    contract_clss = [resolve_contract(c) if isinstance(c, str) else c for c in raw_contracts]
    multi_url = not isinstance(url, str)
    multi_contract = not isinstance(contract, (str, type))

    def _identity_for(u: str) -> BrowserIdentity | None:
        if identities is None:
            return None
        return identities(u) if callable(identities) else identities.get(u)

    def _fetcher_for(u: str) -> str:
        if isinstance(fetcher_type, str):
            return fetcher_type
        return fetcher_type(u) if callable(fetcher_type) else fetcher_type.get(u, 'simple')

    write_lock = asyncio.Lock() if (multi_url or multi_contract) else None
    sem = asyncio.Semaphore(max_concurrency) if max_concurrency else None
    pairs = [(u, c) for u in urls for c in contract_clss]

    async def _unit(u: str, c: type[Contract]) -> list[ContentMap]:
        async def _go() -> list[ContentMap]:
            return await _scrape_one(
                u,
                c,
                model,
                force=force,
                skip_verification=skip_verification,
                fetcher_type=_fetcher_for(u),
                selector_level=selector_level,
                save_formats=save_formats,
                quiet=quiet,
                allow_downloads=allow_downloads,
                allowed_download_types=allowed_download_types,
                download_dir=download_dir,
                max_download_bytes=max_download_bytes,
                keep_downloads=keep_downloads,
                write_lock=write_lock,
                identity=_identity_for(u),
            )

        if sem is None:
            return await _go()
        async with sem:
            return await _go()

    flat = await asyncio.gather(*(_unit(u, c) for (u, c) in pairs))
    cell = {(u, c.__name__): flat[i] for i, (u, c) in enumerate(pairs)}

    if multi_url and multi_contract:
        return {u: {c.__name__: cell[u, c.__name__] for c in contract_clss} for u in urls}
    if multi_url:
        name = contract_clss[0].__name__
        return {u: cell[u, name] for u in urls}
    if multi_contract:
        return {c.__name__: cell[urls[0], c.__name__] for c in contract_clss}
    return flat[0]


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
    write_lock: asyncio.Lock | None = None,
    identity: BrowserIdentity | None = None,
) -> list[ContentMap]:
    """One ``(url, contract)`` unit (returns ``list[record]``).

    ``write_lock`` is the shared per-call lock that :func:`scrape` threads through so
    concurrent units don't race on per-domain selector writes; ``None`` for a lone scrape.
    ``identity`` is the opt-in per-URL :class:`BrowserIdentity` (profile/headful/geo).
    """
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
                write_lock=write_lock,
                identity=identity,
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
