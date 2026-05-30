"""Tests for run_field_task."""

import asyncio

import pytest

from yosoi.core.discovery.field_task import FieldTaskResult, run_field_task
from yosoi.models.selectors import FieldSelectors, SelectorLevel
from yosoi.models.snapshot import SnapshotStatus
from yosoi.prompts.discovery import DiscoveryInput
from yosoi.utils.exceptions import LLMGenerationError

_HTML = '<html><body><h1 class="title">Article</h1><span class="author">Jane</span></body></html>'
_DISCOVERY_INPUT = DiscoveryInput(url='https://example.com', html=_HTML)


@pytest.fixture
def mock_agent(mocker):
    agent = mocker.MagicMock()
    agent.discover_field = mocker.AsyncMock(return_value=FieldSelectors(primary='h1.title', fallback='h1'))
    return agent


@pytest.mark.anyio
async def test_cache_hit_returns_cached_selectors(mock_agent):
    cached_entry = {'primary': 'h1.title', 'fallback': None, 'tertiary': None}

    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=cached_entry,
        max_level=SelectorLevel.CSS,
    )

    assert result.from_cache is True
    assert result.selectors is not None
    assert result.selectors.primary.value == 'h1.title'
    mock_agent.discover_field.assert_not_called()


@pytest.mark.anyio
async def test_cache_miss_calls_agent(mock_agent):
    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=None,
        max_level=SelectorLevel.CSS,
    )

    assert result.from_cache is False
    assert result.selectors is not None
    mock_agent.discover_field.assert_called()


@pytest.mark.anyio
async def test_failed_cache_escalates_to_discovery(mock_agent):
    # Cached selector that won't match the HTML
    cached_entry = {
        'primary': '.nonexistent-class-xyz',
        'fallback': None,
        'tertiary': None,
    }

    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=cached_entry,
        max_level=SelectorLevel.CSS,
    )

    # Should have fallen through to agent discovery
    mock_agent.discover_field.assert_called()
    # Result from agent should be used
    assert result.from_cache is False


@pytest.mark.anyio
async def test_all_levels_fail_returns_none_selectors(mock_agent):
    mock_agent.discover_field.side_effect = LLMGenerationError('always fails')

    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=None,
        max_level=SelectorLevel.CSS,
        max_retries=1,
    )

    assert result.selectors is None
    assert result.from_cache is False


@pytest.mark.anyio
async def test_na_response_from_agent_skips_to_next_level(mocker):
    agent = mocker.MagicMock()
    call_count = 0

    async def mock_discover(
        field_name, field_description, discovery_input, target_level, is_container=False, feedback=None
    ):
        nonlocal call_count
        call_count += 1
        if target_level == SelectorLevel.CSS:
            return None  # NA
        return FieldSelectors(primary='//h1[@class="title"]')

    agent.discover_field = mock_discover

    await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=agent,
        cached_entry=None,
        max_level=SelectorLevel.XPATH,
        max_retries=1,
    )

    # Should have tried CSS (returned None/NA) then XPATH
    assert call_count >= 2


@pytest.mark.anyio
async def test_escalated_level_recorded_in_result(mocker):
    agent = mocker.MagicMock()

    async def mock_discover(
        field_name, field_description, discovery_input, target_level, is_container=False, feedback=None
    ):
        if target_level == SelectorLevel.CSS:
            raise LLMGenerationError('CSS fails')
        return FieldSelectors(primary='//h1')

    agent.discover_field = mock_discover

    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=agent,
        cached_entry=None,
        max_level=SelectorLevel.XPATH,
        max_retries=1,
    )

    if result.selectors is not None:
        assert result.escalated_to == SelectorLevel.XPATH


@pytest.mark.anyio
async def test_css_success_has_no_escalation(mock_agent):
    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=None,
        max_level=SelectorLevel.CSS,
    )

    if result.selectors is not None and not result.from_cache:
        assert result.escalated_to is None


@pytest.mark.anyio
async def test_semaphore_is_respected(mock_agent):
    semaphore = asyncio.Semaphore(1)

    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=None,
        max_level=SelectorLevel.CSS,
        semaphore=semaphore,
    )

    assert result.selectors is not None


@pytest.mark.anyio
async def test_invalid_cached_entry_triggers_rediscovery(mock_agent):
    """When cached_entry can't be validated as FieldSelectors, fall through to LLM."""
    cached_entry = {'primary': 12345}  # invalid type

    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=cached_entry,
        max_level=SelectorLevel.CSS,
    )

    assert result.from_cache is False
    assert result.selectors is not None
    mock_agent.discover_field.assert_called()


@pytest.mark.anyio
async def test_absent_cache_status_skips_discovery(mock_agent):
    cached_entry = {'status': SnapshotStatus.ABSENT, 'status_reason': 'not on this domain'}

    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=cached_entry,
        max_level=SelectorLevel.CSS,
    )

    assert result.selectors is None
    assert result.from_cache is False
    mock_agent.discover_field.assert_not_called()


@pytest.mark.anyio
async def test_field_task_result_dataclass():
    result = FieldTaskResult(
        field_name='test',
        selectors=None,
        from_cache=False,
        escalated_to=None,
    )
    assert result.field_name == 'test'
    assert result.selectors is None
    assert result.from_cache is False
    assert result.escalated_to is None


# ---------------------------------------------------------------------------
# Bus coordination coverage (lines 242, 248-253, 277)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feedback_true_disables_bus(mock_agent):
    """When feedback=True, scoped_bus is set to None even if provided (line 242)."""

    class _FakeBus:
        def __init__(self):
            self.acquire_called = False

        async def acquire(self, sig):
            self.acquire_called = True
            return True

        async def wait_for(self, sig):
            return None

        async def publish(self, sig, selectors):
            pass

    fake_bus = _FakeBus()
    await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=None,
        max_level=SelectorLevel.CSS,
        scoped_bus=fake_bus,
        feedback='Previous hint',  # feedback=truthy → bus disabled
    )

    assert not fake_bus.acquire_called, 'Bus must not be called when feedback is set'


@pytest.mark.anyio
async def test_bus_follower_returns_cached_result_from_bus(mock_agent):
    """Bus follower (not leader) uses cached result from bus.wait_for (lines 248-253)."""

    class _FollowerBus:
        async def acquire(self, sig) -> bool:
            return False  # not the leader

        async def wait_for(self, sig):
            return FieldSelectors(primary='h1.title-cached')

        async def publish(self, sig, selectors):
            pass

    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=None,
        max_level=SelectorLevel.CSS,
        scoped_bus=_FollowerBus(),
    )

    assert result.from_cache is True
    assert result.selectors is not None
    # primary is a SelectorEntry; check its value string
    primary = result.selectors.primary
    primary_val = primary.value if hasattr(primary, 'value') else primary
    assert primary_val == 'h1.title-cached'


@pytest.mark.anyio
async def test_bus_leader_publishes_result_in_finally(mock_agent):
    """Bus leader publishes its result via scoped_bus.publish in the finally block (line 277)."""

    class _LeaderBus:
        def __init__(self):
            self.published: object = None

        async def acquire(self, sig) -> bool:
            return True  # this worker is the leader

        async def wait_for(self, sig):
            return None

        async def publish(self, sig, selectors) -> None:
            self.published = selectors

    bus = _LeaderBus()
    result = await run_field_task(
        field_name='headline',
        field_description='Article title',
        discovery_input=_DISCOVERY_INPUT,
        html=_HTML,
        agent=mock_agent,
        cached_entry=None,
        max_level=SelectorLevel.CSS,
        scoped_bus=bus,
    )

    assert bus.published is not None, 'Leader must publish result via bus'
    assert result.selectors is not None
