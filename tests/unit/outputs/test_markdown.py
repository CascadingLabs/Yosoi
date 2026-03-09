"""Tests for markdown output formatter."""

from yosoi.outputs.markdown import _format_field_name, _format_value, _get_title, format_markdown, save_markdown


def test_format_markdown_contains_source_url():
    content = {'headline': 'My Article', 'body_text': 'Some content.'}
    result = format_markdown('https://example.com/article', 'example.com', content)
    assert 'https://example.com/article' in result


def test_format_markdown_uses_headline_as_title():
    content = {'headline': 'My Article', 'body_text': 'Content.'}
    result = format_markdown('https://example.com', 'example.com', content)
    assert '# My Article' in result


def test_format_markdown_skips_empty_fields():
    content = {'headline': 'Title', 'empty_field': '', 'none_field': None}
    result = format_markdown('https://example.com', 'example.com', content)
    assert 'empty_field' not in result.lower()
    assert 'none_field' not in result.lower()


def test_format_markdown_includes_all_sections():
    content = {'headline': 'Title', 'author': 'Jane', 'body_text': 'Content.'}
    result = format_markdown('https://example.com', 'example.com', content)
    assert '## Author' in result
    assert '## Body Text' in result


def test_get_title_uses_headline():
    content = {'headline': 'My Headline', 'title': 'Other Title'}
    assert _get_title(content) == 'My Headline'


def test_get_title_uses_title_when_no_headline():
    content = {'title': 'My Title', 'author': 'Jane'}
    assert _get_title(content) == 'My Title'


def test_get_title_fallback_to_first_string():
    content = {'author': 'Jane Doe', 'rating': '4.5'}
    result = _get_title(content)
    assert result == 'Jane Doe'


def test_get_title_returns_untitled_when_empty():
    assert _get_title({}) == 'Untitled'


def test_format_field_name_converts_snake_case():
    assert _format_field_name('body_text') == 'Body Text'
    assert _format_field_name('related_content') == 'Related Content'


def test_format_value_string():
    lines = _format_value('Hello World')
    assert lines == ['Hello World']


def test_format_value_list_of_strings():
    lines = _format_value(['item1', 'item2'])
    assert '- item1' in lines
    assert '- item2' in lines


def test_format_value_list_of_dicts():
    lines = _format_value([{'text': 'Link', 'href': 'https://example.com'}])
    assert any('Link' in line and 'https://example.com' in line for line in lines)


def test_format_value_dict():
    lines = _format_value({'key_name': 'value'})
    assert any('Key Name' in line and 'value' in line for line in lines)


def test_format_value_other_types():
    lines = _format_value(42)
    assert lines == ['42']


def test_save_markdown_creates_file(tmp_path):
    filepath = str(tmp_path / 'output' / 'article.md')
    content = {'headline': 'Test', 'body_text': 'Content.'}
    save_markdown(filepath, 'https://example.com', 'example.com', content)
    from pathlib import Path

    assert Path(filepath).exists()
    text = Path(filepath).read_text()
    assert '# Test' in text
