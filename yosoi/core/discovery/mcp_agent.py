"""Agentic MCP discovery: drive a live browser to find verified selectors.

This is the backend-agnostic front. It assembles the shared MCP servers (the
voidcrawl browser + the ``yosoi-validator`` ``check_value`` server) and the task
prompt, then delegates the actual tool loop to whichever
:class:`~yosoi.core.discovery.mcp_backends.MCPDiscoveryBackend` fits the
configured model — pydantic-ai for function-calling provider APIs, or a
subscription SDK's native loop for OpenCode / Claude. Every backend returns the
same :class:`~yosoi.core.discovery.mcp_draft.MCPDiscoveryDraft`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from rich.console import Console

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_backends import (
    VOIDCRAWL_DISCOVERY_TOOLS,
    MCPDiscoveryBackend,
    StdioServerSpec,
    backend_for,
    validator_server_command,
)
from yosoi.core.discovery.mcp_client import voidcrawl_command
from yosoi.core.discovery.mcp_draft import MCPDiscoveryDraft, MCPFieldFinding
from yosoi.integrations.validator_mcp import FIELD_RULES_ENV, field_rules_env
from yosoi.prompts.mcp_discovery import build_mcp_user_prompt, mcp_discovery_instructions
from yosoi.types.registry import SemanticRule
from yosoi.utils import observability as obs
from yosoi.utils.exceptions import LLMGenerationError

__all__ = ['MCPDiscoveryAgent', 'MCPDiscoveryDraft', 'MCPFieldFinding']

_logger = logging.getLogger(__name__)


class MCPDiscoveryAgent:
    """Runs one live-browser discovery session via a model-appropriate backend.

    Attributes:
        model_name: Underlying LLM model name.
        provider: LLM provider name.

    """

    def __init__(
        self,
        llm_config: LLMConfig,
        console: Console | None = None,
        *,
        backend: MCPDiscoveryBackend | None = None,
    ):
        """Initialise the discovery agent.

        Args:
            llm_config: LLM provider and model configuration.
            console: Optional Rich console for output.
            backend: Optional pre-built backend (injected in tests). Defaults to
                the backend selected by :func:`backend_for` for ``llm_config``.

        """
        self.model_name = llm_config.model_name
        self.provider = llm_config.provider
        self.console = console or Console()
        self._backend = backend if backend is not None else backend_for(llm_config)

    def _servers(self, field_rules: Mapping[str, SemanticRule]) -> list[StdioServerSpec]:
        """Build the shared MCP server specs: voidcrawl browser + validator."""
        v_cmd, v_args = validator_server_command()
        return [
            StdioServerSpec(
                name='voidcrawl',
                command=voidcrawl_command(),
                tools=VOIDCRAWL_DISCOVERY_TOOLS,
            ),
            StdioServerSpec(
                name='yosoi_validator',
                command=v_cmd,
                args=v_args,
                env={FIELD_RULES_ENV: field_rules_env(dict(field_rules))},
                tools=('check_value',),
            ),
        ]

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
            LLMGenerationError: If the backend run fails.

        """
        servers = self._servers(field_rules)
        with obs.span(
            'mcp_discovery_agent',
            url=url,
            field_count=len(fields),
            backend=self._backend.name,
            source='agent',
        ) as span:
            obs.annotate_llm(span, provider=self.provider, model=self.model_name)
            try:
                draft = await self._backend.run(
                    instructions=mcp_discovery_instructions(),
                    user_prompt=build_mcp_user_prompt(url, fields),
                    servers=servers,
                )
                _logger.info('MCP discovery returned %d findings (%s)', len(draft.fields), self._backend.name)
                return draft
            except Exception as e:
                self.console.print(f'[danger]  ✗ MCP discovery failed: {e}[/danger]')
                _logger.error('MCP discovery failed', extra={'url': url, 'error': str(e)})
                raise LLMGenerationError(f'MCP discovery failed for {url}: {e}') from e
