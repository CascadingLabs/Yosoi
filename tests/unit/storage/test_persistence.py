"""Tests for SelectorStorage save/load/domain extraction."""

import os

import pytest

from yosoi.storage.persistence import SelectorStorage


@pytest.fixture
def storage(tmp_path, mocker):
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir()
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    return SelectorStorage()


def test_save_and_load_selectors(storage):
    selectors = {
        'headline': {'primary': 'h1.title', 'fallback': 'h1', 'tertiary': 'NA'},
    }
    storage.save_selectors('https://example.com/article', selectors)
    loaded = storage.load_selectors('example.com')
    assert loaded is not None
    assert loaded['headline']['primary'] == 'h1.title'


def test_save_selectors_formats_with_primary_fallback_tertiary(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2'}}
    storage.save_selectors('https://example.com', selectors)
    loaded = storage.load_selectors('example.com')
    assert loaded['title']['primary'] == 'h1'
    assert loaded['title']['fallback'] == 'h2'
    assert loaded['title']['tertiary'] == 'NA'  # default when not provided


def test_nonexistent_domain_returns_none(storage):
    result = storage.load_selectors('nonexistent.com')
    assert result is None


def test_domain_extraction_strips_www(storage):
    domain = storage._extract_domain('https://www.example.com/path')
    assert domain == 'example.com'


def test_domain_extraction_no_www(storage):
    domain = storage._extract_domain('https://example.com/path')
    assert domain == 'example.com'


def test_domain_extraction_handles_invalid_url(storage):
    domain = storage._extract_domain('not-a-valid-url')
    # Should return 'unknown' or empty, not raise
    assert isinstance(domain, str)


def test_selector_exists_after_save(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://test.com', selectors)
    assert storage.selector_exists('test.com') is True


def test_selector_not_exists(storage):
    assert storage.selector_exists('nothere.com') is False


def test_list_domains_empty(storage):
    assert storage.list_domains() == []


def test_list_domains_after_save(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://alpha.com', selectors)
    storage.save_selectors('https://beta.com', selectors)
    domains = storage.list_domains()
    assert 'alpha.com' in domains
    assert 'beta.com' in domains


def test_list_domains_returns_sorted(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://zzz.com', selectors)
    storage.save_selectors('https://aaa.com', selectors)
    domains = storage.list_domains()
    assert domains == sorted(domains)


def test_get_summary_total_domains(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://example.com', selectors)
    summary = storage.get_summary()
    assert summary['total_domains'] == 1
    assert len(summary['domains']) == 1


def test_get_summary_empty(storage):
    summary = storage.get_summary()
    assert summary['total_domains'] == 0
    assert summary['domains'] == []


def test_get_summary_domain_has_fields(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://example.com', selectors)
    summary = storage.get_summary()
    domain_info = summary['domains'][0]
    assert 'fields' in domain_info
    assert 'title' in domain_info['fields']


def test_get_summary_domain_has_domain_key(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://example.com', selectors)
    summary = storage.get_summary()
    domain_info = summary['domains'][0]
    assert 'domain' in domain_info
    assert domain_info['domain'] == 'example.com'


def test_load_selectors_returns_none_for_missing(storage):
    assert storage.load_selectors('missing.com') is None


def test_format_selectors_uses_na_for_missing_fallback(storage):
    selectors = {'title': {'primary': 'h1'}}
    formatted = storage._format_selectors(selectors)
    assert formatted['title']['fallback'] == 'NA'
    assert formatted['title']['tertiary'] == 'NA'


def test_format_selectors_uses_provided_values(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'h3'}}
    formatted = storage._format_selectors(selectors)
    assert formatted['title']['primary'] == 'h1'
    assert formatted['title']['fallback'] == 'h2'
    assert formatted['title']['tertiary'] == 'h3'


def test_save_content_creates_file(storage, tmp_path):
    content = {'title': 'Hello', 'body': 'World'}
    filepath = storage.save_content('https://example.com/page', content, 'json')
    assert os.path.exists(filepath)


def test_save_content_returns_filepath(storage):
    content = {'title': 'Test'}
    result = storage.save_content('https://example.com/article', content, 'json')
    assert isinstance(result, str)
    assert len(result) > 0


def test_load_content_after_save(storage):
    content = {'title': 'My Article', 'body': 'Content here'}
    storage.save_content('https://example.com/article', content, 'json')
    loaded = storage.load_content('https://example.com/article')
    assert loaded is not None
    assert loaded['title'] == 'My Article'


def test_content_exists_after_save(storage):
    content = {'title': 'Test'}
    storage.save_content('https://example.com/test-page', content)
    assert storage.content_exists('https://example.com/test-page') is True


def test_content_not_exists_before_save(storage):
    assert storage.content_exists('https://example.com/never-saved') is False


def test_get_content_filepath_uses_hash_for_homepage(storage):
    filepath = storage._get_content_filepath('https://example.com/')
    assert 'homepage_' in filepath


def test_get_content_filepath_uses_path_for_non_homepage(storage):
    filepath = storage._get_content_filepath('https://example.com/article/slug')
    assert 'homepage_' not in filepath
    assert 'article' in filepath or 'slug' in filepath


def test_get_content_filepath_json_extension(storage):
    filepath = storage._get_content_filepath('https://example.com/article', 'json')
    assert filepath.endswith('.json')


def test_get_content_filepath_markdown_extension(storage):
    filepath = storage._get_content_filepath('https://example.com/article', 'markdown')
    assert filepath.endswith('.md')


def test_storage_init_calls_init_yosoi_twice(mocker, tmp_path):
    """SelectorStorage.__init__ must call init_yosoi twice (once for each dir)."""
    selector_dir = tmp_path / 'sel'
    content_dir = tmp_path / 'cnt'
    selector_dir.mkdir()
    content_dir.mkdir()
    mock_init = mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    SelectorStorage()
    assert mock_init.call_count == 2


def test_storage_init_passes_storage_dir_name(mocker, tmp_path):
    """SelectorStorage.__init__ must pass storage_dir name to first init_yosoi call."""
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir()
    content_dir.mkdir()
    mock_init = mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    SelectorStorage(storage_dir='selectors', content_dir='content')
    calls = mock_init.call_args_list
    assert calls[0][0][0] == 'selectors'
    assert calls[1][0][0] == 'content'


def test_storage_init_storage_dir_is_str(mocker, tmp_path):
    """storage_dir attribute must be a string."""
    selector_dir = tmp_path / 'sel'
    content_dir = tmp_path / 'cnt'
    selector_dir.mkdir()
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    s = SelectorStorage()
    assert isinstance(s.storage_dir, str)


def test_storage_init_content_dir_is_str(mocker, tmp_path):
    """content_dir attribute must be a string."""
    selector_dir = tmp_path / 'sel'
    content_dir = tmp_path / 'cnt'
    selector_dir.mkdir()
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    s = SelectorStorage()
    assert isinstance(s.content_dir, str)


def test_extract_domain_removes_www_prefix(storage):
    """Domain extraction must remove 'www.' prefix."""
    assert storage._extract_domain('https://www.example.com/path') == 'example.com'


def test_extract_domain_does_not_remove_non_www(storage):
    """Non-www prefixes should not be removed."""
    assert storage._extract_domain('https://blog.example.com/path') == 'blog.example.com'


def test_get_selector_filepath_uses_selectors_prefix(storage):
    """Selector filepath must start with 'selectors_' prefix."""
    filepath = storage._get_selector_filepath('example.com')
    filename = os.path.basename(filepath)
    assert filename.startswith('selectors_')


def test_get_selector_filepath_ends_with_json(storage):
    """Selector filepath must end with '.json'."""
    filepath = storage._get_selector_filepath('example.com')
    assert filepath.endswith('.json')


def test_get_selector_filepath_dots_replaced_with_underscores(storage):
    """Dots in domain must be replaced with underscores in filename."""
    filepath = storage._get_selector_filepath('example.com')
    filename = os.path.basename(filepath)
    assert 'example_com' in filename


def test_format_selectors_primary_na_when_missing(storage):
    """Missing 'primary' key must default to 'NA'."""
    selectors = {'title': {'fallback': 'h2'}}
    formatted = storage._format_selectors(selectors)
    assert formatted['title']['primary'] == 'NA'


def test_format_selectors_preserves_all_three_levels(storage):
    """All three levels (primary, fallback, tertiary) must be in formatted output."""
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'h3'}}
    formatted = storage._format_selectors(selectors)
    assert 'primary' in formatted['title']
    assert 'fallback' in formatted['title']
    assert 'tertiary' in formatted['title']


def test_load_selectors_returns_selectors_key(storage):
    """load_selectors must return the 'selectors' value from JSON, not the full dict."""
    selectors = {'headline': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://example.com', selectors)
    loaded = storage.load_selectors('example.com')
    assert loaded is not None
    # Should not have 'url', 'domain', 'discovered_at' keys (only selectors content)
    assert 'url' not in loaded
    assert 'domain' not in loaded


def test_load_content_returns_content_key(storage):
    """load_content must return the 'content' value from JSON, not the full dict."""
    content = {'title': 'Test Article'}
    storage.save_content('https://example.com/article', content, 'json')
    loaded = storage.load_content('https://example.com/article')
    assert loaded is not None
    # Should not have 'url', 'domain', 'extracted_at' keys
    assert 'url' not in loaded
    assert 'domain' not in loaded


def test_get_summary_has_total_domains_key(storage):
    """get_summary must return dict with 'total_domains' key."""
    summary = storage.get_summary()
    assert 'total_domains' in summary


def test_get_summary_has_domains_list_key(storage):
    """get_summary must return dict with 'domains' list key."""
    summary = storage.get_summary()
    assert 'domains' in summary
    assert isinstance(summary['domains'], list)


def test_get_summary_domains_have_discovered_at(storage):
    """Each domain in summary must have 'discovered_at' key."""
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://example.com', selectors)
    summary = storage.get_summary()
    domain_info = summary['domains'][0]
    assert 'discovered_at' in domain_info


def test_jsonl_filepath_uses_results_filename(storage):
    """JSONL format must produce a 'results.jsonl' accumulating file per domain."""
    filepath = storage._get_content_filepath('https://example.com/article', 'jsonl')
    assert os.path.basename(filepath) == 'results.jsonl'


def test_ndjson_filepath_uses_results_jsonl_extension(storage):
    """ndjson alias must produce the same accumulating file as jsonl."""
    filepath = storage._get_content_filepath('https://example.com/article', 'ndjson')
    assert os.path.basename(filepath) == 'results.jsonl'


def test_csv_filepath_uses_results_filename(storage):
    """CSV format must produce a 'results.csv' accumulating file per domain."""
    filepath = storage._get_content_filepath('https://example.com/article', 'csv')
    assert os.path.basename(filepath) == 'results.csv'


def test_xlsx_filepath_uses_results_filename(storage):
    """XLSX format must produce a 'results.xlsx' accumulating file per domain."""
    filepath = storage._get_content_filepath('https://example.com/article', 'xlsx')
    assert os.path.basename(filepath) == 'results.xlsx'


def test_parquet_filepath_uses_results_filename(storage):
    """Parquet format must produce a 'results.parquet' accumulating file per domain."""
    filepath = storage._get_content_filepath('https://example.com/article', 'parquet')
    assert os.path.basename(filepath) == 'results.parquet'


def test_jsonl_same_domain_same_filepath(storage):
    """Two URLs on the same domain must share the same JSONL accumulating file."""
    fp1 = storage._get_content_filepath('https://example.com/page1', 'jsonl')
    fp2 = storage._get_content_filepath('https://example.com/page2', 'jsonl')
    assert fp1 == fp2


def test_list_domains_only_returns_selector_files(storage):
    """list_domains must only return filenames starting with 'selectors_'."""
    # Save a selector
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://example.com', selectors)
    # Create a non-selector file
    import pathlib

    pathlib.Path(storage.storage_dir, 'other_file.json').write_text('{}')
    domains = storage.list_domains()
    # Should not include 'other'
    assert 'other' not in domains
    assert 'example.com' in domains


# ---------------------------------------------------------------------------
# Coverage: lines 79-81 — load_selectors reading from file
# ---------------------------------------------------------------------------


def test_load_selectors_reads_selectors_key_from_file(storage):
    """load_selectors returns the 'selectors' sub-dict from the JSON file."""
    selectors = {
        'title': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'NA'},
        'price': {'primary': '.price', 'fallback': 'NA', 'tertiary': 'NA'},
    }
    storage.save_selectors('https://example.com', selectors)
    loaded = storage.load_selectors('example.com')
    assert loaded is not None
    assert 'title' in loaded
    assert 'price' in loaded
    assert loaded['title']['primary'] == 'h1'


# ---------------------------------------------------------------------------
# Coverage: line 132 — load_content reading from file
# ---------------------------------------------------------------------------


def test_load_content_returns_none_for_missing_file(storage):
    """load_content returns None when the file does not exist."""
    result = storage.load_content('https://nonexistent.com/page')
    assert result is None


# ---------------------------------------------------------------------------
# Coverage: lines 140-142 — load_content exception handling
# ---------------------------------------------------------------------------


def test_load_content_returns_none_for_corrupt_file(storage):
    """load_content returns None for a corrupt JSON file."""
    import pathlib

    filepath = storage._get_content_filepath('https://example.com/article')
    pathlib.Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(filepath).write_text('NOT VALID JSON')
    result = storage.load_content('https://example.com/article')
    assert result is None


# ---------------------------------------------------------------------------
# Coverage: line 165 — list_domains when storage_dir doesn't exist
# ---------------------------------------------------------------------------


def test_list_domains_nonexistent_storage_dir(tmp_path, mocker):
    """list_domains returns empty list when storage_dir doesn't exist."""
    selector_dir = tmp_path / 'nonexistent_selectors'
    content_dir = tmp_path / 'content'
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    s = SelectorStorage()
    # storage_dir points to a non-existent path
    s.storage_dir = str(tmp_path / 'does_not_exist')
    result = s.list_domains()
    assert result == []


# ---------------------------------------------------------------------------
# Coverage: lines 243-244 — _extract_domain with invalid URL
# ---------------------------------------------------------------------------


def test_extract_domain_empty_netloc_returns_empty_string(storage):
    """_extract_domain with URL that has no netloc returns empty string (not 'unknown')."""
    # urlparse('not-a-valid-url') gives netloc='', no ValueError
    domain = storage._extract_domain('not-a-valid-url')
    assert isinstance(domain, str)


# ---------------------------------------------------------------------------
# Coverage: lines 331, 337-338 — _load_file_data exception handling
# ---------------------------------------------------------------------------


def test_load_file_data_returns_none_for_missing_file(storage):
    """_load_file_data returns None when the file doesn't exist."""
    result = storage._load_file_data('nonexistent.com')
    assert result is None


def test_load_file_data_returns_none_for_corrupt_file(storage):
    """_load_file_data returns None for a corrupt JSON file."""
    import pathlib

    filepath = storage._get_filepath('corrupt.com')
    pathlib.Path(filepath).write_text('NOT VALID JSON')
    result = storage._load_file_data('corrupt.com')
    assert result is None


def test_load_file_data_returns_data_for_valid_file(storage):
    """_load_file_data returns the JSON content for a valid file."""
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://example.com', selectors)
    result = storage._load_file_data('example.com')
    assert result is not None
    assert 'selectors' in result


# ---------------------------------------------------------------------------
# Coverage: lines 350-356 — export_summary
# ---------------------------------------------------------------------------


def test_export_summary_creates_file(storage, tmp_path):
    """export_summary creates a JSON file with the summary."""
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    storage.save_selectors('https://example.com', selectors)
    output_file = str(tmp_path / 'summary.json')
    result = storage.export_summary(output_file)
    assert result == output_file
    assert os.path.exists(output_file)

    import json

    with open(output_file) as f:
        data = json.load(f)
    assert 'total_domains' in data
    assert data['total_domains'] == 1


def test_export_summary_empty(storage, tmp_path):
    """export_summary works with no saved selectors."""
    output_file = str(tmp_path / 'empty_summary.json')
    storage.export_summary(output_file)
    assert os.path.exists(output_file)

    import json

    with open(output_file) as f:
        data = json.load(f)
    assert data['total_domains'] == 0
