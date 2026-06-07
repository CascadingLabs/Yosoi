"""Tests for the pure resolve() function (CAS-119)."""

from __future__ import annotations

import pytest

import yosoi as ys
from yosoi.core.resolve import ContractCache, build_cache_from_selectors, resolve
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.needs_discovery import NeedsDiscovery
from yosoi.models.selectors import SelectorEntry
from yosoi.models.spec import ContractSpec, FieldSpec

DOMAIN = 'example.com'
MINIMAL_HTML = """<html><body>
<h1 class="headline">Test Headline</h1>
<span class="author">Jane Doe</span>
</body></html>"""

SELECTORS: dict = {
    'headline': {'primary': 'h1.headline'},
    'author': {'primary': 'span.author'},
    'date': {'primary': 'time'},
    'body_text': {'primary': 'article'},
    'related_content': {'primary': '.related'},
}


@pytest.fixture
def spec():
    return NewsArticle.to_spec()


@pytest.fixture
def warm_cache(spec) -> ContractCache:
    return build_cache_from_selectors(DOMAIN, spec.fingerprint, SELECTORS)


@pytest.fixture
def empty_cache() -> ContractCache:
    return {}


class TestCacheMiss:
    def test_miss_returns_needs_discovery(self, spec, empty_cache):
        result = resolve(spec, MINIMAL_HTML, empty_cache, DOMAIN)
        assert isinstance(result, NeedsDiscovery)

    def test_miss_carries_domain(self, spec, empty_cache):
        result = resolve(spec, MINIMAL_HTML, empty_cache, DOMAIN)
        assert isinstance(result, NeedsDiscovery)
        assert result.domain == DOMAIN

    def test_miss_carries_fingerprint(self, spec, empty_cache):
        result = resolve(spec, MINIMAL_HTML, empty_cache, DOMAIN)
        assert isinstance(result, NeedsDiscovery)
        assert result.contract_fingerprint == spec.fingerprint

    def test_miss_lists_fields(self, spec, empty_cache):
        result = resolve(spec, MINIMAL_HTML, empty_cache, DOMAIN)
        assert isinstance(result, NeedsDiscovery)
        assert len(result.fields) > 0

    def test_miss_returns_discovery_when_atom_reads_requested_and_contract_has_no_fields(
        self,
        monkeypatch,
        empty_cache,
    ):
        monkeypatch.setenv('YOSOI_ATOM_READS', '1')
        spec = ContractSpec(name='Empty', fields={})
        result = resolve(spec, MINIMAL_HTML, empty_cache, DOMAIN)
        assert isinstance(result, NeedsDiscovery)


class TestCacheHit:
    def test_hit_returns_list(self, spec, warm_cache):
        result = resolve(spec, MINIMAL_HTML, warm_cache, DOMAIN)
        assert isinstance(result, list)

    def test_hit_returns_records_with_expected_fields(self, spec, warm_cache):
        result = resolve(spec, MINIMAL_HTML, warm_cache, DOMAIN)
        assert isinstance(result, list)
        if result:
            assert 'headline' in result[0] or 'author' in result[0]

    def test_same_inputs_same_output(self, spec, warm_cache):
        r1 = resolve(spec, MINIMAL_HTML, warm_cache, DOMAIN)
        r2 = resolve(spec, MINIMAL_HTML, warm_cache, DOMAIN)
        assert r1 == r2

    def test_no_global_state_pollution(self, spec, warm_cache, empty_cache):
        resolve(spec, MINIMAL_HTML, warm_cache, DOMAIN)
        r2 = resolve(spec, MINIMAL_HTML, empty_cache, DOMAIN)
        assert isinstance(r2, NeedsDiscovery)

    def test_rooted_cache_hit_returns_one_record_per_container(self):
        class ProductCard(Contract):
            root = SelectorEntry(type='css', value='.card')

            name: str = ys.Title()
            price: str = ys.Field()

        html = """<html><body>
        <div class="card"><h2>Hammer</h2><span class="price">$10</span></div>
        <div class="card"><h2>Anvil</h2><span class="price">$20</span></div>
        </body></html>"""
        spec = ProductCard.to_spec()
        cache = build_cache_from_selectors(
            DOMAIN,
            spec.fingerprint,
            {
                'name': {'primary': {'type': 'css', 'value': 'h2::text'}},
                'price': {'primary': {'type': 'css', 'value': '.price::text'}},
            },
        )

        result = resolve(spec, html, cache, DOMAIN)

        assert result == [{'name': 'Hammer', 'price': '$10'}, {'name': 'Anvil', 'price': '$20'}]


class TestFingerprintDedup:
    def test_renamed_spec_is_distinct_cache_slot(self, spec, warm_cache):
        # P0: contract name is part of identity. A renamed contract no longer
        # piggybacks on another's selectors — it gets its own slot (cache miss).
        # This is the AdLink/OrganicLink discrimination fix at the resolve layer.
        mirror = spec.model_copy(update={'name': 'MirrorArticle'})
        assert mirror.fingerprint != spec.fingerprint
        result = resolve(mirror, MINIMAL_HTML, warm_cache, DOMAIN)
        assert isinstance(result, NeedsDiscovery)

    def test_different_fingerprint_is_miss(self, spec, warm_cache):
        from yosoi.models.spec import ContractSpec, FieldSpec

        different = ContractSpec(
            name='NewsArticle',
            fields={'headline': FieldSpec(yosoi_type='body_text')},
        )
        assert different.fingerprint != spec.fingerprint
        result = resolve(different, MINIMAL_HTML, warm_cache, DOMAIN)
        assert isinstance(result, NeedsDiscovery)

    def test_atom_read_fails_closed_on_atom_pipeline_errors(self, monkeypatch, empty_cache):
        import yosoi.generalization.capture as capture

        monkeypatch.setenv('YOSOI_ATOM_READS', '1')

        def _observe_html(*_args, **_kwargs):
            raise RuntimeError('boom')

        monkeypatch.setattr(
            capture,
            'observe_html',
            _observe_html,
        )

        result = resolve(
            ContractSpec(name='Quote', fields={'symbol': FieldSpec(yosoi_type=None)}),
            MINIMAL_HTML,
            empty_cache,
            DOMAIN,
            url='https://example.com/quote',
        )

        assert isinstance(result, NeedsDiscovery)


class TestBuildCache:
    def test_build_cache_helper(self, spec):
        cache = build_cache_from_selectors(DOMAIN, spec.fingerprint, SELECTORS)
        assert (DOMAIN, spec.fingerprint) in cache
        assert cache[(DOMAIN, spec.fingerprint)] is SELECTORS
