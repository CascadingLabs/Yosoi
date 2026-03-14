"""Tests for outputs utility functions."""

import json
from pathlib import Path

from yosoi.outputs.utils import format_content, format_selectors, save_formatted_content, save_formatted_selectors


def test_format_content_json():
    content = {'title': 'Hello', 'body': 'World'}
    result = format_content('https://example.com', 'example.com', content, 'json')
    assert isinstance(result, dict)
    assert result['content'] == content


def test_format_content_json_default():
    content = {'title': 'Hello'}
    result = format_content('https://example.com', 'example.com', content)
    assert isinstance(result, dict)
    assert result['url'] == 'https://example.com'


def test_format_content_json_has_domain():
    content = {'title': 'Hello'}
    result = format_content('https://example.com', 'example.com', content, 'json')
    assert isinstance(result, dict)
    assert result['domain'] == 'example.com'


def test_format_content_markdown():
    content = {'headline': 'Article Title', 'body_text': 'Content here.'}
    result = format_content('https://example.com', 'example.com', content, 'markdown')
    assert isinstance(result, str)
    assert 'Article Title' in result


def test_format_content_markdown_not_dict():
    content = {'headline': 'Article Title'}
    result = format_content('https://example.com', 'example.com', content, 'markdown')
    assert not isinstance(result, dict)


def test_format_content_unknown_format_defaults_to_json():
    """Any non-markdown format defaults to JSON."""
    content = {'title': 'Hello'}
    result = format_content('https://example.com', 'example.com', content, 'xml')
    assert isinstance(result, dict)


def test_format_selectors_returns_dict():
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'NA'}}
    result = format_selectors('https://example.com', 'example.com', selectors)
    assert isinstance(result, dict)
    assert result['selectors'] == selectors


def test_format_selectors_has_url():
    selectors = {'title': {'primary': 'h1'}}
    result = format_selectors('https://example.com', 'example.com', selectors)
    assert result['url'] == 'https://example.com'


def test_format_selectors_has_domain():
    selectors = {'title': {'primary': 'h1'}}
    result = format_selectors('https://example.com', 'example.com', selectors)
    assert result['domain'] == 'example.com'


def test_save_formatted_content_json(tmp_path):
    filepath = str(tmp_path / 'out' / 'content.json')
    content = {'title': 'Test', 'body': 'Body text'}
    result = save_formatted_content(filepath, 'https://example.com', 'example.com', content, 'json')
    assert Path(filepath).exists()
    assert result == filepath


def test_save_formatted_content_json_valid(tmp_path):
    filepath = str(tmp_path / 'out2' / 'content.json')
    content = {'title': 'Test'}
    save_formatted_content(filepath, 'https://example.com', 'example.com', content, 'json')
    data = json.loads(Path(filepath).read_text())
    assert data['content'] == content


def test_save_formatted_content_markdown(tmp_path):
    filepath = str(tmp_path / 'out' / 'article.md')
    content = {'headline': 'Test', 'body_text': 'Body.'}
    save_formatted_content(filepath, 'https://example.com', 'example.com', content, 'markdown')
    assert Path(filepath).exists()
    assert '# Test' in Path(filepath).read_text()


def test_save_formatted_content_returns_filepath(tmp_path):
    filepath = str(tmp_path / 'article.md')
    content = {'headline': 'Test'}
    result = save_formatted_content(filepath, 'https://example.com', 'example.com', content, 'markdown')
    assert result == filepath


def test_save_formatted_selectors_creates_file(tmp_path):
    filepath = str(tmp_path / 'selectors.json')
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'NA'}}
    result = save_formatted_selectors(filepath, 'https://example.com', 'example.com', selectors)
    assert Path(filepath).exists()
    assert result == filepath


def test_save_formatted_selectors_valid_json(tmp_path):
    filepath = str(tmp_path / 'selectors2.json')
    selectors = {'title': {'primary': 'h1'}}
    save_formatted_selectors(filepath, 'https://example.com', 'example.com', selectors)
    data = json.loads(Path(filepath).read_text())
    assert data['selectors'] == selectors


def test_format_content_calls_format_markdown_for_markdown(mocker):
    """When output_format='markdown', must call format_markdown, not format_json."""
    mock_md = mocker.patch('yosoi.outputs.utils.format_markdown', return_value='# Title\nContent')
    content = {'headline': 'Title', 'body_text': 'Content'}
    result = format_content('https://example.com', 'example.com', content, 'markdown')
    mock_md.assert_called_once_with('https://example.com', 'example.com', content)
    assert result == '# Title\nContent'


def test_format_content_calls_format_json_for_json(mocker):
    """When output_format='json', must call format_json, not format_markdown."""
    mock_json = mocker.patch(
        'yosoi.outputs.utils.format_json', return_value={'url': 'x', 'domain': 'y', 'extracted_at': 't', 'content': {}}
    )
    content = {'title': 'Hello'}
    format_content('https://example.com', 'example.com', content, 'json')
    mock_json.assert_called_once_with('https://example.com', 'example.com', content)


def test_format_content_default_calls_format_json(mocker):
    """Default output_format='json' must call format_json."""
    mock_json = mocker.patch(
        'yosoi.outputs.utils.format_json', return_value={'url': 'x', 'domain': 'y', 'extracted_at': 't', 'content': {}}
    )
    format_content('https://example.com', 'example.com', {'title': 'Hello'})
    mock_json.assert_called_once()


def test_save_formatted_content_calls_save_json_for_json(mocker, tmp_path):
    """When output_format='json', must call save_json, not save_markdown."""
    mock_save = mocker.patch('yosoi.outputs.utils.save_json')
    filepath = str(tmp_path / 'out.json')
    content = {'title': 'Test'}
    save_formatted_content(filepath, 'https://example.com', 'example.com', content, 'json')
    mock_save.assert_called_once_with(filepath, 'https://example.com', 'example.com', content)


def test_save_formatted_content_calls_save_markdown_for_markdown(mocker, tmp_path):
    """When output_format='markdown', must call save_markdown, not save_json."""
    mock_save = mocker.patch('yosoi.outputs.utils.save_markdown')
    filepath = str(tmp_path / 'out.md')
    content = {'headline': 'Test'}
    save_formatted_content(filepath, 'https://example.com', 'example.com', content, 'markdown')
    mock_save.assert_called_once_with(filepath, 'https://example.com', 'example.com', content)


def test_save_formatted_content_returns_filepath_not_none(tmp_path):
    """save_formatted_content must return the filepath string."""
    filepath = str(tmp_path / 'result.json')
    result = save_formatted_content(filepath, 'https://example.com', 'example.com', {'title': 'X'}, 'json')
    assert result == filepath
    assert result is not None


def test_save_formatted_selectors_calls_save_selectors_json(mocker, tmp_path):
    """save_formatted_selectors must call save_selectors_json with correct args."""
    mock_save = mocker.patch('yosoi.outputs.utils.save_selectors_json')
    filepath = str(tmp_path / 'sel.json')
    selectors = {'title': {'primary': 'h1'}}
    save_formatted_selectors(filepath, 'https://example.com', 'example.com', selectors)
    mock_save.assert_called_once_with(filepath, 'https://example.com', 'example.com', selectors)


def test_save_formatted_selectors_returns_filepath(mocker, tmp_path):
    """save_formatted_selectors must return the filepath."""
    mocker.patch('yosoi.outputs.utils.save_selectors_json')
    filepath = str(tmp_path / 'sel2.json')
    result = save_formatted_selectors(filepath, 'https://example.com', 'example.com', {})
    assert result == filepath


# --- New format routing tests ---


def test_save_formatted_content_routes_jsonl(mocker, tmp_path):
    mock = mocker.patch('yosoi.outputs.utils.save_jsonl')
    filepath = str(tmp_path / 'results.jsonl')
    save_formatted_content(filepath, 'https://example.com', 'example.com', {'title': 'X'}, 'jsonl')
    mock.assert_called_once_with(filepath, 'https://example.com', 'example.com', {'title': 'X'})


def test_save_formatted_content_routes_ndjson(mocker, tmp_path):
    mock = mocker.patch('yosoi.outputs.utils.save_jsonl')
    filepath = str(tmp_path / 'results.jsonl')
    save_formatted_content(filepath, 'https://example.com', 'example.com', {'title': 'X'}, 'ndjson')
    mock.assert_called_once_with(filepath, 'https://example.com', 'example.com', {'title': 'X'})


def test_save_formatted_content_routes_csv(mocker, tmp_path):
    mock = mocker.patch('yosoi.outputs.utils.save_csv')
    filepath = str(tmp_path / 'results.csv')
    save_formatted_content(filepath, 'https://example.com', 'example.com', {'title': 'X'}, 'csv')
    mock.assert_called_once_with(filepath, 'https://example.com', 'example.com', {'title': 'X'})


def test_save_formatted_content_routes_xlsx(mocker, tmp_path):
    mock = mocker.patch('yosoi.outputs.utils.save_xlsx')
    filepath = str(tmp_path / 'results.xlsx')
    save_formatted_content(filepath, 'https://example.com', 'example.com', {'title': 'X'}, 'xlsx')
    mock.assert_called_once_with(filepath, 'https://example.com', 'example.com', {'title': 'X'})


def test_save_formatted_content_routes_parquet(mocker, tmp_path):
    mock = mocker.patch('yosoi.outputs.utils.save_parquet')
    filepath = str(tmp_path / 'results.parquet')
    save_formatted_content(filepath, 'https://example.com', 'example.com', {'title': 'X'}, 'parquet')
    mock.assert_called_once_with(filepath, 'https://example.com', 'example.com', {'title': 'X'})


def test_save_formatted_content_unknown_format_falls_back_to_json(mocker, tmp_path):
    mock = mocker.patch('yosoi.outputs.utils.save_json')
    filepath = str(tmp_path / 'out.xml')
    save_formatted_content(filepath, 'https://example.com', 'example.com', {'title': 'X'}, 'xml')
    mock.assert_called_once()
