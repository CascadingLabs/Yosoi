"""Parquet output module (requires pyarrow)."""

import os
from pathlib import Path


def save_parquet(filepath: str, url: str, domain: str, content: dict[str, object]) -> None:
    """Append one record to a Parquet file, creating it if it doesn't exist.

    Requires pyarrow. Install with: uv add pyarrow

    Args:
        filepath: Path to the .parquet file
        url: Source URL
        domain: Domain name
        content: Extracted content dictionary

    Raises:
        ImportError: If pyarrow is not installed.

    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except (ImportError, TypeError):
        raise ImportError('pyarrow is required for Parquet output. Install it: uv add pyarrow') from None

    record = {'url': url, 'domain': domain, **content}
    new_table = pa.table({k: [str(v) if v is not None else None] for k, v in record.items()})

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    if os.path.exists(filepath):
        existing = pq.read_table(filepath)
        combined = pa.concat_tables([existing, new_table], promote_options='default')
        pq.write_table(combined, filepath)
    else:
        pq.write_table(new_table, filepath)
