"""Tests for yosoi.utils.urls — core URL file loading (no CLI deps)."""

import json

import pytest

from yosoi.utils.urls import load_urls_from_file


class TestLoadUrlsFromFile:
    def test_file_not_found_raises(self, tmp_path):
        """FileNotFoundError raised for nonexistent files."""
        with pytest.raises(FileNotFoundError):
            load_urls_from_file(str(tmp_path / 'nope.txt'))

    def test_json_list_of_strings(self, tmp_path):
        """JSON file with a list of URL strings."""
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps(['http://a.com', 'http://b.com']))
        result = load_urls_from_file(str(f))
        assert result == ['http://a.com', 'http://b.com']

    def test_json_list_of_dicts(self, tmp_path):
        """JSON file with list of {url: ...} dicts."""
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps([{'url': 'http://a.com'}, {'url': 'http://b.com'}]))
        result = load_urls_from_file(str(f))
        assert result == ['http://a.com', 'http://b.com']

    def test_plain_text(self, tmp_path):
        """Plain text file with one URL per line."""
        f = tmp_path / 'urls.txt'
        f.write_text('http://a.com\n# comment\nhttp://b.com\n\n')
        result = load_urls_from_file(str(f))
        assert result == ['http://a.com', 'http://b.com']

    def test_plain_text_skips_empty_and_comments(self, tmp_path):
        """Empty lines and comment lines are ignored."""
        f = tmp_path / 'urls.txt'
        f.write_text('\n# skip me\n  \nhttp://only.com\n')
        result = load_urls_from_file(str(f))
        assert result == ['http://only.com']

    def test_markdown_file(self, tmp_path):
        """Markdown file extracts URLs from link syntax and bare URLs."""
        f = tmp_path / 'urls.md'
        f.write_text('[Link](http://a.com)\n\nhttp://b.com\n')
        result = load_urls_from_file(str(f))
        assert 'http://a.com' in result
        assert 'http://b.com' in result


class TestLoadUrlsFromJsonEdgeCases:
    def test_json_dict_with_url_values(self, tmp_path):
        """JSON dict where values are URL strings."""
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps({'page1': 'http://a.com', 'page2': 'http://b.com'}))
        result = load_urls_from_file(str(f))
        assert 'http://a.com' in result
        assert 'http://b.com' in result

    def test_json_dict_with_nested_url(self, tmp_path):
        """JSON dict where values are dicts with 'url' keys."""
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps({'p1': {'url': 'http://a.com'}, 'p2': {'url': 'http://b.com'}}))
        result = load_urls_from_file(str(f))
        assert 'http://a.com' in result

    def test_json_empty_list(self, tmp_path):
        """JSON empty list returns empty."""
        f = tmp_path / 'urls.json'
        f.write_text('[]')
        assert load_urls_from_file(str(f)) == []
