"""Tests for Parquet output module."""

import sys
from pathlib import Path

import pytest

URL = 'https://example.com/article'
DOMAIN = 'example.com'
CONTENT = {'headline': 'Test Article', 'author': 'Jane Doe'}


@pytest.fixture
def parquet_save():
    pytest.importorskip('pyarrow', reason='pyarrow not installed')
    from yosoi.outputs.parquet import save_parquet

    return save_parquet


def test_save_parquet_creates_file(tmp_path, parquet_save):
    filepath = str(tmp_path / 'results.parquet')
    parquet_save(filepath, URL, DOMAIN, CONTENT)
    assert Path(filepath).exists()


def test_save_parquet_file_readable_back(tmp_path, parquet_save):
    import pyarrow.parquet as pq

    filepath = str(tmp_path / 'results.parquet')
    parquet_save(filepath, URL, DOMAIN, CONTENT)
    table = pq.read_table(filepath)
    assert table.num_rows == 1


def test_save_parquet_contains_url_column(tmp_path, parquet_save):
    import pyarrow.parquet as pq

    filepath = str(tmp_path / 'results.parquet')
    parquet_save(filepath, URL, DOMAIN, CONTENT)
    table = pq.read_table(filepath)
    assert 'url' in table.column_names


def test_save_parquet_contains_domain_column(tmp_path, parquet_save):
    import pyarrow.parquet as pq

    filepath = str(tmp_path / 'results.parquet')
    parquet_save(filepath, URL, DOMAIN, CONTENT)
    table = pq.read_table(filepath)
    assert 'domain' in table.column_names


def test_save_parquet_url_value_correct(tmp_path, parquet_save):
    import pyarrow.parquet as pq

    filepath = str(tmp_path / 'results.parquet')
    parquet_save(filepath, URL, DOMAIN, CONTENT)
    table = pq.read_table(filepath)
    assert table.column('url')[0].as_py() == URL


def test_save_parquet_appends_second_row(tmp_path, parquet_save):
    import pyarrow.parquet as pq

    filepath = str(tmp_path / 'results.parquet')
    parquet_save(filepath, URL, DOMAIN, CONTENT)
    parquet_save(filepath, 'https://example.com/page2', DOMAIN, {'headline': 'Second', 'author': 'Bob'})
    table = pq.read_table(filepath)
    assert table.num_rows == 2


def test_save_parquet_creates_parent_directory(tmp_path, parquet_save):
    filepath = str(tmp_path / 'subdir' / 'nested' / 'results.parquet')
    parquet_save(filepath, URL, DOMAIN, CONTENT)
    assert Path(filepath).exists()


def test_save_parquet_raises_import_error_without_pyarrow(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, 'pyarrow', None)
    monkeypatch.setitem(sys.modules, 'pyarrow.parquet', None)
    # Re-import to get fresh module without cached pyarrow
    import importlib

    import yosoi.outputs.parquet as parquet_mod

    importlib.reload(parquet_mod)
    with pytest.raises(ImportError):
        parquet_mod.save_parquet(str(tmp_path / 'f.parquet'), URL, DOMAIN, CONTENT)
