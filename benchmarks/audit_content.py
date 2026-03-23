"""Audit content preservation across the cleaning pipeline.

Traces every CSS class and ID through each pass, reports what's lost where.
Highlights semantic-looking selectors (product, price, title, etc.) that
disappear — these are likely bugs.

Usage:
    uv run python benchmarks/audit_content.py
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from rich.console import Console

from yosoi.core.cleaning.passes.budget import enforce_budget
from yosoi.core.cleaning.passes.classes import strip_utility_classes
from yosoi.core.cleaning.passes.compress import compress_html
from yosoi.core.cleaning.passes.content import extract_content
from yosoi.core.cleaning.passes.dedup import deduplicate_siblings
from yosoi.core.cleaning.passes.density import prune_by_density
from yosoi.core.cleaning.passes.flatten import flatten_wrappers
from yosoi.core.cleaning.passes.noise import remove_noise
from yosoi.core.cleaning.whitespace import collapse_whitespace

FIXTURES_DIR = Path(__file__).parent / 'fixtures'

# Words that suggest a class/id is semantically meaningful for scraping
_SEMANTIC_WORDS = re.compile(
    r'(product|price|title|name|heading|card|item|score|team|match|article|'
    r'news|headline|excerpt|description|summary|author|date|time|rating|'
    r'review|stock|availability|category|badge|content|result|event|'
    r'meta|link|image|body|text|list|table|row|cell|winner|loser|'
    r'amount|currency|status|label|count|value|grid|detail)',
    re.IGNORECASE,
)


def _collect_selectors(soup: BeautifulSoup) -> dict[str, set[str]]:
    """Collect all CSS classes and IDs from the soup."""
    classes: set[str] = set()
    ids: set[str] = set()
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        for cls in tag.get('class', []):
            classes.add(cls)
        tag_id = tag.get('id')
        if tag_id:
            ids.add(tag_id)
    return {'classes': classes, 'ids': ids}


def _collect_text_nodes(soup: BeautifulSoup) -> set[str]:
    """Collect non-empty text content (first 80 chars) for diffing."""
    texts: set[str] = set()
    for text in soup.stripped_strings:
        t = text.strip()[:80]
        if len(t) > 2:  # Skip tiny fragments
            texts.add(t)
    return texts


def _is_semantic(name: str) -> bool:
    return bool(_SEMANTIC_WORDS.search(name))


def audit_fixture(name: str, html: str, console: Console) -> list[str]:
    """Run the pipeline pass-by-pass, tracking selector survival. Returns list of issues."""
    issues: list[str] = []

    passes: list[tuple[str, object]] = []

    # 0 — raw
    soup = BeautifulSoup(html, 'lxml')
    raw_selectors = _collect_selectors(soup)
    raw_texts = _collect_text_nodes(soup)
    passes.append(('0_raw', _collect_selectors(soup)))

    # 1 — noise
    remove_noise(soup)
    passes.append(('1_noise', _collect_selectors(soup)))

    # 2 — content extraction
    content_soup, _ = extract_content(soup)
    passes.append(('2_content', _collect_selectors(content_soup)))

    # 3 — flatten
    flatten_wrappers(content_soup)
    passes.append(('3_flatten', _collect_selectors(content_soup)))

    # 4 — compress
    compress_html(content_soup)
    passes.append(('4_compress', _collect_selectors(content_soup)))

    # 5 — classes
    strip_utility_classes(content_soup)
    passes.append(('5_classes', _collect_selectors(content_soup)))

    # 6 — dedup
    deduplicate_siblings(content_soup)
    passes.append(('6_dedup', _collect_selectors(content_soup)))

    # 7 — density
    prune_by_density(content_soup)
    passes.append(('7_density', _collect_selectors(content_soup)))

    # Collect final text for content diff
    final_texts = _collect_text_nodes(content_soup)

    # 8-9 operate on strings, no structural changes to selectors
    content_str = collapse_whitespace(str(content_soup))
    enforce_budget(content_str, 8000)  # run for side-effect audit only

    # --- Report selector losses per pass ---
    console.print(f'\n[bold cyan]━━━ {name} ━━━[/bold cyan]')

    prev_selectors = passes[0][1]
    for pass_name, selectors in passes[1:]:
        lost_classes = prev_selectors['classes'] - selectors['classes']
        lost_ids = prev_selectors['ids'] - selectors['ids']

        if lost_classes or lost_ids:
            semantic_lost = [c for c in lost_classes if _is_semantic(c)]
            nonsemantic_lost = [c for c in lost_classes if not _is_semantic(c)]

            if semantic_lost:
                console.print(f'  [bold red]{pass_name}[/bold red] lost semantic classes: {sorted(semantic_lost)}')
                for cls in semantic_lost:
                    issues.append(f'{name}/{pass_name}: lost semantic class .{cls}')
            if nonsemantic_lost:
                console.print(f'  [dim]{pass_name}[/dim] lost classes: {sorted(nonsemantic_lost)}')
            if lost_ids:
                semantic_ids = [i for i in lost_ids if _is_semantic(i)]
                other_ids = [i for i in lost_ids if not _is_semantic(i)]
                if semantic_ids:
                    console.print(f'  [bold red]{pass_name}[/bold red] lost semantic IDs: {sorted(semantic_ids)}')
                    for id_ in semantic_ids:
                        issues.append(f'{name}/{pass_name}: lost semantic ID #{id_}')
                if other_ids:
                    console.print(f'  [dim]{pass_name}[/dim] lost IDs: {sorted(other_ids)}')

        prev_selectors = selectors

    # --- Report lost text content ---
    lost_texts = raw_texts - final_texts
    # Filter to substantial text losses (not just nav/footer chrome)
    substantial_lost = [t for t in lost_texts if len(t) > 20]
    if substantial_lost:
        console.print(f'\n  [yellow]Lost {len(substantial_lost)} text fragments (showing first 10):[/yellow]')
        for t in sorted(substantial_lost)[:10]:
            console.print(f'    [dim]"{t}"[/dim]')

    # --- Summary ---
    final_sels = passes[-1][1]
    raw_total = len(raw_selectors['classes']) + len(raw_selectors['ids'])
    final_total = len(final_sels['classes']) + len(final_sels['ids'])
    console.print(f'\n  Selectors: {raw_total} → {final_total} ({raw_total - final_total} removed, {final_total} kept)')
    console.print(f'  Text nodes: {len(raw_texts)} → {len(final_texts)} ({len(raw_texts) - len(final_texts)} removed)')

    return issues


def main() -> None:
    console = Console()
    fixtures: dict[str, str] = {}
    for path in sorted(FIXTURES_DIR.glob('*.html')):
        fixtures[path.stem] = path.read_text(encoding='utf-8')

    if not fixtures:
        console.print('[bold red]No fixtures found![/bold red]')
        return

    console.print('[bold]Content Preservation Audit[/bold]')
    all_issues: list[str] = []

    for name, html in fixtures.items():
        issues = audit_fixture(name, html, console)
        all_issues.extend(issues)

    # Final summary
    console.print(f'\n\n[bold]{"━" * 60}[/bold]')
    if all_issues:
        console.print(f'[bold red]Found {len(all_issues)} potential issues:[/bold red]')
        for issue in all_issues:
            console.print(f'  [red]• {issue}[/red]')
    else:
        console.print('[bold green]No semantic selectors lost — pipeline looks safe.[/bold green]')


if __name__ == '__main__':
    main()
