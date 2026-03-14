"""Tests for yosoi.core.discovery.yosoi_agent — YosoiAgent wrapper."""

import pytest
from pydantic_ai.models.test import TestModel

import yosoi as ys
from yosoi.core.discovery.yosoi_agent import YosoiAgent
from yosoi.models.contract import Contract
from yosoi.prompts.discovery import DiscoveryInput


class SimpleContract(Contract):
    """Simple contract for testing."""

    title: str = ys.Title()


class TestYosoiAgentInit:
    def test_creates_agent_with_system_prompt(self):
        """YosoiAgent with system_prompt sets it on the inner agent."""
        model = TestModel()
        agent = YosoiAgent(model, contract=SimpleContract, system_prompt='Find selectors.')
        assert agent.inner is not None

    def test_creates_agent_without_system_prompt(self):
        """YosoiAgent without system_prompt creates agent without one."""
        model = TestModel()
        agent = YosoiAgent(model, contract=SimpleContract)
        assert agent.inner is not None

    def test_inner_property_returns_agent(self):
        """The inner property returns the underlying pydantic-ai Agent."""
        from pydantic_ai import Agent

        model = TestModel()
        agent = YosoiAgent(model, contract=SimpleContract)
        assert isinstance(agent.inner, Agent)


# ---------------------------------------------------------------------------
# Coverage: lines 47-48 — YosoiAgent.run method
# ---------------------------------------------------------------------------


class TestYosoiAgentRun:
    @pytest.mark.asyncio
    async def test_run_calls_inner_agent(self, mocker):
        """YosoiAgent.run serializes DiscoveryInput and calls the inner agent."""
        model = TestModel()
        agent = YosoiAgent(model, contract=SimpleContract, system_prompt='Find selectors.')

        mock_result = mocker.MagicMock()
        mocker.patch.object(agent._agent, 'run', return_value=mock_result)

        discovery_input = DiscoveryInput(url='https://example.com', html='<h1>Title</h1>')
        result = await agent.run(discovery_input)

        agent._agent.run.assert_called_once()
        assert result is mock_result


# ---------------------------------------------------------------------------
# Coverage: line 52 — YosoiAgent.run_sync method
# ---------------------------------------------------------------------------


class TestYosoiAgentRunSync:
    def test_run_sync_calls_run(self, mocker):
        """YosoiAgent.run_sync is a synchronous wrapper around run."""
        model = TestModel()
        agent = YosoiAgent(model, contract=SimpleContract)

        mock_result = mocker.MagicMock()
        mocker.patch('asyncio.run', return_value=mock_result)

        discovery_input = DiscoveryInput(url='https://example.com', html='<h1>Title</h1>')
        result = agent.run_sync(discovery_input)

        assert result is mock_result
