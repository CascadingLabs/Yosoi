"""Integration tests for Parquet output — uses real pyarrow file I/O, no mocks.

Apache Parquet + PyArrow are embedded/file-based (no Docker container needed).
These tests verify that save_parquet produces valid Parquet files that can be
read back correctly, handles append semantics, and preserves all column values.
"""

import pytest

pyarrow = pytest.importorskip('pyarrow', reason='pyarrow not installed — run: uv add pyarrow')

import pyarrow.parquet as pq

from yosoi.outputs.parquet import save_parquet

ARTICLES = [
    {
        'url': 'https://techcrunch.com/ai-advances',
        'domain': 'techcrunch.com',
        'content': {'headline': 'AI Advances in 2026', 'author': 'Alice Smith', 'word_count': '1200'},
    },
    {
        'url': 'https://techcrunch.com/llm-benchmark',
        'domain': 'techcrunch.com',
        'content': {'headline': 'LLM Benchmark Results', 'author': 'Bob Jones', 'word_count': '800'},
    },
    {
        'url': 'https://wired.com/quantum-computing',
        'domain': 'wired.com',
        'content': {'headline': 'Quantum Computing Today', 'author': 'Carol White', 'word_count': '2000'},
    },
]


@pytest.fixture
def parquet_path(tmp_path):
    return str(tmp_path / 'integration_results.parquet')


def test_single_write_produces_valid_parquet(parquet_path):
    """A single save produces a valid Parquet file readable by pyarrow."""
    article = ARTICLES[0]
    save_parquet(parquet_path, article['url'], article['domain'], article['content'])
    table = pq.read_table(parquet_path)
    assert table.num_rows == 1


def test_parquet_contains_url_and_domain_columns(parquet_path):
    article = ARTICLES[0]
    save_parquet(parquet_path, article['url'], article['domain'], article['content'])
    table = pq.read_table(parquet_path)
    assert 'url' in table.column_names
    assert 'domain' in table.column_names


def test_parquet_url_value_survives_roundtrip(parquet_path):
    article = ARTICLES[0]
    save_parquet(parquet_path, article['url'], article['domain'], article['content'])
    table = pq.read_table(parquet_path)
    assert table.column('url')[0].as_py() == article['url']


def test_parquet_content_fields_survive_roundtrip(parquet_path):
    article = ARTICLES[0]
    save_parquet(parquet_path, article['url'], article['domain'], article['content'])
    table = pq.read_table(parquet_path)
    assert table.column('headline')[0].as_py() == 'AI Advances in 2026'
    assert table.column('author')[0].as_py() == 'Alice Smith'


def test_append_multiple_rows_accumulate_correctly(parquet_path):
    """Sequential saves append rows so final table has all articles."""
    for article in ARTICLES:
        save_parquet(parquet_path, article['url'], article['domain'], article['content'])
    table = pq.read_table(parquet_path)
    assert table.num_rows == len(ARTICLES)


def test_all_urls_present_after_append(parquet_path):
    """All written URLs appear in the final Parquet file."""
    for article in ARTICLES:
        save_parquet(parquet_path, article['url'], article['domain'], article['content'])
    table = pq.read_table(parquet_path)
    urls = table.column('url').to_pylist()
    for article in ARTICLES:
        assert article['url'] in urls


def test_multi_domain_data_in_single_file(parquet_path):
    """Multiple domains coexist in the same Parquet file."""
    for article in ARTICLES:
        save_parquet(parquet_path, article['url'], article['domain'], article['content'])
    table = pq.read_table(parquet_path)
    domains = set(table.column('domain').to_pylist())
    assert 'techcrunch.com' in domains
    assert 'wired.com' in domains


def test_parquet_file_schema_has_expected_columns(parquet_path):
    """The Parquet schema exposes expected field names."""
    article = ARTICLES[0]
    save_parquet(parquet_path, article['url'], article['domain'], article['content'])
    schema = pq.read_schema(parquet_path)
    field_names = schema.names
    assert 'url' in field_names
    assert 'domain' in field_names
    assert 'headline' in field_names
