"""CodSpeed benchmarks for policy preflight — the runtime resolution on the hot edge.

Every ``ys.scrape`` call resolves a :class:`~yosoi.policy.core.Policy` into a
:class:`~yosoi.policy.run.ResolvedRunSpec` *before* any network / model spend (the
CAS-119 purity contract: resolve once at the edge, never read the environment deep
in the stack). That preflight — ``cascade`` to merge the layer stack, ``from_env``
to read the ``YOSOI_*`` switches, ``resolve_run_spec`` to materialize secrets, and
``check_policy`` for the crawl dry-run — runs on every call, so it must stay cheap.

These benchmarks guard that cost. They are pure CPU (no network, no model, no
browser): a regression here means the per-call edge tax grew.
"""

from __future__ import annotations

import pytest
from pytest_codspeed import BenchmarkFixture

import yosoi as ys
from yosoi.policy import Policy, check_policy

# A representative env layer: model + provider key + the scrape/telemetry switches.
_ENV = {
    'YOSOI_MODEL': 'groq:llama-3.3-70b-versatile',
    'GROQ_KEY': 'gk-benchmark-secret',
    'YOSOI_FORCE': '1',
    'YOSOI_FETCHER_TYPE': 'headless',
    'YOSOI_CROSS_ORIGIN_DOM': '1',
    'LANGFUSE_PUBLIC_KEY': 'pk-benchmark',
    'LANGFUSE_SECRET_KEY': 'sk-benchmark',
}


def test_from_env_layer(benchmark: BenchmarkFixture) -> None:
    """Parse the YOSOI_*/LANGFUSE_* env surface into a partial Policy."""
    result = benchmark(lambda: Policy.from_env(_ENV))

    assert result.model is not None
    assert result.scrape is not None


def test_cascade_layer_stack(benchmark: BenchmarkFixture) -> None:
    """Merge the full precedence stack (env < session < contract < call-site)."""
    env = Policy.from_env(_ENV)
    session = Policy(trust_tier='yellow')
    contract = Policy(scrape=ys.ScrapePolicy(selector_level=ys.SelectorLevel.XPATH))
    call = Policy(model=ys.ModelPolicy(temperature=0.0), scrape=ys.ScrapePolicy(cross_origin_dom=True))

    result = benchmark(lambda: Policy.cascade(env, session, contract, call))

    assert result.trust_tier == 'yellow'
    assert result.scrape is not None
    assert result.scrape.cross_origin_dom is True


def test_resolve_run_spec_preflight(benchmark: BenchmarkFixture) -> None:
    """The per-scrape edge resolution: cascade → resolve secrets → ResolvedRunSpec."""
    policy = Policy.cascade(Policy.from_env(_ENV), Policy(scrape=ys.ScrapePolicy(cross_origin_dom=True)))

    spec = benchmark(lambda: policy.resolve_run_spec(_ENV))

    assert spec.llm_config.api_key == 'gk-benchmark-secret'
    assert spec.cross_origin_dom is True
    assert spec.force is True


@pytest.mark.parametrize('preset', ['crawl.conservative', 'crawl.seed_hunt'])
def test_check_policy_crawl_dry_run(benchmark: BenchmarkFixture, preset: str) -> None:
    """Crawl preflight: resolve a preset and derive the executor runtime + warnings."""
    seeds = ('https://www.example.com/',)

    check = benchmark(lambda: check_policy(preset, seeds=seeds))

    assert check.valid is True
    assert check.runtime is not None


def test_policy_hash_provenance(benchmark: BenchmarkFixture) -> None:
    """The content hash stamped on every artifact for provenance (must exclude raw secrets)."""
    policy = Policy.from_env(_ENV)

    digest = benchmark(lambda: policy.policy_hash)

    assert 'gk-benchmark-secret' not in digest
