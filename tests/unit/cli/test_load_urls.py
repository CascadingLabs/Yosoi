"""Tests for load_urls_from_file multi-format support."""

import json

import pytest

from yosoi.cli.utils import _extract_urls_from_text, load_urls_from_file


class TestFileNotFound:
    def test_file_not_found(self, tmp_path):
        with pytest.raises(Exception, match='File not found'):
            load_urls_from_file(str(tmp_path / 'missing.txt'))


class TestJsonFormat:
    def test_json_list_of_strings(self, tmp_path):
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps(['https://a.com', 'https://b.com']))
        assert load_urls_from_file(str(f)) == ['https://a.com', 'https://b.com']

    def test_json_list_of_dicts_with_url_key(self, tmp_path):
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps([{'url': 'https://a.com'}]))
        assert load_urls_from_file(str(f)) == ['https://a.com']

    def test_json_list_skips_empty_strings(self, tmp_path):
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps(['https://a.com', '', 'https://b.com']))
        assert load_urls_from_file(str(f)) == ['https://a.com', 'https://b.com']

    def test_json_dict_of_strings(self, tmp_path):
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps({'a': 'https://a.com', 'b': 'https://b.com'}))
        assert load_urls_from_file(str(f)) == ['https://a.com', 'https://b.com']

    def test_json_dict_of_dicts_with_url_key(self, tmp_path):
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps({'a': {'url': 'https://a.com'}}))
        assert load_urls_from_file(str(f)) == ['https://a.com']

    def test_json_unknown_structure_returns_empty(self, tmp_path):
        f = tmp_path / 'urls.json'
        f.write_text(json.dumps({'a': 42}))
        assert load_urls_from_file(str(f)) == []


class TestPlainTextFormat:
    def test_txt_one_url_per_line(self, tmp_path):
        f = tmp_path / 'urls.txt'
        f.write_text('https://a.com\nhttps://b.com\n')
        assert load_urls_from_file(str(f)) == ['https://a.com', 'https://b.com']

    def test_txt_skips_comment_lines(self, tmp_path):
        f = tmp_path / 'urls.txt'
        f.write_text('# comment\nhttps://a.com\n')
        assert load_urls_from_file(str(f)) == ['https://a.com']

    def test_txt_skips_blank_lines(self, tmp_path):
        f = tmp_path / 'urls.txt'
        f.write_text('https://a.com\n\n   \nhttps://b.com\n')
        assert load_urls_from_file(str(f)) == ['https://a.com', 'https://b.com']


class TestCsvFormat:
    def test_csv_url_column(self, tmp_path):
        pd = pytest.importorskip('pandas')
        f = tmp_path / 'urls.csv'
        pd.DataFrame({'url': ['https://a.com', 'https://b.com']}).to_csv(f, index=False)
        assert load_urls_from_file(str(f)) == ['https://a.com', 'https://b.com']

    def test_csv_url_column_case_insensitive(self, tmp_path):
        pd = pytest.importorskip('pandas')
        f = tmp_path / 'urls.csv'
        pd.DataFrame({'URL': ['https://a.com']}).to_csv(f, index=False)
        assert load_urls_from_file(str(f)) == ['https://a.com']

    def test_csv_no_url_column_extracts_from_text(self, tmp_path):
        pd = pytest.importorskip('pandas')
        f = tmp_path / 'urls.csv'
        pd.DataFrame({'text': ['visit https://a.com today']}).to_csv(f, index=False)
        result = load_urls_from_file(str(f))
        assert 'https://a.com' in result

    def test_csv_missing_pandas_raises_error(self, tmp_path, mocker):
        mocker.patch('yosoi.cli.utils.HAS_PANDAS', False)
        f = tmp_path / 'urls.csv'
        f.write_text('url\nhttps://a.com\n')
        with pytest.raises(Exception, match='pandas is required'):
            load_urls_from_file(str(f))


class TestExcelFormat:
    def test_xlsx_url_column(self, tmp_path):
        pd = pytest.importorskip('pandas')
        pytest.importorskip('openpyxl')
        f = tmp_path / 'urls.xlsx'
        pd.DataFrame({'url': ['https://a.com', 'https://b.com']}).to_excel(f, index=False)
        assert load_urls_from_file(str(f)) == ['https://a.com', 'https://b.com']

    def test_xlsx_multiple_sheets(self, tmp_path):
        pd = pytest.importorskip('pandas')
        pytest.importorskip('openpyxl')
        f = tmp_path / 'urls.xlsx'
        with pd.ExcelWriter(f, engine='openpyxl') as writer:
            pd.DataFrame({'url': ['https://a.com']}).to_excel(writer, sheet_name='Sheet1', index=False)
            pd.DataFrame({'url': ['https://b.com']}).to_excel(writer, sheet_name='Sheet2', index=False)
        result = load_urls_from_file(str(f))
        assert 'https://a.com' in result
        assert 'https://b.com' in result

    def test_xlsx_no_url_column_extracts_from_text(self, tmp_path):
        pd = pytest.importorskip('pandas')
        pytest.importorskip('openpyxl')
        f = tmp_path / 'urls.xlsx'
        pd.DataFrame({'notes': ['see https://a.com for details']}).to_excel(f, index=False)
        result = load_urls_from_file(str(f))
        assert 'https://a.com' in result

    def test_xlsx_missing_pandas_raises_error(self, tmp_path, mocker):
        mocker.patch('yosoi.cli.utils.HAS_PANDAS', False)
        f = tmp_path / 'urls.xlsx'
        f.write_bytes(b'fake')
        with pytest.raises(Exception, match='pandas is required'):
            load_urls_from_file(str(f))


class TestParquetFormat:
    def test_parquet_url_column(self, tmp_path):
        pd = pytest.importorskip('pandas')
        pytest.importorskip('pyarrow')
        f = tmp_path / 'urls.parquet'
        pd.DataFrame({'url': ['https://a.com', 'https://b.com']}).to_parquet(f)
        assert load_urls_from_file(str(f)) == ['https://a.com', 'https://b.com']

    def test_parquet_no_url_column_extracts_from_text(self, tmp_path):
        pd = pytest.importorskip('pandas')
        pytest.importorskip('pyarrow')
        f = tmp_path / 'urls.parquet'
        pd.DataFrame({'notes': ['visit https://a.com']}).to_parquet(f)
        result = load_urls_from_file(str(f))
        assert 'https://a.com' in result

    def test_parquet_missing_pandas_raises_error(self, tmp_path, mocker):
        mocker.patch('yosoi.cli.utils.HAS_PANDAS', False)
        f = tmp_path / 'urls.parquet'
        f.write_bytes(b'fake')
        with pytest.raises(Exception, match='pandas is required'):
            load_urls_from_file(str(f))


class TestMarkdownFormat:
    def test_md_markdown_link_syntax(self, tmp_path):
        f = tmp_path / 'urls.md'
        f.write_text('Check out [this site](https://a.com) and [another](https://b.com).')
        assert load_urls_from_file(str(f)) == ['https://a.com', 'https://b.com']

    def test_md_plain_urls_in_text(self, tmp_path):
        f = tmp_path / 'urls.md'
        f.write_text('Visit https://a.com for more info.')
        result = load_urls_from_file(str(f))
        assert 'https://a.com' in result

    def test_md_deduplication(self, tmp_path):
        f = tmp_path / 'urls.md'
        f.write_text('[link](https://a.com) and also https://a.com in plain text.')
        result = load_urls_from_file(str(f))
        assert result.count('https://a.com') == 1

    def test_md_non_http_links_ignored(self, tmp_path):
        f = tmp_path / 'urls.md'
        f.write_text('[relative](/path/to/page) [mail](mailto:x@y.com) [valid](https://a.com)')
        result = load_urls_from_file(str(f))
        assert result == ['https://a.com']


class TestExtractUrlsFromText:
    def test_extract_urls_from_text_basic(self):
        text = 'Go to https://a.com or http://b.org for details.'
        result = _extract_urls_from_text(text)
        assert 'https://a.com' in result
        assert 'http://b.org' in result

    def test_extract_urls_trailing_punctuation_stripped(self):
        text = 'See https://a.com. Also https://b.com, and https://c.com)'
        result = _extract_urls_from_text(text)
        assert 'https://a.com' in result
        assert 'https://b.com' in result
        assert 'https://c.com' in result
        for url in result:
            assert not url.endswith(('.', ',', ')'))
