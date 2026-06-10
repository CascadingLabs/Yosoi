"""Raw showcase of the ``ys.policy`` API — one typed, frozen, validated crawl policy.

Run:
    uv run python examples/api_design/policy_api_design.py

Every decision that changes *how* the pipeline behaves — budget, concurrency,
politeness, host safety, escalation — lives in a single frozen ``ys.Policy``
value, resolved once and checked before any network / model / vendor spend.
"""

from __future__ import annotations

from pydantic import ValidationError

import yosoi as ys


def main() -> None:
    # 1. The common shape: a named preset plus explicit overrides.
    policy = ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(max_pages=120, max_depth=2, max_pages_per_host=80),
        safety=ys.CrawlSafety(
            allowed_hosts=('www.espn.com', 'sports.yahoo.com'),
            blocked_path_prefixes=('/login', '/account', '/checkout'),
        ),
        escalation=ys.EscalationPolicy(allow_model_discovery=False, allow_paid_scrapers=False),
    )
    print('# named preset + overrides')
    print('policy_hash:', policy.policy_hash)

    # 2. Dry-run: derive the executor runtime + warnings without spending anything.
    check = ys.check_policy(policy, seeds=('https://www.espn.com/nfl/',))
    print('\n# dry-run check')
    print('warnings:', check.warnings)
    print(check.runtime.model_dump_json(indent=2) if check.runtime else None)

    # 3. Cascade: defaults < env < session < call-site; each layer sets only what it overrides.
    layered = ys.Policy.cascade(
        ys.Policy.from_env(),  # env layer — picks up YOSOI_ATOM_* if present
        ys.Policy(atom_reads=True),  # session turns atom reads on
        ys.Policy(trust_tier='yellow'),  # call-site says "let it ride"
    )
    print('\n# cascade')
    print('atom_reads:', layered.atom_reads, '| trust_tier:', layered.trust_tier)

    # 4. ARN-style addressing for policy-as-code / shared org presets.
    seed_hunt = ys.resolve_crawl_policy(ys.policy_arn('default', 'crawl.seed_hunt'))
    print('\n# arn preset')
    print('mode:', seed_hunt.mode, '| max_pages:', seed_hunt.budget.max_pages)

    # 5. Guardrails: invalid combinations raise ValidationError *before* any spend.
    print('\n# guardrails (rejected at construction)')
    try:
        ys.SchedulerPolicy(max_workers=2, per_host_concurrency=3)  # more per-host than total workers
    except ValidationError as exc:
        print(' -', exc.errors()[0]['msg'])
    try:
        ys.CrawlSafety(allow_cross_domain=True, allowed_hosts=('example.com',))  # cross-domain vs allow-list
    except ValidationError as exc:
        print(' -', exc.errors()[0]['msg'])
    try:
        ys.EscalationPolicy(allow_paid_scrapers=False, max_paid_scraper_calls=1)  # budget without permission
    except ValidationError as exc:
        print(' -', exc.errors()[0]['msg'])

    # 6. Hand the resolved policy straight to the public crawl entrypoint:
    #        summary = await ys.crawl_index(seeds, policy=policy)


if __name__ == '__main__':
    main()
