"""Public crawl entrypoint over the policy-driven crawl coordinator."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from yosoi.core.crawler.candidates import contract_name
from yosoi.core.crawler.coordinator import CrawlCoordinator, CrawlRunSummary
from yosoi.core.fetcher import create_fetcher
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
    fetcher = create_fetcher(
        fetcher_type or page.fetcher_type,
        timeout=int(page.timeout_seconds),
        allow_redirects=page.allow_redirects,
    )
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
                return await coordinator.run(seeds=seed_tuple)

        coordinator = CrawlCoordinator(fetcher=active_fetcher, config=runtime, persist_frontier=persist)
        return await coordinator.run(seeds=seed_tuple)


def _show_crawl_progress(policy: Policy) -> bool:
    """Return whether crawl should render live progress for this policy."""
    output = policy.output
    if output is None:
        return True
    return not (output.plain_output or output.json_output or output.quiet)


def _with_crawl_targets(policy: Policy, *, contracts: Sequence[object] | object | None, limit: int | None) -> Policy:
    """Apply call-site contract intent while keeping policy as the lever surface."""
    if contracts is None and limit is None:
        return policy

    crawl = policy.require_crawl()
    existing = crawl.target_contracts
    if contracts is None:
        targets = tuple(
            target.model_copy(update={'max_budget_pages': limit}) if limit is not None else target
            for target in existing
        )
    else:
        contract_items = _contract_items(contracts)
        targets = tuple(CrawlTarget(name=contract_name(item), max_budget_pages=limit) for item in contract_items)

    crawl_payload = crawl.model_dump()
    crawl_payload['target_contracts'] = targets
    return Policy.cascade(policy, Policy(crawl=CrawlPolicy.model_validate(crawl_payload)))


def _contract_items(contracts: Sequence[object] | object) -> tuple[object, ...]:
    if isinstance(contracts, (str, type)):
        return (contracts,)
    try:
        return tuple(contracts)  # type: ignore[arg-type]
    except TypeError:
        return (contracts,)


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
