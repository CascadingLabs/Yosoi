"""Utility functions for formatting and saving extracted content."""

from yosoi.outputs.json_output import format_json, format_selectors_json, save_json, save_selectors_json
from yosoi.outputs.markdown_output import format_markdown, save_markdown


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
        output_format: Output format ('json' or 'markdown'). Defaults to 'json'.

    Returns:
        Path to the saved file.

    """
    # Save using format-specific function (handles directory creation internally)
    if output_format == 'markdown':
        save_markdown(filepath, url, domain, content)
    else:
        save_json(filepath, url, domain, content)

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
