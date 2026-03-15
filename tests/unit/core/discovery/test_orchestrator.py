"""Tests for DiscoveryOrchestrator."""

import pytest
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.orchestrator import DiscoveryOrchestrator
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.selectors import FieldSelectors, SelectorLevel
from yosoi.storage.persistence import SelectorStorage

_HTML = """
<html><body>
  <h1 class="title">Article Title</h1>
  <span class="author">Jane Doe</span>
  <time class="date">2024-01-01</time>
  <article class="body">Content here.</article>
  <div class="related">Related links</div>
</body></html>
"""


@pytest.fixture
def llm_config():
    return LLMConfig(provider='groq', model_name='test-model', api_key='test-key', temperature=0.0)


@pytest.fixture
def mock_storage(mocker, tmp_path):
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir()
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    return SelectorStorage()


@pytest.fixture
def orchestrator(llm_config, mock_storage):
    return DiscoveryOrchestrator(
        contract=NewsArticle,
        llm_config=llm_config,
        storage=mock_storage,
        console=Console(quiet=True),
        target_level=SelectorLevel.CSS,
    )


def _make_field_selectors(value: str) -> FieldSelectors:
    return FieldSelectors(primary=value)


@pytest.mark.anyio
async def test_discover_selectors_returns_selector_map(orchestrator, mocker):
    field_results = {
        'headline': FieldSelectors(primary='h1.title'),
        'author': FieldSelectors(primary='span.author'),
        'date': FieldSelectors(primary='time.date'),
        'body_text': FieldSelectors(primary='article.body'),
        'related_content': FieldSelectors(primary='div.related'),
        'root': None,
    }

    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        sel = field_results.get(name)
        return FieldTaskResult(field_name=name, selectors=sel, from_cache=False, escalated_to=None)

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)

    result = await orchestrator.discover_selectors(_HTML, 'https://example.com')

    assert result is not None
    assert 'headline' in result
    assert 'author' in result


@pytest.mark.anyio
async def test_discover_selectors_returns_none_when_all_fields_fail(orchestrator, mocker):
    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        return FieldTaskResult(
            field_name=kwargs['field_name'],
            selectors=None,
            from_cache=False,
            escalated_to=None,
        )

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)

    result = await orchestrator.discover_selectors(_HTML, 'https://example.com')
    assert result is None


@pytest.mark.anyio
async def test_discover_selectors_partial_results_preserved(orchestrator, mocker):
    """asyncio.gather partial failures should not discard successful fields."""

    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        if name == 'headline':
            return FieldTaskResult(
                field_name=name, selectors=FieldSelectors(primary='h1.title'), from_cache=False, escalated_to=None
            )
        return FieldTaskResult(field_name=name, selectors=None, from_cache=False, escalated_to=None)

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)

    result = await orchestrator.discover_selectors(_HTML, 'https://example.com')
    assert result is not None
    assert 'headline' in result
    assert 'author' not in result


@pytest.mark.anyio
async def test_cached_fields_counted_correctly(orchestrator, mocker):
    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        is_cache = name == 'headline'
        sel = FieldSelectors(primary='h1') if name != 'root' else None
        return FieldTaskResult(field_name=name, selectors=sel, from_cache=is_cache, escalated_to=None)

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)

    result = await orchestrator.discover_selectors(_HTML, 'https://example.com')
    assert result is not None


@pytest.mark.anyio
async def test_target_level_property_settable(orchestrator):
    orchestrator.target_level = SelectorLevel.XPATH
    assert orchestrator.target_level == SelectorLevel.XPATH


@pytest.mark.anyio
async def test_all_fields_overridden_skips_ai(llm_config, mock_storage, mocker):
    class OverriddenContract(Contract):
        title: str

    # Patch the contract to say all fields are overridden
    mocker.patch.object(
        OverriddenContract,
        'field_descriptions',
        return_value={},
    )
    mocker.patch.object(
        OverriddenContract,
        'get_selector_overrides',
        return_value={'title': {'primary': 'h1'}},
    )

    orchestrator = DiscoveryOrchestrator(
        contract=OverriddenContract,
        llm_config=llm_config,
        storage=mock_storage,
        console=Console(quiet=True),
    )
    run_task_spy = mocker.patch('yosoi.core.discovery.orchestrator.run_field_task')

    result = await orchestrator.discover_selectors(_HTML)

    run_task_spy.assert_not_called()
    assert result is not None
    assert 'title' in result


@pytest.mark.anyio
async def test_save_selectors_called_with_url(orchestrator, mocker):
    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        sel = FieldSelectors(primary='h1') if name != 'root' else None
        return FieldTaskResult(field_name=name, selectors=sel, from_cache=False, escalated_to=None)

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)
    save_spy = mocker.patch.object(orchestrator._storage, 'save_selectors')

    await orchestrator.discover_selectors(_HTML, 'https://example.com/article')

    save_spy.assert_called_once()
    call_url = save_spy.call_args[0][0]
    assert call_url == 'https://example.com/article'


@pytest.mark.anyio
async def test_save_selectors_not_called_without_url(orchestrator, mocker):
    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        sel = FieldSelectors(primary='h1') if name != 'root' else None
        return FieldTaskResult(field_name=name, selectors=sel, from_cache=False, escalated_to=None)

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)
    save_spy = mocker.patch.object(orchestrator._storage, 'save_selectors')

    await orchestrator.discover_selectors(_HTML)

    save_spy.assert_not_called()


@pytest.mark.anyio
async def test_storage_read_called_once_not_per_field(orchestrator, mocker):
    """load_selectors must be called exactly once, not N times (one per field)."""

    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        sel = FieldSelectors(primary='h1') if name != 'root' else None
        return FieldTaskResult(field_name=name, selectors=sel, from_cache=False, escalated_to=None)

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)
    load_spy = mocker.patch.object(orchestrator._storage, 'load_selectors', return_value={})

    await orchestrator.discover_selectors(_HTML, 'https://example.com')

    load_spy.assert_called_once()


@pytest.mark.anyio
async def test_pinned_root_included_in_orchestrator_save(llm_config, mock_storage, mocker):
    """When the contract has a pinned root, the orchestrator must persist it in
    the cache so the saved selector map is self-contained."""
    import yosoi as ys

    class ListingContract(Contract):
        root = ys.css('.product-card')
        title: str = ys.Title()

    orchestrator = DiscoveryOrchestrator(
        contract=ListingContract,
        llm_config=llm_config,
        storage=mock_storage,
        console=Console(quiet=True),
    )

    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        return FieldTaskResult(
            field_name=name, selectors=FieldSelectors(primary='h1'), from_cache=False, escalated_to=None
        )

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)
    save_spy = mocker.patch.object(mock_storage, 'save_selectors')

    result = await orchestrator.discover_selectors(_HTML, 'https://example.com')

    assert result is not None
    # root must be present in FieldSelectors-wrapped format so _format_selectors persists it correctly
    assert 'root' in result
    assert result['root']['primary']['type'] == 'css'
    assert result['root']['primary']['value'] == '.product-card'

    # The map passed to save_selectors must also include root in the same format
    assert save_spy.called
    saved_map = save_spy.call_args[0][1]
    assert 'root' in saved_map
    assert saved_map['root']['primary']['value'] == '.product-card'


@pytest.mark.anyio
async def test_orchestrator_field_descriptions_flat_nested(llm_config, mock_storage):
    """field_descriptions() returns flat {parent}_{child} keys for nested contracts."""
    import yosoi as ys

    class _SubPrice(ys.Contract):
        amount: float = ys.Price()
        currency: str = ys.Field(description='Currency symbol')

    class _NestedProduct(ys.Contract):
        root = ys.css('.product-card')
        name: str = ys.Title()
        price: _SubPrice = ys.Field(description='Price info')  # type: ignore[assignment]

    descs = _NestedProduct.field_descriptions()
    assert 'name' in descs
    assert 'price_amount' in descs
    assert 'price_currency' in descs
    assert 'price' not in descs


@pytest.mark.anyio
async def test_orchestrator_adds_discover_task_for_auto_root(llm_config, mock_storage, mocker):
    """When a nested child has root = ys.discover(), a {parent}_root task is added."""
    import yosoi as ys

    class _AutoPrice(ys.Contract):
        root = ys.discover()
        amount: float = ys.Price()
        currency: str = ys.Field(description='Currency symbol')

    class _AutoProduct(ys.Contract):
        root = ys.css('.product-card')
        name: str = ys.Title()
        price: _AutoPrice = ys.Field(description='Price info')  # type: ignore[assignment]

    orch = DiscoveryOrchestrator(
        contract=_AutoProduct,
        llm_config=llm_config,
        storage=mock_storage,
        console=Console(quiet=True),
    )

    captured_specs: list[str] = []

    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        captured_specs.append(name)
        return FieldTaskResult(
            field_name=name, selectors=FieldSelectors(primary='h1'), from_cache=False, escalated_to=None
        )

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)

    await orch.discover_selectors(_HTML, 'https://example.com')

    assert 'price_root' in captured_specs


@pytest.mark.anyio
async def test_gather_exception_is_handled_gracefully(orchestrator, mocker):
    """When asyncio.gather returns a BaseException, the orchestrator logs and skips it."""
    call_count = 0

    async def mock_run_field_task(**kwargs):
        nonlocal call_count
        call_count += 1
        name = kwargs['field_name']
        if name == 'headline':
            raise RuntimeError('unexpected crash')
        from yosoi.core.discovery.field_task import FieldTaskResult

        sel = FieldSelectors(primary='h1') if name != 'root' else None
        return FieldTaskResult(field_name=name, selectors=sel, from_cache=False, escalated_to=None)

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)

    result = await orchestrator.discover_selectors(_HTML, 'https://example.com')
    # Should still return partial results (other fields succeeded)
    assert result is not None
    assert 'headline' not in result


@pytest.mark.anyio
async def test_escalated_count_tracked(orchestrator, mocker):
    """Escalated fields are counted in the orchestrator result."""
    from yosoi.models.selectors import SelectorLevel as SL

    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        if name == 'headline':
            return FieldTaskResult(
                field_name=name, selectors=FieldSelectors(primary='//h1'), from_cache=False, escalated_to=SL.XPATH
            )
        sel = FieldSelectors(primary='span') if name != 'root' else None
        return FieldTaskResult(field_name=name, selectors=sel, from_cache=False, escalated_to=None)

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)

    result = await orchestrator.discover_selectors(_HTML, 'https://example.com')
    assert result is not None
    assert 'headline' in result


@pytest.mark.anyio
async def test_stale_fields_filters_task_specs(orchestrator, mocker):
    """When stale_fields is provided, only those fields are discovered and save is skipped."""
    captured_fields: list[str] = []

    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        captured_fields.append(name)
        return FieldTaskResult(
            field_name=name, selectors=FieldSelectors(primary='h1'), from_cache=False, escalated_to=None
        )

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)
    save_spy = mocker.patch.object(orchestrator._storage, 'save_selectors')

    result = await orchestrator.discover_selectors(_HTML, 'https://example.com', stale_fields={'headline'})

    assert result is not None
    # Only 'headline' should have been processed
    assert 'headline' in captured_fields
    assert 'author' not in captured_fields
    # save_selectors should NOT be called for partial rediscovery
    save_spy.assert_not_called()


@pytest.mark.anyio
async def test_stale_cache_not_resurrected(orchestrator, mock_storage, mocker):
    """Merged map must use task results only — stale cache entries must not appear."""
    # Pre-populate cache with a stale entry for 'author'
    mock_storage.save_selectors('https://example.com', {'author': {'primary': '.stale-author'}})

    async def mock_run_field_task(**kwargs):
        from yosoi.core.discovery.field_task import FieldTaskResult

        name = kwargs['field_name']
        if name == 'headline':
            return FieldTaskResult(
                field_name=name, selectors=FieldSelectors(primary='h1'), from_cache=False, escalated_to=None
            )
        # All other fields fail (including 'author' which is in cache but fails inline verify)
        return FieldTaskResult(field_name=name, selectors=None, from_cache=False, escalated_to=None)

    mocker.patch('yosoi.core.discovery.orchestrator.run_field_task', new=mock_run_field_task)

    result = await orchestrator.discover_selectors(_HTML, 'https://example.com')

    # 'author' must NOT appear — its task returned None regardless of cache
    assert result is not None
    assert 'headline' in result
    assert 'author' not in result
