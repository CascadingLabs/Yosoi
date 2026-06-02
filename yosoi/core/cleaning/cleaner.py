"""Cleans and extracts relevant HTML content for selector discovery and extraction."""

import re

import lxml.html
from lxml.html import HtmlElement
from rich.console import Console

# Attributes stripped during cleaning. This is a deny-list: everything not named
# here is kept, so we never silently lose a selector-worthy attribute (e.g. the
# bare depth/score/permalink attributes on Reddit's <shreddit-comment>). Only
# attributes that are never useful as selectors and bloat the token budget go
# here: inline styles and JS event handlers (any ``on*`` attribute).
_DROP_ATTRIBUTES = {'style'}


def _keep_attribute(attr: str) -> bool:
    """Return True unless the attribute is known noise (inline style / event handler)."""
    lowered = attr.lower()
    if lowered in _DROP_ATTRIBUTES:
        return False
    return not lowered.startswith('on')


def _drop(element: HtmlElement) -> None:
    """Detach *element* from the tree if it is still attached.

    ``drop_tree`` preserves the element's tail text (the run of text after its
    closing tag) by reparenting it — matching BeautifulSoup's ``decompose``,
    which leaves following sibling text in place. We guard on ``getparent`` so a
    node already removed as a descendant of an earlier-dropped parent (still in
    the statically collected list) is skipped instead of raising.
    """
    if element.getparent() is not None:
        element.drop_tree()


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
        if not html or not html.strip():
            return ''

        tree = lxml.html.document_fromstring(html)

        # Step 1: Remove noise that's never useful
        for tag in tree.xpath('.//script | .//style | .//noscript | .//iframe'):
            _drop(tag)

        # Step 2: Remove header, nav, footer
        for tag in tree.xpath('.//header | .//nav | .//footer'):
            _drop(tag)

        # Step 3: Remove common chrome/ad boilerplate. Deliberately conservative —
        # NO substring matchers ([class*="ad-"] also nuked legit nodes like "bread-crumb"
        # or "road-map"), and NO content-bearing class guesses (.related-posts /
        # .useful-links): those can be exactly what a contract targets (e.g. ys.RelatedContent),
        # and this cleaning runs *before* discovery and selector verification.
        for selector in ['.sidebar', '#sidebar', '.widget', '.advertisement', '.ad']:
            for element in tree.cssselect(selector):
                _drop(element)
        self.console.print('  ↻ Removed sidebar/widget/ad boilerplate')

        # Step 4: Get body or main content
        body = tree.find('.//body')
        content: HtmlElement | None = None
        extraction_method = ''

        if body is not None:
            # Check for <main> inside <body> (most specific!)
            main_in_body = body.find('.//main')
            if main_in_body is not None:
                content = main_in_body
                extraction_method = '<main> inside <body>'
            else:
                content = body
                extraction_method = '<body>'
        else:
            # No <body>, try top-level <main>
            main = tree.find('.//main')
            if main is not None:
                body_in_main = main.find('.//body')
                if body_in_main is not None:
                    content = body_in_main
                    extraction_method = '<body> inside <main>'
                else:
                    content = main
                    extraction_method = '<main>'
            else:
                content = tree
                extraction_method = 'full HTML'

        # Step 5: Compress HTML (mutates *content* in place — no re-parse)
        original_size = len(lxml.html.tostring(content, encoding='unicode'))
        content = self._compress_html_simple(content)

        # Convert to string and collapse whitespace
        content_str = lxml.html.tostring(content, encoding='unicode')
        content_str = self._collapse_whitespace(content_str)

        # Warn if content is large but pass through untruncated
        WARN_CHARS = 30_000
        if len(content_str) > WARN_CHARS:
            self.console.print(f'  ⚠ Content is {len(content_str):,} chars (above {WARN_CHARS:,} warning threshold)')

        # Calculate savings
        compression_ratio = (1 - len(content_str) / original_size) * 100 if original_size > 0 else 0

        self.console.print(
            f'  ↻ Using {extraction_method}: '
            f'{original_size:,} → {len(content_str):,} chars '
            f'({compression_ratio:.0f}% savings)'
        )

        return content_str

    def _compress_html_simple(self, tree: HtmlElement) -> HtmlElement:
        """Compress HTML safely for selector discovery.

        Args:
            tree: lxml element to compress in-place

        Returns:
            The compressed element (mutated in-place).

        """
        # 1. Remove HTML comments
        for comment in tree.xpath('.//comment()'):
            _drop(comment)

        # 2. Strip only known-noise attributes (opt-in removal, not opt-in keeping).
        #
        # A keep-allowlist silently discards selector-worthy attributes we never
        # anticipated — the classic failure mode. Reddit, for example, stashes
        # depth/score/permalink/author as *bare* attributes on <shreddit-comment>;
        # an allowlist drops them and discovery can never target them. So we keep
        # every attribute by default and remove only attributes that are never
        # useful as selectors and bloat the token budget: inline styles and
        # JS event handlers.
        for tag in tree.iter():
            if not isinstance(tag.tag, str):
                continue
            for attr in list(tag.attrib):
                if not _keep_attribute(attr):
                    del tag.attrib[attr]

        # 3. Deduplicate list items (keep first 3)
        for lst in tree.xpath('.//ul | .//ol'):
            items = lst.findall('li')  # direct children only
            for item in items[3:]:
                _drop(item)

        # 4. Deduplicate table rows (keep first 5)
        for table in tree.xpath('.//table'):
            rows = table.xpath('.//tr')
            for row in rows[5:]:
                _drop(row)

        # 5. Remove hidden elements.
        # iter() is materialised into a list first so dropping a node doesn't
        # disturb a live traversal; a node already detached as a descendant of
        # an earlier-dropped parent is skipped by _drop's getparent guard.
        for tag in list(tree.iter()):
            if not isinstance(tag.tag, str):
                continue
            if tag.get('hidden') is not None or tag.get('aria-hidden') == 'true':
                _drop(tag)

        # 6. Remove non-semantic bloat (svg, canvas, base64, empty deep divs)
        self._prune_non_semantic(tree)

        return tree

    def _prune_non_semantic(self, tree: HtmlElement) -> HtmlElement:
        """Remove non-semantic bloat from parsed HTML.

        Strips SVG/canvas elements, base64 image data URIs, and deeply nested
        empty divs/spans that contribute no meaningful content.

        Args:
            tree: lxml element to prune in-place

        Returns:
            The pruned element (mutated in-place).

        """
        # Strip <svg> and <canvas> entirely
        for tag in tree.xpath('.//svg | .//canvas'):
            _drop(tag)

        # Strip base64 inline image data (src="data:image/...")
        for tag in tree.iter():
            if not isinstance(tag.tag, str):
                continue
            src = tag.get('src', '')
            if src.startswith('data:'):
                tag.set('src', '[data-uri-removed]')

        # Strip deeply nested anonymous divs/spans (depth > 8, no class/id/data-* attrs, empty text)
        for tag in reversed(tree.xpath('.//div | .//span')):
            has_semantic_attrs = (
                'class' in tag.attrib or 'id' in tag.attrib or any(k.startswith('data-') for k in tag.attrib)
            )
            if has_semantic_attrs:
                continue
            depth = sum(1 for _ in tag.iterancestors())
            if depth > 8 and len(tag.text_content().strip()) == 0:
                _drop(tag)

        return tree

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
