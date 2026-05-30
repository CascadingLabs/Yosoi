"""Agentic MCP discovery: a pydantic-ai Agent that drives a live browser.

Unlike :class:`~yosoi.core.discovery.field_agent.FieldDiscoveryAgent` (one blind
LLM call per field over cleaned HTML), this agent is given the voidcrawl MCP as a
toolset and explores the real page. It self-corrects in-loop via the
``check_value`` tool (the validator-as-tool design from CAS-79) and returns one
structured :class:`MCPDiscoveryDraft` describing every verified selector plus a
replay plan.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPServerStdio
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig, create_model
from yosoi.core.discovery.mcp_client import voidcrawl_server
from yosoi.core.verification.semantic import SemanticValidator
from yosoi.models.replay import ReplayPlan
from yosoi.models.selectors import SelectorEntry
from yosoi.prompts.mcp_discovery import (
    MCPDiscoveryDeps,
    build_mcp_user_prompt,
    mcp_discovery_instructions,
)
from yosoi.types.registry import SemanticRule
from yosoi.utils import observability as obs
from yosoi.utils.exceptions import LLMGenerationError

_logger = logging.getLogger(__name__)


class MCPFieldFinding(BaseModel):
    """One field's verified selector and the value the agent observed it extract."""

    field: str = Field(description='Contract field name this selector targets.')
    selector: SelectorEntry = Field(description='The selector that extracted the right value.')
    sample_value: str = Field(description='The exact value the selector extracted on the live page.')


class MCPDiscoveryDraft(BaseModel):
    """Structured result of one MCP discovery session.

    The orchestrator distills this into a persisted
    :class:`~yosoi.models.replay.DiscoveryLesson`.
    """

    fields: list[MCPFieldFinding] = Field(default_factory=list)
    root: SelectorEntry | None = Field(
        default=None,
        description='Wrapper selector for one repeating item, or null for single-item pages.',
    )
    replay_plan: ReplayPlan = Field(
        default_factory=ReplayPlan,
        description='Navigation/interaction steps to reproduce the page state during replay.',
    )


class MCPDiscoveryAgent:
    """Drives the voidcrawl MCP as an agent loop to discover verified selectors.

    Attributes:
        model_name: Underlying LLM model name.
        provider: LLM provider name.

    """

    def __init__(
        self,
        llm_config: LLMConfig,
        console: Console | None = None,
        *,
        server: MCPServerStdio | None = None,
    ):
        """Initialise the MCP discovery agent.

        Args:
            llm_config: LLM provider and model configuration. The model must
                support tool calling.
            console: Optional Rich console for output.
            server: Optional pre-built voidcrawl MCP toolset. Defaults to
                :func:`~yosoi.core.discovery.mcp_client.voidcrawl_server`, which
                fails fast if the binary is missing.

        """
        model = create_model(llm_config)
        self.model_name = llm_config.model_name
        self.provider = llm_config.provider
        self.console = console or Console()
        self._server = server if server is not None else voidcrawl_server()

        self._agent: Agent[MCPDiscoveryDeps, MCPDiscoveryDraft] = Agent(
            model,
            deps_type=MCPDiscoveryDeps,
            output_type=MCPDiscoveryDraft,
            toolsets=[self._server],
            retries={'output': 3},
            capabilities=obs.agent_capabilities(),
        )
        self._agent.system_prompt(mcp_discovery_instructions)
        self._agent.tool(_check_value)

    async def discover(
        self,
        url: str,
        fields: Mapping[str, str],
        field_rules: Mapping[str, SemanticRule],
    ) -> MCPDiscoveryDraft:
        """Run one live-browser discovery session for all contract fields.

        Args:
            url: Target page URL.
            fields: Field name -> description to discover.
            field_rules: Field name -> semantic rule for in-loop validation.

        Returns:
            The structured draft of verified selectors and the replay plan.

        Raises:
            LLMGenerationError: If the agent run fails.

        """
        deps = MCPDiscoveryDeps(
            url=url,
            fields=fields,
            field_rules=field_rules,
            validator=SemanticValidator(),
        )
        with obs.span('mcp_discovery_agent', url=url, field_count=len(fields), source='agent') as span:
            obs.annotate_llm(span, provider=self.provider, model=self.model_name)
            try:
                async with self._agent:
                    result = await self._agent.run(build_mcp_user_prompt(url, fields), deps=deps)
                _logger.info('MCP discovery returned %d findings', len(result.output.fields))
                return result.output
            except Exception as e:
                self.console.print(f'[danger]  ✗ MCP discovery failed: {e}[/danger]')
                _logger.error('MCP discovery failed', extra={'url': url, 'error': str(e)})
                raise LLMGenerationError(f'MCP discovery failed for {url}: {e}') from e


def _check_value(ctx: RunContext[MCPDiscoveryDeps], field: str, value: str) -> str:
    """Validate that an observed value matches a field's semantic type.

    The agent calls this after extracting a value, before recording the selector.
    Returns ``"ok"`` when the value is well-shaped (or the field has no rule), or
    a human-readable reason to keep trying — letting the agent self-correct in
    real time instead of relying on a post-hoc feedback loop.
    """
    rule = ctx.deps.field_rules.get(field)
    if rule is None:
        return 'ok'
    issues = ctx.deps.validator.validate({field: value}, {field: rule})
    if not issues:
        return 'ok'
    return issues[0].as_feedback()
