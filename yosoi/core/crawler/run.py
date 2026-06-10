"""Public crawl entrypoint over the policy-driven crawl coordinator."""

from __future__ import annotations

from collections.abc import Sequence

from yosoi.core.crawler.coordinator import CrawlCoordinator, CrawlRunSummary
from yosoi.core.fetcher import create_fetcher
from yosoi.policy import Policy


async def crawl_index(
    seeds: Sequence[str],
    *,
    policy: Policy | None = None,
    fetcher_type: str | None = None,
) -> CrawlRunSummary:
    """Crawl from ``seeds`` under a resolved crawl ``policy``, returning a run summary.

    Opinionated default: the ``crawl.conservative`` preset when no policy is given.
    The fetcher defaults to the one the policy resolves (``runtime.fetcher_type``);
    pass ``fetcher_type`` to override it (``auto``/``simple``/``headless``/``headful``).
    """
    pol = policy or Policy.for_crawl('crawl.conservative')
    crawl = pol.require_crawl()
    seed_tuple = tuple(seeds)
    runtime = crawl.to_runtime_config(seeds=seed_tuple)
    fetcher = create_fetcher(fetcher_type or runtime.fetcher_type)
    coordinator = CrawlCoordinator(fetcher=fetcher, config=runtime)
    return await coordinator.run(seeds=seed_tuple)
