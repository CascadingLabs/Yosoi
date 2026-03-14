"""Utility functions for formatting and saving extracted content."""

from collections.abc import Callable

from yosoi.outputs.csv import save_csv
from yosoi.outputs.json import format_json, format_selectors_json, save_json, save_selectors_json
from yosoi.outputs.jsonl import save_jsonl
from yosoi.outputs.markdown import format_markdown, save_markdown
from yosoi.outputs.parquet import save_parquet
from yosoi.outputs.xlsx import save_xlsx

_Saver = Callable[[str, str, str, dict], None]


def format_content(url: str, domain: str, content: dict, output_format: str = 'json') -> str | dict:
    """Format extracted content in the specified format.

    Args:
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary (field -> value)
        output_format: Output format ('json' or 'markdown'). Defaults to 'json'.

    Returns:
        Formatted content - dict for JSON, string for Markdown.

    """
    if output_format == 'markdown':
        return format_markdown(url, domain, content)
    return format_json(url, domain, content)


def save_formatted_content(filepath: str, url: str, domain: str, content: dict, output_format: str = 'json') -> str:
    """Format and save extracted content to file.

    Args:
        filepath: Path to save the file
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary (field -> value)
        output_format: Output format. Defaults to 'json'.

    Returns:
        Path to the saved file.

    """
    # Build the dispatch table at call time so module-level names are resolved
    # against the current globals() — this ensures test mocks are respected.
    _dispatch: dict[str, _Saver] = {
        'json': save_json,
        'markdown': save_markdown,
        'jsonl': save_jsonl,
        'ndjson': save_jsonl,
        'csv': save_csv,
        'xlsx': save_xlsx,
        'parquet': save_parquet,
    }
    saver: _Saver = _dispatch.get(output_format, save_json)
    saver(filepath, url, domain, content)
    return filepath


def format_selectors(url: str, domain: str, selectors: dict) -> dict:
    """Format selectors as JSON.

    Selectors are always formatted as JSON for machine readability.

    Args:
        url: Source URL where selectors were discovered
        domain: Domain name
        selectors: Dictionary of selectors (field -> {primary, fallback, tertiary})

    Returns:
        Formatted selectors as dict.

    """
    return format_selectors_json(url, domain, selectors)


def save_formatted_selectors(filepath: str, url: str, domain: str, selectors: dict) -> str:
    """Format and save selectors to JSON file.

    Selectors are always saved as JSON for machine readability and reuse.

    Args:
        filepath: Path to save the file
        url: Source URL where selectors were discovered
        domain: Domain name
        selectors: Dictionary of selectors (field -> {primary, fallback, tertiary})

    Returns:
        Path to the saved file.

    """
    # Always save selectors as JSON
    save_selectors_json(filepath, url, domain, selectors)
    return filepath
