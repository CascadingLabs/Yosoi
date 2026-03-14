"""Markdown output formatter for extracted content.

This module only handles content output formatting.
"""

import os
from datetime import datetime


def format_markdown(url: str, domain: str, content: dict[str, object] | list[dict[str, object]]) -> str:
    """Format extracted content as Markdown.

    Creates generic markdown output that works for any field structure,
    not just articles. Iterates through all fields and formats appropriately.
    For multi-item content (list of dicts), renders each item as a numbered section.

    Args:
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary or list of dicts for multi-item pages

    Returns:
        Formatted markdown string.

    """
    if isinstance(content, list):
        return _format_markdown_items(url, domain, content)

    lines: list[str] = []

    # Title - use first non-empty text field, or "Untitled"
    title = _get_title(content)
    lines.append(f'# {title}')
    lines.append('')

    # Metadata section
    lines.append('---')
    lines.append(f'**Source:** {url}')
    lines.append(f'**Domain:** {domain}')
    lines.append(f'**Extracted:** {datetime.now().isoformat()}')
    lines.append('---')
    lines.append('')

    # Content sections - iterate through all fields
    for field, value in content.items():
        if value is None or value == '':
            continue

        # Format field name as section header
        field_title = _format_field_name(field)
        lines.append(f'## {field_title}')
        lines.append('')

        # Format value based on type
        lines.extend(_format_value(value))
        lines.append('')

    return '\n'.join(lines)


def _format_markdown_items(url: str, domain: str, items: list[dict[str, object]]) -> str:
    """Format a list of extracted items as numbered Markdown sections.

    Args:
        url: Source URL
        domain: Domain name
        items: List of extracted content dicts

    Returns:
        Formatted markdown string with numbered items separated by ``---``.

    """
    lines: list[str] = []
    lines.append(f'# Extracted Items ({len(items)})')
    lines.append('')
    lines.append('---')
    lines.append(f'**Source:** {url}')
    lines.append(f'**Domain:** {domain}')
    lines.append(f'**Extracted:** {datetime.now().isoformat()}')
    lines.append(f'**Item Count:** {len(items)}')
    lines.append('---')
    lines.append('')

    for idx, item in enumerate(items, 1):
        lines.append(f'## Item {idx}')
        lines.append('')
        for field, value in item.items():
            if value is None or value == '':
                continue
            field_title = _format_field_name(field)
            formatted = _format_value(value)
            if len(formatted) == 1:
                # Inline: **Field:** value
                lines.append(f'**{field_title}:** {formatted[0]}')
            else:
                # Block: label then multi-line value
                lines.append(f'**{field_title}:**')
                lines.extend(formatted)
            lines.append('')
        if idx < len(items):
            lines.append('---')
            lines.append('')

    return '\n'.join(lines)


def save_markdown(filepath: str, url: str, domain: str, content: dict[str, object] | list[dict[str, object]]) -> None:
    """Format and save content as Markdown file.

    Handles directory creation and complete Markdown formatting with metadata.

    Args:
        filepath: Path to save the file
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary or list of dicts for multi-item pages

    """
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Format as markdown
    markdown_content = format_markdown(url, domain, content)

    # Write to file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(markdown_content)


def _get_title(content: dict[str, object]) -> str:
    """Extract title from content fields.

    Looks for common title fields, or uses first non-empty text field.

    Args:
        content: Extracted content dictionary

    Returns:
        Title string, or "Untitled" if none found.

    """
    # Common title field names
    title_fields = ['headline', 'title', 'name', 'heading', 'h1']

    for field in title_fields:
        if content.get(field):
            return str(content[field])

    # Fallback: use first non-empty string value
    for value in content.values():
        if value and isinstance(value, str) and len(value.strip()) > 0:
            # Use first 100 chars if it's long
            title: str = value.strip()
            return title[:100] + '...' if len(title) > 100 else title

    return 'Untitled'


def _format_field_name(field: str) -> str:
    """Format field name for section header.

    Converts snake_case to Title Case.

    Args:
        field: Field name (e.g., 'body_text', 'related_content')

    Returns:
        Formatted field name (e.g., 'Body Text', 'Related Content').

    """
    return field.replace('_', ' ').title()


def _format_value(value: object) -> list[str]:
    """Format a value for markdown output.

    Handles different data types appropriately:
    - Strings: Direct output
    - Lists: Markdown list items
    - Dicts: Key-value pairs
    - Other: String representation

    Args:
        value: Value to format (any type)

    Returns:
        List of markdown lines.

    """
    lines = []

    if isinstance(value, str):
        # Simple string - output directly
        lines.append(value)

    elif isinstance(value, list):
        # List - create markdown list
        for item in value:
            if isinstance(item, dict):
                # List of dicts (e.g., links with text/href)
                text = item.get('text', item.get('title', 'Item'))
                href = item.get('href', item.get('url', item.get('link', '#')))
                lines.append(f'- [{text}]({href})')
            else:
                # Simple list items
                lines.append(f'- {item}')

    elif isinstance(value, dict):
        # Dict - show key-value pairs
        for key, val in value.items():
            if val:
                lines.append(f'**{_format_field_name(key)}:** {val}')

    else:
        # Other types - convert to string
        lines.append(str(value))

    return lines
