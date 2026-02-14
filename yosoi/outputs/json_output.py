"""JSON output formatter for extracted content."""

import json
import os
from datetime import datetime


def format_json(url: str, domain: str, content: dict) -> dict:
    """Format extracted content as JSON with metadata.

    Args:
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary (field -> value)

    Returns:
        Dictionary with metadata and content, ready for JSON serialization.

    """
    return {
        'url': url,
        'domain': domain,
        'extracted_at': datetime.now().isoformat(),
        'content': content,
    }


def save_json(filepath: str, url: str, domain: str, content: dict):
    """Format and save content as JSON file.

    Handles directory creation and complete JSON formatting with metadata.

    Args:
        filepath: Path to save the file
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary (field -> value)

    """
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Format with metadata
    data = format_json(url, domain, content)

    # Write to file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def format_selectors_json(url: str, domain: str, selectors: dict) -> dict:
    """Format selectors as JSON with metadata.

    Args:
        url: Source URL where selectors were discovered
        domain: Domain name
        selectors: Dictionary of selectors (field -> {primary, fallback, tertiary})

    Returns:
        Dictionary with metadata and selectors, ready for JSON serialization.

    """
    return {
        'url': url,
        'domain': domain,
        'discovered_at': datetime.now().isoformat(),
        'selectors': selectors,
    }


def save_selectors_json(filepath: str, url: str, domain: str, selectors: dict):
    """Format and save selectors as JSON file.

    Handles directory creation and complete JSON formatting with metadata.

    Args:
        filepath: Path to save the file
        url: Source URL where selectors were discovered
        domain: Domain name
        selectors: Dictionary of selectors (field -> {primary, fallback, tertiary})

    """
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Format with metadata
    data = format_selectors_json(url, domain, selectors)

    # Write to file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
