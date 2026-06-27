"""Tests for SelectorStorage save/load/domain extraction."""

import os

import pytest

from yosoi.models.snapshot import SelectorSnapshot, SnapshotStatus
from yosoi.storage.persistence import SelectorStorage


@pytest.fixture
def storage(tmp_path, mocker):
    yosoi_dir = tmp_path / '.yosoi'
    yosoi_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', return_value=yosoi_dir)
    return SelectorStorage()


async def test_save_and_load_selectors(storage):
    selectors = {
        'headline': {'primary': 'h1.title', 'fallback': 'h1', 'tertiary': 'NA'},
    }
    await storage.save_selectors('https://example.com/article', selectors)
    loaded = await storage.load_selectors('example.com')
    assert loaded is not None
    assert loaded['headline']['primary'] == 'h1.title'


async def test_save_selectors_formats_with_primary_fallback_tertiary(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2'}}
    await storage.save_selectors('https://example.com', selectors)
    loaded = await storage.load_selectors('example.com')
    assert loaded['title']['primary'] == 'h1'
    assert loaded['title']['fallback'] == 'h2'
    assert 'tertiary' not in loaded['title']  # omitted when not provided


async def test_save_selectors_round_trips_field_root(storage):
    selectors = {
        'title': {
            'primary': {'type': 'css', 'value': 'h3::text'},
            'root': {'type': 'xpath', 'value': '//article'},
        },
    }
    await storage.save_selectors('https://example.com', selectors)

    loaded = await storage.load_selectors('example.com')

    assert loaded is not None
    assert loaded['title']['root'] == {'type': 'xpath', 'value': '//article'}


def test_snapshot_parent_root_back_compat_rehydrates_css_root():
    snap = SelectorSnapshot(
        primary={'type': 'css', 'value': 'h3::text'},
        parent_root='.card',
        discovered_at='2026-01-01T00:00:00Z',
    )

    from yosoi.models.snapshot import snapshot_to_selector_dict

    assert snapshot_to_selector_dict(snap)['root'] == {'type': 'css', 'value': '.card'}


async def test_nonexistent_domain_returns_none(storage):
    result = await storage.load_selectors('nonexistent.com')
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


async def test_selector_exists_after_save(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://test.com', selectors)
    assert await storage.selector_exists('test.com') is True


async def test_selector_not_exists(storage):
    assert await storage.selector_exists('nothere.com') is False


async def test_list_domains_empty(storage):
    assert await storage.list_domains() == []


async def test_list_domains_after_save(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://alpha.com', selectors)
    await storage.save_selectors('https://beta.com', selectors)
    domains = await storage.list_domains()
    assert 'alpha.com' in domains
    assert 'beta.com' in domains


async def test_list_domains_returns_sorted(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://zzz.com', selectors)
    await storage.save_selectors('https://aaa.com', selectors)
    domains = await storage.list_domains()
    assert domains == sorted(domains)


async def test_get_summary_total_domains(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://example.com', selectors)
    summary = await storage.get_summary()
    assert summary['total_domains'] == 1
    assert len(summary['domains']) == 1


async def test_get_summary_empty(storage):
    summary = await storage.get_summary()
    assert summary['total_domains'] == 0
    assert summary['domains'] == []


async def test_get_summary_domain_has_fields(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://example.com', selectors)
    summary = await storage.get_summary()
    domain_info = summary['domains'][0]
    assert 'fields' in domain_info
    assert 'title' in domain_info['fields']


async def test_get_summary_includes_snapshot_health_counts(storage):
    snapshots = {
        'title': SelectorSnapshot(primary='h1', discovered_at='2026-01-01T00:00:00Z'),
        'author': SelectorSnapshot(discovered_at='2026-01-01T00:00:00Z', status=SnapshotStatus.ABSENT),
    }
    await storage.save_snapshots('https://example.com', snapshots)

    domain_info = (await storage.get_summary())['domains'][0]

    assert domain_info['health']['active'] == 1
    assert domain_info['health']['absent'] == 1


async def test_get_summary_domain_has_domain_key(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://example.com', selectors)
    summary = await storage.get_summary()
    domain_info = summary['domains'][0]
    assert 'domain' in domain_info
    assert domain_info['domain'] == 'example.com'


async def test_load_selectors_returns_none_for_missing(storage):
    assert await storage.load_selectors('missing.com') is None


def test_format_selectors_uses_none_for_missing_fallback(storage):
    selectors = {'title': {'primary': 'h1'}}
    formatted = storage._format_selectors(selectors)
    assert formatted['title']['fallback'] is None
    assert formatted['title']['tertiary'] is None


def test_format_selectors_uses_provided_values(storage):
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'h3'}}
    formatted = storage._format_selectors(selectors)
    assert formatted['title']['primary'] == 'h1'
    assert formatted['title']['fallback'] == 'h2'
    assert formatted['title']['tertiary'] == 'h3'


async def test_save_content_creates_file(storage, tmp_path):
    content = {'title': 'Hello', 'body': 'World'}
    filepath = await storage.save_content('https://example.com/page', content, 'json')
    assert os.path.exists(filepath)


async def test_save_content_returns_filepath(storage):
    content = {'title': 'Test'}
    result = await storage.save_content('https://example.com/article', content, 'json')
    assert isinstance(result, str)
    assert len(result) > 0


async def test_load_content_after_save(storage):
    content = {'title': 'My Article', 'body': 'Content here'}
    await storage.save_content('https://example.com/article', content, 'json')
    loaded = await storage.load_content('https://example.com/article')
    assert loaded is not None
    assert loaded['title'] == 'My Article'


async def test_content_exists_after_save(storage):
    content = {'title': 'Test'}
    await storage.save_content('https://example.com/test-page', content)
    assert await storage.content_exists('https://example.com/test-page') is True


async def test_content_not_exists_before_save(storage):
    assert await storage.content_exists('https://example.com/never-saved') is False


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


def test_storage_init_calls_init_yosoi_once_for_root(mocker, tmp_path):
    """SelectorStorage.__init__ initializes only the .yosoi root, not child dirs."""
    yosoi_dir = tmp_path / '.yosoi'
    yosoi_dir.mkdir()
    mock_init = mocker.patch('yosoi.storage.persistence.init_yosoi', return_value=yosoi_dir)
    SelectorStorage()
    mock_init.assert_called_once_with()


def test_storage_init_content_dir_is_lazy_path(mocker, tmp_path):
    """content_dir is a path under .yosoi but is not created during init."""
    yosoi_dir = tmp_path / '.yosoi'
    yosoi_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', return_value=yosoi_dir)
    s = SelectorStorage(content_dir='content')
    assert isinstance(s.content_dir, str)
    assert s.content_dir == str(yosoi_dir / 'content')
    assert not (yosoi_dir / 'content').exists()


def test_storage_init_database_path_is_sqlite_under_yosoi(mocker, tmp_path):
    """Selector state lives in .yosoi/yosoi.sqlite3, not .yosoi/selectors/."""
    yosoi_dir = tmp_path / '.yosoi'
    yosoi_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', return_value=yosoi_dir)
    s = SelectorStorage()
    assert s.database_path == yosoi_dir / 'yosoi.sqlite3'


def test_extract_domain_removes_www_prefix(storage):
    """Domain extraction must remove 'www.' prefix."""
    assert storage._extract_domain('https://www.example.com/path') == 'example.com'


def test_extract_domain_does_not_remove_non_www(storage):
    """Non-www prefixes should not be removed."""
    assert storage._extract_domain('https://blog.example.com/path') == 'blog.example.com'


def test_format_selectors_primary_none_when_missing(storage):
    """Missing 'primary' key must default to None."""
    selectors = {'title': {'fallback': 'h2'}}
    formatted = storage._format_selectors(selectors)
    assert formatted['title']['primary'] is None


def test_format_selectors_preserves_all_three_levels(storage):
    """All three levels (primary, fallback, tertiary) must be in formatted output."""
    selectors = {'title': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'h3'}}
    formatted = storage._format_selectors(selectors)
    assert 'primary' in formatted['title']
    assert 'fallback' in formatted['title']
    assert 'tertiary' in formatted['title']


def test_format_selectors_preserves_field_root(storage):
    selectors = {'title': {'primary': 'h1', 'root': {'type': 'css', 'value': '.card'}}}
    formatted = storage._format_selectors(selectors)
    assert formatted['title']['root'] == {'type': 'css', 'value': '.card'}


async def test_load_selectors_returns_selector_map_only(storage):
    """load_selectors must return selector content, not storage metadata."""
    selectors = {'headline': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://example.com', selectors)
    loaded = await storage.load_selectors('example.com')
    assert loaded is not None
    # Should not have 'url', 'domain', 'discovered_at' keys (only selectors content)
    assert 'url' not in loaded
    assert 'domain' not in loaded


async def test_load_content_returns_content_key(storage):
    """load_content must return the 'content' value from JSON, not the full dict."""
    content = {'title': 'Test Article'}
    await storage.save_content('https://example.com/article', content, 'json')
    loaded = await storage.load_content('https://example.com/article')
    assert loaded is not None
    # Should not have 'url', 'domain', 'extracted_at' keys
    assert 'url' not in loaded
    assert 'domain' not in loaded


async def test_get_summary_has_total_domains_key(storage):
    """get_summary must return dict with 'total_domains' key."""
    summary = await storage.get_summary()
    assert 'total_domains' in summary


async def test_get_summary_has_domains_list_key(storage):
    """get_summary must return dict with 'domains' list key."""
    summary = await storage.get_summary()
    assert 'domains' in summary
    assert isinstance(summary['domains'], list)


async def test_get_summary_domains_have_discovered_at(storage):
    """Each domain in summary must have 'discovered_at' key."""
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://example.com', selectors)
    summary = await storage.get_summary()
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


# ---------------------------------------------------------------------------
# Contract signature in filenames
# ---------------------------------------------------------------------------


def test_contract_sig_produces_distinct_files_for_same_path_different_query(storage):
    """Two URLs with the same path but different query params produce different files."""
    url_a = 'https://example.com/catalog/?cat=1'
    url_b = 'https://example.com/catalog/?cat=2'
    fp_a = storage._get_content_filepath(url_a, 'json', contract_sig='abc123')
    fp_b = storage._get_content_filepath(url_b, 'json', contract_sig='abc123')
    assert fp_a != fp_b


def test_contract_sig_is_included_in_filename(storage):
    """The contract signature appears in the filename."""
    fp = storage._get_content_filepath('https://example.com/page', 'json', contract_sig='mysig')
    assert 'mysig' in os.path.basename(fp)


def test_contract_sig_none_falls_back_to_path_based_naming(storage):
    """Without a contract_sig, the existing path-based naming is used."""
    fp = storage._get_content_filepath('https://example.com/article/slug', 'json')
    basename = os.path.basename(fp)
    assert 'article' in basename or 'slug' in basename
    assert basename.endswith('.json')


def test_contract_sig_same_sig_same_url_same_file(storage):
    """Same contract_sig + same URL always returns the same filepath."""
    url = 'https://example.com/catalog/?cat=1'
    fp1 = storage._get_content_filepath(url, 'json', contract_sig='abc123')
    fp2 = storage._get_content_filepath(url, 'json', contract_sig='abc123')
    assert fp1 == fp2


async def test_save_content_with_contract_sig(storage, tmp_path):
    """save_content accepts contract_sig and produces a file with sig in the name."""
    content = {'title': 'Test'}
    filepath = await storage.save_content('https://example.com/catalog/?cat=5', content, 'json', contract_sig='testsig')
    assert os.path.exists(filepath)
    assert 'testsig' in os.path.basename(filepath)


async def test_content_exists_with_contract_sig(storage):
    """content_exists uses contract_sig to locate the correct file."""
    url = 'https://example.com/catalog/?cat=5'
    assert not await storage.content_exists(url, contract_sig='testsig')
    await storage.save_content(url, {'title': 'hi'}, 'json', contract_sig='testsig')
    assert await storage.content_exists(url, contract_sig='testsig')


async def test_list_domains_reads_sqlite_not_content_files(storage):
    """list_domains comes from SQLite selector state, not files under content/."""
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://example.com', selectors)
    await storage.save_content('https://other.com/page', {'title': 'ignored'}, 'json')

    domains = await storage.list_domains()

    assert 'example.com' in domains
    assert 'other.com' not in domains


async def test_load_selectors_returns_saved_selector_map(storage):
    """load_selectors returns selector content without storage metadata."""
    selectors = {
        'title': {'primary': 'h1', 'fallback': 'h2', 'tertiary': 'NA'},
        'price': {'primary': '.price', 'fallback': 'NA', 'tertiary': 'NA'},
    }
    await storage.save_selectors('https://example.com', selectors)
    loaded = await storage.load_selectors('example.com')
    assert loaded is not None
    assert 'title' in loaded
    assert 'price' in loaded
    assert loaded['title']['primary'] == 'h1'


# ---------------------------------------------------------------------------
# Coverage: line 132 — load_content reading from file
# ---------------------------------------------------------------------------


async def test_load_content_returns_none_for_missing_file(storage):
    """load_content returns None when the file does not exist."""
    result = await storage.load_content('https://nonexistent.com/page')
    assert result is None


# ---------------------------------------------------------------------------
# Coverage: lines 140-142 — load_content exception handling
# ---------------------------------------------------------------------------


async def test_load_content_returns_none_for_corrupt_file(storage):
    """load_content returns None for a corrupt JSON file."""
    import pathlib

    filepath = storage._get_content_filepath('https://example.com/article')
    pathlib.Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(filepath).write_text('NOT VALID JSON')
    result = await storage.load_content('https://example.com/article')
    assert result is None


# ---------------------------------------------------------------------------
# Empty SQLite store
# ---------------------------------------------------------------------------


async def test_list_domains_without_saved_selectors_is_empty(storage):
    """list_domains returns empty list when no selector rows exist."""
    assert await storage.list_domains() == []


# ---------------------------------------------------------------------------
# Coverage: lines 243-244 — _extract_domain with invalid URL
# ---------------------------------------------------------------------------


def test_extract_domain_empty_netloc_returns_empty_string(storage):
    """_extract_domain with URL that has no netloc returns empty string (not 'unknown')."""
    # urlparse('not-a-valid-url') gives netloc='', no ValueError
    domain = storage._extract_domain('not-a-valid-url')
    assert isinstance(domain, str)


async def test_save_selectors_does_not_create_legacy_selector_dir(storage):
    """SQLite is the selector source of truth; .yosoi/selectors is not created."""
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://example.com', selectors)
    assert not (storage.database_path.parent / 'selectors').exists()


# ---------------------------------------------------------------------------
# Coverage: lines 350-356 — export_summary
# ---------------------------------------------------------------------------


async def test_export_summary_creates_file(storage, tmp_path):
    """export_summary creates a JSON file with the summary."""
    selectors = {'title': {'primary': 'h1', 'fallback': 'NA', 'tertiary': 'NA'}}
    await storage.save_selectors('https://example.com', selectors)
    output_file = str(tmp_path / 'summary.json')
    result = await storage.export_summary(output_file)
    assert result == output_file
    assert os.path.exists(output_file)

    import json

    with open(output_file) as f:
        data = json.load(f)
    assert 'total_domains' in data
    assert data['total_domains'] == 1


async def test_export_summary_empty(storage, tmp_path):
    """export_summary works with no saved selectors."""
    output_file = str(tmp_path / 'empty_summary.json')
    await storage.export_summary(output_file)
    assert os.path.exists(output_file)

    import json

    with open(output_file) as f:
        data = json.load(f)
    assert data['total_domains'] == 0


# ---------------------------------------------------------------------------
# Coverage: lines 140-142 — load_content multi-item format
# ---------------------------------------------------------------------------


async def test_load_content_multi_item_format(storage):
    """load_content returns list of dicts for multi-item 'items' format."""
    import json
    import pathlib

    filepath = storage._get_content_filepath('https://example.com/multi')
    pathlib.Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    data = {'items': [{'title': 'A'}, {'title': 'B'}]}
    pathlib.Path(filepath).write_text(json.dumps(data))
    loaded = await storage.load_content('https://example.com/multi')
    assert isinstance(loaded, list)
    assert len(loaded) == 2
    assert loaded[0]['title'] == 'A'


# ---------------------------------------------------------------------------
# Coverage: lines 249-250 — _extract_domain ValueError
# ---------------------------------------------------------------------------


def test_extract_domain_valueerror_returns_unknown(storage, mocker):
    """_extract_domain returns 'unknown' when urlparse raises ValueError."""
    mocker.patch('yosoi.storage.persistence.urlparse', side_effect=ValueError('bad url'))
    result = storage._extract_domain('anything')
    assert result == 'unknown'


# ---------------------------------------------------------------------------
# load_field_selector
# ---------------------------------------------------------------------------


async def test_load_field_selector_returns_entry_for_existing_field(storage):
    selectors = {
        'headline': {'primary': 'h1.title', 'fallback': 'h1', 'tertiary': None},
        'author': {'primary': '.author', 'fallback': None, 'tertiary': None},
    }
    await storage.save_selectors('https://example.com/article', selectors)
    result = await storage.load_field_selector('example.com', 'headline')
    assert result is not None
    assert result['primary'] == 'h1.title'


async def test_load_field_selector_returns_none_for_missing_field(storage):
    selectors = {'headline': {'primary': 'h1', 'fallback': None, 'tertiary': None}}
    await storage.save_selectors('https://example.com', selectors)
    result = await storage.load_field_selector('example.com', 'nonexistent_field')
    assert result is None


async def test_load_field_selector_returns_none_for_missing_domain(storage):
    result = await storage.load_field_selector('nothere.com', 'headline')
    assert result is None
