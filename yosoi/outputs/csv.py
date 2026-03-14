"""CSV output module."""

import csv
import io
import os
from pathlib import Path


def format_csv(url: str, domain: str, content: dict[str, object]) -> str:
    """Format a single record as a CSV row string (no header, no trailing newline).

    Args:
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary

    Returns:
        CSV-formatted string for one data row.

    """
    record = {'url': url, 'domain': domain, **content}
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(record.keys()))
    writer.writerow({k: str(v) if v is not None else '' for k, v in record.items()})
    return buf.getvalue()


def save_csv(filepath: str, url: str, domain: str, content: dict[str, object]) -> None:
    """Append one record to a CSV file.

    Writes a header row on first creation. Subsequent calls append data rows only.

    Args:
        filepath: Path to the .csv file
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary

    """
    record = {'url': url, 'domain': domain, **content}
    file_exists = os.path.exists(filepath)
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(record.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: str(v) if v is not None else '' for k, v in record.items()})
