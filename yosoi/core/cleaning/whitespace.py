"""Whitespace collapsing for cleaned HTML output."""

import re


def collapse_whitespace(html: str) -> str:
    """Collapse excessive whitespace in an HTML string.

    Args:
        html: HTML content to condense.

    Returns:
        Compressed version with single spaces, single newlines, and trimmed lines.

    """
    # Multiple spaces/tabs → single space
    html = re.sub(r'[ \t]+', ' ', html)
    # Multiple newlines → single newline
    html = re.sub(r'\n+', '\n', html)
    # Remove leading/trailing whitespace per line, drop blank lines
    lines = [line.strip() for line in html.split('\n') if line.strip()]
    return '\n'.join(lines)
