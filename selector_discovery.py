"""
selector_discovery.py
=====================
AI-powered CSS selector discovery by reading raw HTML.
"""

import json
from typing import Any

from bs4 import BeautifulSoup, Tag
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.groq import GroqProvider
from rich.console import Console

from models import ScrapingConfig


class SelectorDiscovery:
    """Discovers CSS selectors using AI to read HTML."""

    def __init__(self, model_name: str, api_key: str, provider: str = 'groq', console: Console = None):
        self.model_name = model_name
        self.provider = provider
        self.console = console or Console()
        self.fallback_selectors = self._get_fallback_selectors()

        # Set appropriate API key and model string based on provider
        if provider == 'groq':
            model = GroqModel(model_name, provider=GroqProvider(api_key=api_key))
        elif provider == 'gemini':
            model = GoogleModel(model_name, provider=GoogleProvider(api_key=api_key))
        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'groq' or 'gemini'")

        self.agent: Agent[None, ScrapingConfig] = Agent(
            model,
            output_type=ScrapingConfig,
            system_prompt=(
                'You are analyzing HTML to find CSS selectors for web scraping. '
                'Return selectors that actually exist in the provided HTML.'
            ),
        )

    def discover_from_html(self, url: str, html: str, max_retries: int = 3) -> dict[str, Any]:
        """
        Main method: Extract relevant HTML and ask AI for selectors.

        Args:
            url: The URL being analyzed
            html: Raw HTML content

        Returns:
            Dict of selectors organized by field
        """
        # Extract clean HTML for analysis
        clean_html = self._extract_content_html(html)

        # Convert Pydantic object to dict
        selectors: dict[str, Any] | None = None
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                self.console.print(f'[warning]  Retry attempt {attempt}/{max_retries}...[/warning]')

            # Ask AI to find selectors returns as ScrapingConfig
            selectors_obj = self._get_selectors_from_ai(url, clean_html)

            # Convert Pydantic object to dict
            if selectors_obj:
                selectors = json.loads(selectors_obj.model_dump_json())

                if selectors and not self._is_all_na(selectors):
                    if attempt > 1:
                        self.console.print(f'[success]  ✓ Retry successful on attempt {attempt}[/success]')
                    break

            if attempt < max_retries:
                self.console.print(
                    f'[warning]  ⚠ Attempt {attempt} failed - AI returned no/invalid selectors[/warning]'
                )
            selectors = None

        # Use fallback if AI fails
        if not selectors or self._is_all_na(selectors):
            self.console.print('[warning]  ⚠ All {max_retries} attempts failed, using fallback heuristics[/warning]')
            selectors = self.fallback_selectors

        return selectors

    def _extract_content_html(self, html: str) -> str:
        """Extract the main content area from HTML."""
        soup = BeautifulSoup(html, 'html.parser')

        # Remove noise and navigation elements
        for tag in soup.find_all(['script', 'style', 'svg', 'path', 'noscript', 'iframe']):
            tag.decompose()

        # Remove navigation, header, footer, sidebar
        for tag in soup.find_all(['nav', 'header', 'footer']):
            tag.decompose()

        # Remove common sidebar/widget classes
        for selector in ['.sidebar', '.widget', '.advertisement', '.ad', '#sidebar', '.related-posts']:
            for element in soup.select(selector):
                element.decompose()

        # Try to find main content area (in priority order)
        content_selectors = [
            'article',
            'main',
            '[role="main"]',
            '.post',
            '.entry',
            '.article',
            '.content',
            '#content',
            '.article-content',
            '.post-content',
            '.entry-content',
            '#main-content',
            '.main-content',
        ]

        main_content: Tag | None = None
        for selector in content_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                self.console.print(f"  → Extracted content from '[cyan]{selector}[/cyan]'")
                break

        # Fallback: Look for div with most paragraphs (likely the article)
        if not main_content:
            divs = soup.find_all('div')
            if divs:
                # Find div with most <p> tags
                best_div = max(divs, key=lambda d: len(d.find_all('p')))
                if len(best_div.find_all('p')) >= 3:
                    main_content = best_div
                    self.console.print(f'  → Found content div with {len(best_div.find_all("p"))} paragraphs')

        # Last resort: use body
        if not main_content:
            body_element = soup.find('body')
            if isinstance(body_element, Tag):
                main_content = body_element
                self.console.print('  → Extracted content from <body> tag (last resort)')
            else:
                self.console.print('  → Using full HTML')
                return str(soup)[:30000]

        # Return first 30k characters
        content_str = str(main_content)[:30000]
        self.console.print(f'  → Analyzing {len(content_str)} characters')
        return content_str

    def _get_selectors_from_ai(self, url: str, html: str) -> ScrapingConfig | None:
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
- **fallback**: Less specific but reliable
- **tertiary**: Generic (just tag name, or "NA" if field doesn't exist)

IMPORTANT RULES:
1. Only use class names and IDs that ACTUALLY appear in the HTML above
2. Avoid selectors that would match navigation, menus, headers, or footer elements
3. For headline: find h1/h2 INSIDE the article content, not in page navigation
4. For body_text: find paragraphs that are part of the article, not ads/sidebars/upcoming events"""

        try:
            result = self.agent.run_sync(prompt)
            self.console.print('[success]  ✓ AI found selectors[/success]')
            return result.output  # type: ignore[no-any-return]

        except Exception as e:
            self.console.print(f'[danger]  ✗ Error getting selectors from AI: {e}[/danger]')
            import traceback

            self.console.print(f'[dim]{traceback.format_exc()}[/dim]')
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
