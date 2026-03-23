"""Cleans and extracts relevant HTML content for selector discovery and extraction."""

from enum import IntEnum

from bs4 import BeautifulSoup
from rich.console import Console

from yosoi.core.cleaning.passes.budget import enforce_budget, estimate_tokens
from yosoi.core.cleaning.passes.classes import strip_utility_classes
from yosoi.core.cleaning.passes.compress import compress_html
from yosoi.core.cleaning.passes.content import extract_content
from yosoi.core.cleaning.passes.dedup import deduplicate_siblings
from yosoi.core.cleaning.passes.density import prune_by_density
from yosoi.core.cleaning.passes.flatten import flatten_wrappers
from yosoi.core.cleaning.passes.noise import remove_noise
from yosoi.core.cleaning.whitespace import collapse_whitespace


class CleaningLevel(IntEnum):
    """Escalation levels for HTML cleaning — lower = more aggressive.

    When discovery fails at an aggressive level, the pipeline can retry
    with a higher (less aggressive) level to preserve more content.
    """

    AGGRESSIVE = 0
    MODERATE = 1
    CONSERVATIVE = 2

    @property
    def next_level(self) -> 'CleaningLevel | None':
        """Return the next less-aggressive level, or None if already at max."""
        try:
            return CleaningLevel(self.value + 1)
        except ValueError:
            return None


class HTMLCleaner:
    """Cleans HTML by removing noise and extracting main content.

    Runs a pipeline of composable passes over the HTML tree.
    Supports escalation levels — when discovery fails, call
    ``clean_html(html, level=CleaningLevel.MODERATE)`` to retry
    with less aggressive cleaning and more preserved content.

    Attributes:
        console: Rich console instance for formatted output
        token_budget: Maximum estimated token count for the cleaned output

    """

    def __init__(self, console: Console | None = None, token_budget: int = 8000):
        """Initialize the HTML cleaner.

        Args:
            console: Rich console instance for formatted output. Defaults to None (creates new Console).
            token_budget: Maximum estimated tokens in cleaned output. 0 disables budget enforcement.
                          Defaults to 8000.

        """
        self.console = console or Console()
        self.token_budget = token_budget

    def clean_html(self, html: str, level: CleaningLevel = CleaningLevel.AGGRESSIVE) -> str:
        """Extract and clean the main content area from HTML.

        Args:
            html: Raw HTML content to clean
            level: Cleaning aggression level. AGGRESSIVE (default) applies all
                   passes; MODERATE skips dedup and density; CONSERVATIVE only
                   removes scripts/styles and collapses whitespace.

        Returns:
            Cleaned HTML string with noise removed and content extracted.

        """
        soup = BeautifulSoup(html, 'lxml')

        # Pass 1: Remove noise (scripts, styles, nav, sidebar, ads)
        remove_noise(soup)
        self.console.print('  ↻ Removed sidebars/widgets/ads')

        # Pass 2: Extract main content region
        content_soup, extraction_method = extract_content(soup)
        original_size = len(str(content_soup))

        # Pass 3: Flatten meaningless wrapper divs/spans
        flatten_wrappers(content_soup)

        # Pass 4: Compress (strip attrs, remove comments, hidden elements, non-semantic bloat)
        compress_html(content_soup)

        # Pass 5: Strip utility CSS classes (Tailwind, Bootstrap)
        strip_utility_classes(content_soup)

        # Pass 6-7: Only run destructive structural passes at AGGRESSIVE level
        if level <= CleaningLevel.AGGRESSIVE:
            deduplicate_siblings(content_soup)
            prune_by_density(content_soup)

        # Pass 8: Collapse whitespace
        content_str = collapse_whitespace(str(content_soup))

        # Pass 9: Enforce token budget (scale up for less aggressive levels)
        effective_budget = self.token_budget
        if level == CleaningLevel.MODERATE:
            effective_budget = max(self.token_budget, self.token_budget * 2)
        elif level >= CleaningLevel.CONSERVATIVE:
            effective_budget = 0  # No budget limit

        if effective_budget > 0:
            content_str = enforce_budget(content_str, effective_budget)

        # Warn if content is large
        WARN_CHARS = 30_000
        if len(content_str) > WARN_CHARS:
            self.console.print(f'  ⚠ Content is {len(content_str):,} chars (above {WARN_CHARS:,} warning threshold)')

        # Report savings
        compression_ratio = (1 - len(content_str) / original_size) * 100 if original_size > 0 else 0
        est_tokens = estimate_tokens(content_str)
        level_label = f' [{level.name}]' if level != CleaningLevel.AGGRESSIVE else ''
        self.console.print(
            f'  ↻ Using {extraction_method}{level_label}: '
            f'{original_size:,} → {len(content_str):,} chars '
            f'({compression_ratio:.0f}% savings, ~{est_tokens:,} tokens)'
        )

        return content_str

    # ------------------------------------------------------------------
    # Backward-compatible wrappers (used by existing tests)
    # ------------------------------------------------------------------

    def _compress_html_simple(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Compress HTML safely for selector discovery.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Compressed BeautifulSoup parsed HTML.

        """
        return compress_html(soup)

    def _prune_non_semantic(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Remove non-semantic bloat from parsed HTML.

        Strips SVG/canvas elements, base64 image data URIs, and deeply nested
        empty divs/spans that contribute no meaningful content.

        Args:
            soup: BeautifulSoup parsed HTML to prune in-place

        Returns:
            The pruned BeautifulSoup object (mutated in-place).

        """
        from yosoi.core.cleaning.passes.compress import _prune_non_semantic

        _prune_non_semantic(soup)
        return soup

    def _collapse_whitespace(self, html: str) -> str:
        """Collapse excessive whitespace.

        Args:
            html: HTML content to condense

        Returns:
            Compressed version of the HTML.

        """
        return collapse_whitespace(html)
