"""Small programmatic API for in-memory Yosoi scraping."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from yosoi.core.configs import YosoiConfig, auto_config
from yosoi.core.discovery import LLMConfig
from yosoi.core.fetcher.identity import BrowserIdentity
from yosoi.core.pipeline import ContentMap, Pipeline
from yosoi.core.pipeline.discovery_gate import DiscoveryGate
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.models.snapshot import SnapshotMap
from yosoi.storage.recipe_loader import is_recipe_source, load_recipe
from yosoi.utils import observability as obs
from yosoi.utils.contracts import resolve_contract

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from yosoi.generalization.fingerprint import PageFingerprint

# Per-contract capture for the cross-contract discrimination gate.
GateCollector = dict[str, tuple[dict[str, Any], str | None]]

_ATOM_STORE_PATH = '.yosoi/atoms.jsonl'


def fingerprint(
    source: object,
    *,
    ax_snapshot: Any = None,
    headers: Mapping[str, str] | None = None,
    endpoints: Sequence[str] | None = None,
) -> PageFingerprint:
    """Compute a page fingerprint from HTML or a Yosoi fetch result."""
    from yosoi.reporting.fingerprint import coerce_fingerprint

    return coerce_fingerprint(source, ax_snapshot=ax_snapshot, headers=headers, endpoints=endpoints)


def _run_discrimination_gates(
    collectors: dict[str, GateCollector], contract_by_name: dict[str, type[Contract]]
) -> None:
    store = None
    for url, collected in collectors.items():
        report = _advisory_discrimination_gate(url, collected)
        if report is None or not report.accepted:
            continue
        if store is None:
            from yosoi.storage.atoms import AtomStore, default_store_path

            store_path = _ATOM_STORE_PATH if _ATOM_STORE_PATH != '.yosoi/atoms.jsonl' else default_store_path()
            store = AtomStore(store_path)
        _internalize_accepted(store, url, collected, contract_by_name)


def _advisory_discrimination_gate(url: str, collected: GateCollector) -> Any:
    if len(collected) < 2:
        return None
    try:
        from yosoi.core.discovery.discrimination import evaluate_discrimination

        maps = {name: selectors for name, (selectors, _html) in collected.items()}
        html = next((h for (_s, h) in collected.values() if h), None)
        if not html:
            return None
        report = evaluate_discrimination(html, maps)
        logger.log(
            logging.INFO if report.accepted else logging.WARNING,
            'discrimination gate url=%s accepted=%s reason=%s footprints=%s overlaps=%s',
            url,
            report.accepted,
            report.reason,
            report.footprints,
            report.overlaps,
        )
        return report
    except Exception as exc:  # noqa: BLE001
        logger.debug('discrimination gate skipped (url=%s): %s', url, exc)
        return None


def _internalize_accepted(
    store: Any,
    url: str,
    collected: GateCollector,
    contract_by_name: dict[str, type[Contract]],
) -> None:
    try:
        from yosoi.core.discovery.discrimination import _STRUCTURAL
        from yosoi.generalization.capture import observe_html
        from yosoi.generalization.fingerprint import is_degenerate_shape, page_shape_fp
        from yosoi.models.selectors import coerce_selector_entry
        from yosoi.storage.atoms import derive_atoms
        from yosoi.utils.signatures import _get_yosoi_type

        html = next((h for (_s, h) in collected.values() if h), None)
        if not html:
            return
        page_shape = page_shape_fp(observe_html(url, html, row_selector=''))
        if is_degenerate_shape(page_shape):
            return
        domain = obs.normalize_user_id(url) or url

        minted = reused = 0
        for name, (selectors, _h) in collected.items():
            cls = contract_by_name.get(name)
            fields = []
            for field_name, slot in selectors.items():
                if field_name in _STRUCTURAL or not isinstance(slot, dict):
                    continue
                primary = coerce_selector_entry(slot.get('primary'))
                if primary is None:
                    continue
                root = coerce_selector_entry(slot.get('root'))
                yosoi_type = _get_yosoi_type(cls, field_name) if cls else None
                fields.append((field_name, primary.model_dump(), root.value if root else None, yosoi_type))
            atoms = derive_atoms(page_shape, name, domain, fields, source='verified')
            new = store.upsert_all(atoms)
            minted += new
            reused += len(atoms) - new
        logger.info(
            'field-atoms internalized url=%s shape=%s minted=%d reused=%d store_total=%d',
            url,
            page_shape,
            minted,
            reused,
            len(store),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug('field-atom dual-write skipped (url=%s): %s', url, exc)


async def _resolve_contract_and_preload(
    contract,  # type[Contract] | str
    selectors: str | dict[str, SnapshotMap] | None = None,
) -> tuple[type[Contract], dict[str, SnapshotMap] | None]:
    """Resolve a contract and optionally load selectors from a separate source.

    Handles four cases:
    1. contract is a full recipe URL/path  → load bundle, extract contract + selectors
    2. contract is a contract JSON/URL     → load just the contract; selectors separate
    3. selectors is a string (URL/path)    → load selectors from that source
    4. selectors is already a dict         → use directly as preloaded snapshots

    Args:
        contract: A Contract class, name string, recipe URL/path, or contract JSON path.
        selectors: Optional separate selector source — a URL/path string or already-loaded
            dict[domain, SnapshotMap]. When provided, overrides any selectors that would
            have come from a recipe bundle.

    Returns:
        (contract_cls, preloaded_snapshots_or_None)
    """
    from yosoi.utils.contract_io import is_contract_source, load_contract
    from yosoi.utils.selector_io import is_selector_source, load_selectors

    # Case 1: full recipe source (has both contract and selectors bundled)
    # Only treat as recipe when no separate selectors are provided and it looks
    # like a recipe (not a bare contract JSON).
    if isinstance(contract, str) and is_recipe_source(contract) and selectors is None:
        bundle = await load_recipe(contract)
        Pipeline._recipe_source = contract
        contract_cls = bundle.contract.to_contract()
        return contract_cls, bundle.selectors

    # Case 2: contract is a standalone contract JSON/URL
    if isinstance(contract, str) and is_contract_source(contract):
        contract_cls = await load_contract(contract)
    else:
        contract_cls = resolve_contract(contract) if isinstance(contract, str) else contract

    # Case 3 & 4: resolve selectors from a separate source
    preloaded: dict[str, SnapshotMap] | None = None
    if selectors is not None:
        if isinstance(selectors, str):
            if not is_selector_source(selectors):
                raise ValueError(
                    f'selectors={selectors!r} does not look like a valid selector source. '
                    'Expected a local .json path, an https:// URL, or a gh: ref.'
                )
            preloaded = await load_selectors(selectors)
        elif isinstance(selectors, dict):
            # Already loaded by the caller — validate shape
            preloaded = {}
            for domain, value in selectors.items():
                if isinstance(value, SnapshotMap):
                    preloaded[domain] = value
                elif isinstance(value, dict):
                    preloaded[domain] = SnapshotMap.model_validate(value)
                else:
                    raise ValueError(
                        f'selectors dict entry for {domain!r} must be a SnapshotMap '
                        f'or dict, got {type(value).__name__}.'
                    )
        else:
            raise ValueError(
                f'selectors must be a string (path/URL) or dict[domain, SnapshotMap], got {type(selectors).__name__}.'
            )

    return contract_cls, preloaded


async def scrape(
    url: str | Sequence[str],
    contract: type[Contract] | str | Sequence[type[Contract] | str],
    model: YosoiConfig | LLMConfig | str | None = None,
    *,
    selectors: str | dict[str, SnapshotMap] | None = None,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str | Mapping[str, str] | Callable[[str], str] = 'auto',
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
    """Scrape one-or-many URLs with one-or-many contracts.

    The ``selectors`` parameter lets you supply pre-discovered selector snapshots
    from a separate source rather than discovering them fresh or using a bundled
    recipe. This enables mixing and matching:

    - Your contract + someone else's selectors::

        await scrape(url, contract=MyContract,
                     selectors="gh:someone/selectors/shopify.json")

    - Someone else's contract + your local selectors::

        await scrape(url, contract="gh:someone/contracts/product.json",
                     selectors="selectors/my_shopify.json")

    - A full recipe (contract + selectors bundled, existing behavior)::

        await scrape(url, contract="gh:someone/recipes/shopify.json")

    - No selectors (discover fresh, existing behavior)::

        await scrape(url, contract=MyContract)

    Args:
        url: Single URL string or list of URLs.
        contract: Contract class, name string, local .json path, https:// URL,
            gh: ref pointing to a ContractSpec JSON, or a full recipe URL/path
            (when selectors is None).
        model: LLM configuration. Defaults to auto-detected provider.
        selectors: Optional separate selector source. Accepts:
            - A local .json path to a selector snapshot file
            - An https:// URL to a selector snapshot file
            - A gh:owner/repo/path@ref shorthand
            - A pre-loaded dict[domain, SnapshotMap]
            When provided, these selectors are used instead of discovering fresh
            or loading from a recipe bundle. Selectors for domains not covered
            fall through to normal discovery if a model is configured.
        force: Force re-discovery even if selectors are cached.
        skip_verification: Skip selector verification for faster processing.
        fetcher_type: HTML fetcher to use. Defaults to 'auto'.
        selector_level: Maximum selector strategy level. Defaults to CSS.
        save_formats: Output formats to save (e.g. ('json',)).
        quiet: Suppress console output.
        allow_downloads: Enable ys.File() downloads.
        allowed_download_types: Run-wide file-type allowlist.
        download_dir: Quarantine root for downloads.
        max_download_bytes: Run-wide per-file size cap.
        keep_downloads: Keep downloaded files after the run.
        identities: Per-URL browser identities.
        max_concurrency: Cap on concurrent (url, contract) units.

    Returns:
        - ``scrape(url, Contract)``      → ``list[record]``
        - ``scrape(url, [A, B])``        → ``{contract_name: [records]}``
        - ``scrape([u1, u2], Contract)`` → ``{url: [records]}``
        - ``scrape([u1, u2], [A, B])``   → ``{url: {contract_name: [records]}}``
    """
    urls: list[str] = [url] if isinstance(url, str) else list(url)
    raw_contracts = [contract] if isinstance(contract, (str, type)) else list(contract)

    contract_clss = []
    preloaded_by_contract: dict[str, dict[str, SnapshotMap] | None] = {}

    for raw in raw_contracts:
        cls, preloaded = await _resolve_contract_and_preload(raw, selectors)
        contract_clss.append(cls)
        preloaded_by_contract[cls.__name__] = preloaded

    multi_url = not isinstance(url, str)
    multi_contract = not isinstance(contract, (str, type))

    def _identity_for(u: str) -> BrowserIdentity | None:
        if identities is None:
            return None
        return identities(u) if callable(identities) else identities.get(u)

    def _fetcher_for(u: str) -> str:
        if isinstance(fetcher_type, str):
            return fetcher_type
        return fetcher_type(u) if callable(fetcher_type) else fetcher_type.get(u, 'auto')

    write_lock = asyncio.Lock() if (multi_url or multi_contract) else None
    discovery_gate = DiscoveryGate()
    sem = asyncio.Semaphore(max_concurrency) if max_concurrency else None
    pairs = [(u, c) for u in urls for c in contract_clss]

    gate_collectors: dict[str, GateCollector] = {u: {} for u in urls}

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
                gate_collect=gate_collectors[u],
                discovery_gate=discovery_gate,
                preloaded=preloaded_by_contract.get(c.__name__),
            )

        if sem is None:
            return await _go()
        async with sem:
            return await _go()

    flat = await asyncio.gather(*(_unit(u, c) for (u, c) in pairs))
    cell = {(u, c.__name__): flat[i] for i, (u, c) in enumerate(pairs)}

    _run_discrimination_gates(gate_collectors, {c.__name__: c for c in contract_clss})

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
    fetcher_type: str = 'auto',
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
    gate_collect: GateCollector | None = None,
    discovery_gate: DiscoveryGate | None = None,
    preloaded: dict[str, SnapshotMap] | None = None,
) -> list[ContentMap]:
    """One (url, contract) unit — returns list[record]."""
    contract_cls = resolve_contract(contract) if isinstance(contract, str) else contract
    llm_config = _resolve_model(model)
    save_format_list = list(save_formats)
    from yosoi.models.snapshot import SnapshotMap
    from yosoi.utils.urls import extract_domain

    preloaded_snapshots = None
    if preloaded is not None:
        domain = extract_domain(url)
        covered = domain in preloaded or any(domain.endswith('.' + k) or k.endswith('.' + domain) for k in preloaded)
        if not covered:
            raise ValueError(
                f'Selector source does not cover domain {domain!r}.\n'
                f'The provided selectors cover: {list(preloaded.keys())}.\n'
                f'Re-fetch selectors targeting {domain!r}, or scrape a URL '
                f'from one of the covered domains.'
            )
        preloaded_snapshots = {}
        for domain_key, value in preloaded.items():
            if isinstance(value, SnapshotMap):
                preloaded_snapshots[domain_key] = value
            elif isinstance(value, dict):
                preloaded_snapshots[domain_key] = SnapshotMap.model_validate(value)

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
                discovery_gate=discovery_gate,
                preloaded_snapshots=preloaded_snapshots,
            ) as pipeline:
                items = [
                    item
                    async for item in pipeline.scrape(
                        url,
                        force=force,
                        skip_verification=skip_verification,
                        fetcher_type=fetcher_type,
                        output_format=save_format_list,
                    )
                ]
                last_selectors = getattr(pipeline, 'last_selectors', None)
                if gate_collect is not None and last_selectors is not None:
                    gate_collect[contract_cls.__name__] = (last_selectors, getattr(pipeline, 'last_cleaned_html', None))
                return items
        except Exception as e:
            obs.warning('API scrape failed', url=url, contract=contract_cls.__name__, error=str(e))
            raise


async def scrape_many(
    urls: Sequence[str],
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | str | None = None,
    *,
    selectors: str | dict[str, SnapshotMap] | None = None,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'auto',
    selector_level: SelectorLevel = SelectorLevel.CSS,
    save_formats: Sequence[str] = (),
    quiet: bool = True,
) -> dict[str, list[ContentMap]]:
    """Scrape multiple URLs and return items keyed by URL.

    Args:
        urls: List of URLs to scrape.
        contract: Contract class, name, local .json path, or URL.
        model: LLM configuration.
        selectors: Optional separate selector source (path, URL, or preloaded dict).
        force: Force re-discovery.
        skip_verification: Skip selector verification.
        fetcher_type: HTML fetcher to use.
        selector_level: Maximum selector strategy level.
        save_formats: Output formats to save.
        quiet: Suppress console output.

    Returns:
        Dict mapping URL strings to lists of extracted records.
    """
    url_list = list(urls)
    with obs.span(
        'api.scrape_many',
        urls=len(url_list),
        contract=contract if isinstance(contract, str) else contract.__name__,
    ):
        results: dict[str, list[ContentMap]] = {}
        current_url: str | None = None
        try:
            # Resolve contract + selectors once, reuse across all URLs
            contract_cls, preloaded = await _resolve_contract_and_preload(contract, selectors)
            for url in url_list:
                current_url = url
                results[url] = await _scrape_one(
                    url,
                    contract_cls,
                    model,
                    force=force,
                    skip_verification=skip_verification,
                    fetcher_type=fetcher_type,
                    selector_level=selector_level,
                    save_formats=save_formats,
                    quiet=quiet,
                    preloaded=preloaded,
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
    selectors: str | dict[str, SnapshotMap] | None = None,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'auto',
    selector_level: SelectorLevel = SelectorLevel.CSS,
    save_formats: Sequence[str] = (),
    quiet: bool = True,
) -> list[ContentMap]:
    """Synchronous wrapper around scrape().

    Args:
        url: URL to scrape.
        contract: Contract class, name, local .json path, or URL.
        model: LLM configuration.
        selectors: Optional separate selector source (path, URL, or preloaded dict).
        force: Force re-discovery.
        skip_verification: Skip selector verification.
        fetcher_type: HTML fetcher to use.
        selector_level: Maximum selector strategy level.
        save_formats: Output formats to save.
        quiet: Suppress console output.

    Returns:
        List of extracted records.

    Raises:
        RuntimeError: If called inside an active event loop.
    """
    with obs.span(
        'api.scrape_sync',
        url=url,
        contract=contract if isinstance(contract, str) else contract.__name__,
    ):
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
                    preloaded=(asyncio.run(_resolve_selectors_only(selectors)) if selectors is not None else None),
                )
            )
        error = 'scrape_sync() cannot run inside an active event loop; await scrape() instead.'
        obs.warning('API scrape_sync called inside active event loop', url=url)
        raise RuntimeError(error)


async def _resolve_selectors_only(
    selectors: str | dict[str, SnapshotMap],
) -> dict[str, SnapshotMap] | None:
    """Resolve selectors from a string source without resolving a contract."""
    from yosoi.utils.selector_io import is_selector_source, load_selectors

    if isinstance(selectors, str):
        if not is_selector_source(selectors):
            raise ValueError(
                f'selectors={selectors!r} does not look like a valid selector source. '
                'Expected a local .json path, an https:// URL, or a gh: ref.'
            )
        return await load_selectors(selectors)
    return selectors if isinstance(selectors, dict) else None


def _resolve_model(model: YosoiConfig | LLMConfig | str | None) -> YosoiConfig | LLMConfig:
    if model is None:
        return auto_config()
    if isinstance(model, str):
        return auto_config(model=model)
    return model


def _model_label(model: YosoiConfig | LLMConfig) -> str:
    llm = model.llm if isinstance(model, YosoiConfig) else model
    return f'{llm.provider}:{llm.model_name}'
