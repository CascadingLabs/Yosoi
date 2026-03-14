import logging

import pytest
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel
from rich.console import Console

from yosoi.core.discovery.agent import SelectorDiscovery, _extract_provider_error
from yosoi.core.discovery.yosoi_agent import YosoiAgent
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.selectors import SelectorLevel


def _make_yosoi_agent() -> YosoiAgent:
    return YosoiAgent(TestModel(), contract=NewsArticle)


def test_selector_discovery_with_no_config_raises():
    with pytest.raises(ValueError, match='Either provide llm_config or agent'):
        SelectorDiscovery(contract=NewsArticle, llm_config=None, agent=None)


def test_selector_discovery_with_custom_agent():
    discovery = SelectorDiscovery(contract=NewsArticle, agent=_make_yosoi_agent(), console=Console(quiet=True))
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
    discovery = SelectorDiscovery(contract=NewsArticle, agent=_make_yosoi_agent(), console=Console(quiet=True))
    assert discovery.model_name == 'custom-agent'


def test_selector_discovery_with_custom_agent_provider_is_custom():
    """When using custom agent, provider must be 'custom'."""
    discovery = SelectorDiscovery(contract=NewsArticle, agent=_make_yosoi_agent(), console=Console(quiet=True))
    assert discovery.provider == 'custom'


def test_selector_discovery_console_defaults_to_console():
    """When no console given, a Console instance should be created."""
    discovery = SelectorDiscovery(contract=NewsArticle, agent=_make_yosoi_agent())
    from rich.console import Console as RichConsole

    assert isinstance(discovery.console, RichConsole)


def test_selector_discovery_contract_is_stored():
    """The contract parameter must be stored as _contract."""
    discovery = SelectorDiscovery(contract=NewsArticle, agent=_make_yosoi_agent(), console=Console(quiet=True))
    assert discovery._contract is NewsArticle


def test_selector_discovery_custom_agent_is_stored():
    """When YosoiAgent is passed, it must be stored as self._yosoi_agent."""
    yosoi_agent = _make_yosoi_agent()
    discovery = SelectorDiscovery(contract=NewsArticle, agent=yosoi_agent, console=Console(quiet=True))
    assert discovery._yosoi_agent is yosoi_agent


def test_selector_discovery_raises_valueerror_message():
    """ValueError message must be exact: 'Either provide llm_config or agent parameter'."""
    with pytest.raises(ValueError, match='Either provide llm_config or agent'):
        SelectorDiscovery(contract=NewsArticle, llm_config=None, agent=None)


def test_yosoi_agent_derives_output_type_from_contract():
    """YosoiAgent should internally derive output_type from the contract."""
    agent = _make_yosoi_agent()
    assert agent.inner.output_type.__name__ == NewsArticle.to_selector_model().__name__


def test_yosoi_agent_inner_has_system_prompt():
    """YosoiAgent with system_prompt should pass it to the inner agent."""
    agent = YosoiAgent(TestModel(), contract=NewsArticle, system_prompt='Find selectors.')
    assert agent.inner is not None


# ---------------------------------------------------------------------------
# _extract_provider_error — pure function tests
# ---------------------------------------------------------------------------


def test_extract_provider_error_finds_body_message():
    """Exception with .body={'error': {'message': ...}} returns the message."""
    exc = Exception('wrapper')
    exc.body = {'error': {'message': 'rate limit exceeded'}}  # type: ignore[attr-defined]
    assert _extract_provider_error(exc) == 'rate limit exceeded'


def test_extract_provider_error_returns_none_for_plain_exception():
    """Plain ValueError without body attr returns None."""
    assert _extract_provider_error(ValueError('plain')) is None


def test_extract_provider_error_walks_cause_chain():
    """Walks __cause__ chain to find body on inner exception."""
    inner = Exception('inner')
    inner.body = {'error': {'message': 'from inner'}}  # type: ignore[attr-defined]
    outer = Exception('outer')
    outer.__cause__ = inner
    assert _extract_provider_error(outer) == 'from inner'


# ---------------------------------------------------------------------------
# _is_all_na — pure method tests
# ---------------------------------------------------------------------------


def test_is_all_na_true_when_all_na():
    """All fields NA (ignoring yosoi_container) returns True."""
    discovery = SelectorDiscovery(contract=NewsArticle, agent=_make_yosoi_agent(), console=Console(quiet=True))
    selectors = {
        'headline': {'primary': 'NA'},
        'yosoi_container': {'primary': '.items'},
    }
    assert discovery._is_all_na(selectors) is True


def test_is_all_na_false_when_valid_selector():
    """A real selector value makes _is_all_na return False."""
    discovery = SelectorDiscovery(contract=NewsArticle, agent=_make_yosoi_agent(), console=Console(quiet=True))
    selectors = {'headline': {'primary': 'h1.title'}}
    assert discovery._is_all_na(selectors) is False


# ---------------------------------------------------------------------------
# Contract mismatch
# ---------------------------------------------------------------------------


class _OtherContract(Contract):
    title: str


def test_contract_mismatch_raises_valueerror():
    """Passing an agent built with a different contract raises ValueError."""
    agent = _make_yosoi_agent()  # built with NewsArticle
    with pytest.raises(ValueError, match='Contract mismatch'):
        SelectorDiscovery(contract=_OtherContract, agent=agent, console=Console(quiet=True))


# ---------------------------------------------------------------------------
# target_level warning with custom agent
# ---------------------------------------------------------------------------


def test_target_level_warning_with_custom_agent(caplog):
    """Non-default target_level with custom agent logs a warning."""
    with caplog.at_level(logging.WARNING, logger='yosoi.core.discovery.agent'):
        SelectorDiscovery(
            contract=NewsArticle,
            agent=_make_yosoi_agent(),
            console=Console(quiet=True),
            target_level=SelectorLevel.XPATH,
        )
    assert 'has no effect with custom agents' in caplog.text
