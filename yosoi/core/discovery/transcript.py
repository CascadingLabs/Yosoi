"""OpenCode/voidcrawl tool-transcript → A3Node ReplayPlan distillation.

Promoted from ``examples/opencode_voidcrawl/recipe.py`` so the package can
build replayable action plans from agent runs without depending on
example-side code. The distillation logic is the same — only successful tool
calls become acts; lifecycle / perceive tools are dropped — but the MCP-tool
prefix is now a parameter instead of a hardcoded ``voidcrawl_`` constant,
making the module reusable across other MCP servers.

Used by:
  * :class:`yosoi.core.discovery.mcp_orchestrator.MCPDiscoveryOrchestrator`
    after an interactive discovery run — distils the agent's voidcrawl tool
    calls into an A3Node sequence cached in
    :class:`yosoi.storage.action_plan.ActionPlanStorage` so subsequent runs
    replay without LLM activity.
  * Example code (``examples/opencode_voidcrawl/browse_and_save.py``,
    ``recipe.py``) can re-export the helpers it already exposes.
"""

from __future__ import annotations

from typing import Any

from yosoi.models.replay import (
    A3Node,
    Act,
    Parallel,
    ReplayPlan,
    click,
    css,
    navigate,
    role,
    teleport,
    visual,
)

DEFAULT_MCP_PREFIX = 'voidcrawl_'


def plan_from_tool_parts(
    tool_parts: list[dict[str, Any]],
    *,
    target: str,
    task: str,
    mcp_prefix: str = DEFAULT_MCP_PREFIX,
) -> ReplayPlan:
    """Distil completed MCP tool calls into a replayable ReplayPlan.

    Mirrors the A3Node "save what worked" ethos: only completed tool calls
    become nodes (an errored click the agent corrected never enters the plan).
    Read-only / lifecycle / perceive tools (``session_open/close``,
    ``ax_tree``, ``title``, ``extract``, ``eval_js``, ``screenshot``) are
    dropped — they don't drive page state forward.

    Args:
        tool_parts: OpenCode ``message.part.updated`` parts of type ``tool``
            with state status ``completed``. Caller is responsible for
            collecting these from OpenCode's ``/event`` SSE stream.
        target: Stable cache key for the plan (typically
            ``domain/ContractName``).
        task: One-sentence description of what the plan accomplishes; surfaces
            in the persisted JSON for human inspection.
        mcp_prefix: Tool-name prefix used by OpenCode to namespace this MCP
            server's tools. Defaults to ``"voidcrawl_"`` for the voidcrawl-mcp
            server; pass a different prefix to distil transcripts from other
            MCP servers.

    Returns:
        A ``ReplayPlan`` with ``source='mcp-agent'`` whose nodes are the
        ordered successful actions. Empty plan if no usable acts were found.
    """
    nodes: list[A3Node | Parallel] = []
    for part in tool_parts:
        if part.get('type') != 'tool':
            continue
        state = part.get('state') or {}
        if state.get('status') != 'completed':
            continue
        tool = part.get('tool', '')
        if not tool.startswith(mcp_prefix):
            continue
        node = _node_for(tool[len(mcp_prefix) :], state.get('input') or {})
        if node is not None:
            nodes.append(node)
    return ReplayPlan(target=target, task=task, nodes=nodes, source='mcp-agent')


def _node_for(name: str, inp: dict[str, Any]) -> A3Node | None:
    """Map a single voidcrawl-style tool name + input onto an A3Node, or None."""
    if name in ('session_navigate', 'fetch', 'navigate'):
        return navigate(inp.get('url', ''))
    if name == 'teleport':
        return teleport(inp['latitude'], inp['longitude'], inp.get('timezone'), inp.get('locale'))
    if name == 'click_by_role':
        return click(role(inp.get('role', ''), inp.get('name', ''), inp.get('nth') or 0))
    if name == 'click':
        return click(css(inp.get('selector', '')))
    if name == 'click_visual_coords':
        return click(visual(inp['x'], inp['y']))
    if name == 'wait_for_network_idle':
        return A3Node(act=Act(op='wait'))
    return None  # session_open/close, ax_tree, title, extract, eval_js, screenshot, ...
