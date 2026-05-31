"""Pluggable MCP-discovery backends — one concern, three conformers.

MCP discovery is a single concern: give an LLM the voidcrawl MCP toolset plus a
structured output schema, let it drive the live DOM, and hand back an
:class:`~yosoi.core.discovery.mcp_draft.MCPDiscoveryDraft`. What differs between
backends is only *who owns the tool loop*:

* :class:`PydanticAIBackend` — pydantic-ai drives the loop (provider-API models
  that support function calling: OpenRouter, OpenAI, Anthropic, …).
* :class:`ClaudeSDKBackend` — the Claude Agent SDK runs its own native loop.
* :class:`OpenCodeBackend` — a local OpenCode server runs its own native loop.

All three mount the *same* MCP servers (voidcrawl + the shared
``yosoi-validator`` ``check_value`` server), so in-loop self-correction and the
returned schema are identical regardless of backend. The orchestrator depends
only on the :class:`MCPDiscoveryBackend` protocol — never on a concrete model
class — and :func:`backend_for` is the single place a model maps to a backend.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from yosoi.core.discovery.config import LLMConfig, create_model
from yosoi.core.discovery.mcp_draft import MCPDiscoveryDraft
from yosoi.utils import observability as obs
from yosoi.utils.exceptions import LLMGenerationError

logger = logging.getLogger(__name__)

#: voidcrawl MCP tools the discovery agent is allowed to call. Enumerated because
#: subscription SDKs gate tool access by an explicit allowlist.
VOIDCRAWL_DISCOVERY_TOOLS: tuple[str, ...] = (
    'session_open',
    'session_navigate',
    'session_ax_tree',
    'session_content',
    'session_close',
    'eval_js',
    'extract',
    'click',
    'click_by_role',
    'screenshot',
    'title',
    'type_text',
    'wait_for_network_idle',
)


@dataclass(frozen=True)
class StdioServerSpec:
    """A stdio MCP server each backend renders into its own host config.

    Attributes:
        name: Server key (becomes the ``mcp__<name>__<tool>`` prefix).
        command: Executable to launch.
        args: Command arguments.
        env: Extra environment variables for the spawned process.
        tools: Tool names the agent may call from this server (the allowlist
            subscription SDKs require; ignored by the pydantic-ai backend, which
            discovers tools from the server).
    """

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    tools: tuple[str, ...] = ()

    def allowed_tool_ids(self) -> list[str]:
        """Return ``mcp__<name>__<tool>`` ids for this server's allowed tools."""
        return [f'mcp__{self.name}__{tool}' for tool in self.tools]


@runtime_checkable
class MCPDiscoveryBackend(Protocol):
    """One way to run an MCP discovery session and return a structured draft."""

    name: str

    async def run(
        self,
        *,
        instructions: str,
        user_prompt: str,
        servers: Sequence[StdioServerSpec],
    ) -> MCPDiscoveryDraft:
        """Drive a discovery session and return the validated draft."""
        ...


class PydanticAIBackend:
    """pydantic-ai drives the MCP tool loop. For function-calling provider APIs."""

    name = 'pydantic-ai'

    def __init__(self, model: Any):
        """Initialise with a pydantic-ai model instance."""
        self._model = model

    async def run(
        self,
        *,
        instructions: str,
        user_prompt: str,
        servers: Sequence[StdioServerSpec],
    ) -> MCPDiscoveryDraft:
        """Build an Agent with the MCP servers as toolsets and run one session."""
        from pydantic_ai import Agent

        from yosoi.core.discovery.mcp_client import stdio_toolset

        toolsets = [stdio_toolset(s.command, s.args, env=dict(s.env) or None, id=s.name) for s in servers]
        agent: Agent[None, MCPDiscoveryDraft] = Agent(
            self._model,
            output_type=MCPDiscoveryDraft,
            instructions=instructions,
            toolsets=toolsets,
            retries={'output': 3},
            capabilities=obs.agent_capabilities(),
        )
        async with agent:
            result = await agent.run(user_prompt)
        return result.output


class ClaudeSDKBackend:
    """The Claude Agent SDK runs its own native MCP tool loop."""

    name = 'claude-sdk'

    def __init__(self, model_name: str):
        """Initialise with a Claude model name (e.g. ``claude-opus-4-7``)."""
        self._model_name = model_name

    async def run(
        self,
        *,
        instructions: str,
        user_prompt: str,
        servers: Sequence[StdioServerSpec],
    ) -> MCPDiscoveryDraft:
        """Drive the Claude Agent SDK with the MCP servers and harvest structured output."""
        from claude_agent_sdk import ClaudeAgentOptions, query

        mcp_servers = {
            s.name: {'type': 'stdio', 'command': s.command, 'args': list(s.args), 'env': dict(s.env)} for s in servers
        }
        allowed_tools = [tool_id for s in servers for tool_id in s.allowed_tool_ids()]
        options = ClaudeAgentOptions(
            system_prompt=instructions,
            model=self._model_name,
            mcp_servers=cast(Any, mcp_servers),
            allowed_tools=allowed_tools,
            permission_mode='bypassPermissions',
            output_format={'type': 'json_schema', 'schema': MCPDiscoveryDraft.model_json_schema()},
        )
        structured: object | None = None
        with obs.transport_span(obs.BACKEND_CLAUDE_SDK, self._model_name, structured_output=True):
            async with aclosing(cast(Any, query(prompt=user_prompt, options=options))) as stream:
                async for message in stream:
                    if type(message).__name__ == 'ResultMessage':
                        structured = getattr(message, 'structured_output', None)
                        break
        if structured is None:
            raise LLMGenerationError('Claude SDK discovery returned no structured output')
        return MCPDiscoveryDraft.model_validate(structured)


def validator_server_command() -> tuple[str, tuple[str, ...]]:
    """Return the (command, args) that launch the bundled validator MCP server.

    Prefers the ``yosoi-validator-mcp`` console script (on PATH under ``uv run``);
    falls back to ``python -m`` so it works even when the script is absent.
    """
    import shutil

    script = shutil.which('yosoi-validator-mcp')
    if script is not None:
        return script, ()
    return sys.executable, ('-m', 'yosoi.integrations.validator_mcp')


def backend_for(llm_config: LLMConfig) -> MCPDiscoveryBackend:
    """Map an LLM config to the MCP discovery backend that can drive it.

    Subscription transports (OpenCode, Claude Agent SDK) run their own native
    tool loop; everything else is a function-calling provider API driven by
    pydantic-ai. This is the single dispatch point — callers never branch on the
    concrete model type.
    """
    provider = llm_config.provider.lower()
    if provider in {'claude-sdk', 'claude_sdk'}:
        return ClaudeSDKBackend(llm_config.model_name)
    if provider == 'opencode':
        from yosoi.core.discovery.mcp_opencode import OpenCodeBackend

        return OpenCodeBackend(llm_config)
    return PydanticAIBackend(create_model(llm_config))
