"""Tests for outputs utility functions."""

from yosoi.outputs.utils import format_content, format_selectors, save_formatted_content


def test_format_content_json():
    content = {'title': 'Hello', 'body': 'World'}
    result = format_content('https://example.com', 'example.com', content, 'json')
    assert isinstance(result, dict)
    assert result['content'] == content


def test_format_content_markdown():
    content = {'headline': 'Article Title', 'body_text': 'Content here.'}
    result = format_content('https://example.com', 'example.com', content, 'markdown')
    assert isinstance(result, str)
    assert 'Article Title' in result


def test_format_selectors_returns_dict():
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'NA'}}
    result = format_selectors('https://example.com', 'example.com', selectors)
    assert isinstance(result, dict)
    assert result['selectors'] == selectors


def test_save_formatted_content_markdown(tmp_path):
    from pathlib import Path

    filepath = str(tmp_path / 'out' / 'article.md')
    content = {'headline': 'Test', 'body_text': 'Body.'}
    save_formatted_content(filepath, 'https://example.com', 'example.com', content, 'markdown')
    assert Path(filepath).exists()
    assert '# Test' in Path(filepath).read_text()
