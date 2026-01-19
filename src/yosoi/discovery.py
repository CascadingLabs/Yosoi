"""
discovery.py
=====================
AI-powered CSS selector discovery by reading raw HTML.
"""

from typing import Any

import logfire
from bs4 import BeautifulSoup, Tag
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.groq import GroqProvider
from rich.console import Console

from yosoi.services import configure_logfire

# 1. Configure Logfire and instrument Pydantic
# This automatically traces Pydantic model validation and Pydantic AI agents
configure_logfire()
logfire.instrument_pydantic()


class SelectorDiscovery:
    """Discovers CSS selectors using AI to read HTML."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        provider: str = 'groq',
        console: Console | None = None,
        debug_mode: bool = False,
        remove_sidebars: bool = False,
    ):
        self.model_name = model_name
        self.provider = provider
        self.console = console or Console()
        self.fallback_selectors = self._get_fallback_selectors()
        self.debug_mode = debug_mode
        self.remove_sidebars = remove_sidebars

        # Set appropriate API key and model string based on provider
        if provider == 'groq':
            model = GroqModel(model_name, provider=GroqProvider(api_key=api_key))
        elif provider == 'gemini':
            model = GoogleModel(model_name, provider=GoogleProvider(api_key=api_key))
        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'groq' or 'gemini'")

        self.agent: Agent[None, str] = Agent(
            model,
            system_prompt=(
                'You are analyzing HTML to find CSS selectors for web scraping. '
                'Return selectors that actually exist in the provided HTML.'
            ),
        )

    # 2. Instrument the main entry point.
    # extract_args=False prevents sending the massive raw HTML string to Logfire logs.
    @logfire.instrument('discover_selectors', extract_args=False)
    def discover_from_html(self, url: str, html: str, max_retries: int = 3) -> dict[str, Any]:
        """
        Main method: Extract relevant HTML and ask AI for selectors.
        """
        # Manually log the URL since we disabled auto-arg extraction
        logfire.info('Starting discovery for {url}', url=url)

        # Extract clean HTML for analysis
        clean_html = self._extract_content_html(html)

        if self.debug_mode:
            self._debug_save_html(url, clean_html)

        # Convert Pydantic object to dict
        selectors: dict[str, Any] | None = None

        for attempt in range(1, max_retries + 1):
            # Create a span for each retry attempt to group them in the UI
            with logfire.span(f'attempt_{attempt}'):
                if attempt > 1:
                    msg = f'Retry attempt {attempt}/{max_retries}...'
                    self.console.print(f'[warning]  {msg}[/warning]')
                    logfire.warn(msg)

                # Ask AI to find selectors returns as ScrapingConfig
                selectors_obj = self._get_selectors_from_ai(url, clean_html)

                # AI now returns dict directly
                if selectors_obj:
                    selectors = selectors_obj

                    if selectors and not self._is_all_na(selectors):
                        if attempt > 1:
                            self.console.print(f'[success]  ✓ Retry successful on attempt {attempt}[/success]')

                        logfire.info('Selectors found successfully', selectors=selectors)
                        break

                if attempt < max_retries:
                    self.console.print(
                        f'[warning]  ⚠ Attempt {attempt} failed - AI returned no/invalid selectors[/warning]'
                    )
                selectors = None

        # Use fallback if AI fails
        if not selectors or self._is_all_na(selectors):
            self.console.print(f'[warning]  ⚠ All {max_retries} attempts failed, using fallback heuristics[/warning]')
            logfire.error('All attempts failed, using fallback', url=url)
            selectors = self.fallback_selectors

        return selectors

    # 3. Instrument the CPU-bound parsing logic
    # This helps you see how much time is spent cleaning HTML vs waiting for AI
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
            content_str = str(main)[:30000]  # ← FIX: Changed from str(body)
            self.console.print(f'  → No <body> found, using <main> ({len(content_str)} chars)')
            return content_str  # ← FIX: Added missing return

        # Last resort: use entire soup
        content_str = str(soup)[:30000]
        self.console.print(f'  → No <body> or <main> found, using full HTML ({len(content_str)} chars)')
        return content_str

    # 4. Instrument the AI call
    # Pydantic AI automatically instruments the agent internals, but this outer span
    # captures the full context of prompt construction + execution.
    @logfire.instrument('llm_discovery_request')
    def _get_selectors_from_ai(self, url: str, html: str) -> dict | None:
        """Ask AI to find CSS selectors by reading the HTML."""

        prompt = f"""CRITICAL INSTRUCTIONS:
1. Look at the ACTUAL class names, IDs, and attributes in the HTML below
2. Do NOT guess or make up common class names unless they actually appear
3. Return ONLY selectors that exist in the provided HTML

Here is the HTML from {url}:
```html
{html}
```

Analyze the HTML above and find CSS selectors for these fields:

**headline** - Main article title (look for h1, h2 with specific classes IN THE ARTICLE, NOT in navigation/header/menu)
**author** - Author name (look for links with "author" in href, or author/byline classes)
**date** - Publication date (look for <time> tags or date/published classes)
**body_text** - Article paragraphs (look for <p> tags inside article/content containers, NOT in sidebars/ads/events)
**related_content** - Related article links (look in aside, sidebar, or related sections)

For each field, return THREE selectors:
- **primary**: Most specific (using actual classes/IDs from the HTML)
- **fallback**: Less specific but reliable'''Allow running as: python -m yosoi'''
- **tertiary**: Generic (just tag name, or "NA" if field doesn't exist)

IMPORTANT RULES:
1. Only use class names and IDs that ACTUALLY appear in the HTML above
2. Avoid selectors that would match navigation, menus, headers, or footer elements
3. For headline: find h1/h2 INSIDE the article content, not in page navigation
4. For body_text: find paragraphs that are part of the article, not ads/sidebars/upcoming events"""

        try:
            result = self.agent.run_sync(prompt)
            text_output = result.output

            # Log raw output for debugging
            logfire.debug('AI raw response', response=text_output[:500])

            # Parse the simple text format
            selectors = self._parse_text_selectors(text_output)

            if selectors and not self._is_all_na(selectors):
                self.console.print('[success]  ✓ AI found selectors[/success]')
                return selectors
            self.console.print('[warning]  ⚠ Could not parse AI response or all NA[/warning]')
            return None

        except Exception as e:
            self.console.print(f'[danger]  ✗ Error getting selectors from AI: {e}[/danger]')
            logfire.error('AI request failed', error=str(e))
            return None

    def _parse_text_selectors(self, text: str) -> dict | None:
        """
        Parse simple text format into selector dictionary.

        Expected format:
            headline_primary: .primary h1
            headline_fallback: article h1
            headline_tertiary: h1
            author_primary: .primary .author
            ...

        Returns:
            {
                'headline': {'primary': '...', 'fallback': '...', 'tertiary': '...'},
                'author': {...},
                ...
            }
        """
        import re

        try:
            selectors = {'headline': {}, 'author': {}, 'date': {}, 'body_text': {}, 'related_content': {}}

            # Clean up the text - remove markdown code blocks if present
            text = text.strip()
            text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)  # Remove code blocks
            text = re.sub(r'`', '', text)  # Remove backticks

            lines_parsed = 0
            for line in text.split('\n'):
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue

                # Must have a colon
                if ':' not in line:
                    continue

                # Parse "field_priority: selector"
                parts = line.split(':', 1)
                if len(parts) != 2:
                    continue

                key = parts[0].strip()
                value = parts[1].strip()

                # Skip if value is empty
                if not value:
                    continue

                # Split field and priority
                if '_' not in key:
                    continue

                field, priority = key.rsplit('_', 1)

                # Validate field and priority
                if field in selectors and priority in ['primary', 'fallback', 'tertiary']:
                    selectors[field][priority] = value
                    lines_parsed += 1

            self.console.print(f'[dim]  → Parsed {lines_parsed} selector lines[/dim]')

            # Check if we got at least some valid selectors
            # Each field should have at least one priority
            valid_fields = sum(1 for field_sels in selectors.values() if len(field_sels) > 0)

            if valid_fields >= 3:  # At least 3 fields with selectors
                return selectors

            self.console.print(f'[warning]  ⚠ Only parsed {valid_fields} valid fields[/warning]')
            return None

        except Exception as e:
            self.console.print(f'[warning]  ⚠ Parse error: {e}[/warning]')
            logfire.error('Parse error', error=str(e), text=text[:200])
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
