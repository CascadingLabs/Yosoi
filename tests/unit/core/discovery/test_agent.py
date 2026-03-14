import pytest
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel
from rich.console import Console

from yosoi.core.discovery.agent import SelectorDiscovery
from yosoi.models.defaults import NewsArticle


def test_selector_discovery_with_no_config_raises():
    with pytest.raises(ValueError, match='Either provide llm_config or agent'):
        SelectorDiscovery(contract=NewsArticle, llm_config=None, agent=None)


def test_selector_discovery_with_custom_agent():
    model = TestModel()
    SelectorModel = NewsArticle.to_selector_model()
    agent = Agent(model, output_type=SelectorModel)
    discovery = SelectorDiscovery(contract=NewsArticle, agent=agent, console=Console(quiet=True))
    assert discovery.model_name == 'custom-agent'
    assert discovery.provider == 'custom'


def test_agent_prompt_construction(mock_selectors):
    """Verify that the HTML input is formatted into the prompt correctly."""
    model = TestModel(custom_output_args=mock_selectors)

    SelectorModel = NewsArticle.to_selector_model()
    agent = Agent(model, output_type=SelectorModel)

    html_input = '<html><body><h1>Real Data</h1></body></html>'

    with capture_run_messages() as messages:
        result = agent.run_sync(f'Analyze this: {html_input}')

    assert isinstance(result.output, SelectorModel)
    # primary is now a SelectorEntry, not a plain string
    assert result.output.headline.primary.value == 'h1.title'  # type: ignore[attr-defined]

    user_msg = messages[0]
    full_content = ' '.join(
        part.content for part in user_msg.parts if hasattr(part, 'content') and isinstance(part.content, str)
    )
    assert 'Analyze this' in full_content
    assert 'Real Data' in full_content


def test_selector_discovery_with_custom_agent_model_name_is_custom():
    """When using custom agent, model_name must be 'custom-agent'."""
    model = TestModel()
    SelectorModel = NewsArticle.to_selector_model()
    agent = Agent(model, output_type=SelectorModel)
    discovery = SelectorDiscovery(contract=NewsArticle, agent=agent, console=Console(quiet=True))
    assert discovery.model_name == 'custom-agent'


def test_selector_discovery_with_custom_agent_provider_is_custom():
    """When using custom agent, provider must be 'custom'."""
    model = TestModel()
    SelectorModel = NewsArticle.to_selector_model()
    agent = Agent(model, output_type=SelectorModel)
    discovery = SelectorDiscovery(contract=NewsArticle, agent=agent, console=Console(quiet=True))
    assert discovery.provider == 'custom'


def test_selector_discovery_console_defaults_to_console():
    """When no console given, a Console instance should be created."""
    model = TestModel()
    SelectorModel = NewsArticle.to_selector_model()
    agent = Agent(model, output_type=SelectorModel)
    discovery = SelectorDiscovery(contract=NewsArticle, agent=agent)
    from rich.console import Console as RichConsole

    assert isinstance(discovery.console, RichConsole)


def test_selector_discovery_contract_is_stored():
    """The contract parameter must be stored as _contract."""
    model = TestModel()
    SelectorModel = NewsArticle.to_selector_model()
    agent = Agent(model, output_type=SelectorModel)
    discovery = SelectorDiscovery(contract=NewsArticle, agent=agent, console=Console(quiet=True))
    assert discovery._contract is NewsArticle


def test_selector_discovery_custom_agent_is_stored():
    """When custom agent is passed, it must be stored as self.agent."""
    model = TestModel()
    SelectorModel = NewsArticle.to_selector_model()
    agent = Agent(model, output_type=SelectorModel)
    discovery = SelectorDiscovery(contract=NewsArticle, agent=agent, console=Console(quiet=True))
    assert discovery.agent is agent


def test_selector_discovery_raises_valueerror_message():
    """ValueError message must be exact: 'Either provide llm_config or agent parameter'."""
    with pytest.raises(ValueError, match='Either provide llm_config or agent'):
        SelectorDiscovery(contract=NewsArticle, llm_config=None, agent=None)
