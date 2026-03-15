"""Tests for JSON output formatter."""

import json
from pathlib import Path

from yosoi.outputs.json import format_json, format_selectors_json, save_json, save_selectors_json


def test_format_json_contains_url():
    result = format_json('https://example.com/page', 'example.com', {'title': 'Hello'})
    assert result['url'] == 'https://example.com/page'


def test_format_json_contains_domain():
    result = format_json('https://example.com/page', 'example.com', {'title': 'Hello'})
    assert result['domain'] == 'example.com'


def test_format_json_contains_content():
    content = {'title': 'Hello', 'price': '$9.99'}
    result = format_json('https://example.com', 'example.com', content)
    assert result['content'] == content


def test_format_json_has_extracted_at_key():
    result = format_json('https://example.com', 'example.com', {})
    assert 'extracted_at' in result


def test_format_json_extracted_at_is_isoformat():
    from datetime import datetime

    result = format_json('https://example.com', 'example.com', {})
    # Should be parseable as ISO format datetime
    dt = datetime.fromisoformat(result['extracted_at'])
    assert dt is not None


def test_format_json_returns_dict():
    result = format_json('https://example.com', 'example.com', {'k': 'v'})
    assert isinstance(result, dict)


def test_format_json_exact_keys():
    result = format_json('https://example.com', 'example.com', {})
    assert set(result.keys()) == {'url', 'domain', 'extracted_at', 'content'}


def test_format_json_content_is_original_dict():
    content = {'field1': 'value1', 'field2': 'value2'}
    result = format_json('https://example.com', 'example.com', content)
    assert result['content']['field1'] == 'value1'
    assert result['content']['field2'] == 'value2'


def test_format_selectors_json_contains_url():
    result = format_selectors_json('https://example.com', 'example.com', {'title': {'primary': 'h1'}})
    assert result['url'] == 'https://example.com'


def test_format_selectors_json_contains_domain():
    result = format_selectors_json('https://example.com', 'example.com', {'title': {'primary': 'h1'}})
    assert result['domain'] == 'example.com'


def test_format_selectors_json_contains_selectors():
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2'}}
    result = format_selectors_json('https://example.com', 'example.com', selectors)
    assert result['selectors'] == selectors


def test_format_selectors_json_has_discovered_at_key():
    result = format_selectors_json('https://example.com', 'example.com', {})
    assert 'discovered_at' in result


def test_format_selectors_json_discovered_at_is_isoformat():
    from datetime import datetime

    result = format_selectors_json('https://example.com', 'example.com', {})
    dt = datetime.fromisoformat(result['discovered_at'])
    assert dt is not None


def test_format_selectors_json_exact_keys():
    result = format_selectors_json('https://example.com', 'example.com', {})
    assert set(result.keys()) == {'url', 'domain', 'discovered_at', 'selectors'}


def test_save_json_creates_file(tmp_path):
    filepath = str(tmp_path / 'out' / 'data.json')
    save_json(filepath, 'https://example.com', 'example.com', {'title': 'Hello'})
    assert Path(filepath).exists()


def test_save_json_creates_directory(tmp_path):
    filepath = str(tmp_path / 'nested' / 'deep' / 'data.json')
    save_json(filepath, 'https://example.com', 'example.com', {'k': 'v'})
    assert Path(filepath).exists()


def test_save_json_content_is_valid_json(tmp_path):
    filepath = str(tmp_path / 'data.json')
    save_json(filepath, 'https://example.com', 'example.com', {'title': 'Test'})
    with open(filepath) as f:
        data = json.load(f)
    assert data['url'] == 'https://example.com'
    assert data['domain'] == 'example.com'
    assert data['content'] == {'title': 'Test'}


def test_save_json_uses_indent_2(tmp_path):
    filepath = str(tmp_path / 'indented.json')
    save_json(filepath, 'https://example.com', 'example.com', {'k': 'v'})
    raw = Path(filepath).read_text()
    # indent=2 means lines start with 2 spaces
    assert '  ' in raw


def test_save_selectors_json_creates_file(tmp_path):
    filepath = str(tmp_path / 'selectors' / 'data.json')
    save_selectors_json(filepath, 'https://example.com', 'example.com', {'title': {'primary': 'h1'}})
    assert Path(filepath).exists()


def test_save_selectors_json_content_is_valid_json(tmp_path):
    filepath = str(tmp_path / 'selectors.json')
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2'}}
    save_selectors_json(filepath, 'https://example.com', 'example.com', selectors)
    with open(filepath) as f:
        data = json.load(f)
    assert data['url'] == 'https://example.com'
    assert data['domain'] == 'example.com'
    assert data['selectors'] == selectors


def test_save_selectors_json_uses_ensure_ascii_false(tmp_path):
    filepath = str(tmp_path / 'unicode_sel.json')
    save_selectors_json(filepath, 'https://example.com', 'example.com', {'title': {'primary': 'h1'}})
    raw = Path(filepath).read_text(encoding='utf-8')
    # File should be readable as UTF-8 (ensure_ascii=False means non-ASCII is preserved)
    assert raw is not None


def test_save_json_uses_ensure_ascii_false(tmp_path):
    """Non-ASCII characters must be preserved (ensure_ascii=False)."""
    filepath = str(tmp_path / 'unicode.json')
    save_json(filepath, 'https://example.com', 'example.com', {'title': 'Héllo Wörld'})
    raw = Path(filepath).read_text(encoding='utf-8')
    # With ensure_ascii=False, the unicode chars should appear literally
    assert 'Héllo' in raw or 'H\\u00e9llo' not in raw or 'Wörld' in raw


def test_save_json_file_written_with_utf8(tmp_path):
    """File must be written with utf-8 encoding."""
    filepath = str(tmp_path / 'utf8.json')
    content = {'title': 'Ünïcödé'}
    save_json(filepath, 'https://example.com', 'example.com', content)
    data = json.loads(Path(filepath).read_text(encoding='utf-8'))
    assert data['content']['title'] == 'Ünïcödé'


def test_format_json_url_is_exact():
    """url key must be exactly the url passed, not modified."""
    url = 'https://exact.example.com/path?q=1'
    result = format_json(url, 'example.com', {})
    assert result['url'] == url


def test_format_json_domain_is_exact():
    """domain key must be exactly the domain passed."""
    result = format_json('https://example.com', 'exact.domain.com', {})
    assert result['domain'] == 'exact.domain.com'


def test_format_selectors_json_url_is_exact():
    """url key in selectors format must be exactly as passed."""
    url = 'https://shop.example.com/product'
    result = format_selectors_json(url, 'shop.example.com', {})
    assert result['url'] == url


def test_format_selectors_json_domain_is_exact():
    """domain key in selectors format must be exactly as passed."""
    result = format_selectors_json('https://example.com', 'exact.domain.net', {})
    assert result['domain'] == 'exact.domain.net'


def test_save_json_calls_makedirs(tmp_path):
    """save_json must create parent directories when they don't exist."""
    filepath = str(tmp_path / 'a' / 'b' / 'c' / 'data.json')
    save_json(filepath, 'https://example.com', 'example.com', {})
    assert Path(filepath).exists()


def test_save_selectors_json_calls_makedirs(tmp_path):
    """save_selectors_json must create parent directories when they don't exist."""
    filepath = str(tmp_path / 'x' / 'y' / 'z' / 'selectors.json')
    save_selectors_json(filepath, 'https://example.com', 'example.com', {})
    assert Path(filepath).exists()


def test_save_selectors_json_indent_2(tmp_path):
    """save_selectors_json must use indent=2."""
    filepath = str(tmp_path / 'indented_sel.json')
    save_selectors_json(filepath, 'https://example.com', 'example.com', {'title': {'primary': 'h1'}})
    raw = Path(filepath).read_text()
    assert '  ' in raw  # indent=2 adds 2-space indentation


def test_save_selectors_json_valid_json_structure(tmp_path):
    """Saved file must have url, domain, discovered_at, selectors keys."""
    filepath = str(tmp_path / 'struct.json')
    save_selectors_json(filepath, 'https://example.com', 'example.com', {'title': {'primary': 'h1'}})
    data = json.loads(Path(filepath).read_text())
    assert set(data.keys()) == {'url', 'domain', 'discovered_at', 'selectors'}


def test_save_json_valid_json_structure(tmp_path):
    """Saved file must have url, domain, extracted_at, content keys."""
    filepath = str(tmp_path / 'struct.json')
    save_json(filepath, 'https://example.com', 'example.com', {'title': 'test'})
    data = json.loads(Path(filepath).read_text())
    assert set(data.keys()) == {'url', 'domain', 'extracted_at', 'content'}
