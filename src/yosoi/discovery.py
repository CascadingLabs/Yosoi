"""
discovery.py
=====================
AI-powered CSS selector discovery by reading raw HTML.
"""

from typing import Any

import logfire
from bs4 import BeautifulSoup, Tag
from pydantic_ai import Agent
from rich.console import Console

from yosoi.llm_config import LLMConfig, create_model
from yosoi.models import ScrapingConfig


class SelectorDiscovery:
    """Discovers CSS selectors using AI to read HTML."""

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        agent: Agent | None = None,
        console: Console | None = None,
        debug_mode: bool = False,
        remove_sidebars: bool = False,
    ):
        self.console = console or Console()
        self.fallback_selectors = self._get_fallback_selectors()
        self.debug_mode = debug_mode
        self.remove_sidebars = remove_sidebars

        # System prompt for the agent
        system_prompt = (
            'You are analyzing HTML to find CSS selectors for web scraping. '
            'Return selectors that actually exist in the provided HTML. '
            'CRITICAL: You must return valid JSON only. No preamble, no markdown formatting, '
            'no code fences. Just pure JSON matching the ScrapingConfig schema.'
        )

        # Priority: agent > llm_config
        if agent is not None:
            self.agent: Agent[None, ScrapingConfig] = agent
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
    def discover_from_html(self, url: str, html: str) -> dict[str, Any] | None:
        """
        Main method: Extract relevant HTML and ask AI for selectors.

        Returns None if discovery fails - pipeline handles retries.
        """
        logfire.info('Starting discovery for {url}', url=url)

        # Extract clean HTML for analysis
        clean_html = self._extract_content_html(html)

        if self.debug_mode:
            self._debug_save_html(url, clean_html)

        # Ask AI to find selectors - returns as ScrapingConfig object
        selectors_obj = self._get_selectors_from_ai(url, clean_html)

        if selectors_obj:
            selectors = selectors_obj.model_dump()

            if selectors and not self._is_all_na(selectors):
                logfire.info('Selectors found successfully', selectors=selectors)
                return selectors

        logfire.warn('Discovery failed - AI returned no/invalid selectors', url=url)
        return None

    @logfire.instrument('bs4_extract_content', extract_args=False)
    def _extract_content_html(self, html: str) -> str:  # noqa: C901
        """Extract the main content area from HTML."""
        soup = BeautifulSoup(html, 'html.parser')

        # Step 1: Remove noise that's never useful
        for tag in soup.find_all(['script', 'style', 'noscript', 'iframe']):
            tag.decompose()

        # Step 2: Remove header, nav, footer
        for tag in soup.find_all(['header', 'nav', 'footer']):
            tag.decompose()

        # Step 3: Optionally remove sidebars, widgets, ads
        if self.remove_sidebars:
            for selector in [
                '.sidebar',
                '.widget',
                '#sidebar',
                '.advertisement',
                '.ad',
                '[class*="ad-"]',
                '[id*="ad-"]',
                '.related-posts',
                '.useful-links',
            ]:
                for element in soup.select(selector):
                    element.decompose()
            self.console.print('  → Removed sidebars/widgets/ads')

        # Step 4: Get body or main content
        body = soup.find('body')

        if body and isinstance(body, Tag):
            content_str = str(body)[:30000]  # Limit to 30k chars
            self.console.print(f'  → Using entire <body> ({len(content_str)} chars)')
            return content_str

        # Fallback: Try main tag
        main = soup.find('main')
        if main and isinstance(main, Tag):
            content_str = str(main)[:30000]
            self.console.print(f'  → No <body> found, using <main> ({len(content_str)} chars)')
            return content_str

        # Last resort: use entire soup
        content_str = str(soup)[:30000]
        self.console.print(f'  → No <body> or <main> found, using full HTML ({len(content_str)} chars)')
        return content_str

    @logfire.instrument('llm_discovery_request')
    def _get_selectors_from_ai(self, url: str, html: str) -> ScrapingConfig | None:
        """Ask AI to find CSS selectors by reading the HTML."""

        prompt = f"""Analyze this HTML and find CSS selectors for web scraping.

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
            return result.output  # type: ignore[no-any-return]

        except Exception as e:
            error_msg = str(e)

            # Check for structured output failures
            if 'tool_use_failed' in error_msg or 'invalid_request_error' in error_msg:
                self.console.print('[danger]  ✗ AI failed to generate valid JSON structure[/danger]')
            else:
                self.console.print(f'[danger]  ✗ Error getting selectors from AI: {e}[/danger]')

            logfire.error('AI request failed', error=error_msg, provider=self.provider)
            return None

    def _is_all_na(self, selectors: dict) -> bool:
        """Check if AI returned all NA (gave up)."""
        return all(all(v == 'NA' for v in field_sel.values()) for field_sel in selectors.values())

    def _get_fallback_selectors(self) -> dict:
        """Return generic heuristic selectors when AI fails."""
        return {
            'headline': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'h3'},
            'author': {'primary': "a[href*='author']", 'fallback': '.author', 'tertiary': '.byline'},
            'date': {'primary': 'time', 'fallback': '.published', 'tertiary': '.date'},
            'body_text': {'primary': 'article p', 'fallback': '.content p', 'tertiary': 'p'},
            'related_content': {'primary': 'aside a', 'fallback': '.related a', 'tertiary': '.sidebar a'},
        }

    def _debug_save_html(self, url: str, html: str):
        """Save extracted HTML to file for debugging."""
        import os
        from urllib.parse import urlparse

        # Create debug directory
        os.makedirs('debug_html', exist_ok=True)

        # Create safe filename from URL
        parsed = urlparse(url)
        filename = f'{parsed.netloc}_{parsed.path.replace("/", "_")[:50]}.html'
        filepath = os.path.join('debug_html', filename)

        # Save HTML
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f'<!-- URL: {url} -->\n')
            f.write(f'<!-- Extracted HTML length: {len(html)} chars -->\n\n')
            f.write(html)

        self.console.print(f'  [dim]→ Debug HTML saved to: {filepath}[/dim]')
