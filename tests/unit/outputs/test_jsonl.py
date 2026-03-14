"""Tests for JSONL output module."""

import json
from pathlib import Path

from yosoi.outputs.jsonl import format_jsonl, save_jsonl

URL = 'https://example.com/article'
DOMAIN = 'example.com'
CONTENT = {'headline': 'Test Article', 'author': 'Jane Doe'}


def test_format_jsonl_returns_valid_json_string():
    line = format_jsonl(URL, DOMAIN, CONTENT)
    parsed = json.loads(line)
    assert isinstance(parsed, dict)


def test_format_jsonl_includes_url():
    line = format_jsonl(URL, DOMAIN, CONTENT)
    assert json.loads(line)['url'] == URL


def test_format_jsonl_includes_domain():
    line = format_jsonl(URL, DOMAIN, CONTENT)
    assert json.loads(line)['domain'] == DOMAIN


def test_format_jsonl_includes_content_fields():
    line = format_jsonl(URL, DOMAIN, CONTENT)
    parsed = json.loads(line)
    assert parsed['headline'] == 'Test Article'
    assert parsed['author'] == 'Jane Doe'


def test_format_jsonl_includes_extracted_at():
    line = format_jsonl(URL, DOMAIN, CONTENT)
    parsed = json.loads(line)
    assert 'extracted_at' in parsed


def test_format_jsonl_no_trailing_newline():
    line = format_jsonl(URL, DOMAIN, CONTENT)
    assert not line.endswith('\n')


def test_format_jsonl_filters_reserved_keys():
    content = {'url': 'http://attacker.com', 'domain': 'evil.com', 'extracted_at': 'fake', 'headline': 'Test'}
    line = format_jsonl(URL, DOMAIN, content)
    parsed = json.loads(line)
    assert parsed['url'] == URL
    assert parsed['domain'] == DOMAIN
    assert parsed['extracted_at'] != 'fake'
    assert parsed['headline'] == 'Test'


def test_save_jsonl_creates_file(tmp_path):
    filepath = str(tmp_path / 'results.jsonl')
    save_jsonl(filepath, URL, DOMAIN, CONTENT)
    assert Path(filepath).exists()


def test_save_jsonl_file_has_one_line(tmp_path):
    filepath = str(tmp_path / 'results.jsonl')
    save_jsonl(filepath, URL, DOMAIN, CONTENT)
    lines = Path(filepath).read_text().splitlines()
    assert len(lines) == 1


def test_save_jsonl_each_line_is_valid_json(tmp_path):
    filepath = str(tmp_path / 'results.jsonl')
    save_jsonl(filepath, URL, DOMAIN, CONTENT)
    save_jsonl(filepath, 'https://example.com/page2', DOMAIN, {'headline': 'Second'})
    for line in Path(filepath).read_text().splitlines():
        json.loads(line)  # must not raise


def test_save_jsonl_appends_second_call(tmp_path):
    filepath = str(tmp_path / 'results.jsonl')
    save_jsonl(filepath, URL, DOMAIN, CONTENT)
    save_jsonl(filepath, 'https://example.com/page2', DOMAIN, {'headline': 'Second'})
    lines = Path(filepath).read_text().splitlines()
    assert len(lines) == 2


def test_save_jsonl_second_line_has_correct_url(tmp_path):
    filepath = str(tmp_path / 'results.jsonl')
    save_jsonl(filepath, URL, DOMAIN, CONTENT)
    url2 = 'https://example.com/page2'
    save_jsonl(filepath, url2, DOMAIN, {'headline': 'Second'})
    lines = Path(filepath).read_text().splitlines()
    assert json.loads(lines[1])['url'] == url2


def test_save_jsonl_creates_parent_directory(tmp_path):
    filepath = str(tmp_path / 'subdir' / 'nested' / 'results.jsonl')
    save_jsonl(filepath, URL, DOMAIN, CONTENT)
    assert Path(filepath).exists()


def test_save_jsonl_unicode_content(tmp_path):
    filepath = str(tmp_path / 'results.jsonl')
    content = {'headline': 'Ünïcödé têxt 日本語'}
    save_jsonl(filepath, URL, DOMAIN, content)
    parsed = json.loads(Path(filepath).read_text(encoding='utf-8').strip())
    assert parsed['headline'] == 'Ünïcödé têxt 日本語'


def test_save_jsonl_none_values_serialized(tmp_path):
    filepath = str(tmp_path / 'results.jsonl')
    content = {'headline': None, 'author': 'Someone'}
    save_jsonl(filepath, URL, DOMAIN, content)
    parsed = json.loads(Path(filepath).read_text().strip())
    assert parsed['author'] == 'Someone'
    assert parsed['headline'] is None
