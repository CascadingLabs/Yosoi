"""
discovery.py
=====================
AI-powered CSS selector discovery by reading raw HTML.
"""

import re
from typing import Any

import logfire
from bs4 import BeautifulSoup, Comment, Tag
from pydantic_ai import Agent
from rich.console import Console

from yosoi.llm_config import LLMConfig, create_model
from yosoi.models import ScrapingConfig


class SelectorDiscovery:
    """Discovers CSS selectors using AI to read HTML.

    Attributes:
        console: Rich console instance for formatted output
        fallback_selectors: Second level of selectors to choose from
        debug_mode: If enabled will give entire HTML
        remove_sidebars: Enabled automatically and will remove the sidebars and more from HTML
        system_prompt: The start of the prompt to give to the LLM
    """

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        agent: Agent | None = None,
        console: Console | None = None,
        debug_mode: bool = False,
        remove_sidebars: bool = False,
    ):
        """Initialize the discovery with LLM configuration or an agent

        Args:
            llm_config: Configuration for the LLM provider and model
            agent: The LLM agent that will be used
            console: Rich console instance for formatted output
            debug_mode: If enabled will give entire HTML
            remove_sidebars: Enabled automatically and will remove the sidebars and more from HTML

        Raises:
            ValueError: Must provide llm_config or an agent
        """
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
        """Main method: Extract relevant HTML and ask AI for selectors.

        Args:
            url: The URL that is being scraped
            html: The HTML of the URL

        Returns: 
            Dictionary of discovered selectors if found, None if discovery fails.
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

    def _compress_html_simple(self, soup: BeautifulSoup) -> BeautifulSoup:  # noqa: C901
        """Simple, safe HTML compression for selector discovery.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            The compressed BeautifulSoup parsed HTML
        """
        # 1. Remove HTML comments
        for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
            comment.extract()

        # 2. Remove attributes not used in CSS selectors
        KEEP_ATTRIBUTES = {'class', 'id', 'href', 'src', 'datetime', 'alt', 'name', 'type'}

        for tag in soup.find_all(True):
            if isinstance(tag, Tag) and tag.attrs:
                tag.attrs = {
                    attr: value
                    for attr, value in tag.attrs.items()
                    if attr in KEEP_ATTRIBUTES or attr.startswith('data-')
                }

        # 3. Deduplicate list items (keep first 3 as examples)
        for list_tag in soup.find_all(['ul', 'ol']):
            items = list_tag.find_all('li', recursive=False)
            if len(items) > 3:
                for item in items[3:]:
                    item.decompose()

        # 4. Deduplicate table rows (keep first 5)
        for table in soup.find_all('table'):
            rows = table.find_all('tr')
            if len(rows) > 5:
                for row in rows[5:]:
                    row.decompose()

        # 5. Remove hidden elements
        for tag in soup.find_all(True):
            if isinstance(tag, Tag):
                if tag.get('hidden') is not None:
                    tag.decompose()
                    continue
                if tag.get('aria-hidden') == 'true':
                    tag.decompose()

        return soup

    def _collapse_whitespace(self, html: str) -> str:
        """Collapse excessive whitespace.

        Args:
            html: HTML content to condense

        Returns:
            The compressed verion of the HTML
        """
        # Multiple spaces → single space
        html = re.sub(r'[ \t]+', ' ', html)
        # Multiple newlines → single newline
        html = re.sub(r'\n+', '\n', html)
        # Remove leading/trailing whitespace per line
        lines = [line.strip() for line in html.split('\n') if line.strip()]
        return '\n'.join(lines)

    @logfire.instrument('bs4_extract_content', extract_args=False)
    def _extract_content_html(self, html: str) -> str:  # noqa: C901
        """Extract the main content area from HTML.

        Args:
            html: HTML content to extract

        Returns:
            Portion of HTML that will be used to give to LLM
        """
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
        content = None
        extraction_method = ''

        if body and isinstance(body, Tag):
            # Check for <main> inside <body> (most specific!)
            main_in_body = body.find('main')
            if main_in_body and isinstance(main_in_body, Tag):
                content = main_in_body
                extraction_method = '<main> inside <body>'
            else:
                content = body
                extraction_method = '<body>'
        else:
            # No <body>, try top-level <main>
            main = soup.find('main')
            if main and isinstance(main, Tag):
                body_in_main = main.find('body')
                if body_in_main and isinstance(body_in_main, Tag):
                    content = body_in_main
                    extraction_method = '<body> inside <main>'
                else:
                    content = main
                    extraction_method = '<main>'
            else:
                content = soup
                extraction_method = 'full HTML'

        # Step 5: Compress HTML
        if content:
            original_size = len(str(content))

            # Apply compression
            content_soup = BeautifulSoup(str(content), 'html.parser')
            content_soup = self._compress_html_simple(content_soup)

            # Convert to string and collapse whitespace
            content_str = str(content_soup)
            content_str = self._collapse_whitespace(content_str)

            # Truncate to 30k
            final_str = content_str[:30000]

            # Calculate savings
            compression_ratio = (1 - len(content_str) / original_size) * 100 if original_size > 0 else 0

            self.console.print(
                f'  → Using {extraction_method}: '
                f'{original_size:,} → {len(content_str):,} chars '
                f'({compression_ratio:.0f}% savings)'
            )

            return final_str

        # Fallback
        return str(soup)[:30000]
        self.console.print(f'  → No <body> or <main> found, using full HTML ({len(content_str)} chars)')
        return content_str

    @logfire.instrument('llm_discovery_request')
    def _get_selectors_from_ai(self, url: str, html: str) -> ScrapingConfig | None:
        """Ask AI to find CSS selectors by reading the HTML.

        Args:
            url: URL from which the HTML was obtained
            html: HTML content to give to LLM

        Returns:
            ScrapingConfig object with discovered selectors, or None if request failed.
        """

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
        """Check if AI returned all NA (gave up).

        Args:
            selectors: The selectors gotten from the LLM

        Returns:
            True if all the selectors are NA, otherwise False
        """
        return all(all(v == 'NA' for v in field_sel.values()) for field_sel in selectors.values())

    def _get_fallback_selectors(self) -> dict:
        """Return generic heuristic selectors when AI fails.

        Returns:
            A dict of the average selectors of the data
        """
        return {
            'headline': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'h3'},
            'author': {'primary': "a[href*='author']", 'fallback': '.author', 'tertiary': '.byline'},
            'date': {'primary': 'time', 'fallback': '.published', 'tertiary': '.date'},
            'body_text': {'primary': 'article p', 'fallback': '.content p', 'tertiary': 'p'},
            'related_content': {'primary': 'aside a', 'fallback': '.related a', 'tertiary': '.sidebar a'},
        }

    def _debug_save_html(self, url: str, html: str):
        """Save extracted HTML to file for debugging.

        Args:
            url: URL from which the HTML was obtained
            html: HTML content to save
        """
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
