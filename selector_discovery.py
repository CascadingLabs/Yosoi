"""
selector_discovery.py
=====================
AI-powered CSS selector discovery by reading raw HTML.
"""

import json
from typing import Any

import logfire
from bs4 import BeautifulSoup, Tag
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.groq import GroqProvider
from rich.console import Console

from models import ScrapingConfig
from services import configure_logfire

# 1. Configure Logfire and instrument Pydantic
# This automatically traces Pydantic model validation and Pydantic AI agents
configure_logfire()
logfire.instrument_pydantic()


class SelectorDiscovery:
    """Discovers CSS selectors using AI to read HTML."""

    def __init__(
        self, model_name: str, api_key: str, provider: str = 'groq', console: Console = None, debug_mode: bool = False
    ):
        self.model_name = model_name
        self.provider = provider
        self.console = console or Console()
        self.fallback_selectors = self._get_fallback_selectors()
        self.debug_mode = debug_mode

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

                # Convert Pydantic object to dict
                if selectors_obj:
                    selectors = json.loads(selectors_obj.model_dump_json())

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

        # Remove noise
        for tag in soup.find_all(['script', 'style', 'svg', 'path', 'noscript', 'iframe']):
            tag.decompose()
        for tag in soup.find_all(['nav', 'header', 'footer']):
            tag.decompose()
        for selector in [
            '.sidebar',
            '.widget',
            '.advertisement',
            '.ad',
            '#sidebar',
            '.related-posts',
            '.useful-links',
            '.useful-link-item',
        ]:
            element: Tag | None
            for element in soup.select(selector):
                element.decompose()

        main_content: Tag | None = None
        best_score = 0

        # Step 1: Try hard-coded selectors
        content_selectors = [
            # Standard HTML5 semantic tags
            'article',
            'main',
            '[role="main"]',
            # Blog platform specific
            '.blog-post-full__body',  # Google Workspace blog
            '.post-body',
            '.entry-content',
            '.post-content',
            '.article-content',
            '.blog-post-body',
            # Generic content containers
            '.post',
            '.entry',
            '.article',
            '.content',
            '#content',
            '#main-content',
            '.main-content',
        ]

        for selector in content_selectors:
            element = soup.select_one(selector)
            if element is not None:
                score = self._calculate_content_score(element)
                if score > best_score:
                    main_content = element
                    best_score = score
                    self.console.print(f"  → Found content with '[cyan]{selector}[/cyan]' (score: {score})")
                    break

        # Step 2: Try div scoring
        if main_content is None or best_score == 0:
            divs = soup.find_all('div')
            if divs:
                for div in divs:
                    score = self._calculate_content_score(div)
                    if score > best_score:
                        best_score = score
                        main_content = div

                if main_content and best_score > 0:
                    p_count = len(main_content.find_all('p'))
                    self.console.print(f'  → Found content div with {p_count} paragraphs (score: {best_score})')

        # Step 3: Manual div search if score still 0
        if best_score == 0:
            self.console.print('  [warning]⚠ Score is 0 - searching for any content div...[/warning]')
            for div in soup.find_all('div'):
                score = self._calculate_content_score(div)
                if score > 10:  # At least some content
                    main_content = div
                    best_score = score
                    self.console.print(f'  → Found fallback div with score: {score}')
                    break

        # Step 4: Fallback to body
        if main_content is None or best_score == 0:
            body_element = soup.find('body')
            if isinstance(body_element, Tag):
                main_content = body_element
                self.console.print('  → Extracted content from <body> tag')

        # Last resort
        if main_content is None:
            self.console.print('  → Using full HTML (all content selectors failed)')
            return str(soup)[:30000]

        content_str = str(main_content)[:30000]
        self.console.print(f'  → Analyzing {len(content_str)} characters')
        return content_str

    def _calculate_content_score(self, element: Tag) -> int:
        """Calculate quality score for a content element."""
        score = 0

        p_count = len(element.find_all('p'))
        score += p_count * 10

        h_count = len(element.find_all(['h1', 'h2', 'h3']))
        score += h_count * 5

        a_count = len(element.find_all('a'))
        if p_count > 0 and a_count > p_count * 2:
            score -= 20

        text_length = len(element.get_text(strip=True))
        if text_length < 200:
            score -= 10

        return score

    # 4. Instrument the AI call
    # Pydantic AI automatically instruments the agent internals, but this outer span
    # captures the full context of prompt construction + execution.
    @logfire.instrument('llm_discovery_request')
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
