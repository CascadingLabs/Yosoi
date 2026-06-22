"""Public crawl entrypoint over the policy-driven crawl coordinator."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast

from yosoi.core.crawler.coordinator import CrawlCoordinator, CrawlRunSummary
from yosoi.core.fetcher import create_fetcher
from yosoi.models.contract import Contract
from yosoi.policy import CrawlPolicy, CrawlTarget, Policy
from yosoi.reporting import RichCrawlProgress


async def crawl(
    seeds: str | Sequence[str],
    *,
    contracts: Sequence[object] | object | None = None,
    limit: int | None = None,
    policy: Policy | None = None,
    fetcher_type: str | None = None,
    persist: bool = False,
    progress: bool | None = None,
    console: Any | None = None,
) -> CrawlRunSummary:
    """Crawl from ``seeds`` under a resolved crawl ``policy``, returning a run summary.

    Opinionated default: the ``crawl.conservative`` preset when no policy is given.
    The fetcher defaults to the one the policy resolves (``runtime.fetcher_type``);
    pass ``fetcher_type`` to override it (``auto``/``simple``/``headless``/``headful``).

    The crawl is **ephemeral by default** (``persist=False``) so repeated runs start
    fresh. Set ``persist=True`` (with a ``crawl_session_id`` on the policy budget) to
    checkpoint the frontier and resume an interrupted crawl instead of re-running it.
    """
    pol = _with_crawl_targets(policy or Policy.for_crawl('crawl.conservative'), contracts=contracts, limit=limit)
    crawl = pol.require_crawl()
    seed_tuple = _seed_items(seeds)
    runtime = crawl.to_runtime_config(seeds=seed_tuple)
    page = pol.page_runtime(crawl=crawl)
    runtime = runtime.model_copy(update={'page': page})
    resolved_fetcher_type = fetcher_type or page.fetcher_type
    fetcher_kwargs: dict[str, Any] = {
        'timeout': int(page.timeout_seconds),
        'allow_redirects': page.allow_redirects,
    }
    if page.chrome_ws_urls:
        fetcher_kwargs['chrome_ws_urls'] = page.chrome_ws_urls
    if resolved_fetcher_type in {'auto', 'waterfall'}:
        # Crawl explores heterogeneous page shapes under one host. The scrape-time
        # domain strategy cache is too coarse here: one JS-gated URL must not force
        # every sibling URL through Chrome. Re-run the waterfall per URL so L1 pages
        # stay on simple HTTP while L2/L3 pages can still escalate emergently.
        fetcher_kwargs['force'] = True
        browser_slots = max(1, min(crawl.scheduler.per_host_concurrency, 4))
        if page.chrome_ws_urls:
            browser_slots = max(1, min(browser_slots, len(page.chrome_ws_urls)))
        fetcher_kwargs['max_concurrent'] = browser_slots
        fetcher_kwargs['crawl_frontier_only'] = True
    fetcher = create_fetcher(resolved_fetcher_type, **fetcher_kwargs)
    async with _fetcher_context(fetcher) as active_fetcher:
        show_progress = _show_crawl_progress(pol) if progress is None else progress
        if show_progress:
            with RichCrawlProgress(console=console) as reporter:
                coordinator = CrawlCoordinator(
                    fetcher=active_fetcher,
                    config=runtime,
                    persist_frontier=persist,
                    reporter=reporter,
                )
                summary = await coordinator.run(seeds=seed_tuple)
        else:
            coordinator = CrawlCoordinator(fetcher=active_fetcher, config=runtime, persist_frontier=persist)
            summary = await coordinator.run(seeds=seed_tuple)

    if crawl.scrape_contracts:
        scrape_contracts = _resolve_scrape_contracts(crawl.scrape_contracts, contracts)
        await _scrape_crawl_candidates(
            summary,
            contracts=scrape_contracts,
            policy=pol,
            limit=crawl.scrape_url_limit_per_contract,
        )
    return summary


def _resolve_scrape_contracts(
    scrape_contracts: bool | Sequence[object], contracts: Sequence[object] | object | None
) -> Sequence[object] | object | None:
    if scrape_contracts is True:
        return contracts
    if scrape_contracts is False:
        return None
    call_site = _contract_items(contracts) if contracts is not None else ()
    by_name = {contract_name(item): item for item in call_site}
    return tuple(by_name.get(contract_name(item), item) for item in scrape_contracts)


async def _scrape_crawl_candidates(
    summary: CrawlRunSummary,
    *,
    contracts: Sequence[object] | object | None,
    policy: Policy,
    limit: int,
) -> None:
    from yosoi.api import scrape

    contract_items = _contract_items(contracts) if contracts is not None else ()
    if len(contract_items) > 1:
        raise ValueError(
            'policy-driven crawl scraping cannot route multiple contracts after candidate scoring removal; '
            'scrape a single contract or use summary.scrape_target_urls() with an explicit planner'
        )
    for item in contract_items:
        name = contract_name(item)
        urls = summary.scrape_target_urls(limit=limit)
        if not urls:
            summary.scraped_content[name] = []
            continue
        scrape_contract = item if isinstance(item, (str, type)) else name
        summary.scraped_content[name] = await scrape(urls, cast('type[Contract] | str', scrape_contract), policy=policy)


def _show_crawl_progress(policy: Policy) -> bool:
    """Return whether crawl should render live progress for this policy."""
    output = policy.output
    if output is None:
        return True
    return not (output.plain_output or output.json_output or output.quiet)


def _with_crawl_targets(policy: Policy, *, contracts: Sequence[object] | object | None, limit: int | None) -> Policy:
    """Apply call-site contract intent while keeping policy as the lever surface."""
    crawl = policy.require_crawl()
    if contracts is None and limit is None:
        if isinstance(crawl.scrape_contracts, tuple) and crawl.scrape_contracts and not crawl.target_contracts:
            crawl_payload = crawl.model_dump()
            crawl_payload['target_contracts'] = crawl.scrape_contracts
            return Policy.cascade(policy, Policy(crawl=CrawlPolicy.model_validate(crawl_payload)))
        return policy

    existing = crawl.target_contracts
    if contracts is None:
        targets = tuple(
            target.model_copy(update={'max_budget_pages': limit}) if limit is not None else target
            for target in existing
        )
    else:
        contract_items = _contract_items(contracts)
        targets = tuple(
            CrawlTarget(
                name=contract_name(item),
                max_budget_pages=limit,
                intent_tokens=_contract_intent_tokens(item),
            )
            for item in contract_items
        )

    crawl_payload = crawl.model_dump()
    crawl_payload['target_contracts'] = targets
    return Policy.cascade(policy, Policy(crawl=CrawlPolicy.model_validate(crawl_payload)))


def contract_name(contract: str | type[Contract] | Any) -> str:
    """Return a stable public name for a contract-like object."""
    if isinstance(contract, str):
        return contract
    target_name = getattr(contract, 'name', None)
    if isinstance(target_name, str) and target_name:
        return target_name
    name = getattr(contract, '__name__', None)
    if isinstance(name, str) and name:
        return name
    return str(contract)


def _contract_items(contracts: Sequence[object] | object) -> tuple[object, ...]:
    if isinstance(contracts, (str, type)):
        return (contracts,)
    try:
        return tuple(contracts)  # type: ignore[arg-type]
    except TypeError:
        return (contracts,)


def _contract_intent_tokens(contract: object) -> tuple[str, ...]:
    tokens: set[str] = set(_tokens_from_text(contract_name(contract)))
    doc = getattr(contract, '__doc__', None)
    if isinstance(doc, str):
        tokens.update(_tokens_from_text(doc))
    fields = getattr(contract, 'model_fields', None) if isinstance(contract, type) else None
    if isinstance(fields, dict):
        for name, field in fields.items():
            tokens.update(_tokens_from_text(str(name)))
            description = getattr(field, 'description', None)
            if isinstance(description, str):
                tokens.update(_tokens_from_text(description))
    return tuple(sorted(tokens))


def _tokens_from_text(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+', text) if len(token) >= 3}


def _seed_items(seeds: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(seeds, str):
        return (seeds,)
    return tuple(seeds)


@asynccontextmanager
async def _fetcher_context(fetcher: Any) -> AsyncIterator[Any]:
    """Enter fetchers that own async resources while tolerating test doubles."""
    if hasattr(fetcher, '__aenter__') and hasattr(fetcher, '__aexit__'):
        async with fetcher:
            yield fetcher
        return
    yield fetcher
