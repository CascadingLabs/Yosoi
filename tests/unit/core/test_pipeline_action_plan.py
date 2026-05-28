"""Integration test for the Pipeline → ActionPlanStorage → ActionPlanDiscoveryAgent
→ replay-runtime wiring.

The end-to-end loop (discover → cache → replay) is verified against a fake
fetcher + fake page. No LLM is invoked: we monkeypatch ActionPlanDiscoveryAgent
to return a representative reddit-shape plan on the discovery path, and we
seed ActionPlanStorage to test the replay path independently.
"""

from __future__ import annotations

import pytest

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.models.replay import (
    ReplayPlan,
    click_until,
    css,
    selector_absent,
)
from yosoi.storage.action_plan import ActionPlanStorage


class _SimpleContract(ys.Contract):
    title: str = ys.Title()


def _make_pipeline_stub(mocker):
    """Action-plan tests only touch ``_derive_action_intent`` + ``_build_prepare_page``.
    The shared full stub is overkill but cheap — keep tests simple."""
    from tests.unit.core.conftest import make_pipeline_stub

    return make_pipeline_stub(mocker, contract=_SimpleContract)


def test_derive_intent_mentions_contract_name_and_fields(mocker):
    stub = _make_pipeline_stub(mocker)
    intent = Pipeline._derive_action_intent(stub)
    assert '_SimpleContract' in intent
    # The intent guides the LLM toward click_until + selector_absent termination.
    assert 'click them until no more remain' in intent
    assert 'selector_absent' in intent
    assert 'empty plan' in intent.lower()


@pytest.mark.asyncio
async def test_prepare_page_replays_cached_plan_without_invoking_llm(mocker, tmp_path):
    """When ActionPlanStorage has a cached plan, the hook executes it and returns.

    The LLM agent must NOT be constructed in this path — that's the whole
    point of the cache. We verify by patching ActionPlanDiscoveryAgent to a
    sentinel that would raise if called.
    """
    stub = _make_pipeline_stub(mocker)

    # Seed the storage with a representative reddit plan keyed by (domain, contract).
    storage = ActionPlanStorage(storage_dir=tmp_path)
    target_key = 'reddit.com/_SimpleContract'
    plan = ReplayPlan(
        target=target_key,
        task='load every comment',
        source='scripted',
        nodes=[
            click_until(
                css('faceplate-partial[src*="more-comments"] button'),
                expect=selector_absent(css('faceplate-partial[src*="more-comments"]')),
                max_iters=20,
            ),
        ],
    )
    storage.save(plan)

    # Point Pipeline's hook at our tmp_path storage by patching at the module level.
    mocker.patch('yosoi.core.pipeline.ActionPlanStorage', return_value=storage)

    # Discovery must NOT happen on the cached path.
    sentinel_agent = mocker.patch('yosoi.core.pipeline.ActionPlanDiscoveryAgent')
    sentinel_agent.side_effect = AssertionError('LLM agent must not be invoked on cache hit')

    # Patch the executor so we don't need a real page.
    fake_execute = mocker.patch(
        'yosoi.core.pipeline._execute_action_plan',
        new=mocker.AsyncMock(return_value=mocker.MagicMock(score=1.0)),
    )

    hook = Pipeline._build_prepare_page(stub, 'https://www.reddit.com/r/ted/comments/abc')
    assert hook is not None

    # Run the hook against any object — the executor is mocked.
    fake_tab = mocker.MagicMock()
    await hook(fake_tab)

    sentinel_agent.assert_not_called()  # cache hit → no LLM
    fake_execute.assert_awaited_once()  # but the plan WAS executed
    executed_plan = fake_execute.await_args.args[0]
    assert executed_plan.target == target_key


@pytest.mark.asyncio
async def test_prepare_page_discovers_and_persists_on_cache_miss(mocker, tmp_path):
    """First visit: cache empty → run agent → save plan → execute."""
    stub = _make_pipeline_stub(mocker)

    storage = ActionPlanStorage(storage_dir=tmp_path)
    target_key = 'reddit.com/_SimpleContract'
    assert storage.load(target_key) is None  # empty cache

    mocker.patch('yosoi.core.pipeline.ActionPlanStorage', return_value=storage)

    # Build a fake agent whose discover_plan returns a reddit-shape plan.
    discovered = ReplayPlan(
        target=target_key,
        task='load every comment',
        source='scripted',
        nodes=[
            click_until(
                css('faceplate-partial[src*="more-comments"] button'),
                expect=selector_absent(css('faceplate-partial[src*="more-comments"]')),
                max_iters=20,
            ),
        ],
    )
    fake_agent_instance = mocker.MagicMock()
    fake_agent_instance.discover_plan = mocker.AsyncMock(return_value=discovered)
    mocker.patch('yosoi.core.pipeline.ActionPlanDiscoveryAgent', return_value=fake_agent_instance)

    fake_execute = mocker.patch(
        'yosoi.core.pipeline._execute_action_plan',
        new=mocker.AsyncMock(return_value=mocker.MagicMock(score=1.0)),
    )

    # Fake tab with a content() coroutine to satisfy the discovery path.
    fake_tab = mocker.MagicMock()
    fake_tab.content = mocker.AsyncMock(return_value='<html><body>x</body></html>')

    hook = Pipeline._build_prepare_page(stub, 'https://www.reddit.com/r/ted/comments/abc')
    assert hook is not None
    await hook(fake_tab)

    # Discovery agent was called with the contract-derived intent.
    fake_agent_instance.discover_plan.assert_awaited_once()
    call_kwargs = fake_agent_instance.discover_plan.await_args.kwargs
    assert call_kwargs['target'] == target_key
    assert '_SimpleContract' in call_kwargs['intent']
    assert call_kwargs['html'] == '<html><body>x</body></html>'

    # Plan was persisted — second call would replay without LLM.
    reloaded = storage.load(target_key)
    assert reloaded is not None
    assert len(reloaded.nodes) == 1

    # And it was executed once.
    fake_execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_prepare_page_skips_execute_when_discovered_plan_is_empty(mocker, tmp_path):
    """LLM returning [] is a valid answer for eagerly-rendered pages; we still
    persist that decision so the next call replays instantly."""
    stub = _make_pipeline_stub(mocker)

    storage = ActionPlanStorage(storage_dir=tmp_path)
    target_key = 'static.example/_SimpleContract'

    mocker.patch('yosoi.core.pipeline.ActionPlanStorage', return_value=storage)

    empty_plan = ReplayPlan(target=target_key, task='nothing', source='scripted', nodes=[])
    fake_agent_instance = mocker.MagicMock()
    fake_agent_instance.discover_plan = mocker.AsyncMock(return_value=empty_plan)
    mocker.patch('yosoi.core.pipeline.ActionPlanDiscoveryAgent', return_value=fake_agent_instance)

    fake_execute = mocker.patch(
        'yosoi.core.pipeline._execute_action_plan',
        new=mocker.AsyncMock(),
    )

    fake_tab = mocker.MagicMock()
    fake_tab.content = mocker.AsyncMock(return_value='<html><body>full</body></html>')

    hook = Pipeline._build_prepare_page(stub, 'https://static.example/page')
    await hook(fake_tab)

    fake_agent_instance.discover_plan.assert_awaited_once()
    fake_execute.assert_not_called()  # empty plan → no execution
    # Empty plan is cached too — next call replays this empty result instantly.
    reloaded = storage.load(target_key)
    assert reloaded is not None
    assert reloaded.nodes == []


@pytest.mark.asyncio
async def test_prepare_page_swallows_discovery_errors_so_extraction_can_still_attempt(mocker, tmp_path):
    """Action-plan discovery is best-effort — if the LLM fails, we log and proceed
    to extraction on whatever HTML the page already shows. Better partial data
    than no data."""
    from yosoi.utils.exceptions import LLMGenerationError

    stub = _make_pipeline_stub(mocker)
    storage = ActionPlanStorage(storage_dir=tmp_path)
    mocker.patch('yosoi.core.pipeline.ActionPlanStorage', return_value=storage)

    fake_agent_instance = mocker.MagicMock()
    fake_agent_instance.discover_plan = mocker.AsyncMock(side_effect=LLMGenerationError('upstream went sideways'))
    mocker.patch('yosoi.core.pipeline.ActionPlanDiscoveryAgent', return_value=fake_agent_instance)

    fake_execute = mocker.patch(
        'yosoi.core.pipeline._execute_action_plan',
        new=mocker.AsyncMock(),
    )

    fake_tab = mocker.MagicMock()
    fake_tab.content = mocker.AsyncMock(return_value='<html><body>x</body></html>')

    hook = Pipeline._build_prepare_page(stub, 'https://x.example/page')
    # Must NOT raise — the hook is best-effort, extraction can still run after.
    await hook(fake_tab)

    fake_execute.assert_not_called()
    # No plan persisted on failure (so the next call will retry discovery).
    assert storage.load('x.example/_SimpleContract') is None
