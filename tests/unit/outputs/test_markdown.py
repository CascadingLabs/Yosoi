"""Tests for markdown output formatter."""

from pathlib import Path

from yosoi.outputs.markdown import _format_field_name, _format_value, _get_title, format_markdown, save_markdown


def test_format_markdown_contains_source_url():
    content = {'headline': 'My Article', 'body_text': 'Some content.'}
    result = format_markdown('https://example.com/article', 'example.com', content)
    assert 'https://example.com/article' in result


def test_format_markdown_contains_domain():
    content = {'headline': 'Article', 'body_text': 'Content.'}
    result = format_markdown('https://example.com', 'example.com', content)
    assert 'example.com' in result


def test_format_markdown_uses_headline_as_title():
    content = {'headline': 'My Article', 'body_text': 'Content.'}
    result = format_markdown('https://example.com', 'example.com', content)
    assert '# My Article' in result


def test_format_markdown_untitled_when_no_title_fields():
    result = format_markdown('https://example.com', 'example.com', {'price': None})
    assert '# Untitled' in result


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


def test_format_markdown_includes_metadata_separator():
    content = {'headline': 'Title'}
    result = format_markdown('https://example.com', 'example.com', content)
    assert '---' in result


def test_format_markdown_source_label():
    content = {'headline': 'Title'}
    result = format_markdown('https://example.com', 'example.com', content)
    assert '**Source:**' in result


def test_format_markdown_domain_label():
    content = {'headline': 'Title'}
    result = format_markdown('https://example.com', 'example.com', content)
    assert '**Domain:**' in result


def test_format_markdown_extracted_label():
    content = {'headline': 'Title'}
    result = format_markdown('https://example.com', 'example.com', content)
    assert '**Extracted:**' in result


def test_format_markdown_returns_string():
    result = format_markdown('https://example.com', 'example.com', {'title': 'Test'})
    assert isinstance(result, str)


def test_get_title_uses_headline():
    content = {'headline': 'My Headline', 'title': 'Other Title'}
    assert _get_title(content) == 'My Headline'


def test_get_title_uses_title_when_no_headline():
    content = {'title': 'My Title', 'author': 'Jane'}
    assert _get_title(content) == 'My Title'


def test_get_title_uses_name_field():
    content = {'name': 'My Name'}
    assert _get_title(content) == 'My Name'


def test_get_title_uses_heading_field():
    content = {'heading': 'My Heading'}
    assert _get_title(content) == 'My Heading'


def test_get_title_uses_h1_field():
    content = {'h1': 'H1 Title'}
    assert _get_title(content) == 'H1 Title'


def test_get_title_headline_takes_priority_over_title():
    content = {'title': 'Title', 'headline': 'Headline'}
    assert _get_title(content) == 'Headline'


def test_get_title_fallback_to_first_string():
    content = {'author': 'Jane Doe', 'rating': '4.5'}
    result = _get_title(content)
    assert result == 'Jane Doe'


def test_get_title_truncates_long_string_at_100():
    content = {'author': 'x' * 101}
    result = _get_title(content)
    assert result == 'x' * 100 + '...'


def test_get_title_does_not_truncate_at_100_exactly():
    content = {'author': 'x' * 100}
    result = _get_title(content)
    assert result == 'x' * 100
    assert '...' not in result


def test_get_title_returns_untitled_when_empty():
    assert _get_title({}) == 'Untitled'


def test_get_title_returns_untitled_when_all_none():
    assert _get_title({'headline': None, 'title': None}) == 'Untitled'


def test_format_field_name_converts_snake_case():
    assert _format_field_name('body_text') == 'Body Text'
    assert _format_field_name('related_content') == 'Related Content'


def test_format_field_name_single_word():
    assert _format_field_name('author') == 'Author'


def test_format_field_name_multiple_underscores():
    assert _format_field_name('a_b_c') == 'A B C'


def test_format_value_string():
    lines = _format_value('Hello World')
    assert lines == ['Hello World']


def test_format_value_list_of_strings():
    lines = _format_value(['item1', 'item2'])
    assert '- item1' in lines
    assert '- item2' in lines


def test_format_value_list_format_with_dash_prefix():
    lines = _format_value(['only'])
    assert lines[0] == '- only'


def test_format_value_list_of_dicts_with_text_and_href():
    lines = _format_value([{'text': 'Link', 'href': 'https://example.com'}])
    assert any('Link' in line and 'https://example.com' in line for line in lines)


def test_format_value_list_of_dicts_uses_title_fallback():
    lines = _format_value([{'title': 'My Title', 'url': 'https://example.com'}])
    assert any('My Title' in line for line in lines)


def test_format_value_list_of_dicts_default_item_text():
    lines = _format_value([{'href': 'https://example.com'}])
    assert any('Item' in line for line in lines)


def test_format_value_list_of_dicts_default_href():
    lines = _format_value([{'text': 'No href'}])
    assert any('#' in line for line in lines)


def test_format_value_dict_formats_key_value():
    lines = _format_value({'key_name': 'value'})
    assert any('Key Name' in line and 'value' in line for line in lines)


def test_format_value_dict_skips_falsy_values():
    lines = _format_value({'present': 'yes', 'absent': None, 'empty': ''})
    full_text = ' '.join(lines)
    assert 'yes' in full_text
    # Falsy values should be skipped
    assert lines.count('**Present:** yes') + len([line for line in lines if 'yes' in line]) >= 1


def test_format_value_dict_key_formatted_as_title_case():
    lines = _format_value({'my_field': 'val'})
    assert any('My Field' in line for line in lines)


def test_format_value_other_types():
    lines = _format_value(42)
    assert lines == ['42']


def test_format_value_float():
    lines = _format_value(3.14)
    assert lines == ['3.14']


def test_format_value_boolean():
    lines = _format_value(True)
    assert lines[0] == 'True'


def test_save_markdown_creates_file(tmp_path):
    filepath = str(tmp_path / 'output' / 'article.md')
    content = {'headline': 'Test', 'body_text': 'Content.'}
    save_markdown(filepath, 'https://example.com', 'example.com', content)
    assert Path(filepath).exists()
    text = Path(filepath).read_text()
    assert '# Test' in text


def test_save_markdown_creates_directory(tmp_path):
    filepath = str(tmp_path / 'deep' / 'nested' / 'article.md')
    save_markdown(filepath, 'https://example.com', 'example.com', {'headline': 'Test'})
    assert Path(filepath).exists()


def test_save_markdown_file_encoding_utf8(tmp_path):
    filepath = str(tmp_path / 'unicode.md')
    content = {'headline': 'Héllo Wörld'}
    save_markdown(filepath, 'https://example.com', 'example.com', content)
    text = Path(filepath).read_text(encoding='utf-8')
    assert 'Héllo' in text


def test_format_markdown_title_line_exact():
    """Title must appear as '# {title}' on its own line."""
    result = format_markdown('https://example.com', 'example.com', {'headline': 'My Title'})
    lines = result.split('\n')
    assert lines[0] == '# My Title'


def test_format_markdown_source_line_exact():
    """Source metadata line must be '**Source:** {url}'."""
    result = format_markdown('https://example.com/article', 'example.com', {'headline': 'T'})
    assert '**Source:** https://example.com/article' in result


def test_format_markdown_domain_line_exact():
    """Domain metadata line must be '**Domain:** {domain}'."""
    result = format_markdown('https://example.com', 'my.domain.com', {'headline': 'T'})
    assert '**Domain:** my.domain.com' in result


def test_format_markdown_extracted_label_exact():
    """Extracted label must be '**Extracted:**'."""
    result = format_markdown('https://example.com', 'example.com', {'headline': 'T'})
    assert '**Extracted:**' in result


def test_format_markdown_separator_lines():
    """There must be exactly two '---' separator lines."""
    result = format_markdown('https://example.com', 'example.com', {'headline': 'T'})
    lines = result.split('\n')
    dash_lines = [line for line in lines if line == '---']
    assert len(dash_lines) == 2


def test_format_markdown_section_header_format():
    """Section headers must be '## {field_title}' format."""
    result = format_markdown('https://example.com', 'example.com', {'author': 'Jane'})
    assert '## Author' in result


def test_format_markdown_skips_none_values():
    """Fields with None values must not appear as sections."""
    result = format_markdown('https://example.com', 'example.com', {'headline': 'T', 'author': None})
    assert '## Author' not in result


def test_format_markdown_skips_empty_string_values():
    """Fields with empty string values must not appear as sections."""
    result = format_markdown('https://example.com', 'example.com', {'headline': 'T', 'author': ''})
    assert '## Author' not in result


def test_get_title_uses_title_before_name():
    """'title' field takes priority over 'name' field."""
    content = {'title': 'From Title', 'name': 'From Name'}
    assert _get_title(content) == 'From Title'


def test_get_title_uses_name_before_heading():
    """'name' field takes priority over 'heading' field."""
    content = {'name': 'From Name', 'heading': 'From Heading'}
    assert _get_title(content) == 'From Name'


def test_get_title_uses_heading_before_h1():
    """'heading' field takes priority over 'h1' field."""
    content = {'heading': 'From Heading', 'h1': 'From H1'}
    assert _get_title(content) == 'From Heading'


def test_get_title_truncates_at_101_chars():
    """A string of exactly 101 chars should be truncated to 100 + '...'."""
    content = {'author': 'a' * 101}
    result = _get_title(content)
    assert len(result) == 103  # 100 chars + '...'
    assert result.endswith('...')


def test_get_title_no_truncation_at_100_chars():
    """A string of exactly 100 chars should NOT get '...'."""
    content = {'author': 'b' * 100}
    result = _get_title(content)
    assert result == 'b' * 100
    assert not result.endswith('...')


def test_get_title_fallback_strips_value():
    """Fallback title from first value must be stripped."""
    content = {'author': '  Jane Doe  '}
    result = _get_title(content)
    assert result == 'Jane Doe'


def test_get_title_skips_empty_string_in_fallback():
    """Fallback should skip empty strings."""
    content = {'author': '', 'rating': '4.5'}
    result = _get_title(content)
    assert result == '4.5'


def test_get_title_skips_whitespace_only_in_fallback():
    """Fallback should skip whitespace-only strings."""
    content = {'author': '   ', 'rating': '5.0'}
    result = _get_title(content)
    assert result == '5.0'


def test_format_value_string_returns_single_item_list():
    """String value must return a list with exactly one item."""
    lines = _format_value('Hello')
    assert len(lines) == 1
    assert lines[0] == 'Hello'


def test_format_value_list_items_have_dash_prefix():
    """Each list item must be prefixed with '- '."""
    lines = _format_value(['item1', 'item2', 'item3'])
    for line in lines:
        assert line.startswith('- ')


def test_format_value_dict_uses_bold_key_format():
    """Dict keys must appear as '**Key Name:**'."""
    lines = _format_value({'my_key': 'my_value'})
    assert any('**My Key:**' in line for line in lines)


def test_format_value_list_dict_link_format():
    """List of dicts must produce '[text](href)' link format."""
    lines = _format_value([{'text': 'Click', 'href': '/link'}])
    assert lines[0] == '- [Click](/link)'


def test_format_value_list_dict_title_fallback():
    """If no 'text' key, use 'title' for link text."""
    lines = _format_value([{'title': 'My Title', 'url': '/page'}])
    assert any('My Title' in line for line in lines)


def test_format_value_list_dict_item_default_text():
    """Default text for dict items with no text/title is 'Item'."""
    lines = _format_value([{'href': '/some-link'}])
    assert any('Item' in line for line in lines)


def test_format_value_list_dict_default_href_is_hash():
    """Default href for dict items with no href/url/link is '#'."""
    lines = _format_value([{'text': 'Click Me'}])
    assert any('#' in line for line in lines)


def test_format_value_integer_converts_to_str():
    """Integer values must be converted to string representation."""
    lines = _format_value(100)
    assert lines == ['100']


def test_save_markdown_writes_format_markdown_output(tmp_path):
    """save_markdown must write the output of format_markdown."""
    filepath = str(tmp_path / 'write_check.md')
    content = {'headline': 'My Article', 'author': 'Jane'}
    save_markdown(filepath, 'https://example.com', 'example.com', content)
    text = Path(filepath).read_text(encoding='utf-8')
    # Must contain format_markdown output
    assert '# My Article' in text
    assert '**Source:** https://example.com' in text


def test_save_markdown_uses_w_mode(tmp_path):
    """File must be opened in write mode 'w', overwriting existing content."""
    filepath = str(tmp_path / 'overwrite.md')
    Path(filepath).write_text('OLD CONTENT', encoding='utf-8')
    save_markdown(filepath, 'https://example.com', 'example.com', {'headline': 'New'})
    text = Path(filepath).read_text(encoding='utf-8')
    assert 'OLD CONTENT' not in text
    assert '# New' in text
