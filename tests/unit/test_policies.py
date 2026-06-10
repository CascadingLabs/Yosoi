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
    ModelPolicy,
    Outcome,
    Policy,
    SchedulerPolicy,
    ScrapePolicy,
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
        p.atom_reads = True  # type: ignore[misc]


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
        {'name': 'Article', 'min_fields': False},
        {'name': 'Article', 'min_confidence': False},
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
