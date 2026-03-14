"""AI-powered selector discovery by reading cleaned HTML."""

from typing import Any, cast

import logfire
from pydantic import BaseModel
from pydantic_ai import Agent
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig, create_model
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.prompts.discovery import (
    DiscoveryDeps,
    base_instructions,
    build_custom_agent_prompt,
    build_user_prompt,
    field_instructions,
    level_instructions,
    page_hints,
)
from yosoi.utils.exceptions import LLMGenerationError


class SelectorDiscovery:
    """Discovers selectors using AI to read cleaned HTML.

    Attributes:
        console: Rich console instance for formatted output
        agent: The LLM agent that will be used
        model_name: Name of the model being used
        provider: Name of the LLM provider
        target_level: Maximum selector strategy level for discovery

    """

    console: Console
    agent: Agent[Any, BaseModel]
    model_name: str
    provider: str
    target_level: SelectorLevel

    def __init__(
        self,
        contract: type[Contract],
        llm_config: LLMConfig | None = None,
        agent: Agent[Any, BaseModel] | None = None,
        console: Console | None = None,
        target_level: SelectorLevel = SelectorLevel.CSS,
    ):
        """Initialize the discovery with LLM configuration or an agent.

        Args:
            llm_config: Configuration for the LLM provider and model
            agent: The LLM agent that will be used
            console: Rich console instance for formatted output
            contract: Contract subclass defining fields to discover.
            target_level: Maximum selector strategy level. Defaults to CSS.

        Raises:
            ValueError: Must provide llm_config or an agent

        """
        self.console = console or Console()
        self._contract = contract
        self.target_level = target_level
        output_model = self._contract.to_selector_model()

        if agent is not None:
            self.agent = agent
            self.model_name = 'custom-agent'
            self.provider = 'custom'
            self._use_deps = False
        elif llm_config is not None:
            model = create_model(llm_config)
            self.agent = Agent(model, deps_type=DiscoveryDeps, output_type=output_model)
            # Register dynamic system-prompt functions
            self.agent.system_prompt(base_instructions)
            self.agent.system_prompt(field_instructions)
            self.agent.system_prompt(level_instructions)
            self.agent.system_prompt(page_hints)
            self.model_name = llm_config.model_name
            self.provider = llm_config.provider
            self._use_deps = True
        else:
            raise ValueError('Either provide llm_config or agent parameter')

    @logfire.instrument('discover_selectors', extract_args=False)
    async def discover_selectors(self, html: str, url: str | None = None) -> dict[str, Any] | None:
        """Discover CSS selectors from cleaned HTML using AI.

        Args:
            html: Cleaned HTML content to analyze
            url: Optional URL for context in LLM prompt. Defaults to None.

        Returns:
            Dictionary of discovered selectors, or None if discovery fails.

        """
        url_context = url or 'the provided page'
        logfire.info('Starting discovery', url=url_context)

        try:
            selectors_obj = await self._get_selectors_from_ai(url_context, html)

            if selectors_obj:
                selectors: dict[str, Any] = selectors_obj.model_dump(exclude_none=True)

                if selectors and not self._is_all_na(selectors):
                    logfire.info('Selectors found successfully', selectors=selectors)
                    return selectors

        except LLMGenerationError as e:
            logfire.warn('Discovery failed - AI error', error=str(e), url=url_context)
            return None

        logfire.warn('Discovery failed - AI returned no/invalid selectors', url=url_context)
        return None

    @logfire.instrument('llm_discovery_request')
    async def _get_selectors_from_ai(self, url: str, html: str) -> BaseModel | None:
        """Ask AI to find selectors by reading the HTML.

        Args:
            url: URL from which the HTML was obtained
            html: HTML content to give to LLM

        Returns:
            Selector config model with discovered selectors, or None if request failed.

        """
        prompt = self._build_user_prompt(url, html)

        try:
            if self._use_deps:
                deps = DiscoveryDeps(
                    contract=self._contract,
                    url=url,
                    target_level=self.target_level,
                    html=html,
                )
                result = await self.agent.run(prompt, deps=deps)
            else:
                result = await self.agent.run(prompt)

            self.console.print('[success]  ✓ AI found selectors[/success]')
            return cast(BaseModel, result.output)

        except Exception as e:
            error_msg = str(e)

            if 'tool_use_failed' in error_msg or 'invalid_request_error' in error_msg:
                self.console.print('[danger]  ✗ AI failed to generate structured output[/danger]')
            else:
                self.console.print(f'[danger]  ✗ Error getting selectors from AI: {e}[/danger]')

            logfire.error('AI request failed', error=error_msg, provider=self.provider)
            raise LLMGenerationError(f'AI discovery failed: {error_msg}') from e

    def _build_user_prompt(self, url: str, html: str) -> str:
        """Build the user prompt for AI discovery.

        When using deps (auto-created agent), field descriptions are injected via system
        prompts — the user message only needs to provide the HTML.
        When using a custom agent, include field descriptions in the user message.

        Args:
            url: URL for context
            html: Cleaned HTML content

        Returns:
            Formatted prompt string

        """
        if self._use_deps:
            return build_user_prompt(url, html)

        descriptions = self._contract.field_descriptions()
        fields_text = '\n'.join(f'**{name}** - {desc}' for name, desc in descriptions.items())
        return build_custom_agent_prompt(url, html, fields_text)

    def _is_all_na(self, selectors: dict) -> bool:
        """Check if AI returned all NA (gave up).

        Args:
            selectors: The selectors gotten from the LLM

        Returns:
            True if all the selectors are NA or None, otherwise False

        """
        for field_sel in selectors.values():
            for v in field_sel.values():
                if v and v != 'NA':
                    return False
        return True
