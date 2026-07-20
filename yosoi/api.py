"""Small programmatic API for in-memory Yosoi scraping."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from yosoi.core.configs import YosoiConfig, auto_config
from yosoi.core.discovery import LLMConfig
from yosoi.core.fetcher.identity import BrowserIdentity
from yosoi.core.fetcher.profile_policy import cascade_from_profile_policy
from yosoi.core.pipeline import ContentMap, Pipeline
from yosoi.core.pipeline.discovery_gate import DiscoveryGate
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.policy import DiscoveryPolicy, DownloadPolicy, ModelPolicy, OutputPolicy, Policy, ScrapePolicy
from yosoi.utils import observability as obs
from yosoi.utils.contracts import resolve_contract

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from yosoi.fingerprints.store import FingerprintStore
    from yosoi.generalization.fingerprint import PageFingerprint

# Per-contract capture for the cross-contract discrimination gate: contract name ->
# (selector_map, cleaned_html) from that contract's fresh discovery on a page.
GateCollector = dict[str, tuple[dict[str, Any], str | None]]

# Default on-disk field-atom corpus (P2 dual-write target). Gitignored like .yosoi/.
_ATOM_STORE_PATH = '.yosoi/atoms.jsonl'


async def extract(
    html: str,
    contract: type[Contract] | str,
    *,
    url: str = '',
    selectors: Mapping[str, Mapping[str, Any]] | None = None,
    root: Any = None,
    runtime_evidence: Mapping[str, Sequence[str]] | None = None,
    policy: Policy | None = None,
    fingerprint_store: FingerprintStore | None = None,
) -> list[ContentMap]:
    """Extract validated records from pre-fetched HTML without acquisition or discovery.

    Deterministic extractor-only contracts need no selector data. Mixed contracts
    must provide selectors (field overrides declared on the contract are merged
    automatically). A discovered root must be supplied explicitly because this API
    never invokes an LLM. ``runtime_evidence`` carries already-observed values such
    as resource URLs or browser endpoints; extractors cannot acquire more evidence.
    """
    from rich.console import Console

    from yosoi.core.extraction import ContentExtractor
    from yosoi.models.selectors import is_discover_sentinel

    contract_cls = resolve_contract(contract) if isinstance(contract, str) else contract
    if not isinstance(contract_cls, type) or not issubclass(contract_cls, Contract):
        raise TypeError('ys.extract() contract must be a ys.Contract subclass or registered contract name')
    action_fields = sorted(contract_cls.action_fields())
    if action_fields:
        raise ValueError('ys.extract() cannot execute browser or download action fields: ' + ', '.join(action_fields))
    resolved_selectors: dict[str, dict[str, Any]] = {name: dict(value) for name, value in (selectors or {}).items()}
    for name, value in contract_cls.get_selector_overrides().items():
        resolved_selectors.setdefault(name, value)

    missing = contract_cls.required_discovery_field_names() - set(resolved_selectors)
    if missing:
        raise ValueError(
            'ys.extract() does not discover selectors; provide selector data for required field(s): '
            + ', '.join(sorted(missing))
        )

    resolved_root = root if root is not None else contract_cls.get_root()
    if is_discover_sentinel(resolved_root):
        raise ValueError('ys.extract() cannot discover a contract root; pass root= with an explicit selector')

    effective_policy = policy or Policy()
    extractor_policy = effective_policy.extractor
    if (
        extractor_policy is not None
        and (extractor_policy.reference_writes or extractor_policy.generalized_reads)
        and fingerprint_store is None
    ):
        raise ValueError('ys.extract() requires fingerprint_store= when extractor reference I/O is enabled')
    coordinator = ContentExtractor(
        console=Console(quiet=True),
        contract=contract_cls,
        policy=effective_policy,
        fingerprint_store=fingerprint_store,
    )
    raw = (
        await coordinator.extract_items_async(
            url,
            html,
            resolved_selectors,
            resolved_root,
            runtime_evidence=runtime_evidence,
        )
        if resolved_root is not None
        else await coordinator.extract_content_with_html_async(
            url,
            html,
            resolved_selectors,
            runtime_evidence=runtime_evidence,
        )
    )
    if raw is None:
        return []
    records = raw if isinstance(raw, list) else [raw]
    validated: list[ContentMap] = []
    for row_index, record in enumerate(records):
        try:
            value = contract_cls.model_validate(record, context={'source_url': url}).model_dump()
        except Exception as exc:  # public boundary adds row context and never returns raw values
            if contract_cls.extractor_fields():
                raise ValueError(f'{contract_cls.__name__} validation failed for extracted row {row_index}') from None
            raise ValueError(f'{contract_cls.__name__} validation failed for extracted row {row_index}: {exc}') from exc
        validated.append(cast(ContentMap, value))
    coordinator.persist_validated_references()
    return validated


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
        from yosoi.utils.signatures import _get_yosoi_type, field_signature

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
            descriptions = cls.field_descriptions() if cls is not None else {}
            fields = []
            for field_name, slot in selectors.items():
                if field_name in _STRUCTURAL or not isinstance(slot, dict):
                    continue
                primary = coerce_selector_entry(slot.get('primary'))
                if primary is None:
                    continue
                root = coerce_selector_entry(slot.get('root'))
                yosoi_type = _get_yosoi_type(cls, field_name) if cls else None
                field_fp = field_signature(field_name, descriptions.get(field_name, ''), yosoi_type)
                fields.append((field_name, primary.model_dump(), root.value if root else None, yosoi_type, field_fp))
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


async def _scrape_impl(
    url: str | Sequence[str],
    contract: type[Contract] | str | Sequence[type[Contract] | str],
    model: YosoiConfig | LLMConfig | ModelPolicy | str | None = None,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str | Mapping[str, str] | Callable[[str], str] = 'auto',
    selector_level: SelectorLevel = max(SelectorLevel),
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
    allow_llm: bool = True,
    experimental_a3node: bool = False,
    metadata_collect: MutableMapping[tuple[str, str], dict[str, Any]] | None = None,
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
    ``fetcher_type`` (``auto``/``waterfall``/``headless``/``headful``); the ``simple`` fetcher
    ignores it (and warns). Direct browser tiers (``headless``/``headful``) receive the single
    identity as-is; the waterfall tiers (``auto``/``waterfall``) wrap it as a one-item identity
    cascade so it composes with profile-cascade recovery.

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
                policy=Policy.cascade(policy, base_call_policy, per_url_policy),
                allow_llm=allow_llm,
                experimental_a3node=experimental_a3node,
                metadata_collect=metadata_collect,
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


async def scrape(
    url: str | Sequence[str],
    contract: type[Contract] | str | Sequence[type[Contract] | str],
    model: YosoiConfig | LLMConfig | ModelPolicy | str | None = None,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str | Mapping[str, str] | Callable[[str], str] = 'auto',
    selector_level: SelectorLevel = max(SelectorLevel),
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
    allow_llm: bool = True,
    experimental_a3node: bool = False,
) -> Any:
    """Scrape one-or-many URLs with one-or-many contracts.

    Thin constructor for the canonical :class:`yosoi.operations.ScrapeRequest`.
    Returns :class:`yosoi.operations.ScrapeResult` rather than axis-shaped data;
    use ``result.results`` for stable URL x contract units.
    """
    from yosoi.operations import ScrapeRequest, execute_scrape, normalize_scrape_result

    request = ScrapeRequest.from_axes(
        url,
        contract,
        model=model if isinstance(model, str) else None,
        policy=policy,
        force=force,
        skip_verification=skip_verification,
        fetcher_type=fetcher_type,
        selector_level='all' if selector_level == max(SelectorLevel) else selector_level.name.lower(),
        save_formats=list(save_formats),
        quiet=quiet,
        allow_downloads=allow_downloads,
        allowed_download_types=list(allowed_download_types),
        download_dir=download_dir,
        max_download_bytes=max_download_bytes,
        keep_downloads=keep_downloads,
        identities=identities,
        max_concurrency=max_concurrency,
        allow_llm=allow_llm,
        experimental_a3node=experimental_a3node,
    )
    if model is not None and not isinstance(model, str):
        # Keep non-JSON-safe model/config objects on the edge by delegating directly.
        raw = await _scrape_impl(
            url,
            contract,
            model=model,
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
            identities=identities,
            max_concurrency=max_concurrency,
            policy=policy,
            allow_llm=allow_llm,
            experimental_a3node=experimental_a3node,
        )
        return normalize_scrape_result(request, raw)
    return await execute_scrape(request)


async def fetch(
    url: str | Sequence[str],
    *,
    view: str = 'text',
    fetcher_type: str | None = None,
    page: int = 1,
    page_size: int = 12_000,
    chars: int | None = None,
    include: Sequence[str] = (),
    contracts: Any = None,
    output_dir: str | None = None,
    policy: Policy | None = None,
    experimental_a3node: bool = False,
    max_concurrency: int = 5,
) -> Any:
    """Fetch one-or-many URLs as bounded page acquisition content.

    This is the contractless inspection surface: no LLM discovery, no selector
    writes, no scrape replay. Optional ``contracts`` run advisory cache/fingerprint
    probes only.
    """
    from yosoi.operations import FetchRequest, run_fetch

    if chars is not None:
        page_size = chars
    effective_policy = Policy.cascade(Policy.from_env(), policy)
    request = FetchRequest.from_axes(
        url,
        contracts,
        view=view,
        fetcher_type=fetcher_type,
        page=page,
        page_size=page_size,
        include=list(include),
        output_dir=output_dir,
        policy=effective_policy,
        experimental_a3node=experimental_a3node,
        max_concurrency=max_concurrency,
    )
    return await run_fetch(request)


async def search(
    query: str | Sequence[str],
    *,
    kind: str | None = None,
    provider: str | None = None,
    backend: str | None = None,
    region: str | None = None,
    safesearch: str | None = None,
    timelimit: str | None = None,
    max_results: int | None = None,
    limit: int | None = None,
    page: int | None = None,
    policy: Policy | None = None,
    max_concurrency: int = 5,
) -> Any:
    """Search one query or a bounded concurrent sequence of independent queries."""
    from yosoi.operations import SearchRequest, run_search, run_searches

    if max_results is not None and limit is not None and max_results != limit:
        raise ValueError('Pass only one of max_results or limit')
    if isinstance(max_concurrency, bool) or max_concurrency < 1:
        raise ValueError('max_concurrency must be >= 1')
    effective_policy = Policy.cascade(Policy.from_env(), policy)
    queries = [query] if isinstance(query, str) else list(query)
    if not queries:
        raise ValueError('query sequence must not be empty')
    requests = [
        SearchRequest.from_policy(
            query=item,
            policy=effective_policy,
            kind=cast(Literal['text'], kind) if kind is not None else None,
            provider=cast(Literal['ddgs'], provider) if provider is not None else None,
            backend=backend,
            region=region,
            safesearch=cast(Literal['on', 'moderate', 'off'], safesearch) if safesearch is not None else None,
            timelimit=timelimit,
            max_results=max_results if max_results is not None else limit,
            page=page,
        )
        for item in queries
    ]
    if len(requests) == 1:
        return await run_search(requests[0])
    return await run_searches(requests, max_concurrency=max_concurrency)


async def map(
    url: str,
    *,
    max_sitemaps: int = 20,
    max_urls: int = 500,
    max_subdomains: int = 500,
    subfinder_bin: str = 'subfinder',
    subfinder_timeout: int = 60,
    include_robots: bool = True,
    include_default_sitemaps: bool = True,
    include_subdomains: bool = True,
    discover_subdomains: bool = False,
) -> Any:
    """Discover a site's sitemap URLs or enumerate subdomains with subfinder."""
    from yosoi.operations import MapRequest, run_map

    request = MapRequest(
        url=url,
        max_sitemaps=max_sitemaps,
        max_urls=max_urls,
        max_subdomains=max_subdomains,
        subfinder_bin=subfinder_bin,
        subfinder_timeout=subfinder_timeout,
        include_robots=include_robots,
        include_default_sitemaps=include_default_sitemaps,
        include_subdomains=include_subdomains,
        discover_subdomains=discover_subdomains,
    )
    return await run_map(request)


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
    if selector_level != max(SelectorLevel):
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
    selector_level: SelectorLevel = max(SelectorLevel),
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
    allow_llm: bool = True,
    experimental_a3node: bool = False,
    metadata_collect: MutableMapping[tuple[str, str], dict[str, Any]] | None = None,
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
    # Pure/cache/extractor paths do not need model credentials. Discovery remains
    # fail-closed inside Pipeline if it is actually reached without a model.
    spec = effective_policy.resolve_run_spec(require_model=False)
    page_runtime = effective_policy.page_runtime(scrape=effective_policy.scrape)
    policy_cascade, policy_max_live = cascade_from_profile_policy(page_runtime.profile)
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
                identity_cascade=None if identity is not None else policy_cascade,
                max_live_identities=policy_max_live,
                discovery_gate=discovery_gate,
                experimental_a3node=experimental_a3node,
                policy=effective_policy,
                allow_llm=allow_llm,
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
                if metadata_collect is not None:
                    extractor_runtime = getattr(pipeline, 'extractor', None)
                    extractor_diagnostics = list(getattr(extractor_runtime, 'last_extractor_diagnostics', []))
                    extractor_fingerprints = list(getattr(extractor_runtime, 'last_extractor_fingerprints', []))
                    metadata_collect[(url, contract_cls.__name__)] = {
                        'selector_source': getattr(pipeline, 'last_selector_source', 'unknown'),
                        'cache_decision': getattr(pipeline, 'last_cache_decision', 'unknown'),
                        'llm_used': bool(getattr(pipeline, 'last_llm_used', False)),
                        'llm_reason': getattr(pipeline, 'last_llm_reason', None),
                        'quality_status': getattr(pipeline, 'last_quality_status', 'unknown'),
                        'quality_issues': list(getattr(pipeline, 'last_quality_issues', [])),
                        'expected_record_count': getattr(pipeline, 'last_expected_record_count', None),
                        'extractor_field_count': len(contract_cls.extractor_fields()),
                        'extractor_success_count': sum(
                            entry.get('category') == 'success' for entry in extractor_diagnostics
                        ),
                        'extractor_no_match_count': sum(
                            entry.get('category') == 'no_match' for entry in extractor_diagnostics
                        ),
                        'extractor_validation_failure_count': sum(
                            entry.get('category') == 'validation_failure' for entry in extractor_diagnostics
                        ),
                        'extractor_resolver_ids': sorted(
                            {
                                str(entry.get('resolver_id'))
                                for entry in extractor_diagnostics
                                if entry.get('resolver_id')
                            }
                        ),
                        'extractor_fingerprint_version': (
                            extractor_fingerprints[0].scheme if extractor_fingerprints else None
                        ),
                    }
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
    selector_level: SelectorLevel = max(SelectorLevel),
    save_formats: Sequence[str] = (),
    quiet: bool = True,
    policy: Policy | None = None,
    allow_llm: bool = True,
) -> Any:
    """Scrape multiple URLs and return the canonical ScrapeResult envelope."""
    return await scrape(
        list(urls),
        contract,
        model,
        force=force,
        skip_verification=skip_verification,
        fetcher_type=fetcher_type,
        selector_level=selector_level,
        save_formats=save_formats,
        quiet=quiet,
        policy=policy,
        allow_llm=allow_llm,
    )


def scrape_sync(
    url: str,
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | ModelPolicy | str | None = None,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'auto',
    selector_level: SelectorLevel = max(SelectorLevel),
    save_formats: Sequence[str] = (),
    quiet: bool = True,
    policy: Policy | None = None,
    allow_llm: bool = True,
) -> Any:
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
                    policy=policy,
                    allow_llm=allow_llm,
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


def _model_label(model: YosoiConfig | LLMConfig | None) -> str:
    if model is None:
        return 'deferred:model-required'
    llm = model.llm if isinstance(model, YosoiConfig) else model
    return f'{llm.provider}:{llm.model_name}'
