"""Raw showcase of the ``ys.Policy`` API — one typed, frozen, validated policy tree.

Run:
    uv run python examples/api_design/policy_api_design.py

Every decision that changes *how* the pipeline behaves — model, scrape mode,
discovery, telemetry, output, downloads, crawl budget, concurrency, politeness,
host safety, escalation — lives in a single frozen ``ys.Policy`` value. Public
policy artifacts stay serializable; secrets resolve only into ``ResolvedRunSpec``.
"""

from __future__ import annotations

from pydantic import ValidationError

import yosoi as ys


def main() -> None:
    # 1. The common scrape shape: env defaults plus an explicit call-site layer.
    scrape_policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            model=ys.ModelPolicy.from_string(
                'groq:llama-3.3-70b-versatile',
                credential_ref=ys.SecretRef.env('GROQ_KEY'),
                temperature=0.0,
            ),
            scrape=ys.ScrapePolicy(
                force=True,
                fetcher_type='auto',
                selector_level=ys.SelectorLevel.XPATH,
                max_concurrency=4,
            ),
            discovery=ys.DiscoveryPolicy(max_concurrent=3, mode='auto', replay_verify_threshold=0.9),
            telemetry=ys.TelemetryPolicy(
                langfuse_public_key_ref=ys.SecretRef.env('LANGFUSE_PUBLIC_KEY'),
                langfuse_secret_key_ref=ys.SecretRef.env('LANGFUSE_SECRET_KEY'),
                langfuse_host='http://localhost:3000',
            ),
            output=ys.OutputPolicy(formats=('jsonl', 'parquet'), quiet=False),
            download=ys.DownloadPolicy(
                allow=True,
                allowed_types=('pdf', 'csv'),
                directory='example_downloads',
                max_bytes=10_000_000,
                keep=True,
            ),
        ),
    )
    print('# scrape policy tree')
    print(scrape_policy.model_dump_json(indent=2))
    print('policy_hash:', scrape_policy.policy_hash)
    print('credential ref in normal dump:', 'GROQ_KEY' in scrape_policy.model_dump_json())

    helper_policy = ys.Policy(model=ys.groq('llama-3.3-70b-versatile', credential_ref=ys.SecretRef.env('GROQ_KEY')))
    print('helper model:', helper_policy.model.provider if helper_policy.model else None)

    # 2. Resolve runtime-only objects at the edge. Raw secrets live here, not in the policy.
    run_spec = scrape_policy.resolve_run_spec(
        {
            'GROQ_KEY': 'secret-groq-key',
            'LANGFUSE_PUBLIC_KEY': 'pk-local',
            'LANGFUSE_SECRET_KEY': 'sk-local',
        }
    )
    print('\n# resolved run spec')
    print('model:', f'{run_spec.llm_config.provider}:{run_spec.llm_config.model_name}')
    print('secret length:', len(run_spec.llm_config.api_key or ''))
    print('raw secret in policy dump:', 'secret-groq-key' in scrape_policy.model_dump_json())
    print('telemetry host:', run_spec.telemetry_config.langfuse_host)
    print('output formats:', run_spec.output_formats)

    # 3. The common crawl shape: a named preset plus explicit crawl overrides.
    crawl_policy = ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(max_pages=120, max_depth=2, max_pages_per_host=80),
        safety=ys.CrawlSafety(
            allowed_hosts=('www.espn.com', 'sports.yahoo.com'),
            blocked_path_prefixes=('/login', '/account', '/checkout'),
        ),
        escalation=ys.EscalationPolicy(allow_model_discovery=False, allow_paid_scrapers=False),
    )
    print('# named preset + overrides')
    print('policy_hash:', crawl_policy.policy_hash)

    # 4. Dry-run: derive the executor runtime + warnings without spending anything.
    check = ys.check_policy(crawl_policy, seeds=('https://www.espn.com/nfl/',))
    print('\n# dry-run check')
    print('warnings:', check.warnings)
    print(check.runtime.model_dump_json(indent=2) if check.runtime else None)

    # 5. Cascade: defaults < env < session < contract < call-site.
    layered = ys.Policy.cascade(
        ys.Policy.from_env(),  # env layer — picks up YOSOI_ATOM_* if present
        ys.Policy(atom_reads=True),  # session turns atom reads on
        ys.Policy(trust_tier='yellow'),  # call-site says "let it ride"
    )
    print('\n# cascade')
    print('atom_reads:', layered.atom_reads, '| trust_tier:', layered.trust_tier)

    # 6. ARN-style addressing for policy-as-code / shared org presets.
    seed_hunt = ys.resolve_crawl_policy(ys.policy_arn('default', 'crawl.seed_hunt'))
    print('\n# arn preset')
    print('mode:', seed_hunt.mode, '| max_pages:', seed_hunt.budget.max_pages)

    # 7. Guardrails: invalid combinations raise ValidationError *before* any spend.
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
    try:
        ys.DownloadPolicy(allowed_types=('pdf',))  # download settings without allow=True
    except ValidationError as exc:
        print(' -', exc.errors()[0]['msg'])

    # 8. Hand policy straight to public entrypoints:
    #        rows = await ys.scrape(url, Contract, policy=scrape_policy)
    #        summary = await ys.crawl(seeds, policy=crawl_policy)


if __name__ == '__main__':
    main()
