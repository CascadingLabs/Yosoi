"""XLSX output module (requires openpyxl)."""

import os
from pathlib import Path


def save_xlsx(filepath: str, url: str, domain: str, content: dict) -> None:
    """Append one record to an XLSX workbook, creating it if it doesn't exist.

    Requires openpyxl. Install with: uv add openpyxl

    Args:
        filepath: Path to the .xlsx file
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary

    Raises:
        ImportError: If openpyxl is not installed.

    """
    try:
        import openpyxl
    except (ImportError, TypeError):
        raise ImportError('openpyxl is required for XLSX output. Install it: uv add openpyxl') from None

    record = {'url': url, 'domain': domain, **content}
    values = [str(v) if v is not None else '' for v in record.values()]

    if os.path.exists(filepath):
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active
        ws.append(values)
    else:
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(list(record.keys()))
        ws.append(values)

    wb.save(filepath)
