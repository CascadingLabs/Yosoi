"""Tests for FieldDiscoveryAgent."""

import pytest
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.field_agent import FieldDiscoveryAgent
from yosoi.models.selectors import FieldSelectors, SelectorLevel
from yosoi.prompts.discovery import DiscoveryInput
from yosoi.utils.exceptions import LLMGenerationError


@pytest.fixture
def llm_config():
    return LLMConfig(provider='groq', model_name='test-model', api_key='test-key', temperature=0.0)


@pytest.fixture
def discovery_input():
    return DiscoveryInput(url='https://example.com', html='<html><body><h1 class="title">Hello</h1></body></html>')


@pytest.fixture
def field_selectors():
    return FieldSelectors(primary='h1.title', fallback='h1', tertiary=None)


def test_field_discovery_agent_init(llm_config):
    agent = FieldDiscoveryAgent(llm_config, console=Console(quiet=True))
    assert agent.model_name == 'test-model'
    assert agent.provider == 'groq'


def test_field_discovery_agent_default_console(llm_config):
    from rich.console import Console as RichConsole

    agent = FieldDiscoveryAgent(llm_config)
    assert isinstance(agent.console, RichConsole)


@pytest.mark.anyio
async def test_discover_field_returns_field_selectors(llm_config, discovery_input, field_selectors, mocker):
    agent = FieldDiscoveryAgent(llm_config, console=Console(quiet=True))
    mock_result = mocker.MagicMock()
    mock_result.output = field_selectors
    mocker.patch.object(agent._agent, 'run', new=mocker.AsyncMock(return_value=mock_result))

    result = await agent.discover_field(
        field_name='headline',
        field_description='Main article title',
        field_hint=None,
        discovery_input=discovery_input,
        target_level=SelectorLevel.CSS,
    )
    assert result is not None
    assert result.primary.value == 'h1.title'


@pytest.mark.anyio
async def test_discover_field_returns_none_for_na_primary(llm_config, discovery_input, mocker):
    na_selectors = FieldSelectors(primary='NA')
    agent = FieldDiscoveryAgent(llm_config, console=Console(quiet=True))
    mock_result = mocker.MagicMock()
    mock_result.output = na_selectors
    mocker.patch.object(agent._agent, 'run', new=mocker.AsyncMock(return_value=mock_result))

    result = await agent.discover_field(
        field_name='headline',
        field_description='Main article title',
        field_hint=None,
        discovery_input=discovery_input,
        target_level=SelectorLevel.CSS,
    )
    assert result is None


@pytest.mark.anyio
async def test_discover_field_raises_llm_generation_error_on_exception(llm_config, discovery_input, mocker):
    agent = FieldDiscoveryAgent(llm_config, console=Console(quiet=True))
    mocker.patch.object(agent._agent, 'run', new=mocker.AsyncMock(side_effect=RuntimeError('LLM exploded')))

    with pytest.raises(LLMGenerationError, match='Field discovery failed'):
        await agent.discover_field(
            field_name='headline',
            field_description='Main article title',
            field_hint=None,
            discovery_input=discovery_input,
            target_level=SelectorLevel.CSS,
        )


@pytest.mark.anyio
async def test_discover_field_with_hint_passes_through(llm_config, discovery_input, field_selectors, mocker):
    agent = FieldDiscoveryAgent(llm_config, console=Console(quiet=True))
    mock_result = mocker.MagicMock()
    mock_result.output = field_selectors
    mock_run = mocker.AsyncMock(return_value=mock_result)
    mocker.patch.object(agent._agent, 'run', new=mock_run)

    result = await agent.discover_field(
        field_name='price',
        field_description='Product price',
        field_hint='Look for currency symbols',
        discovery_input=discovery_input,
        target_level=SelectorLevel.CSS,
    )
    assert result is not None
    mock_run.assert_called_once()
