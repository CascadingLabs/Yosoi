"""Tests for granular (per-field) cache verification in Pipeline."""

import time
from datetime import datetime, timezone

import pytest

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.results import FieldVerificationResult, VerificationResult
from yosoi.models.selectors import SelectorLevel
from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SimpleContract(Contract):
    title: str = ys.Title()
    price: float = ys.Price()


def _make_pipeline_stub(mocker, contract=None):
    """Create a minimal Pipeline instance without calling __init__."""
    stub = Pipeline.__new__(Pipeline)
    stub.contract = contract or SimpleContract
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    stub.cleaner = mocker.MagicMock()
    stub.discovery = mocker.MagicMock()
    stub.discovery.discover_selectors = mocker.AsyncMock()
    stub.verifier = mocker.MagicMock()
    stub.extractor = mocker.MagicMock()
    stub.storage = mocker.MagicMock()
    stub.tracker = mocker.MagicMock()
    stub.debug = mocker.MagicMock()
    stub.debug_mode = False
    stub.output_formats = ['json']
    stub.force = False
    stub.selector_level = SelectorLevel.CSS
    return stub


def _make_snapshot(value: str, **kwargs) -> SelectorSnapshot:
    """Create a simple CSS SelectorSnapshot."""
    defaults = {
        'primary': {'type': 'css', 'value': value},
        'discovered_at': datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return SelectorSnapshot(**defaults)


# ---------------------------------------------------------------------------
# _verify_per_field
# ---------------------------------------------------------------------------


class TestVerifyPerField:
    def test_all_fresh(self, mocker):
        stub = _make_pipeline_stub(mocker)
        snapshots = {
            'title': _make_snapshot('h1.title'),
            'price': _make_snapshot('.price'),
        }

        # Both fields verify successfully
        stub.verifier._verify_field.return_value = FieldVerificationResult(
            field_name='any', status='verified', working_level='primary', selector='h1.title'
        )

        verdicts = stub._verify_per_field('<html><h1 class="title">X</h1></html>', snapshots)

        assert verdicts['title'] == CacheVerdict.FRESH
        assert verdicts['price'] == CacheVerdict.FRESH

    def test_one_stale(self, mocker):
        stub = _make_pipeline_stub(mocker)
        snapshots = {
            'title': _make_snapshot('h1.title'),
            'price': _make_snapshot('.price'),
        }

        def _verify_field(sel, field_name, field_data, max_level):
            if field_name == 'title':
                return FieldVerificationResult(
                    field_name='title', status='verified', working_level='primary', selector='h1.title'
                )
            return FieldVerificationResult(field_name='price', status='failed', failed_selectors=[])

        stub.verifier._verify_field.side_effect = _verify_field

        verdicts = stub._verify_per_field('<html></html>', snapshots)

        assert verdicts['title'] == CacheVerdict.FRESH
        assert verdicts['price'] == CacheVerdict.STALE

    def test_root_cascade(self, mocker):
        """When root is STALE, all child fields should cascade to STALE."""
        stub = _make_pipeline_stub(mocker)
        snapshots = {
            'root': _make_snapshot('.product-card'),
            'title': _make_snapshot('h1.title'),
            'price': _make_snapshot('.price'),
        }

        def _verify_field(sel, field_name, field_data, max_level):
            if field_name == 'root':
                return FieldVerificationResult(field_name='root', status='failed', failed_selectors=[])
            return FieldVerificationResult(
                field_name=field_name, status='verified', working_level='primary', selector='x'
            )

        stub.verifier._verify_field.side_effect = _verify_field

        verdicts = stub._verify_per_field('<html></html>', snapshots)

        assert verdicts['root'] == CacheVerdict.STALE
        assert verdicts['title'] == CacheVerdict.STALE
        assert verdicts['price'] == CacheVerdict.STALE


# ---------------------------------------------------------------------------
# _try_cached integration paths
# ---------------------------------------------------------------------------


class TestTryCachedGranular:
    @pytest.fixture
    def stub(self, mocker):
        return _make_pipeline_stub(mocker)

    async def test_no_cache_returns_none(self, stub):
        stub.storage.load_snapshots.return_value = None
        result = await stub._try_cached('https://example.com', 'example.com', mocker_fetcher(stub), False, ['json'])
        assert result is None

    async def test_all_fresh_extracts_without_discovery(self, stub, mocker):
        """When all fields verify FRESH, no discovery should be called."""
        stub._url_start = time.monotonic()
        stub.storage.load_snapshots.return_value = {
            'title': _make_snapshot('h1.title'),
            'price': _make_snapshot('.price'),
        }

        # Mock fetcher
        mock_fetcher = mocker.AsyncMock()
        mock_result = mocker.MagicMock()
        mock_result.success = True
        mock_result.html = '<html><h1 class="title">Test</h1><span class="price">$10</span></html>'
        mock_fetcher.fetch.return_value = mock_result

        # Mock cleaner
        stub.cleaner.clean_html.return_value = mock_result.html

        # All fields verify as FRESH
        stub.verifier._verify_field.return_value = FieldVerificationResult(
            field_name='any', status='verified', working_level='primary', selector='x'
        )

        # Mock extraction
        stub.extractor.extract_content_with_html.return_value = {'title': 'Test', 'price': '$10'}

        # Mock contract validation
        stub.contract = SimpleContract
        stub.tracker.record_url.return_value = {
            'llm_calls': 0,
            'url_count': 1,
            'level_distribution': {},
            'total_elapsed': 0.0,
            'partial_rediscovery_count': 0,
        }

        gen = await stub._try_cached('https://example.com', 'example.com', mock_fetcher, False, ['json'])
        assert gen is not None

        items = [item async for item in gen]
        assert len(items) >= 1

        # Discovery should NOT be called
        stub.discovery.discover_selectors.assert_not_called()

    async def test_all_stale_returns_none(self, stub, mocker):
        """When all fields are stale, should return None for full discovery."""
        stub.storage.load_snapshots.return_value = {
            'title': _make_snapshot('h1.title'),
            'price': _make_snapshot('.price'),
        }

        mock_fetcher = mocker.AsyncMock()
        mock_result = mocker.MagicMock()
        mock_result.success = True
        mock_result.html = '<html></html>'
        mock_fetcher.fetch.return_value = mock_result
        stub.cleaner.clean_html.return_value = '<html></html>'

        # All fields fail verification
        stub.verifier._verify_field.return_value = FieldVerificationResult(
            field_name='any', status='failed', failed_selectors=[]
        )

        result = await stub._try_cached('https://example.com', 'example.com', mock_fetcher, False, ['json'])
        assert result is None

    async def test_partial_stale_triggers_partial_discovery(self, stub, mocker):
        """When some fields are stale, should trigger partial rediscovery."""
        stub._url_start = time.monotonic()
        stub.storage.load_snapshots.return_value = {
            'title': _make_snapshot('h1.title'),
            'price': _make_snapshot('.old-price'),
        }

        mock_fetcher = mocker.AsyncMock()
        mock_result = mocker.MagicMock()
        mock_result.success = True
        mock_result.html = '<html><h1 class="title">Test</h1></html>'
        mock_fetcher.fetch.return_value = mock_result
        stub.cleaner.clean_html.return_value = mock_result.html

        # title fresh, price stale
        def _verify_field(sel, field_name, field_data, max_level):
            if field_name == 'title':
                return FieldVerificationResult(
                    field_name='title', status='verified', working_level='primary', selector='h1.title'
                )
            return FieldVerificationResult(field_name='price', status='failed', failed_selectors=[])

        stub.verifier._verify_field.side_effect = _verify_field

        # Mock partial discovery returning a new price selector
        stub.discovery.discover_selectors.return_value = {
            'price': {'primary': {'type': 'css', 'value': '.new-price'}},
        }

        # Mock verification of newly discovered selectors
        stub.verifier.verify.return_value = VerificationResult(
            total_fields=1,
            verified_count=1,
            results={
                'price': FieldVerificationResult(
                    field_name='price', status='verified', working_level='primary', selector='.new-price'
                )
            },
        )

        # Mock extraction
        stub.extractor.extract_content_with_html.return_value = {'title': 'Test', 'price': '$20'}

        stub.tracker.record_url.return_value = {
            'llm_calls': 1,
            'url_count': 1,
            'level_distribution': {},
            'total_elapsed': 1.0,
            'partial_rediscovery_count': 1,
        }

        gen = await stub._try_cached('https://example.com', 'example.com', mock_fetcher, False, ['json'])
        assert gen is not None

        items = [item async for item in gen]
        assert len(items) >= 1

        # Discovery should be called with stale_fields={'price'}
        stub.discovery.discover_selectors.assert_called_once()
        call_kwargs = stub.discovery.discover_selectors.call_args
        assert call_kwargs.kwargs.get('stale_fields') == {'price'}


def mocker_fetcher(stub):
    """Return a mock fetcher that returns None (used when we expect early return)."""
    return stub.storage  # any mock will do — won't be called
