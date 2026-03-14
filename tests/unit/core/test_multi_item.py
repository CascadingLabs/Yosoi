"""Unit tests for multi-item pipeline features."""

from pydantic import ConfigDict

import yosoi as ys

# ---------------------------------------------------------------------------
# Contract helpers
# ---------------------------------------------------------------------------
from yosoi import Pipeline
from yosoi.models.results import FetchResult


class SimpleContract(ys.Contract):
    title: str = ys.Title()
    price: float = ys.Price()


class ContainerContract(ys.Contract):
    model_config = ConfigDict(json_schema_extra={'yosoi_container': '.product-card'})

    name: str = ys.Title()
    price: str = ys.Field(description='Price')


# ---------------------------------------------------------------------------
# Contract.get_container_selector
# ---------------------------------------------------------------------------


def test_get_container_selector_returns_none_by_default():
    assert SimpleContract.get_container_selector() is None


def test_get_container_selector_returns_override():
    assert ContainerContract.get_container_selector() == '.product-card'


def test_get_container_selector_ignores_non_string():
    class BadContainer(ys.Contract):
        model_config = ConfigDict(json_schema_extra={'yosoi_container': 123})

    assert BadContainer.get_container_selector() is None


def test_get_container_selector_ignores_empty_string():
    class EmptyContainer(ys.Contract):
        model_config = ConfigDict(json_schema_extra={'yosoi_container': ''})

    assert EmptyContainer.get_container_selector() is None


# ---------------------------------------------------------------------------
# Contract.to_selector_model includes yosoi_container
# ---------------------------------------------------------------------------


def test_selector_model_includes_yosoi_container():
    SelectorModel = SimpleContract.to_selector_model()
    assert 'yosoi_container' in SelectorModel.model_fields


def test_selector_model_yosoi_container_is_optional():
    SelectorModel = SimpleContract.to_selector_model()
    field = SelectorModel.model_fields['yosoi_container']
    assert field.default is None


# ---------------------------------------------------------------------------
# Pipeline._pop_container
# ---------------------------------------------------------------------------


def test_pop_container_extracts_primary_string():
    selectors = {
        'title': {'primary': 'h1'},
        'yosoi_container': {'primary': '.card', 'fallback': None, 'tertiary': None},
    }
    result = Pipeline._pop_container(selectors)
    assert result == '.card'
    assert 'yosoi_container' not in selectors


def test_pop_container_returns_none_when_absent():
    selectors = {'title': {'primary': 'h1'}}
    result = Pipeline._pop_container(selectors)
    assert result is None


def test_pop_container_handles_selector_entry_dict():
    selectors = {
        'yosoi_container': {'primary': {'type': 'css', 'value': '.card'}, 'fallback': None},
    }
    result = Pipeline._pop_container(selectors)
    assert result == '.card'
    assert 'yosoi_container' not in selectors


def test_pop_container_returns_none_for_empty_primary():
    selectors = {'yosoi_container': {'primary': '', 'fallback': None}}
    result = Pipeline._pop_container(selectors)
    assert result is None


# ---------------------------------------------------------------------------
# Pipeline._resolve_container
# ---------------------------------------------------------------------------


def _make_pipeline_stub(mocker, contract=None):
    """Create a minimal Pipeline instance without calling __init__."""
    stub = Pipeline.__new__(Pipeline)
    stub.contract = contract or SimpleContract
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    return stub


def test_resolve_container_prefers_contract_override(mocker):
    stub = _make_pipeline_stub(mocker, ContainerContract)
    selectors = {
        'name': {'primary': 'h2'},
        'yosoi_container': {'primary': '.ai-discovered'},
    }
    result = stub._resolve_container(selectors)
    assert result == '.product-card'
    assert 'yosoi_container' not in selectors


def test_resolve_container_uses_ai_discovered(mocker):
    stub = _make_pipeline_stub(mocker, SimpleContract)
    selectors = {
        'title': {'primary': 'h1'},
        'yosoi_container': {'primary': '.listing-item'},
    }
    result = stub._resolve_container(selectors)
    assert result == '.listing-item'
    assert 'yosoi_container' not in selectors


def test_resolve_container_returns_none_when_neither(mocker):
    stub = _make_pipeline_stub(mocker, SimpleContract)
    selectors = {'title': {'primary': 'h1'}}
    result = stub._resolve_container(selectors)
    assert result is None


# ---------------------------------------------------------------------------
# Pipeline._validate_with_contract — list support
# ---------------------------------------------------------------------------


def test_validate_with_contract_handles_list(mocker):
    stub = _make_pipeline_stub(mocker, SimpleContract)
    items = [
        {'title': 'Book A', 'price': '12.99'},
        {'title': 'Book B', 'price': '9.99'},
    ]
    result = stub._validate_with_contract(items, 'https://x.com')
    assert isinstance(result, list)
    assert len(result) == 2


def test_validate_with_contract_handles_single_dict(mocker):
    stub = _make_pipeline_stub(mocker, SimpleContract)
    extracted = {'title': 'Book A', 'price': '12.99'}
    result = stub._validate_with_contract(extracted, 'https://x.com')
    assert isinstance(result, dict)
    assert result['title'] == 'Book A'


# ---------------------------------------------------------------------------
# Pipeline._extract with container_selector
# ---------------------------------------------------------------------------


def test_extract_dispatches_to_extract_items_when_container(mocker):
    stub = _make_pipeline_stub(mocker, SimpleContract)
    stub.extractor = mocker.MagicMock()
    stub.extractor.extract_items.return_value = [{'title': 'A', 'price': '1'}]
    from yosoi.models.selectors import SelectorLevel

    stub.selector_level = SelectorLevel.CSS

    result = stub._extract('https://x.com', '<html></html>', {'title': {'primary': 'h1'}}, '.card')
    assert isinstance(result, list)
    stub.extractor.extract_items.assert_called_once()


def test_extract_falls_back_to_single_when_no_container(mocker):
    stub = _make_pipeline_stub(mocker, SimpleContract)
    stub.extractor = mocker.MagicMock()
    stub.extractor.extract_content_with_html.return_value = {'title': 'A'}
    from yosoi.models.selectors import SelectorLevel

    stub.selector_level = SelectorLevel.CSS

    result = stub._extract('https://x.com', '<html></html>', {'title': {'primary': 'h1'}})
    assert isinstance(result, dict)
    stub.extractor.extract_content_with_html.assert_called_once()


# ---------------------------------------------------------------------------
# scrape() — full pipeline stub helpers
# ---------------------------------------------------------------------------


def _make_scrape_stub(mocker, contract=None):
    """Create a Pipeline stub wired up for scrape() integration tests."""
    from yosoi.models.selectors import SelectorLevel

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
    stub.tracker.record_url.return_value = {'llm_calls': 0, 'url_count': 1}
    stub.debug = mocker.MagicMock()
    stub.debug_mode = False
    stub.output_formats = ['json']
    stub.force = False
    stub.selector_level = SelectorLevel.CSS

    # Stub normalize_url to pass through
    mocker.patch.object(stub, 'normalize_url', new=mocker.AsyncMock(side_effect=lambda u: u))
    return stub


# ---------------------------------------------------------------------------
# scrape() — cached fail-open (fetch fails after finding cached selectors)
# ---------------------------------------------------------------------------


async def test_scrape_cached_fail_open_yields_nothing(mocker):
    """When cached selectors exist but fetch fails, scrape() yields nothing
    and process_url() returns True (fail-open)."""
    stub = _make_scrape_stub(mocker)
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1'}}

    # Fetcher whose fetch() returns a failed result
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.__aenter__ = mocker.AsyncMock(return_value=mock_fetcher)
    mock_fetcher.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(url='https://example.com', html=None, is_blocked=True)
    )
    mocker.patch.object(stub, '_create_fetcher', return_value=mock_fetcher)

    items = [item async for item in stub.scrape('https://example.com')]
    assert items == []

    # process_url wrapper completes without raising (fail-open)
    await stub.process_url('https://example.com')


# ---------------------------------------------------------------------------
# scrape() — cached verification failure falls through to fresh discovery
# ---------------------------------------------------------------------------


async def test_scrape_cached_verification_failure_falls_through(mocker):
    """When cached selectors fail verification, scrape() falls through to
    the fresh discovery path."""
    from yosoi.models.results import FieldVerificationResult, VerificationResult

    stub = _make_scrape_stub(mocker)
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1.old'}}

    # Fetcher returns valid HTML
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.__aenter__ = mocker.AsyncMock(return_value=mock_fetcher)
    mock_fetcher.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(url='https://example.com', html='<html><h1>Hello</h1></html>')
    )
    mocker.patch.object(stub, '_create_fetcher', return_value=mock_fetcher)

    stub.cleaner.clean_html.return_value = '<h1>Hello</h1>'

    # Cached verification fails
    stub.verifier.verify.return_value = VerificationResult(
        total_fields=1,
        verified_count=0,
        results={
            'title': FieldVerificationResult(
                field_name='title', status='failed', matched_selector=None, failed_selectors=[]
            )
        },
    )

    # Fresh discovery returns new selectors
    stub.discovery.target_level = stub.selector_level
    stub.discovery.discover_selectors = mocker.AsyncMock(
        return_value={'title': {'primary': 'h1', 'fallback': None, 'tertiary': None}}
    )

    # After the first (cached) verification fails, the second (fresh) succeeds
    def verify_side_effect(html, selectors, max_level=None):
        if 'h1.old' in str(selectors):
            return VerificationResult(
                total_fields=1,
                verified_count=0,
                results={
                    'title': FieldVerificationResult(
                        field_name='title', status='failed', matched_selector=None, failed_selectors=[]
                    )
                },
            )
        return VerificationResult(
            total_fields=1,
            verified_count=1,
            results={
                'title': FieldVerificationResult(
                    field_name='title', status='verified', matched_selector='h1', failed_selectors=[]
                )
            },
        )

    stub.verifier.verify.side_effect = verify_side_effect

    stub.extractor.extract_content_with_html.return_value = {'title': 'Hello'}

    items = [item async for item in stub.scrape('https://example.com')]
    assert len(items) == 1
    assert items[0]['title'] == 'Hello'

    # Fetch called twice: once in cached path, once in fresh discovery via _fetch
    assert mock_fetcher.fetch.call_count == 2
    # AI discovery was called after cache miss
    assert stub.discovery.discover_selectors.call_count == 1


# ---------------------------------------------------------------------------
# scrape() — force=True skips cache
# ---------------------------------------------------------------------------


async def test_scrape_force_skips_cache(mocker):
    """When force=True, scrape() goes straight to fresh discovery even with
    cached selectors present."""
    from yosoi.models.results import FieldVerificationResult, VerificationResult

    stub = _make_scrape_stub(mocker)
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1.cached'}}

    mock_fetcher = mocker.MagicMock()
    mock_fetcher.__aenter__ = mocker.AsyncMock(return_value=mock_fetcher)
    mock_fetcher.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(url='https://example.com', html='<html><h1>Fresh</h1></html>')
    )
    mocker.patch.object(stub, '_create_fetcher', return_value=mock_fetcher)

    stub.cleaner.clean_html.return_value = '<h1>Fresh</h1>'

    stub.discovery.target_level = stub.selector_level
    stub.discovery.discover_selectors = mocker.AsyncMock(
        return_value={'title': {'primary': 'h1', 'fallback': None, 'tertiary': None}}
    )

    stub.verifier.verify.return_value = VerificationResult(
        total_fields=1,
        verified_count=1,
        results={
            'title': FieldVerificationResult(
                field_name='title', status='verified', matched_selector='h1', failed_selectors=[]
            )
        },
    )

    stub.extractor.extract_content_with_html.return_value = {'title': 'Fresh'}

    items = [item async for item in stub.scrape('https://example.com', force=True)]
    assert len(items) == 1
    assert items[0]['title'] == 'Fresh'

    # load_selectors should NOT have been consulted (force skips cache)
    stub.storage.load_selectors.assert_not_called()
    # AI discovery was called
    assert stub.discovery.discover_selectors.call_count == 1


# ---------------------------------------------------------------------------
# scrape() — last_elapsed is set correctly
# ---------------------------------------------------------------------------


async def test_scrape_sets_last_elapsed(mocker):
    """After scrape() completes, last_elapsed is a positive float."""
    stub = _make_scrape_stub(mocker)
    stub.storage.load_selectors.return_value = None  # no cache

    mock_fetcher = mocker.MagicMock()
    mock_fetcher.__aenter__ = mocker.AsyncMock(return_value=mock_fetcher)
    mock_fetcher.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(url='https://example.com', html='<html><h1>Test</h1></html>')
    )
    mocker.patch.object(stub, '_create_fetcher', return_value=mock_fetcher)

    stub.cleaner.clean_html.return_value = '<h1>Test</h1>'

    from yosoi.models.results import FieldVerificationResult, VerificationResult

    stub.discovery.target_level = stub.selector_level
    stub.discovery.discover_selectors = mocker.AsyncMock(
        return_value={'title': {'primary': 'h1', 'fallback': None, 'tertiary': None}}
    )
    stub.verifier.verify.return_value = VerificationResult(
        total_fields=1,
        verified_count=1,
        results={
            'title': FieldVerificationResult(
                field_name='title', status='verified', matched_selector='h1', failed_selectors=[]
            )
        },
    )
    stub.extractor.extract_content_with_html.return_value = {'title': 'Test'}

    async for _ in stub.scrape('https://example.com'):
        pass

    assert hasattr(stub, 'last_elapsed')
    assert isinstance(stub.last_elapsed, float)
    assert stub.last_elapsed >= 0
