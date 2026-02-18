"""AI-powered selector discovery by reading cleaned HTML."""

from typing import Any, cast

import logfire
from pydantic_ai import Agent
from rich.console import Console

from yosoi.exceptions import LLMGenerationError
from yosoi.llm_config import LLMConfig, create_model
from yosoi.models import ScrapingConfig


class SelectorDiscovery:
    """Discovers selectors using AI to read cleaned HTML.

    Attributes:
        console: Rich console instance for formatted output
        fallback_selectors: Second level of selectors to choose from
        agent: The LLM agent that will be used
        model_name: Name of the model being used
        provider: Name of the LLM provider

    """

    console: Console
    agent: Agent[Any, ScrapingConfig]
    model_name: str
    provider: str

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        agent: Agent[Any, ScrapingConfig] | None = None,
        console: Console | None = None,
    ):
        """Initialize the discovery with LLM configuration or an agent.

        Args:
            llm_config: Configuration for the LLM provider and model
            agent: The LLM agent that will be used
            console: Rich console instance for formatted output

        Raises:
            ValueError: Must provide llm_config or an agent

        """
        self.console = console or Console()

        # System prompt for the agent
        system_prompt = (
            'You are analyzing HTML to find selectors for web scraping. '
            'Return selectors that actually exist in the provided HTML. '
            'CRITICAL: You must return valid JSON only. No preamble, no markdown formatting, '
            'no code fences. Just pure JSON matching the ScrapingConfig schema.'
        )

        # Priority: agent > llm_config
        if agent is not None:
            self.agent = agent
            self.model_name = 'custom-agent'
            self.provider = 'custom'
        elif llm_config is not None:
            model = create_model(llm_config)
            self.agent = Agent(model, output_type=ScrapingConfig, system_prompt=system_prompt)
            self.model_name = llm_config.model_name
            self.provider = llm_config.provider
        else:
            raise ValueError('Either provide llm_config or agent parameter')

    @logfire.instrument('discover_selectors', extract_args=False)
    def discover_selectors(self, html: str, url: str | None = None) -> dict[str, Any] | None:
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
            # Ask AI to find selectors - returns as ScrapingConfig object
            selectors_obj = self._get_selectors_from_ai(url_context, html)

            if selectors_obj:
                selectors: dict[str, Any] = selectors_obj.model_dump()

                if selectors and not self._is_all_na(selectors):
                    logfire.info('Selectors found successfully', selectors=selectors)
                    return selectors

        except LLMGenerationError as e:
            logfire.warn('Discovery failed - AI error', error=str(e), url=url_context)
            return None

        logfire.warn('Discovery failed - AI returned no/invalid selectors', url=url_context)
        return None

    @logfire.instrument('llm_discovery_request')
    def _get_selectors_from_ai(self, url: str, html: str) -> ScrapingConfig | None:
        """Ask AI to find selectors by reading the HTML.

        Args:
            url: URL from which the HTML was obtained
            html: HTML content to give to LLM

        Returns:
            ScrapingConfig object with discovered selectors, or None if request failed.

        """
        prompt = f"""Analyze this HTML and find selectors for web scraping.

Here is the HTML from {url}:
```html
{html}
```

Find CSS selectors for these fields:

**headline** - Main article title (h1/h2 in article, NOT navigation)
**author** - Author name (author/byline classes or links)
**date** - Publication date (time tags or date/published classes)
**body_text** - Article paragraphs (p tags in article, NOT sidebars/ads)
**related_content** - Related article links (aside/sidebar sections)

For each field provide three selectors:
- primary: Most specific selector using actual classes/IDs from the HTML
- fallback: Less specific but reliable selector
- tertiary: Generic selector or "NA" if field doesn't exist

IMPORTANT: Only use selectors that actually exist in the HTML above.

Return ONLY the JSON object, nothing else."""

        try:
            result = self.agent.run_sync(prompt)
            self.console.print('[success]  ✓ AI found selectors[/success]')
            return cast(ScrapingConfig, result.output)

        except Exception as e:
            error_msg = str(e)

            # Check for structured output failures
            if 'tool_use_failed' in error_msg or 'invalid_request_error' in error_msg:
                self.console.print('[danger]  ✗ AI failed to generate valid JSON structure[/danger]')
            else:
                self.console.print(f'[danger]  ✗ Error getting selectors from AI: {e}[/danger]')

            logfire.error('AI request failed', error=error_msg, provider=self.provider)
            raise LLMGenerationError(f'AI discovery failed: {error_msg}') from e

    def _is_all_na(self, selectors: dict) -> bool:
        """Check if AI returned all NA (gave up).

        Args:
            selectors: The selectors gotten from the LLM

        Returns:
            True if all the selectors are NA, otherwise False

        """
        return all(all(v == 'NA' for v in field_sel.values()) for field_sel in selectors.values())
