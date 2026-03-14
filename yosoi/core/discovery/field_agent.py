"""Single-field AI discovery agent wrapping a narrow pydantic-ai Agent."""

import logfire
from pydantic_ai import Agent
from rich.console import Console

from yosoi.core.discovery.agent import _extract_provider_error
from yosoi.core.discovery.config import LLMConfig, create_model
from yosoi.models.selectors import FieldSelectors, SelectorLevel
from yosoi.prompts.discovery import (
    DiscoveryInput,
    FieldDiscoveryDeps,
    build_user_prompt,
    field_single_base_instructions,
    field_single_field_instructions,
    field_single_level_instructions,
    field_single_page_hints,
)
from yosoi.utils.exceptions import LLMGenerationError


class FieldDiscoveryAgent:
    """Discovers selectors for a single contract field via a narrow LLM call.

    One instance is shared across all concurrent field tasks — pydantic-ai
    agents are stateless across runs; deps are injected per-run via RunContext.

    Attributes:
        model_name: Name of the underlying LLM model
        provider: LLM provider name
        console: Rich console for output

    """

    def __init__(self, llm_config: LLMConfig, console: Console | None = None):
        """Initialize with LLM configuration.

        Args:
            llm_config: LLM provider and model configuration
            console: Optional Rich console for output

        """
        model = create_model(llm_config)
        self.model_name = llm_config.model_name
        self.provider = llm_config.provider
        self.console = console or Console()

        self._agent: Agent[FieldDiscoveryDeps, FieldSelectors] = Agent(
            model,
            deps_type=FieldDiscoveryDeps,
            output_type=FieldSelectors,
            output_retries=3,
        )
        self._agent.system_prompt(field_single_base_instructions)
        self._agent.system_prompt(field_single_field_instructions)
        self._agent.system_prompt(field_single_level_instructions)
        self._agent.system_prompt(field_single_page_hints)

    @logfire.instrument('field_discover', extract_args=False)
    async def discover_field(
        self,
        field_name: str,
        field_description: str,
        field_hint: str | None,
        discovery_input: DiscoveryInput,
        target_level: SelectorLevel,
        is_container: bool = False,
    ) -> FieldSelectors | None:
        """Ask the LLM to find selectors for a single field.

        Args:
            field_name: Name of the field to find selectors for
            field_description: Human-readable field description
            field_hint: Optional hint from contract field definition
            discovery_input: URL and HTML input for the agent
            target_level: Maximum selector strategy level allowed
            is_container: True when discovering the yosoi_container selector

        Returns:
            FieldSelectors with discovered selectors, or None if LLM returned NA.

        Raises:
            LLMGenerationError: If the LLM call fails.

        """
        deps = FieldDiscoveryDeps(
            field_name=field_name,
            field_description=field_description,
            field_hint=field_hint,
            input=discovery_input,
            target_level=target_level,
            is_container=is_container,
        )

        try:
            result = await self._agent.run(build_user_prompt(discovery_input), deps=deps)
            field_selectors: FieldSelectors = result.output

            # Treat primary value of NA as not found
            if field_selectors.primary.value.upper() == 'NA':
                logfire.info('Field discovery returned NA', field=field_name)
                return None

            logfire.info('Field selectors found', field=field_name)
            return field_selectors

        except Exception as e:
            error_msg = str(e)
            detail = _extract_provider_error(e)

            if detail:
                self.console.print(f'[danger]  ✗ {field_name}: {detail}[/danger]')
            else:
                self.console.print(f'[danger]  ✗ {field_name}: {e}[/danger]')

            logfire.error('Field discovery failed', field=field_name, error=error_msg, provider=self.provider)
            raise LLMGenerationError(f'Field discovery failed for {field_name}: {detail or error_msg}') from e
