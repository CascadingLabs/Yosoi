"""Tests for CSV output module."""

import csv
import io
from pathlib import Path

from yosoi.outputs.csv import format_csv, save_csv

URL = 'https://example.com/article'
DOMAIN = 'example.com'
CONTENT = {'headline': 'Test Article', 'author': 'Jane Doe'}


def test_format_csv_returns_string():
    result = format_csv(URL, DOMAIN, CONTENT)
    assert isinstance(result, str)


def test_format_csv_includes_data_values():
    result = format_csv(URL, DOMAIN, CONTENT)
    assert 'Test Article' in result


def test_format_csv_round_trips_through_reader():
    result = format_csv(URL, DOMAIN, CONTENT)
    reader = csv.DictReader(io.StringIO('url,domain,headline,author\n' + result))
    row = next(reader)
    assert row['headline'] == 'Test Article'
    assert row['author'] == 'Jane Doe'


def test_save_csv_creates_file(tmp_path):
    filepath = str(tmp_path / 'results.csv')
    save_csv(filepath, URL, DOMAIN, CONTENT)
    assert Path(filepath).exists()


def test_save_csv_writes_header_row(tmp_path):
    filepath = str(tmp_path / 'results.csv')
    save_csv(filepath, URL, DOMAIN, CONTENT)
    with Path(filepath).open(newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
    assert 'url' in fieldnames
    assert 'domain' in fieldnames
    assert 'headline' in fieldnames


def test_save_csv_writes_data_row(tmp_path):
    filepath = str(tmp_path / 'results.csv')
    save_csv(filepath, URL, DOMAIN, CONTENT)
    with Path(filepath).open(newline='') as f:
        reader = csv.DictReader(f)
        row = next(reader)
    assert row['headline'] == 'Test Article'
    assert row['url'] == URL


def test_save_csv_no_duplicate_header_on_append(tmp_path):
    filepath = str(tmp_path / 'results.csv')
    save_csv(filepath, URL, DOMAIN, CONTENT)
    save_csv(filepath, 'https://example.com/page2', DOMAIN, {'headline': 'Second', 'author': 'Bob'})
    lines = Path(filepath).read_text().splitlines()
    header_count = sum(1 for line in lines if line.startswith('url,'))
    assert header_count == 1


def test_save_csv_second_row_appends(tmp_path):
    filepath = str(tmp_path / 'results.csv')
    save_csv(filepath, URL, DOMAIN, CONTENT)
    save_csv(filepath, 'https://example.com/page2', DOMAIN, {'headline': 'Second', 'author': 'Bob'})
    with Path(filepath).open(newline='') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2


def test_save_csv_second_row_has_correct_url(tmp_path):
    filepath = str(tmp_path / 'results.csv')
    save_csv(filepath, URL, DOMAIN, CONTENT)
    url2 = 'https://example.com/page2'
    save_csv(filepath, url2, DOMAIN, {'headline': 'Second', 'author': 'Bob'})
    with Path(filepath).open(newline='') as f:
        rows = list(csv.DictReader(f))
    assert rows[1]['url'] == url2


def test_save_csv_creates_parent_directory(tmp_path):
    filepath = str(tmp_path / 'subdir' / 'nested' / 'results.csv')
    save_csv(filepath, URL, DOMAIN, CONTENT)
    assert Path(filepath).exists()


def test_save_csv_none_values_become_empty_string(tmp_path):
    filepath = str(tmp_path / 'results.csv')
    save_csv(filepath, URL, DOMAIN, {'headline': None, 'author': 'Bob'})
    with Path(filepath).open(newline='') as f:
        row = next(csv.DictReader(f))
    assert row['headline'] == ''
    assert row['author'] == 'Bob'
