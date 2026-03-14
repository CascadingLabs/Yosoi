"""JSONL (newline-delimited JSON) output module."""

import json
from datetime import datetime, timezone
from pathlib import Path


def format_jsonl(url: str, domain: str, content: dict) -> str:
    """Format a single record as a JSONL line (no trailing newline).

    Args:
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary

    Returns:
        JSON-serialized string for one record.

    """
    record = {
        'url': url,
        'domain': domain,
        'extracted_at': datetime.now(timezone.utc).isoformat(),
        **content,
    }
    return json.dumps(record, ensure_ascii=False)


def save_jsonl(filepath: str, url: str, domain: str, content: dict) -> None:
    """Append one record to a JSONL file, creating it if it doesn't exist.

    Args:
        filepath: Path to the .jsonl file
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary

    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(format_jsonl(url, domain, content) + '\n')
