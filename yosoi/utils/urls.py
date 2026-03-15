"""URL file loading utilities — core logic without CLI dependencies."""

import json
import os
import re

_URL_RE = re.compile(r'https?://[^\s\'"<>]+')
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\((https?://[^)]+)\)')


try:
    import pandas as pd

    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def _extract_urls_from_text(text: str) -> list[str]:
    """Extract http/https URLs from arbitrary text, stripping trailing punctuation."""
    urls = []
    for match in _URL_RE.finditer(text):
        url = match.group().rstrip('.,;:)\'"')
        urls.append(url)
    return urls


def _load_urls_from_csv(filepath: str) -> list[str]:
    """Load URLs from a CSV file using pandas."""
    if not HAS_PANDAS:
        raise ValueError('pandas is required to read CSV files. Install it with: uv add yosoi[pandas]')
    df = pd.read_csv(filepath)
    url_col = next((c for c in df.columns if c.lower() == 'url'), None)
    if url_col:
        return [str(v) for v in df[url_col].dropna() if str(v)]
    urls: list[str] = []
    for col in df.columns:
        for val in df[col].dropna():
            urls.extend(_extract_urls_from_text(str(val)))
    return urls


def _load_urls_from_excel(filepath: str) -> list[str]:
    """Load URLs from all sheets of an Excel file using pandas."""
    if not HAS_PANDAS:
        raise ValueError('pandas is required to read Excel files. Install it with: uv add yosoi[pandas,openpyxl]')
    sheets = pd.read_excel(filepath, sheet_name=None)
    urls: list[str] = []
    for df in sheets.values():
        url_col = next((c for c in df.columns if c.lower() == 'url'), None)
        if url_col:
            urls.extend(str(v) for v in df[url_col].dropna() if str(v))
        else:
            for col in df.columns:
                for val in df[col].dropna():
                    urls.extend(_extract_urls_from_text(str(val)))
    return urls


def _load_urls_from_parquet(filepath: str) -> list[str]:
    """Load URLs from a Parquet file using pandas."""
    if not HAS_PANDAS:
        raise ValueError('pandas is required to read Parquet files. Install it with: uv add yosoi[pandas,pyarrow]')
    df = pd.read_parquet(filepath)
    url_col = next((c for c in df.columns if c.lower() == 'url'), None)
    if url_col:
        return [str(v) for v in df[url_col].dropna() if str(v)]
    urls: list[str] = []
    for col in df.columns:
        for val in df[col].dropna():
            urls.extend(_extract_urls_from_text(str(val)))
    return urls


def _load_urls_from_markdown(filepath: str) -> list[str]:
    """Load URLs from a Markdown file (link syntax + bare URLs), deduplicated."""
    with open(filepath) as f:
        text = f.read()
    seen: set[str] = set()
    urls: list[str] = []
    for match in _MD_LINK_RE.finditer(text):
        url = match.group(2)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    remaining = _MD_LINK_RE.sub('', text)
    for url in _extract_urls_from_text(remaining):
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _load_urls_from_json(data: object) -> list[str]:
    """Extract URLs from a parsed JSON structure (list or dict)."""
    if isinstance(data, list):
        urls: list[str] = []
        for item in data:
            if isinstance(item, str) and item:
                urls.append(item)
            elif isinstance(item, dict):
                url = item.get('url')
                if isinstance(url, str) and url:
                    urls.append(url)
        return urls
    if isinstance(data, dict):
        urls = []
        for key in data:
            value = data.get(key, {})
            if isinstance(value, str) and value:
                urls.append(value)
            elif isinstance(value, dict) and 'url' in value and isinstance(value['url'], str) and value['url']:
                urls.append(value['url'])
        return urls
    return []


def load_urls_from_file(filepath: str) -> list[str]:
    """Load URLs from a file (JSON, plain text, CSV, Excel, Parquet, or Markdown).

    Args:
        filepath: Path to file containing URLs.

    Returns:
        List of URL strings.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file format requires unavailable dependencies.

    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f'File not found: {filepath}')

    filepath_lower = filepath.lower()

    if filepath_lower.endswith('.csv'):
        return _load_urls_from_csv(filepath)

    if filepath_lower.endswith('.xlsx') or filepath_lower.endswith('.xls'):
        return _load_urls_from_excel(filepath)

    if filepath_lower.endswith('.parquet'):
        return _load_urls_from_parquet(filepath)

    if filepath_lower.endswith('.md'):
        return _load_urls_from_markdown(filepath)

    if filepath_lower.endswith('.json'):
        with open(filepath) as f:
            data = json.load(f)
        return _load_urls_from_json(data)

    with open(filepath) as f:
        return [s for line in f if (s := line.strip()) and not s.startswith('#')]
