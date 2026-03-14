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

    if os.path.exists(filepath):
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active
        # Read existing header to align columns
        header = [cell.value for cell in ws[1]]
        # Extend header with any new keys from the incoming record
        new_cols = [k for k in record if k not in header]
        if new_cols:
            for col_name in new_cols:
                header.append(col_name)
                ws.cell(row=1, column=len(header), value=col_name)
        row = [str(value) if (value := record.get(col)) is not None else '' for col in header]
        ws.append(row)
    else:
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(list(record.keys()))
        values = [str(v) if v is not None else '' for v in record.values()]
        ws.append(values)

    wb.save(filepath)
