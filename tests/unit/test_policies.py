"""ys.policies — the resolved-once, immutable pipeline policy (P6 MVP slice / P5 phase 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.policy import (
    QUARANTINED_SOURCES,
    TRUSTED_SOURCES,
    CrawlBudget,
    CrawlPolicy,
    CrawlSafety,
    CrawlTarget,
    EscalationPolicy,
    ExtractorPolicy,
    ModelPolicy,
    Outcome,
    OutputPolicy,
    PagePolicy,
    Policy,
    SchedulerPolicy,
    ScrapePolicy,
    SearchPolicy,
    SecretRef,
    Trust,
    check_policy,
    policy_arn,
    promote_trust,
    resolve_crawl_policy,
)


def test_defaults_are_deny() -> None:
    p = Policy()
    assert p.atom_reads is False  # default-deny
    assert p.trust_tier == 'strict'
    # strict serves only the positive trusted allow-list
    assert p.allowed_sources == TRUSTED_SOURCES
    assert 'fingerprint' not in (p.allowed_sources or frozenset())


def test_extractor_policy_is_opt_in_and_cascades_by_field() -> None:
    assert Policy().extractor is None
    assert ys.ExtractorPolicy() == ExtractorPolicy()
    assert ExtractorPolicy().model_dump() == {
        'reference_writes': False,
        'generalized_reads': False,
        'allowed_references': (),
        'allow_opaque': False,
    }

    effective = Policy.cascade(
        Policy(extractor=ExtractorPolicy(reference_writes=True)),
        Policy(
            extractor=ExtractorPolicy(
                generalized_reads=True,
                allowed_references=('tests.extractors:links',),
            )
        ),
    )
    assert effective.extractor == ExtractorPolicy(
        reference_writes=True,
        generalized_reads=True,
        allowed_references=('tests.extractors:links',),
    )

    with pytest.raises(ValidationError, match='allowed_references'):
        ExtractorPolicy(generalized_reads=True)


def test_run_spec_can_defer_model_only_when_explicitly_requested() -> None:
    with pytest.raises(ValueError, match='No model specified'):
        Policy().resolve_run_spec({})

    spec = Policy().resolve_run_spec({}, require_model=False)
    assert spec.llm_config is None
    unresolved_credentials = Policy(model=ModelPolicy.from_string('openai:gpt-4o')).resolve_run_spec(
        {},
        require_model=False,
    )
    assert unresolved_credentials.llm_config is None


def test_strict_allowlist_is_positive_and_partitions_all_sources() -> None:
    # Guards the fail-OPEN seam: strict must be an explicit allow-list, and every known provenance
    # tier must be classified as trusted XOR quarantined. A new tier added to SOURCE_TRUST without
    # a deliberate classification fails THIS test (fail closed), never silently serves under strict.
    from yosoi.storage.atoms import SOURCE_TRUST

    assert TRUSTED_SOURCES.isdisjoint(QUARANTINED_SOURCES)
    assert set(SOURCE_TRUST) == TRUSTED_SOURCES | QUARANTINED_SOURCES


def test_yellow_serves_all_tiers() -> None:
    assert Policy(trust_tier='yellow').allowed_sources is None


def test_source_trust_maps_known_tiers_to_lattice() -> None:
    p = Policy()
    assert p.source_trust('verified') is Trust.VERIFIED
    assert p.source_trust('manual') is Trust.VERIFIED
    assert p.source_trust('llm') is Trust.VERIFIED
    assert p.source_trust('fingerprint') is Trust.QUARANTINED
    assert p.source_trust('new-tier') is Trust.REJECTED


def test_strict_rejects_quarantined_output() -> None:
    p = Policy(trust_tier='strict')
    assert p.allows_source('verified') is True
    assert p.output_trust('verified') is Trust.VERIFIED
    assert p.allows_source('fingerprint') is False
    assert p.output_trust('fingerprint') is Trust.REJECTED


def test_yellow_serves_quarantined_output_without_verifying_it() -> None:
    p = Policy(trust_tier='yellow')
    assert p.allows_source('fingerprint') is True
    assert p.output_trust('fingerprint') is Trust.QUARANTINED


def test_promote_trust_resolves_quarantined_state() -> None:
    assert promote_trust(Trust.QUARANTINED, confirmed=True) == (Trust.VERIFIED, Outcome.CONFIRMED)
    assert promote_trust(Trust.QUARANTINED, confirmed=False) == (Trust.REJECTED, Outcome.REFUTED)
    assert promote_trust(Trust.VERIFIED, confirmed=False) == (Trust.VERIFIED, Outcome.PENDING)


def test_frozen_is_immutable() -> None:
    p = Policy()
    with pytest.raises(ValidationError):
        p.atom_reads = True


@pytest.mark.parametrize('raw', ['1', 'true', 'YES', 'On'])
def test_from_env_reads_truthy_variants(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv('YOSOI_ATOM_READS', raw)
    assert Policy.from_env().atom_reads is True


def test_from_env_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('YOSOI_ATOM_READS', raising=False)
    monkeypatch.delenv('YOSOI_ATOM_TRUST', raising=False)
    p = Policy.from_env()
    assert p.atom_reads is False
    assert p.trust_tier == 'strict'


@pytest.mark.parametrize(
    ('raw', 'tier'),
    [
        ('yellow', 'yellow'),
        ('ride', 'yellow'),
        ('YELLOW', 'yellow'),  # normalized (strip/lower) in the one classifier
        ('strict', 'strict'),
        ('all', 'strict'),  # NOT an alias — only yellow/ride mean "let it ride"
        ('green', 'strict'),  # NOT an alias — anything unrecognized is strict (fail closed)
        ('garbage', 'strict'),
    ],
)
def test_from_env_trust_tier_aliases(monkeypatch: pytest.MonkeyPatch, raw: str, tier: str) -> None:
    monkeypatch.setenv('YOSOI_ATOM_TRUST', raw)
    assert Policy.from_env().trust_tier == tier


def test_from_env_accepts_injected_mapping() -> None:
    # pure: no global env needed — the env layer can be fed a mapping (testability)
    p = Policy.from_env({'YOSOI_ATOM_READS': 'on', 'YOSOI_ATOM_TRUST': 'yellow'})
    assert p.atom_reads is True
    assert p.trust_tier == 'yellow'


def test_from_env_only_sets_present_vars() -> None:
    # an absent env var must NOT be materialized as an explicitly-set field (or it would clobber a
    # lower cascade layer). Empty env → nothing set → contributes nothing to a cascade.
    assert Policy.from_env({}).model_dump(exclude_unset=True) == {}
    assert set(Policy.from_env({'YOSOI_ATOM_TRUST': 'yellow'}).model_fields_set) == {'trust_tier'}


# ── the cascade: defaults < env < session < contract < call ──────────────────────────────────
def test_cascade_later_layer_wins() -> None:
    base = Policy(atom_reads=False, trust_tier='strict')
    override = Policy(trust_tier='yellow')  # partial: only trust_tier set
    eff = Policy.cascade(base, override)
    assert eff.trust_tier == 'yellow'  # overridden
    assert eff.atom_reads is False  # untouched field preserved from the lower layer


def test_page_policy_overlays_crawl_runtime_acquisition() -> None:
    policy = Policy(
        page=PagePolicy(fetcher_type='headless', clean_html=False),
        crawl=CrawlPolicy(
            budget=CrawlBudget(max_pages=1),
            scheduler=SchedulerPolicy(fetch_timeout_seconds=7, max_fetch_retries=1),
            safety=CrawlSafety(allow_redirects=False),
        ),
    )

    checked = policy.check_crawl(seeds=('https://example.com/',))

    assert checked.runtime is not None
    assert checked.runtime.page.fetcher_type == 'headless'
    assert checked.runtime.page.timeout_seconds == 7
    assert checked.runtime.page.max_fetch_retries == 1
    assert checked.runtime.page.allow_redirects is False
    assert checked.runtime.page.clean_html is False


def test_cascade_partial_layer_only_changes_set_fields() -> None:
    env = Policy(atom_reads=True, trust_tier='strict')
    contract = Policy(atom_reads=False)  # only atom_reads explicitly set
    eff = Policy.cascade(env, contract)
    assert eff.atom_reads is False
    assert eff.trust_tier == 'strict'  # not clobbered back to a default


def test_cascade_env_layer_does_not_clobber_lower_hardening() -> None:
    # the dictator's reset-the-hardening case: a lower layer pins yellow, then an env layer whose
    # YOSOI_ATOM_TRUST is UNSET runs on top. The unset env var must not reset the tier.
    session = Policy(trust_tier='yellow')
    eff = Policy.cascade(session, Policy.from_env({}))
    assert eff.trust_tier == 'yellow'


def test_cascade_skips_none_layers() -> None:
    eff = Policy.cascade(Policy.from_env({'YOSOI_ATOM_TRUST': 'yellow'}), None, None)
    assert eff.trust_tier == 'yellow'


def test_cascade_empty_is_defaults() -> None:
    assert Policy.cascade() == Policy()


def test_nested_cascade_preserves_lower_model_fields() -> None:
    base = Policy(model=ModelPolicy(provider='groq', model_name='llama'))
    override = Policy(model=ModelPolicy(temperature=0.0))

    eff = Policy.cascade(base, override)

    assert eff.model is not None
    assert eff.model.provider == 'groq'
    assert eff.model.model_name == 'llama'
    assert eff.model.temperature == 0.0


def test_from_env_model_and_secret_ref_are_redacted() -> None:
    policy = Policy.from_env({'YOSOI_MODEL': 'groq:llama', 'GROQ_KEY': 'super-secret'})

    assert policy.model is not None
    assert policy.model.credential_ref == SecretRef.env('GROQ_KEY')
    dumped = policy.model_dump()
    assert dumped['model']['credential_ref'] == {'source': 'env', 'name': 'GROQ_KEY'}
    assert 'super-secret' not in repr(policy)
    assert 'super-secret' not in policy.policy_hash


def test_secret_refs_participate_in_policy_hash_without_raw_values() -> None:
    a = Policy(model=ModelPolicy.from_string('groq:llama', credential_ref=SecretRef.env('GROQ_KEY')))
    b = Policy(model=ModelPolicy.from_string('groq:llama', credential_ref=SecretRef.env('ALT_GROQ_KEY')))

    assert a.policy_hash != b.policy_hash
    assert 'GROQ_KEY' in a.model_dump_json()
    assert 'secret-value' not in a.policy_hash


def test_resolve_run_spec_reads_secret_without_storing_it() -> None:
    policy = Policy.from_env({'YOSOI_MODEL': 'groq:llama', 'GROQ_KEY': 'super-secret'})

    spec = policy.resolve_run_spec({'YOSOI_MODEL': 'groq:llama', 'GROQ_KEY': 'super-secret'})

    assert spec.llm_config.provider == 'groq'
    assert spec.llm_config.model_name == 'llama'
    assert spec.llm_config.api_key == 'super-secret'
    assert policy.model is not None
    assert policy.model_dump()['model'] == {
        'provider': 'groq',
        'model_name': 'llama',
        'temperature': 0.01,
        'max_tokens': None,
        'extra_params': None,
        'credential_ref': {'source': 'env', 'name': 'GROQ_KEY'},
    }


def test_explicit_model_does_not_fall_back_to_other_provider_key() -> None:
    policy = Policy(model=ModelPolicy.from_string('openai:gpt-4o'))

    with pytest.raises(ValueError, match="explicit provider 'openai'"):
        policy.resolve_run_spec({'GROQ_KEY': 'groq-key'})


def test_root_provider_helpers_return_redacted_model_policy() -> None:
    model = ys.groq('llama', api_key='super-secret')
    policy = ys.Policy(model=model)

    assert isinstance(model, ModelPolicy)
    assert model.provider == 'groq'
    assert model.model_name == 'llama'
    assert 'super-secret' not in repr(model)
    assert 'super-secret' not in policy.model_dump_json()
    assert 'super-secret' not in policy.policy_hash
    assert policy.resolve_run_spec({}).llm_config.api_key == 'super-secret'


def test_from_env_reads_scrape_policy() -> None:
    policy = Policy.from_env({'YOSOI_FORCE': '1', 'YOSOI_FETCHER_TYPE': 'headless', 'YOSOI_SELECTOR_LEVEL': 'xpath'})

    assert policy.scrape == ScrapePolicy(force=True, fetcher_type='headless', selector_level=ys.SelectorLevel.XPATH)


def test_from_env_reads_search_policy() -> None:
    policy = Policy.from_env(
        {
            'YOSOI_SEARCH_BACKEND': 'bing',
            'YOSOI_SEARCH_REGION': 'wt-wt',
            'YOSOI_SEARCH_SAFESEARCH': 'off',
            'YOSOI_SEARCH_MAX_RESULTS': '7',
            'YOSOI_SEARCH_PAGE': '2',
            'YOSOI_SEARCH_TIMELIMIT': 'w',
        }
    )

    assert policy.search == SearchPolicy(
        backend='bing',
        region='wt-wt',
        safesearch='off',
        max_results=7,
        page=2,
        timelimit='w',
    )


# ── crawl policy: fail-fast config layer ─────────────────────────────────────
def test_crawl_policy_preset_resolves_to_runtime_config() -> None:
    policy = Policy.for_crawl(
        'crawl.conservative',
        safety=CrawlSafety(allowed_hosts=('https://Example.com',)),
    )

    check = policy.check_crawl(seeds=('https://example.com/news/a',))

    assert check.valid is True
    assert check.policy_hash == policy.policy_hash
    assert check.runtime is not None
    assert check.runtime.max_pages == 80
    assert check.runtime.max_depth == 2
    assert check.runtime.max_workers == 3
    assert check.runtime.per_host_concurrency == 1
    assert check.runtime.allowed_hosts == ('example.com',)
    assert check.runtime.respect_robots is True  # default-respect robots
    assert check.runtime.allow_redirects is False  # default: frontier URLs do not silently move


def test_crawl_policy_arn_preset_resolution() -> None:
    arn = policy_arn('default', 'crawl.seed_hunt')

    policy = resolve_crawl_policy(arn)

    assert policy.mode == 'seed_hunt'
    assert policy.budget.max_pages == 200


def test_crawl_policy_runtime_config_uses_seed_host_when_allowed_hosts_omitted() -> None:
    policy = CrawlPolicy(
        budget=CrawlBudget(max_pages=5, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=2),
    )

    runtime = policy.to_runtime_config(seeds=('https://sports.example.com/articles/1',))

    assert runtime.allowed_hosts == ('sports.example.com',)
    assert runtime.allow_cross_domain is False


def test_crawl_policy_check_warns_when_workers_exceed_budget() -> None:
    policy = Policy(
        crawl=CrawlPolicy(
            budget=CrawlBudget(max_pages=2, max_depth=0),
            scheduler=SchedulerPolicy(max_workers=8),
        )
    )

    check = policy.check_crawl(seeds=('https://example.com/',))

    assert 'max_workers exceeds max_pages; some workers will be idle' in check.warnings


def test_crawl_budget_rejects_depth_without_page_budget() -> None:
    with pytest.raises(ValidationError, match='max_depth > 0 requires max_pages > 1'):
        CrawlBudget(max_pages=1, max_depth=1)


@pytest.mark.parametrize(
    ('field_name', 'kwargs'),
    [
        ('max_pages', {'max_pages': False}),
        ('max_depth', {'max_depth': False}),
        ('max_attempts', {'max_attempts': False}),
        ('max_pages_per_host', {'max_pages_per_host': False}),
    ],
)
def test_crawl_budget_rejects_bool_numeric_fields(field_name: str, kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match='boolean values are not valid numeric policy settings'):
        CrawlBudget(**kwargs)


def test_crawl_budget_rejects_attempt_budget_below_page_budget() -> None:
    with pytest.raises(ValidationError, match='max_attempts must be >= max_pages'):
        CrawlBudget(max_pages=10, max_depth=1, max_attempts=5)


def test_scheduler_rejects_per_host_concurrency_above_workers() -> None:
    with pytest.raises(ValidationError, match='per_host_concurrency cannot exceed max_workers'):
        SchedulerPolicy(max_workers=2, per_host_concurrency=3)


@pytest.mark.parametrize(
    'kwargs',
    [
        {'max_workers': False},
        {'per_host_concurrency': False},
        {'politeness_delay': False},
        {'fetch_timeout_seconds': False},
        {'max_fetch_retries': False},
    ],
)
def test_scheduler_rejects_bool_numeric_fields(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match='boolean values are not valid numeric policy settings'):
        SchedulerPolicy(**kwargs)


def test_safety_rejects_host_overlap() -> None:
    with pytest.raises(ValidationError, match='hosts cannot be both allowed and denied'):
        CrawlSafety(allowed_hosts=('example.com',), denied_hosts=('https://example.com',))


def test_safety_rejects_cross_domain_with_allowed_hosts() -> None:
    with pytest.raises(ValidationError, match='allow_cross_domain=True cannot be combined with allowed_hosts'):
        CrawlSafety(allow_cross_domain=True, allowed_hosts=('example.com',))


def test_safety_can_opt_into_redirects() -> None:
    safety = CrawlSafety(allow_redirects=True)

    assert safety.allow_redirects is True


def test_safety_rejects_path_shaped_host_entries() -> None:
    with pytest.raises(ValidationError, match='host entries may not include paths'):
        CrawlSafety(allowed_hosts=('example.com/news',))


def test_escalation_rejects_model_budget_when_discovery_disabled() -> None:
    with pytest.raises(ValidationError, match='max_llm_calls must be 0'):
        EscalationPolicy(allow_model_discovery=False, max_llm_calls=1)


@pytest.mark.parametrize('kwargs', [{'max_llm_calls': False}, {'max_paid_scraper_calls': False}])
def test_escalation_rejects_bool_numeric_fields(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match='boolean values are not valid numeric policy settings'):
        EscalationPolicy(**kwargs)


def test_escalation_rejects_paid_budget_when_paid_scrapers_disabled() -> None:
    with pytest.raises(ValidationError, match='max_paid_scraper_calls must be 0'):
        EscalationPolicy(allow_paid_scrapers=False, max_paid_scraper_calls=1)


@pytest.mark.parametrize(
    'kwargs',
    [
        {'name': 'Article', 'max_budget_pages': False},
    ],
)
def test_crawl_target_rejects_bool_numeric_fields(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match='boolean values are not valid numeric policy settings'):
        CrawlTarget(**kwargs)


def test_check_policy_resolves_public_preset_without_network() -> None:
    check = check_policy('crawl.conservative', seeds=('https://example.com/start',))

    assert check.valid is True
    assert check.runtime is not None
    assert check.runtime.allowed_hosts == ('example.com',)
    assert check.runtime.fetcher_type == 'auto'


# ── run-stack policy: provider helpers + validator guards ────────────────────
_KEYED_PROVIDER_HELPERS = [
    'alibaba',
    'anthropic',
    'azure',
    'bedrock',
    'cerebras',
    'deepseek',
    'fireworks',
    'gemini',
    'github',
    'grok',
    'groq',
    'heroku',
    'huggingface',
    'litellm',
    'mistral',
    'moonshotai',
    'nebius',
    'openai',
    'openrouter',
    'ovhcloud',
    'sambanova',
    'together',
    'vercel',
    'xai',
]


@pytest.mark.parametrize('helper', _KEYED_PROVIDER_HELPERS)
def test_keyed_provider_helper_returns_redacted_model_policy(helper: str) -> None:
    model = getattr(ys, helper)('some-model', api_key='raw-secret')

    assert isinstance(model, ModelPolicy)
    assert model.provider == helper
    assert model.model_name == 'some-model'
    assert 'raw-secret' not in model.model_dump_json()
    assert ys.Policy(model=model).resolve_run_spec({}).llm_config.api_key == 'raw-secret'


@pytest.mark.parametrize(
    ('helper', 'provider_name'),
    [('ollama', 'ollama'), ('vertexai', 'vertexai')],
)
def test_keyless_provider_helpers(helper: str, provider_name: str) -> None:
    model = getattr(ys, helper)('some-model')

    assert isinstance(model, ModelPolicy)
    assert model.provider == provider_name
    assert model.model_name == 'some-model'


@pytest.mark.parametrize(
    ('helper', 'provider_name'),
    [('claude_sdk', 'claude-sdk'), ('opencode', 'opencode')],
)
def test_default_model_provider_helpers(helper: str, provider_name: str) -> None:
    model = getattr(ys, helper)()

    assert isinstance(model, ModelPolicy)
    assert model.provider == provider_name
    assert model.model_name


def test_provider_helper_parses_model_string_and_keeps_key_runtime_only() -> None:
    model = ys.provider('groq:llama-3.3-70b-versatile', api_key='raw-secret')

    assert model.provider == 'groq'
    assert model.model_name == 'llama-3.3-70b-versatile'
    assert 'raw-secret' not in model.model_dump_json()
    assert ys.Policy(model=model).resolve_run_spec({}).llm_config.api_key == 'raw-secret'


def test_secret_ref_rejects_empty_env_name() -> None:
    with pytest.raises(ValidationError, match='must be non-empty'):
        SecretRef.env('   ')


def test_model_policy_rejects_provider_without_model_name() -> None:
    with pytest.raises(ValidationError, match='must be set together'):
        ModelPolicy(provider='groq')


def test_download_policy_rejects_settings_without_allow() -> None:
    with pytest.raises(ValidationError, match='require DownloadPolicy\\(allow=True\\)'):
        ys.DownloadPolicy(allowed_types=('pdf',))


# ── cascade credential firewall ───────────────────────────────────────────────
def test_cascade_provider_override_drops_lower_layer_runtime_key() -> None:
    base = Policy(model=ys.anthropic('claude-x', api_key='sk-ant-secret'))
    override = Policy(model=ModelPolicy.from_string('groq:llama'))

    merged = Policy.cascade(base, override).model

    assert merged is not None
    assert merged.provider == 'groq'
    assert merged._runtime_api_key is None


def test_cascade_provider_override_drops_lower_layer_credential_ref() -> None:
    env = {'YOSOI_MODEL': 'anthropic:claude-x', 'ANTHROPIC_API_KEY': 'sk-ant-env', 'GROQ_KEY': 'groq-env'}
    eff = Policy.cascade(Policy.from_env(env), Policy(model=ModelPolicy.from_string('groq:llama')))

    spec = eff.resolve_run_spec(env)

    assert spec.llm_config.provider == 'groq'
    assert spec.llm_config.api_key == 'groq-env'


def test_cascade_revalidates_nested_secret_refs() -> None:
    low = Policy(model=ModelPolicy.from_string('groq:llama'))
    high = Policy(model=ModelPolicy.from_string('groq:llama', credential_ref=SecretRef.env('GROQ_KEY')))

    merged = Policy.cascade(low, high).model

    assert merged is not None
    assert isinstance(merged.credential_ref, SecretRef)
    assert merged.credential_ref.name == 'GROQ_KEY'


def test_cascade_non_identity_override_keeps_runtime_key() -> None:
    base = Policy(model=ys.groq('llama', api_key='groq-secret'))
    override = Policy(model=ModelPolicy(temperature=0.5))

    merged = Policy.cascade(base, override).model

    assert merged is not None
    assert merged.provider == 'groq'
    assert merged.temperature == 0.5
    assert merged._runtime_api_key == 'groq-secret'


def test_cascade_telemetry_merge_keeps_secret_refs_as_models() -> None:
    low = Policy(telemetry=ys.TelemetryPolicy(langfuse_host='http://low'))
    high = Policy(telemetry=ys.TelemetryPolicy(langfuse_public_key_ref=SecretRef.env('LANGFUSE_PUBLIC_KEY')))

    merged = Policy.cascade(low, high).telemetry

    assert merged is not None
    assert merged.langfuse_host == 'http://low'
    assert isinstance(merged.langfuse_public_key_ref, SecretRef)


# ── small uncovered guard branches ────────────────────────────────────────────
def test_require_crawl_raises_without_crawl_settings() -> None:
    with pytest.raises(ValueError, match='does not include crawl settings'):
        Policy().require_crawl()


def test_allows_source_quarantined_requires_yellow_tier() -> None:
    quarantined = next(iter(QUARANTINED_SOURCES))

    assert Policy(trust_tier='yellow').allows_source(quarantined) is True
    assert Policy(trust_tier='strict').allows_source(quarantined) is False


def test_output_trust_rejects_quarantined_source_under_strict_tier() -> None:
    quarantined = next(iter(QUARANTINED_SOURCES))

    assert Policy(trust_tier='strict').output_trust(quarantined) is Trust.REJECTED
    assert Policy(trust_tier='yellow').output_trust(quarantined) is Trust.QUARANTINED


def test_crawl_session_id_validator_branches() -> None:
    assert CrawlBudget(crawl_session_id=None).crawl_session_id is None
    assert CrawlBudget(crawl_session_id='  ').crawl_session_id is None
    with pytest.raises(ValidationError, match='120 characters'):
        CrawlBudget(crawl_session_id='x' * 121)


def test_crawl_target_rejects_blank_name() -> None:
    with pytest.raises(ValidationError, match='non-empty'):
        CrawlTarget(name='   ')


def test_crawl_policy_accepts_string_target_contracts() -> None:
    policy = CrawlPolicy(mode='seed_hunt', target_contracts=('NewsArticle',))
    runtime = policy.to_runtime_config(seeds=('https://example.com/news/',))

    assert policy.target_contracts == (CrawlTarget(name='NewsArticle'),)
    assert runtime.target_contracts == (CrawlTarget(name='NewsArticle'),)


def test_policy_arn_rejects_blank_parts() -> None:
    with pytest.raises(ValueError, match='non-empty'):
        policy_arn('  ', 'crawl.seed_hunt')


# ── branch-coverage closure on PR-changed lines ───────────────────────────────
def test_allows_source_rejects_unknown_source_outright() -> None:
    assert Policy(trust_tier='yellow').allows_source('not-a-known-tier') is False
    assert Policy().output_trust('not-a-known-tier') is Trust.REJECTED


def test_output_trust_passes_verified_source_through() -> None:
    assert Policy().output_trust('verified') is Trust.VERIFIED


def test_resolve_crawl_policy_accepts_inline_crawl_policy_and_rejects_unknown_key() -> None:
    inline = CrawlPolicy(mode='seed_hunt')
    assert resolve_crawl_policy(inline) is inline
    with pytest.raises(KeyError, match='Unknown crawl policy'):
        resolve_crawl_policy('crawl.not-a-preset')


def test_crawl_session_id_valid_value_round_trips() -> None:
    assert CrawlBudget(crawl_session_id=' run-7 ').crawl_session_id == 'run-7'


@pytest.mark.parametrize(
    ('hosts', 'message'),
    [
        (('',), 'non-empty'),
        (('example.com/path',), 'may not include paths'),
        (('example.com?q=1',), 'may not include paths'),
        (('http://',), 'invalid host entry'),
    ],
)
def test_crawl_safety_rejects_malformed_hosts(hosts: tuple[str, ...], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        CrawlSafety(allowed_hosts=hosts)


def test_crawl_safety_path_prefix_validation() -> None:
    assert CrawlSafety(blocked_path_prefixes=('', '/ok')).blocked_path_prefixes == ('/ok',)
    with pytest.raises(ValidationError, match='must start with'):
        CrawlSafety(blocked_path_prefixes=('login',))


def test_provider_helper_without_api_key_has_no_runtime_key() -> None:
    model = ys.provider('groq:llama')

    assert model._runtime_api_key is None


# ── cross-origin DOM opt-in (VoidCrawl >= 0.3.5) ─────────────────────────────
def test_cross_origin_dom_defaults_off_and_resolves_into_spec() -> None:
    assert ScrapePolicy().cross_origin_dom is False

    policy = Policy(model=ys.claude_sdk(), scrape=ScrapePolicy(cross_origin_dom=True))
    spec = policy.resolve_run_spec({})

    assert spec.cross_origin_dom is True
    assert Policy(model=ys.claude_sdk()).resolve_run_spec({}).cross_origin_dom is False


def test_flat_files_default_off_and_resolves_into_spec() -> None:
    assert OutputPolicy().flat_files is False

    policy = Policy(model=ys.claude_sdk(), output=OutputPolicy(flat_files=True))

    assert policy.resolve_run_spec({}).output_flat_files is True
    assert Policy(model=ys.claude_sdk()).resolve_run_spec({}).output_flat_files is False


def test_from_env_reads_cross_origin_dom() -> None:
    policy = Policy.from_env({'YOSOI_CROSS_ORIGIN_DOM': '1'})

    assert policy.scrape is not None
    assert policy.scrape.cross_origin_dom is True
    assert Policy.from_env({}).scrape is None


def test_resolve_crawl_policy_unwraps_full_policy() -> None:
    policy = Policy.for_crawl('crawl.conservative')

    assert resolve_crawl_policy(policy) is policy.crawl


def test_from_string_api_key_is_runtime_only_no_env_dict_needed() -> None:
    """Clean key handoff: api_key rides on the model, resolve_run_spec() needs no env mapping."""
    policy = Policy(model=ModelPolicy.from_string('groq:llama', api_key='gk-secret', temperature=0.0))

    spec = policy.resolve_run_spec()

    assert spec.llm_config.provider == 'groq'
    assert spec.llm_config.api_key == 'gk-secret'
    # never serialized — same contract as the provider helpers
    assert 'gk-secret' not in policy.model_dump_json()
    assert 'gk-secret' not in repr(policy)
    assert 'gk-secret' not in policy.policy_hash


def test_resolved_run_spec_never_leaks_secrets_in_repr_or_dump() -> None:
    """ResolvedRunSpec carries the live key for use but masks it in repr/dump/json."""
    spec = Policy(model=ModelPolicy.from_string('groq:llama', api_key='SECRET-KEY-123')).resolve_run_spec()

    assert spec.llm_config.api_key == 'SECRET-KEY-123'  # live value reachable at point of use
    assert 'SECRET-KEY-123' not in repr(spec)
    assert 'SECRET-KEY-123' not in repr(spec.llm_config)
    assert 'SECRET-KEY-123' not in str(spec.model_dump())
    assert 'SECRET-KEY-123' not in spec.model_dump_json()
    assert spec.model_dump()['llm_config']['api_key'] == '***REDACTED***'


def test_check_crawl_does_not_warn_for_enforced_per_host_caps() -> None:
    policy = Policy.for_crawl('crawl.seed_hunt')

    warnings = policy.check_crawl(seeds=('https://x.test/',)).warnings

    assert warnings == ()


def test_redact_secret_configs_handles_none_and_dict_inputs() -> None:
    """The redaction serializer is defensive for the Any-typed config fields."""
    spec = Policy(model=ModelPolicy.from_string('groq:llama', api_key='k')).resolve_run_spec()

    assert spec._redact_secret_configs(None) is None
    assert spec._redact_secret_configs({'api_key': 'raw', 'other': 1}) == {
        'api_key': '***REDACTED***',
        'other': 1,
    }


def test_page_policy_accepts_comma_separated_chrome_ws_urls() -> None:
    policy = PagePolicy(chrome_ws_urls='http://127.0.0.1:9222, http://127.0.0.1:9223')

    assert policy.chrome_ws_urls == ('http://127.0.0.1:9222', 'http://127.0.0.1:9223')
    assert policy.to_runtime_config().chrome_ws_urls == policy.chrome_ws_urls
