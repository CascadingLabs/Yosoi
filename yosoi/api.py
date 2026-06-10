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
from yosoi.policy import DiscoveryPolicy, DownloadPolicy, ModelPolicy, OutputPolicy, Policy, ScrapePolicy
from yosoi.utils import observability as obs
from yosoi.utils.contracts import resolve_contract

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from yosoi.generalization.fingerprint import PageFingerprint

# Per-contract capture for the cross-contract discrimination gate: contract name ->
# (selector_map, cleaned_html) from that contract's fresh discovery on a page.
GateCollector = dict[str, tuple[dict[str, Any], str | None]]

# Default on-disk field-atom corpus (P2 dual-write target). Gitignored like .yosoi/.
_ATOM_STORE_PATH = '.yosoi/atoms.jsonl'


def fingerprint(
    source: object,
    *,
    ax_snapshot: Any = None,
    headers: Mapping[str, str] | None = None,
    endpoints: Sequence[str] | None = None,
) -> PageFingerprint:
    """Compute a page fingerprint from HTML or a Yosoi fetch result.

    This is the high-level escape hatch for inspecting page shape directly:
    pass raw HTML, or pass an object with ``.html`` plus optional
    ``.ax_snapshot``, ``.headers``, and ``.endpoints`` attributes. It never
        reads ``.yosoi`` cache files.
    """
    from yosoi.reporting.fingerprint import coerce_fingerprint

    return coerce_fingerprint(source, ax_snapshot=ax_snapshot, headers=headers, endpoints=endpoints)


def _run_discrimination_gates(
    collectors: dict[str, GateCollector], contract_by_name: dict[str, type[Contract]]
) -> None:
    """Gate each URL's contract set; on ACCEPT, dual-write its atoms (P1.5 + P2).

    The gate verdict is logged advisory (P1.5). When a set is ACCEPTED — non-empty,
    pairwise-disjoint regions — its selectors are internalized into the field-atom store
    (P2 dual-write). A REJECTED set writes NOTHING: never internalize a conflation.
    Reads still come from the legacy lesson cache; this only builds the atom corpus.
    """
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
    """Run the discrimination gate over a page's contract set and LOG the verdict (P1.5).

    Returns the :class:`DiscriminationReport` (or None when <2 contracts / no HTML / a
    failure), so the caller can gate dual-write on ``report.accepted``. Best-effort — a
    gate failure must never break a scrape.
    """
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
    except Exception as exc:  # noqa: BLE001 — advisory gate must never break a scrape
        logger.debug('discrimination gate skipped (url=%s): %s', url, exc)
        return None


def _internalize_accepted(
    store: Any,
    url: str,
    collected: GateCollector,
    contract_by_name: dict[str, type[Contract]],
) -> None:
    """Dual-write a gate-ACCEPTED page's selectors into the field-atom store (P2).

    Each contract's content fields become atoms keyed by ``(page_shape, region, field,
    yosoi_type)`` — domain-independent, so the next mirror/locale merges provenance
    instead of re-minting. Best-effort: a failure here must never break the scrape.
    """
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
            return  # never internalize on a too-thin page — its bucket is shared by all thin pages
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
            # Gate-accepted on the real DOM → highest-truth provenance tier.
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
    except Exception as exc:  # noqa: BLE001 — dual-write must never break a scrape
        logger.debug('field-atom dual-write skipped (url=%s): %s', url, exc)


async def scrape(
    url: str | Sequence[str],
    contract: type[Contract] | str | Sequence[type[Contract] | str],
    model: YosoiConfig | LLMConfig | ModelPolicy | str | None = None,
    *,
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
    policy: Policy | None = None,
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
    discover concurrently and do not block one another. NOTE: the ``DiscoveryBus`` is a
    process-wide singleton scoped only by ``domain`` and dedupes on ``field_signature``
    (name + description + type — NO contract name/doc). So today the per-field ``description``
    token is the ONLY thing keeping ``Ad.url`` and ``Organic.url`` in separate in-flight slots on a
    shared domain — a fragile, stochastic separator (the bus has no region/intent concept, and the
    discrimination gate is a post-hoc reject, not a pre-discovery split). Threading contract identity
    into the bus key is a tracked follow-up (FU-3); until then, related same-shape contracts rely on
    divergent field descriptions to avoid bus conflation.

    ``fetcher_type`` defaults to ``'auto'`` (plain HTTP first, then browser tiers only when
    needed). It also accepts a scalar OR a per-URL ``{url: tier}`` map / ``url -> tier`` callable,
    so different engines get different tiers in ONE concurrent call (e.g. ``google: 'headful'``,
    ``bing``/``brave``: ``'headless'``). ``max_concurrency`` (opt-in) caps how many
    ``(url, contract)`` units run at once — set it on big SERP grids so you don't open hundreds
    of tabs and trip anti-bot; default ``None`` is unbounded (today's behavior).

    ``identities`` is an OPT-IN, per-URL :class:`~yosoi.core.fetcher.identity.BrowserIdentity`
    (a dict ``{url: identity}`` or a ``url -> identity | None`` callable). It is how you opt
    into the *sensitive* choices a SERP scrape needs — a trusted Chromium ``profile_dir``,
    ``headful``, a ``geo`` teleport, ``proxy``/``locale``/``timezone_id`` — PER URL, so e.g. a
    google tab runs headful+profile while bing/brave tabs run plain headless, all concurrently.
    Default ``None`` keeps today's behavior exactly. An identity needs a browser
    ``fetcher_type`` (``auto``/``headless``/``headful``); the ``simple`` fetcher ignores it
    (and warns).

    By default this API does not write files. Pass ``save_formats=('json',)`` for file output.
    ``ys.File()`` download fields need ``allow_downloads=True`` + a browser-capable
    ``fetcher_type``;
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
        return fetcher_type(u) if callable(fetcher_type) else fetcher_type.get(u, 'auto')

    base_call_policy = _compat_policy_layer(
        model,
        force=force,
        skip_verification=skip_verification,
        fetcher_type=fetcher_type if isinstance(fetcher_type, str) else 'auto',
        selector_level=selector_level,
        save_formats=save_formats,
        quiet=quiet,
        allow_downloads=allow_downloads,
        allowed_download_types=allowed_download_types,
        download_dir=download_dir,
        max_download_bytes=max_download_bytes,
        keep_downloads=keep_downloads,
        max_concurrency=max_concurrency,
    )

    fanout_policy = Policy.cascade(Policy.from_env(), policy, base_call_policy)
    effective_max_concurrency = max_concurrency
    if effective_max_concurrency is None and fanout_policy.scrape is not None:
        effective_max_concurrency = fanout_policy.scrape.max_concurrency

    write_lock = asyncio.Lock() if (multi_url or multi_contract) else None
    # Shared single-flight gate: concurrent units for the same (domain, contract) discover
    # ONCE; the rest wait and replay — so the simple call stays simple.
    discovery_gate = DiscoveryGate()
    sem = asyncio.Semaphore(effective_max_concurrency) if effective_max_concurrency else None
    pairs = [(u, c) for u in urls for c in contract_clss]

    # P1.5 advisory gate: collect each contract's discovered selector map per URL so we
    # can judge region disjointness after the run (the gate self-skips a URL with <2).
    gate_collectors: dict[str, GateCollector] = {u: {} for u in urls}

    async def _unit(u: str, c: type[Contract]) -> list[ContentMap]:
        async def _go() -> list[ContentMap]:
            # A per-URL mapping that resolves to 'auto' (e.g. dict miss) contributes nothing,
            # so an explicit policy fetcher_type still wins for that URL.
            per_url_fetcher = _fetcher_for(u)
            per_url_policy = (
                Policy(scrape=ScrapePolicy.model_validate({'fetcher_type': per_url_fetcher}))
                if not isinstance(fetcher_type, str) and per_url_fetcher != 'auto'
                else None
            )
            return await _scrape_one(
                u,
                c,
                None,
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
                policy=Policy.cascade(policy, base_call_policy, per_url_policy),
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


def _edge_policy(contract_cls: type[Contract], call_policy: Policy | None) -> Policy:
    """Resolve the effective policy ONCE at the api edge via the cascade.

    Precedence ``defaults < env < contract < call-site``: the contract's pinned
    ``policy`` partial (if any) sits between the env layer and the per-call override.
    """
    return Policy.cascade(Policy.from_env(), getattr(contract_cls, 'policy', None), call_policy)


def _compat_policy_layer(  # noqa: C901
    model: YosoiConfig | LLMConfig | ModelPolicy | str | None,
    *,
    force: bool,
    skip_verification: bool,
    fetcher_type: str = 'auto',
    selector_level: SelectorLevel,
    save_formats: Sequence[str],
    quiet: bool,
    allow_downloads: bool,
    allowed_download_types: Sequence[str],
    download_dir: str | None,
    max_download_bytes: int | None,
    keep_downloads: bool,
    max_concurrency: int | None,
) -> Policy:
    """Convert legacy scrape kwargs into a call-site policy layer."""
    kwargs: dict[str, Any] = {}
    model_policy: ModelPolicy | None = None
    if isinstance(model, str):
        model_policy = ModelPolicy.from_string(model)
    elif isinstance(model, ModelPolicy):
        model_policy = model
    elif isinstance(model, LLMConfig):
        model_policy = ModelPolicy(
            provider=model.provider,
            model_name=model.model_name,
            temperature=model.temperature,
            max_tokens=model.max_tokens,
            extra_params=model.extra_params,
        )
        model_policy._runtime_api_key = model.api_key
    elif isinstance(model, YosoiConfig):
        model_policy = ModelPolicy(
            provider=model.llm.provider,
            model_name=model.llm.model_name,
            temperature=model.llm.temperature,
            max_tokens=model.llm.max_tokens,
            extra_params=model.llm.extra_params,
        )
        model_policy._runtime_api_key = model.llm.api_key
    if model_policy is not None:
        kwargs['model'] = model_policy

    scrape_payload: dict[str, Any] = {}
    if force or (isinstance(model, YosoiConfig) and model.force):
        scrape_payload['force'] = True
    if skip_verification:
        scrape_payload['skip_verification'] = skip_verification
    if fetcher_type != 'auto':
        scrape_payload['fetcher_type'] = fetcher_type
    if selector_level != SelectorLevel.CSS:
        scrape_payload['selector_level'] = selector_level
    if max_concurrency is not None:
        scrape_payload['max_concurrency'] = max_concurrency
    if scrape_payload:
        kwargs['scrape'] = ScrapePolicy(**scrape_payload)

    if isinstance(model, YosoiConfig):
        discovery_defaults = DiscoveryPolicy()
        discovery_payload: dict[str, Any] = {}
        if model.discovery.max_concurrent != discovery_defaults.max_concurrent:
            discovery_payload['max_concurrent'] = model.discovery.max_concurrent
        if model.discovery.replay_verify_threshold != discovery_defaults.replay_verify_threshold:
            discovery_payload['replay_verify_threshold'] = model.discovery.replay_verify_threshold
        if discovery_payload:
            kwargs['discovery'] = DiscoveryPolicy(**discovery_payload)

    output_payload: dict[str, Any] = {}
    if save_formats:
        output_payload['formats'] = tuple(save_formats)
    if not quiet:
        output_payload['quiet'] = quiet
    if isinstance(model, YosoiConfig) and model.debug.save_html:
        output_payload['debug_html'] = True
        output_payload['debug_html_dir'] = model.debug.html_dir
    if output_payload:
        kwargs['output'] = OutputPolicy(**output_payload)

    # Downloads stay default-deny: the sub-settings only mean anything once the caller
    # opted in via allow_downloads=True, matching the legacy kwarg semantics.
    if allow_downloads:
        download_payload: dict[str, Any] = {'allow': True}
        if allowed_download_types:
            download_payload['allowed_types'] = tuple(allowed_download_types)
        if download_dir is not None:
            download_payload['directory'] = download_dir
        if max_download_bytes is not None:
            download_payload['max_bytes'] = max_download_bytes
        if not keep_downloads:
            download_payload['keep'] = False
        kwargs['download'] = DownloadPolicy(**download_payload)

    return Policy(**kwargs)


async def _scrape_one(
    url: str,
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | ModelPolicy | str | None = None,
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
    policy: Policy | None = None,
) -> list[ContentMap]:
    """One ``(url, contract)`` unit (returns ``list[record]``).

    ``write_lock`` is the shared per-call lock that :func:`scrape` threads through so
    concurrent units don't race on per-domain selector writes; ``None`` for a lone scrape.
    ``identity`` is the opt-in per-URL :class:`BrowserIdentity` (profile/headful/geo).
    ``gate_collect``, when provided, receives this contract's freshly-discovered selector
    map + cleaned HTML for the cross-contract discrimination gate (P1.5, advisory).
    ``policy`` is the resolved pipeline policy; this is the edge — resolve ONCE here
    (``policy or Policy.from_env()``) and hand the concrete Policy down so the core never
    re-reads the environment (the CAS-119 purity contract).
    """
    contract_cls = resolve_contract(contract) if isinstance(contract, str) else contract
    call_policy = _compat_policy_layer(
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
        max_concurrency=None,
    )
    effective_policy = _edge_policy(contract_cls, Policy.cascade(policy, call_policy))
    spec = effective_policy.resolve_run_spec()
    if isinstance(model, YosoiConfig):
        spec = spec.model_copy(update={'llm_config': model.llm, 'telemetry_config': model.telemetry})
    elif isinstance(model, LLMConfig):
        spec = spec.model_copy(update={'llm_config': model})
    save_format_list = list(spec.output_formats)
    with obs.span(
        'api.scrape',
        url=url,
        contract=contract_cls.__name__,
        model=_model_label(spec.llm_config),
        fetcher_type=spec.fetcher_type,
        selector_level=spec.selector_level.value,
        save_formats=','.join(save_format_list),
    ):
        try:
            async with Pipeline(
                llm_config=spec.llm_config,
                contract=contract_cls,
                output_format=save_format_list,
                force=spec.force,
                quiet=spec.quiet,
                selector_level=spec.selector_level,
                allow_downloads=spec.allow_downloads,
                allowed_download_types=spec.allowed_download_types,
                download_dir=spec.download_dir,
                max_download_bytes=spec.max_download_bytes,
                keep_downloads=spec.keep_downloads,
                write_lock=write_lock,
                identity=identity,
                discovery_gate=discovery_gate,
                policy=effective_policy,
            ) as pipeline:
                items = [
                    item
                    async for item in pipeline.scrape(
                        url,
                        force=spec.force,
                        skip_verification=spec.skip_verification,
                        fetcher_type=spec.fetcher_type,
                        output_format=save_format_list,
                    )
                ]
                # P1.5: hand this contract's freshly-discovered selectors to the gate
                # collector (only set on a fresh discovery, not a cache replay).
                # getattr-guarded so a Pipeline-like double without these attrs is fine.
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
    model: YosoiConfig | LLMConfig | ModelPolicy | str | None = None,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'auto',
    selector_level: SelectorLevel = SelectorLevel.CSS,
    save_formats: Sequence[str] = (),
    quiet: bool = True,
    policy: Policy | None = None,
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
                    policy=policy,
                )
        except Exception as e:
            obs.warning('API scrape_many URL failed', url=current_url, error=str(e))
            raise
        return results


def scrape_sync(
    url: str,
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | ModelPolicy | str | None = None,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'auto',
    selector_level: SelectorLevel = SelectorLevel.CSS,
    save_formats: Sequence[str] = (),
    quiet: bool = True,
    policy: Policy | None = None,
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
                    policy=policy,
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
