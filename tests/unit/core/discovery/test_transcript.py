"""Tests for the OpenCode tool-transcript → ReplayPlan distillation.

Promoted from ``examples/opencode_voidcrawl/recipe.py``; the package version
produces a :class:`yosoi.models.replay.ReplayPlan` rather than a BrowseRecipe,
and the MCP-tool prefix is now configurable so the same distillation works
across MCP servers.
"""

from __future__ import annotations

from yosoi.core.discovery.transcript import DEFAULT_MCP_PREFIX, plan_from_tool_parts


def _completed_tool(name: str, inp: dict | None = None) -> dict:
    """Shape one OpenCode ``message.part.updated`` tool part — completed status."""
    return {
        'type': 'tool',
        'tool': name,
        'callID': name + '-id',
        'state': {'status': 'completed', 'input': inp or {}, 'output': 'ok'},
    }


def _errored_tool(name: str, inp: dict | None = None) -> dict:
    return {
        'type': 'tool',
        'tool': name,
        'callID': name + '-err',
        'state': {'status': 'error', 'input': inp or {}, 'error': 'boom'},
    }


# ---------------------------------------------------------------------------
# Basic distillation
# ---------------------------------------------------------------------------


def test_navigate_then_click_becomes_two_node_plan() -> None:
    parts = [
        _completed_tool('voidcrawl_session_navigate', {'url': 'https://example.com'}),
        _completed_tool('voidcrawl_click', {'selector': '.load-more'}),
    ]
    plan = plan_from_tool_parts(parts, target='example.com/MyContract', task='discover via MCP')
    assert plan.target == 'example.com/MyContract'
    assert plan.source == 'mcp-agent'
    assert len(plan.nodes) == 2
    assert plan.nodes[0].act.op == 'navigate'  # type: ignore[union-attr]
    assert plan.nodes[0].act.url == 'https://example.com'  # type: ignore[union-attr]
    assert plan.nodes[1].act.op == 'click'  # type: ignore[union-attr]


def test_errored_tool_calls_are_dropped() -> None:
    """A click the agent corrected mid-run should NOT enter the cached plan
    — replay must be a record of what worked, not of what was attempted."""
    parts = [
        _errored_tool('voidcrawl_click', {'selector': '.wrong'}),
        _completed_tool('voidcrawl_click', {'selector': '.right'}),
    ]
    plan = plan_from_tool_parts(parts, target='x.example/C', task='t')
    assert len(plan.nodes) == 1
    target = plan.nodes[0].act.targets[0]  # type: ignore[union-attr]
    assert target.value == '.right'


def test_perceive_only_tools_are_dropped() -> None:
    """Read-only / lifecycle tools (ax_tree, session_open, title, extract, …)
    don't drive page state forward and shouldn't end up as replay nodes."""
    parts = [
        _completed_tool('voidcrawl_session_open', {}),
        _completed_tool('voidcrawl_session_ax_tree', {}),
        _completed_tool('voidcrawl_title', {}),
        _completed_tool('voidcrawl_extract', {'selector': '.x'}),
        _completed_tool('voidcrawl_eval_js', {'script': '1+1'}),
        _completed_tool('voidcrawl_screenshot', {}),
        _completed_tool('voidcrawl_session_close', {}),
        _completed_tool('voidcrawl_session_navigate', {'url': 'https://x.example'}),
    ]
    plan = plan_from_tool_parts(parts, target='x.example/C', task='t')
    # Only the navigate makes it through.
    assert len(plan.nodes) == 1
    assert plan.nodes[0].act.op == 'navigate'  # type: ignore[union-attr]


def test_click_by_role_produces_role_selector() -> None:
    parts = [
        _completed_tool(
            'voidcrawl_click_by_role',
            {'role': 'button', 'name': 'Load more', 'nth': 0},
        ),
    ]
    plan = plan_from_tool_parts(parts, target='x.example/C', task='t')
    assert len(plan.nodes) == 1
    target = plan.nodes[0].act.targets[0]  # type: ignore[union-attr]
    assert target.type == 'role'
    assert target.role == 'button'
    assert target.name == 'Load more'


def test_visual_click_produces_visual_selector() -> None:
    parts = [_completed_tool('voidcrawl_click_visual_coords', {'x': 100, 'y': 200})]
    plan = plan_from_tool_parts(parts, target='x.example/C', task='t')
    assert len(plan.nodes) == 1
    target = plan.nodes[0].act.targets[0]  # type: ignore[union-attr]
    assert target.type == 'visual'
    assert target.x == 100
    assert target.y == 200


# ---------------------------------------------------------------------------
# Tool-name prefix is configurable
# ---------------------------------------------------------------------------


def test_default_prefix_is_voidcrawl() -> None:
    """Sanity check — the default matches the voidcrawl-mcp tool namespace."""
    assert DEFAULT_MCP_PREFIX == 'voidcrawl_'


def test_alternate_prefix_isolates_tool_namespace() -> None:
    """A different MCP server's tools shouldn't be picked up under the
    default prefix, and vice versa."""
    parts = [
        _completed_tool('otherscan_navigate', {'url': 'https://x.example'}),
        _completed_tool('otherscan_click', {'selector': '.x'}),
        _completed_tool('voidcrawl_session_navigate', {'url': 'https://other.example'}),
    ]
    # Default prefix picks up only voidcrawl_*
    plan_vc = plan_from_tool_parts(parts, target='vc/C', task='t')
    assert len(plan_vc.nodes) == 1
    assert plan_vc.nodes[0].act.url == 'https://other.example'  # type: ignore[union-attr]

    # Alternate prefix picks up only otherscan_*
    plan_os = plan_from_tool_parts(parts, target='os/C', task='t', mcp_prefix='otherscan_')
    assert len(plan_os.nodes) == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_parts_returns_empty_plan() -> None:
    plan = plan_from_tool_parts([], target='x.example/C', task='t')
    assert plan.nodes == []
    assert plan.target == 'x.example/C'


def test_non_tool_parts_are_ignored() -> None:
    """OpenCode's stream also surfaces step-finish, reasoning, and other part
    kinds — only tool parts feed the recipe."""
    parts = [
        {'type': 'step-finish', 'tokens': {}, 'cost': 0.0},
        {'type': 'reasoning', 'id': 'r1', 'text': 'let me think'},
        _completed_tool('voidcrawl_session_navigate', {'url': 'https://x.example'}),
    ]
    plan = plan_from_tool_parts(parts, target='x.example/C', task='t')
    assert len(plan.nodes) == 1
