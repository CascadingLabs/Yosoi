"""Tests for ActionPlanDiscoveryAgent — constructor + happy-path mocking.

The LLM round-trip is mocked: we verify that the agent stitches its emitted
A3Nodes into a ReplayPlan with the right target/task/source, and that failures
from the underlying pydantic-ai Agent surface as LLMGenerationError. Mirrors
the established pattern used by ``test_field_agent.py``.
"""

from __future__ import annotations

import pytest

from yosoi.models.replay import ReplayPlan, click_until, css, selector_absent
from yosoi.utils.exceptions import LLMGenerationError


def _llm_config():
    from yosoi.core.discovery.config import LLMConfig

    return LLMConfig(provider='test', model_name='test-model', api_key='fake')


def test_agent_constructs_and_exposes_provider(mocker):
    """The constructor wires through provider + model_name and creates an Agent."""
    mocker.patch('yosoi.core.discovery.action_plan_agent.create_model')
    mocker.patch('yosoi.core.discovery.action_plan_agent.Agent')

    from yosoi.core.discovery.action_plan_agent import ActionPlanDiscoveryAgent

    agent = ActionPlanDiscoveryAgent(_llm_config())
    assert agent.provider == 'test'
    assert agent.model_name == 'test-model'


@pytest.mark.asyncio
async def test_discover_plan_stitches_nodes_into_replay_plan(mocker):
    """Agent's emitted nodes wrap into a ReplayPlan with the caller's target/task."""
    from yosoi.core.discovery import action_plan_agent as mod

    # Stub pydantic-ai: replace the Agent class with one whose .run returns a
    # candidate carrying a representative click_until node — the same shape the
    # real LLM would emit for reddit's load-more.
    load_more = css('faceplate-partial[src*="more-comments"] button')
    candidate = mod._PlanCandidate(
        nodes=[
            click_until(
                load_more,
                expect=selector_absent(css('faceplate-partial[src*="more-comments"]')),
                max_iters=40,
                intent='expand every more-comments partial until none remain',
            ),
        ]
    )

    class _FakeRun:
        def __init__(self, output):
            self.output = output

    class _FakeAgent:
        def __init__(self, *a, **kw):
            pass

        def system_prompt(self, fn):  # the agent registers prompt fns at __init__
            return fn

        async def run(self, *a, **kw):
            return _FakeRun(candidate)

    mocker.patch.object(mod, 'create_model')
    mocker.patch.object(mod, 'Agent', _FakeAgent)

    agent = mod.ActionPlanDiscoveryAgent(_llm_config())
    plan = await agent.discover_plan(
        target='reddit.com/r/ted/post',
        intent='load every public comment on the post',
        html='<html><body><faceplate-partial src="/more-comments/..."></faceplate-partial></body></html>',
    )

    assert isinstance(plan, ReplayPlan)
    assert plan.target == 'reddit.com/r/ted/post'
    assert plan.task == 'load every public comment on the post'
    assert plan.source == 'scripted'
    assert len(plan.nodes) == 1
    node = plan.nodes[0]
    assert getattr(node, 'repeat', False) is True
    assert node.expect is not None  # type: ignore[union-attr]
    assert node.expect.kind == 'selector_absent'  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_discover_plan_empty_plan_is_valid_output(mocker):
    """An empty plan (no actions needed) is a valid response — wraps to ReplayPlan with zero nodes."""
    from yosoi.core.discovery import action_plan_agent as mod

    class _FakeRun:
        def __init__(self, output):
            self.output = output

    class _FakeAgent:
        def __init__(self, *a, **kw):
            pass

        def system_prompt(self, fn):
            return fn

        async def run(self, *a, **kw):
            return _FakeRun(mod._PlanCandidate(nodes=[]))

    mocker.patch.object(mod, 'create_model')
    mocker.patch.object(mod, 'Agent', _FakeAgent)

    agent = mod.ActionPlanDiscoveryAgent(_llm_config())
    plan = await agent.discover_plan(target='static.example.com', intent='', html='<html></html>')
    assert plan.nodes == []
    assert plan.task == ''


@pytest.mark.asyncio
async def test_discover_plan_wraps_underlying_errors_as_llm_generation_error(mocker):
    from yosoi.core.discovery import action_plan_agent as mod

    class _FakeAgent:
        def __init__(self, *a, **kw):
            pass

        def system_prompt(self, fn):
            return fn

        async def run(self, *a, **kw):
            raise RuntimeError('upstream went sideways')

    mocker.patch.object(mod, 'create_model')
    mocker.patch.object(mod, 'Agent', _FakeAgent)

    agent = mod.ActionPlanDiscoveryAgent(_llm_config())
    with pytest.raises(LLMGenerationError, match='Action plan discovery failed'):
        await agent.discover_plan(target='reddit.com/r/ted/post', intent='load every comment', html='<html/>')
