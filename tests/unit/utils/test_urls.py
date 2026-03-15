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


class TestExtractUrlsFromText:
    def test_extracts_http_url(self):
        from yosoi.utils.urls import _extract_urls_from_text

        result = _extract_urls_from_text('Check out https://example.com/page today!')
        assert 'https://example.com/page' in result

    def test_strips_trailing_punctuation(self):
        from yosoi.utils.urls import _extract_urls_from_text

        result = _extract_urls_from_text('See https://example.com/path.')
        assert 'https://example.com/path' in result
        assert 'https://example.com/path.' not in result

    def test_strips_trailing_comma(self):
        from yosoi.utils.urls import _extract_urls_from_text

        result = _extract_urls_from_text('Visit https://a.com, then https://b.com')
        assert 'https://a.com' in result
        assert 'https://b.com' in result

    def test_strips_trailing_parenthesis(self):
        from yosoi.utils.urls import _extract_urls_from_text

        result = _extract_urls_from_text('(see https://a.com/page)')
        assert 'https://a.com/page' in result

    def test_multiple_urls(self):
        from yosoi.utils.urls import _extract_urls_from_text

        text = 'First: https://a.com second: http://b.org'
        result = _extract_urls_from_text(text)
        assert len(result) == 2

    def test_empty_string_returns_empty(self):
        from yosoi.utils.urls import _extract_urls_from_text

        assert _extract_urls_from_text('') == []

    def test_no_urls_returns_empty(self):
        from yosoi.utils.urls import _extract_urls_from_text

        assert _extract_urls_from_text('no urls here') == []


class TestLoadUrlsFromMarkdown:
    def test_deduplicates_url_in_link_and_bare(self, tmp_path):
        """A URL appearing as markdown link and bare text is deduplicated."""
        from yosoi.utils.urls import _load_urls_from_markdown

        f = tmp_path / 'links.md'
        # Same URL appears in link syntax AND bare in text
        f.write_text('[Link](https://example.com)\n\nhttps://example.com\n')
        result = _load_urls_from_markdown(str(f))
        assert result.count('https://example.com') == 1

    def test_bare_url_only(self, tmp_path):
        """Bare URL (no markdown link) is extracted."""
        from yosoi.utils.urls import _load_urls_from_markdown

        f = tmp_path / 'links.md'
        f.write_text('Visit https://bare.com/page today\n')
        result = _load_urls_from_markdown(str(f))
        assert 'https://bare.com/page' in result

    def test_link_syntax_only(self, tmp_path):
        """Markdown link URL is extracted."""
        from yosoi.utils.urls import _load_urls_from_markdown

        f = tmp_path / 'links.md'
        f.write_text('[Click here](https://link.com/path)\n')
        result = _load_urls_from_markdown(str(f))
        assert 'https://link.com/path' in result

    def test_multiple_links_deduplicated(self, tmp_path):
        """Multiple links with same URL are deduplicated."""
        from yosoi.utils.urls import _load_urls_from_markdown

        f = tmp_path / 'links.md'
        f.write_text('[A](https://dup.com)\n[B](https://dup.com)\n')
        result = _load_urls_from_markdown(str(f))
        assert result.count('https://dup.com') == 1
