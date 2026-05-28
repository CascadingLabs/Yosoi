"""Tests for MCPDiscoveryOrchestrator (CAS-79).

The LLM round-trip is mocked: we install a fake pydantic-ai Agent whose
``run`` returns a canned ``MCPDiscoveryResult``, then verify the orchestrator
unpacks it into the same SelectorMap shape ``DiscoveryOrchestrator`` produces
so downstream Pipeline code (verify → extract → save) is mode-agnostic.

No OpenCode server / voidcrawl MCP is spawned by these tests.
"""

from __future__ import annotations

import pytest

import yosoi as ys
from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_orchestrator import (
    FieldFinding,
    MCPDiscoveryResult,
)
from yosoi.models.selectors import SelectorEntry
from yosoi.utils.exceptions import LLMGenerationError


class _RedditPost(ys.Contract):
    title: str = ys.Title()
    author: str = ys.Author()
    score: int | None = ys.Count()


def _opencode_config() -> LLMConfig:
    """Caller-side shape: OpenCode requires provider='opencode' + provider_id/model_id."""
    return LLMConfig(
        provider='opencode',
        model_name='gpt-5.4-mini',
        api_key=None,
        extra_params={'provider_id': 'openrouter', 'model_id': 'openai/gpt-5.4-mini'},
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_orchestrator_construction_requires_opencode_config(mocker) -> None:
    """MCP path is OpenCode-specific (voidcrawl-mcp tooling lives in the OC config).
    A non-OpenCode LLMConfig must fail loudly at construction, not silently degrade."""
    from yosoi.core.discovery.mcp_orchestrator import MCPDiscoveryOrchestrator

    mocker.patch('yosoi.integrations.opencode.OpenCodeModel')
    with pytest.raises(ValueError, match='requires an OpenCode-shaped'):
        MCPDiscoveryOrchestrator(
            contract=_RedditPost,
            llm_config=LLMConfig(provider='openrouter', model_name='x', api_key='fake'),
        )


def test_orchestrator_construction_succeeds_with_opencode_config(mocker) -> None:
    """OpenCode config + mocked model -> instantiable. The agent is built lazily
    once but never run by this test."""
    from yosoi.core.discovery.mcp_orchestrator import MCPDiscoveryOrchestrator

    mocker.patch('yosoi.integrations.opencode.OpenCodeModel')
    fake_agent_cls = mocker.patch('yosoi.core.discovery.mcp_orchestrator.Agent')

    orch = MCPDiscoveryOrchestrator(contract=_RedditPost, llm_config=_opencode_config())
    assert orch.provider == 'opencode'
    assert orch.model_name == 'gpt-5.4-mini'
    fake_agent_cls.assert_called_once()


# ---------------------------------------------------------------------------
# discover_selectors() — happy path + unpacking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_selectors_unpacks_findings_into_selector_map(mocker) -> None:
    from yosoi.core.discovery import mcp_orchestrator as mod

    canned = MCPDiscoveryResult(
        field_selectors={
            'title': FieldFinding(
                selector=SelectorEntry(type='attr', value='post-title'),
                sample_value='An example title',
                rationale='attribute on shreddit-post',
            ),
            'author': FieldFinding(
                selector=SelectorEntry(type='attr', value='author'),
                sample_value='u/example',
            ),
            'score': FieldFinding(
                selector=SelectorEntry(type='attr', value='score'),
                sample_value='42',
            ),
        },
        root_selector=SelectorEntry(type='css', value='shreddit-post'),
        action_plan_intent='page is fully rendered; no actions needed',
    )

    class _FakeRun:
        def __init__(self, output):
            self.output = output

    class _FakeAgent:
        def __init__(self, *a, **kw):
            pass

        async def run(self, *a, **kw):
            return _FakeRun(canned)

    mocker.patch.object(mod, 'OpenCodeModel', create=True)
    mocker.patch.object(mod, 'Agent', _FakeAgent)

    orch = mod.MCPDiscoveryOrchestrator(contract=_RedditPost, llm_config=_opencode_config())
    selectors = await orch.discover_selectors(url='https://www.reddit.com/r/ted/top')

    assert selectors is not None
    # All three contract fields + root, no fallback/tertiary (agent commits to ONE verified selector).
    assert set(selectors) == {'title', 'author', 'score', 'root'}
    assert selectors['title']['primary']['type'] == 'attr'
    assert selectors['title']['primary']['value'] == 'post-title'
    assert selectors['root']['primary']['type'] == 'css'
    assert selectors['root']['primary']['value'] == 'shreddit-post'
    # No fallback/tertiary keys leak in (the agent path doesn't emit a cascade).
    assert 'fallback' not in selectors['title']
    assert 'tertiary' not in selectors['title']


@pytest.mark.asyncio
async def test_discover_selectors_narrows_to_stale_fields_when_requested(mocker) -> None:
    """When the Pipeline asks for partial re-discovery (stale_fields=...),
    the orchestrator narrows the returned SelectorMap to just those fields
    even though the agent always works the full contract."""
    from yosoi.core.discovery import mcp_orchestrator as mod

    canned = MCPDiscoveryResult(
        field_selectors={
            'title': FieldFinding(selector=SelectorEntry(type='css', value='h1'), sample_value='T'),
            'author': FieldFinding(selector=SelectorEntry(type='attr', value='author'), sample_value='u/x'),
            'score': FieldFinding(selector=SelectorEntry(type='attr', value='score'), sample_value='3'),
        },
    )

    class _FakeRun:
        def __init__(self, output):
            self.output = output

    class _FakeAgent:
        def __init__(self, *a, **kw):
            pass

        async def run(self, *a, **kw):
            return _FakeRun(canned)

    mocker.patch.object(mod, 'OpenCodeModel', create=True)
    mocker.patch.object(mod, 'Agent', _FakeAgent)

    orch = mod.MCPDiscoveryOrchestrator(contract=_RedditPost, llm_config=_opencode_config())
    selectors = await orch.discover_selectors(url='https://x.example', stale_fields={'score'})
    assert selectors is not None
    # Only score landed (no title / author / root because they weren't asked for).
    assert set(selectors) == {'score'}


@pytest.mark.asyncio
async def test_discover_selectors_returns_none_on_empty_agent_output(mocker) -> None:
    """If the agent comes back with zero field selectors (very degenerate), the
    orchestrator returns None rather than an empty dict — same semantics as the
    static orchestrator's 'all fields failed' branch."""
    from yosoi.core.discovery import mcp_orchestrator as mod

    canned = MCPDiscoveryResult(field_selectors={}, root_selector=None)

    class _FakeRun:
        def __init__(self, output):
            self.output = output

    class _FakeAgent:
        def __init__(self, *a, **kw):
            pass

        async def run(self, *a, **kw):
            return _FakeRun(canned)

    mocker.patch.object(mod, 'OpenCodeModel', create=True)
    mocker.patch.object(mod, 'Agent', _FakeAgent)

    orch = mod.MCPDiscoveryOrchestrator(contract=_RedditPost, llm_config=_opencode_config())
    result = await orch.discover_selectors(url='https://x.example')
    assert result is None


@pytest.mark.asyncio
async def test_discover_selectors_wraps_agent_errors_in_llm_generation_error(mocker) -> None:
    from yosoi.core.discovery import mcp_orchestrator as mod

    class _FakeAgent:
        def __init__(self, *a, **kw):
            pass

        async def run(self, *a, **kw):
            raise RuntimeError('voidcrawl session crashed mid-discovery')

    mocker.patch.object(mod, 'OpenCodeModel', create=True)
    mocker.patch.object(mod, 'Agent', _FakeAgent)

    orch = mod.MCPDiscoveryOrchestrator(contract=_RedditPost, llm_config=_opencode_config())
    with pytest.raises(LLMGenerationError, match='MCP discovery failed'):
        await orch.discover_selectors(url='https://x.example')


# ---------------------------------------------------------------------------
# Output-shape parity with DiscoveryOrchestrator
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Action-plan latching (transcript distillation side-effect)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_action_plan_is_reset_to_none_at_start_of_each_run(mocker) -> None:
    """A new discover_selectors run must clear any stale plan from a prior run —
    callers (Pipeline._persist_mcp_action_plan) read the latch right after,
    so a leftover value would persist wrong data into the cache."""
    from yosoi.core.discovery import mcp_orchestrator as mod
    from yosoi.models.replay import ReplayPlan

    canned = MCPDiscoveryResult(
        field_selectors={
            'title': FieldFinding(selector=SelectorEntry(type='css', value='h1'), sample_value='t'),
        },
    )

    class _FakeRun:
        def __init__(self, output):
            self.output = output

    class _FakeAgent:
        def __init__(self, *a, **kw):
            pass

        async def run(self, *a, **kw):
            return _FakeRun(canned)

    mocker.patch.object(mod, 'OpenCodeModel', create=True)
    mocker.patch.object(mod, 'Agent', _FakeAgent)
    # Ensure no SSE capture (no OPENCODE_BASE_URL) so the latch stays None
    # after the run unless we manually plant one.
    import os as _os

    _os.environ.pop('OPENCODE_BASE_URL', None)

    orch = mod.MCPDiscoveryOrchestrator(contract=_RedditPost, llm_config=_opencode_config())
    # Plant a stale plan to prove the next run clears it.
    orch.last_action_plan = ReplayPlan(target='stale/Old', task='stale', source='scripted', nodes=[])

    await orch.discover_selectors(url='https://x.example')
    assert orch.last_action_plan is None  # cleared on entry; no SSE → never set again


@pytest.mark.asyncio
async def test_mcp_output_shape_matches_static_orchestrator(mocker) -> None:
    """Both orchestrators promise the same SelectorMap shape:
    ``dict[field_name, dict[level_name, selector_dict]]`` with ``'primary'`` always present.
    The Pipeline's verify/extract/save layer relies on this — sanity-check the contract."""
    from yosoi.core.discovery import mcp_orchestrator as mod

    canned = MCPDiscoveryResult(
        field_selectors={
            'title': FieldFinding(selector=SelectorEntry(type='css', value='h1'), sample_value='ok'),
        },
        root_selector=SelectorEntry(type='css', value='article'),
    )

    class _FakeRun:
        def __init__(self, output):
            self.output = output

    class _FakeAgent:
        def __init__(self, *a, **kw):
            pass

        async def run(self, *a, **kw):
            return _FakeRun(canned)

    mocker.patch.object(mod, 'OpenCodeModel', create=True)
    mocker.patch.object(mod, 'Agent', _FakeAgent)

    orch = mod.MCPDiscoveryOrchestrator(contract=_RedditPost, llm_config=_opencode_config())
    result = await orch.discover_selectors(url='https://x.example')

    # The shape contract: every value is a dict with at least 'primary'.
    assert result is not None
    for entry in result.values():
        assert isinstance(entry, dict)
        assert 'primary' in entry
        primary = entry['primary']
        # SelectorEntry.model_dump shape — must include type + value at minimum.
        assert isinstance(primary, dict)
        assert 'type' in primary
        assert 'value' in primary
