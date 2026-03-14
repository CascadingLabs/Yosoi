"""Unit tests for multi-item output formatting (JSON and Markdown)."""

from yosoi.outputs.json import format_json
from yosoi.outputs.markdown import format_markdown

# ---------------------------------------------------------------------------
# JSON multi-item
# ---------------------------------------------------------------------------

ITEMS = [
    {'name': 'Iron Pickaxe', 'price': '14.50 Gold'},
    {'name': 'Steel Anvil', 'price': '89.00 Gold'},
]


def test_format_json_multi_item_has_items_key():
    result = format_json('https://x.com', 'x.com', ITEMS)
    assert 'items' in result
    assert 'content' not in result


def test_format_json_multi_item_has_item_count():
    result = format_json('https://x.com', 'x.com', ITEMS)
    assert result['item_count'] == 2


def test_format_json_multi_item_items_match():
    result = format_json('https://x.com', 'x.com', ITEMS)
    assert result['items'] == ITEMS


def test_format_json_single_item_has_content_key():
    single = {'name': 'Iron Pickaxe', 'price': '14.50 Gold'}
    result = format_json('https://x.com', 'x.com', single)
    assert 'content' in result
    assert 'items' not in result


def test_format_json_metadata_present():
    result = format_json('https://x.com', 'x.com', ITEMS)
    assert result['url'] == 'https://x.com'
    assert result['domain'] == 'x.com'
    assert 'extracted_at' in result


# ---------------------------------------------------------------------------
# Markdown multi-item
# ---------------------------------------------------------------------------


def test_format_markdown_multi_item_contains_item_count():
    result = format_markdown('https://x.com', 'x.com', ITEMS)
    assert 'Item Count:** 2' in result


def test_format_markdown_multi_item_has_numbered_sections():
    result = format_markdown('https://x.com', 'x.com', ITEMS)
    assert '## Item 1' in result
    assert '## Item 2' in result


def test_format_markdown_multi_item_contains_field_values():
    result = format_markdown('https://x.com', 'x.com', ITEMS)
    assert 'Iron Pickaxe' in result
    assert 'Steel Anvil' in result


def test_format_markdown_single_item_unchanged():
    single = {'name': 'Iron Pickaxe'}
    result = format_markdown('https://x.com', 'x.com', single)
    assert '## Item 1' not in result
    assert '# Iron Pickaxe' in result


def test_format_markdown_multi_item_has_separator():
    result = format_markdown('https://x.com', 'x.com', ITEMS)
    # Items should be separated by ---
    assert '---' in result
