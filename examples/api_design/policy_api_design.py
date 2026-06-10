"""Policy API design sketch for crawler safety and scale.

Run:
    uv run python examples/api_design/policy_api_design.py

This file is intentionally API design, not a production crawler recipe. It
documents the call shapes Yosoi should make boring:

- construct a typed `ys.Policy`
- check it before crawl spend
- derive a small runtime config
- reject bad config before network/model/vendor work
- keep model/paid scraper escalation out of the crawler hotpath
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import ValidationError

import yosoi as ys


def _bad_scheduler_policy() -> None:
    ys.SchedulerPolicy(max_workers=2, per_host_concurrency=3)


def _bad_depth_budget() -> None:
    ys.CrawlBudget(max_pages=1, max_depth=1)


def _bad_cross_domain_safety() -> None:
    ys.CrawlSafety(allow_cross_domain=True, allowed_hosts=('example.com',))


def _bad_model_escalation() -> None:
    ys.EscalationPolicy(allow_model_discovery=False, max_llm_calls=1)


def _bad_paid_escalation() -> None:
    ys.EscalationPolicy(allow_paid_scrapers=False, max_paid_scraper_calls=1)


def _failure_message(build: Callable[[], None]) -> str:
    try:
        build()
    except ValidationError as exc:
        return str(exc.errors()[0]['msg'])
    raise RuntimeError('bad config example unexpectedly passed')


def policy_from_named_preset() -> ys.Policy:
    """Smallest common user shape: preset plus explicit overrides."""
    return ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(
            max_pages=False,
            max_depth=2,
            max_attempts=240,
            max_pages_per_host=80,
            crawl_session_id='sports-news-index-001',
        ),
        scheduler=ys.SchedulerPolicy(
            max_workers=5,
            per_host_concurrency=1,
            politeness_delay=1.0,
            fetch_timeout_seconds=15.0,
            max_fetch_retries=2,
        ),
        safety=ys.CrawlSafety(
            respect_robots=True,
            allowed_hosts=('www.espn.com', 'sports.yahoo.com', 'www.cbssports.com'),
            blocked_path_prefixes=('/login', '/account', '/cart', '/checkout'),
        ),
        escalation=ys.EscalationPolicy(
            allow_model_discovery=False,
            allow_paid_scrapers=False,
            max_llm_calls=0,
            max_paid_scraper_calls=0,
        ),
        fetcher_type='auto',
    )


def policy_from_arn() -> ys.Policy:
    """Registry-style addressing for policy-as-code and future org presets."""
    arn = ys.policy_arn('default', 'crawl.seed_hunt')
    return ys.Policy(crawl=ys.resolve_crawl_policy(arn))


def direct_url_backlog_policy() -> ys.Policy:
    """Known-URL jobs should not pretend to be exploratory crawls."""
    return ys.Policy.for_crawl(
        'crawl.local_single',
        budget=ys.CrawlBudget(
            max_pages=200_000,
            max_depth=0,
            max_attempts=220_000,
            max_pages_per_host=25_000,
            crawl_session_id='known-article-url-backlog',
        ),
        scheduler=ys.SchedulerPolicy(
            max_workers=32,
            per_host_concurrency=1,
            politeness_delay=0.25,
            fetch_timeout_seconds=20.0,
            max_fetch_retries=2,
        ),
        safety=ys.CrawlSafety(
            respect_robots=True,
            allow_cross_domain=True,
        ),
        escalation=ys.EscalationPolicy(),
    )


def future_call_shapes() -> dict[str, str]:
    """Intended API shape once policy-driven crawl entrypoints are public."""
    return {
        'dry_run': "ys.check_policy(policy, seeds=('https://www.espn.com/nfl/',))",
        'crawl_index': 'await ys.crawl_index(seeds, policy=policy)',
        'plan_scrapes': 'ys.plan_scrapes(index, target=ArticlePage)',
        'scrape_jobs': 'await ys.scrape_jobs(plan, policy=scrape_policy)',
        'rediscovery': 'await ys.rediscover_contracts(failed_jobs, max_llm_calls=3)',
    }


def bad_config_examples() -> list[str]:
    """Examples that must fail before spend."""
    bad_configs = [
        _bad_scheduler_policy,
        _bad_depth_budget,
        _bad_cross_domain_safety,
        _bad_model_escalation,
        _bad_paid_escalation,
    ]
    return [_failure_message(build) for build in bad_configs]


def main() -> None:
    seed = 'https://www.espn.com/nfl/'
    policy = policy_from_named_preset()
    check = ys.check_policy(policy, seeds=(seed,))

    print('policy hash')
    print(check.policy_hash)
    print('runtime config')
    print(check.runtime.model_dump_json(indent=2) if check.runtime else None)

    print('arn preset')
    print(policy_from_arn().require_crawl().model_dump_json(indent=2))

    print('known url backlog')
    backlog_check = ys.check_policy(direct_url_backlog_policy())
    print(backlog_check.runtime.model_dump_json(indent=2) if backlog_check.runtime else None)

    print('future call shapes')
    print(future_call_shapes())

    print('bad config failures')
    print(bad_config_examples())


if __name__ == '__main__':
    main()
