"""Cleans and extracts relevant HTML content for selector discovery and extraction."""

import re

from bs4 import BeautifulSoup, Comment, Tag
from rich.console import Console


class HTMLCleaner:
    """Cleans HTML by removing noise and extracting main content.

    Attributes:
        console: Rich console instance for formatted output

    """

    def __init__(self, console: Console | None = None):
        """Initialize the HTML cleaner.

        Args:
            console: Rich console instance for formatted output. Defaults to None (creates new Console).

        """
        self.console = console or Console()

    def clean_html(self, html: str) -> str:
        """Extract and clean the main content area from HTML.

        Args:
            html: Raw HTML content to clean

        Returns:
            Cleaned HTML string with noise removed and content extracted.

        """
        soup = BeautifulSoup(html, 'lxml')

        # Step 1: Remove noise that's never useful
        for tag in soup.find_all(['script', 'style', 'noscript', 'iframe']):
            tag.decompose()

        # Step 2: Remove header, nav, footer
        for tag in soup.find_all(['header', 'nav', 'footer']):
            tag.decompose()

        # Step 3: Remove sidebars, widgets, ads (always enabled)
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
        self.console.print('  ↻ Removed sidebars/widgets/ads')

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
            content_soup = BeautifulSoup(str(content), 'lxml')
            content_soup = self._compress_html_simple(content_soup)

            # Convert to string and collapse whitespace
            content_str = str(content_soup)
            content_str = self._collapse_whitespace(content_str)

            # Warn if content is large but pass through untruncated
            WARN_CHARS = 30_000
            if len(content_str) > WARN_CHARS:
                self.console.print(
                    f'  ⚠ Content is {len(content_str):,} chars (above {WARN_CHARS:,} warning threshold)'
                )
            final_str = content_str

            # Calculate savings
            compression_ratio = (1 - len(content_str) / original_size) * 100 if original_size > 0 else 0

            self.console.print(
                f'  ↻ Using {extraction_method}: '
                f'{original_size:,} → {len(content_str):,} chars '
                f'({compression_ratio:.0f}% savings)'
            )

            return final_str

        # Fallback
        return str(self._compress_html_simple(soup))

    def _compress_html_simple(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Compress HTML safely for selector discovery.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Compressed BeautifulSoup parsed HTML.

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

        # 6. Remove non-semantic bloat (svg, canvas, base64, empty deep divs)
        self._prune_non_semantic(soup)

        return soup

    def _prune_non_semantic(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Remove non-semantic bloat from parsed HTML.

        Strips SVG/canvas elements, base64 image data URIs, and deeply nested
        empty divs/spans that contribute no meaningful content.

        Args:
            soup: BeautifulSoup parsed HTML to prune in-place

        Returns:
            The pruned BeautifulSoup object (mutated in-place).

        """
        # Strip <svg> and <canvas> entirely
        for tag in soup.find_all(['svg', 'canvas']):
            tag.decompose()

        # Strip base64 inline image data (src="data:image/...")
        for tag in soup.find_all(True):
            if isinstance(tag, Tag):
                src = tag.get('src', '')
                if isinstance(src, str) and src.startswith('data:'):
                    tag['src'] = '[data-uri-removed]'

        # Strip deeply nested anonymous divs/spans (depth > 8, no class/id/data-* attrs, empty text)
        for tag in reversed(soup.find_all(['div', 'span'])):
            if not isinstance(tag, Tag):
                continue
            has_semantic_attrs = (
                'class' in tag.attrs or 'id' in tag.attrs or any(k.startswith('data-') for k in tag.attrs)
            )
            if has_semantic_attrs:
                continue
            depth = sum(1 for _ in tag.parents)
            if depth > 8 and len(tag.get_text(strip=True)) == 0:
                tag.decompose()

        return soup

    def _collapse_whitespace(self, html: str) -> str:
        """Collapse excessive whitespace.

        Args:
            html: HTML content to condense

        Returns:
            Compressed version of the HTML.

        """
        # Multiple spaces → single space
        html = re.sub(r'[ \t]+', ' ', html)
        # Multiple newlines → single newline
        html = re.sub(r'\n+', '\n', html)
        # Remove leading/trailing whitespace per line
        lines = [line.strip() for line in html.split('\n') if line.strip()]
        return '\n'.join(lines)
