"""Tests for yosoi.storage.strategy — FetchStrategyStorage."""

import json

import pytest


@pytest.fixture
def storage(tmp_path, mocker):
    mocker.patch('yosoi.storage.strategy.init_yosoi', return_value=tmp_path / 'fetch')
    (tmp_path / 'fetch').mkdir()
    from yosoi.storage.strategy import FetchStrategyStorage

    return FetchStrategyStorage()


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------


class TestSave:
    def test_save_valid_fetcher_creates_file(self, storage):
        import os

        storage.save('example.com', 'simple')
        fp = storage._filepath('example.com')
        assert os.path.exists(fp)

    def test_save_headless(self, storage):
        storage.save('example.com', 'headless')
        assert storage.load('example.com') == 'headless'

    def test_save_headful(self, storage):
        storage.save('example.com', 'headful')
        assert storage.load('example.com') == 'headful'

    def test_save_selector_level(self, storage):
        storage.save('example.com', 'headless', selector_level='xpath')
        strategy = storage.load_strategy('example.com')
        assert strategy is not None
        assert strategy.fetcher == 'headless'
        assert strategy.selector_level == 'xpath'

    def test_save_invalid_fetcher_returns_early(self, storage):
        storage.save('example.com', 'invalid_tier')
        assert storage.load('example.com') is None

    def test_save_invalid_fetcher_logs_warning(self, storage, mocker):
        mock_warn = mocker.patch('yosoi.storage.strategy.logger.warning')
        storage.save('example.com', 'bad_value')
        mock_warn.assert_called_once()

    def test_save_overwrites_existing(self, storage):
        storage.save('example.com', 'simple')
        storage.save('example.com', 'headful')
        assert storage.load('example.com') == 'headful'

    def test_save_oserror_does_not_raise(self, storage, mocker):
        mocker.patch('builtins.open', side_effect=OSError('disk full'))
        storage.save('example.com', 'simple')  # should not raise

    def test_save_oserror_logs_warning(self, storage, mocker):
        mocker.patch('builtins.open', side_effect=OSError('disk full'))
        mock_warn = mocker.patch('yosoi.storage.strategy.logger.warning')
        storage.save('example.com', 'simple')
        mock_warn.assert_called_once()


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_returns_none_for_unknown_domain(self, storage):
        assert storage.load('unknown.com') is None

    def test_load_returns_saved_tier(self, storage):
        storage.save('example.com', 'headless')
        assert storage.load('example.com') == 'headless'

    def test_load_strategy_supports_legacy_file_without_selector_level(self, storage):
        fp = storage._filepath('legacy.com')
        with open(fp, 'w') as f:
            json.dump({'domain': 'legacy.com', 'fetcher': 'headless'}, f)
        strategy = storage.load_strategy('legacy.com')
        assert strategy is not None
        assert strategy.fetcher == 'headless'
        assert strategy.selector_level is None

    def test_load_returns_none_for_corrupt_json(self, storage):
        fp = storage._filepath('bad.com')
        with open(fp, 'w') as f:
            f.write('NOT VALID JSON')
        assert storage.load('bad.com') is None

    def test_load_returns_none_for_invalid_fetcher_in_file(self, storage):
        fp = storage._filepath('bad.com')
        with open(fp, 'w') as f:
            json.dump({'domain': 'bad.com', 'fetcher': 'unknown_tier'}, f)
        assert storage.load('bad.com') is None

    def test_load_logs_warning_for_invalid_fetcher_in_file(self, storage, mocker):
        fp = storage._filepath('bad.com')
        with open(fp, 'w') as f:
            json.dump({'domain': 'bad.com', 'fetcher': 'unknown_tier'}, f)
        mock_warn = mocker.patch('yosoi.storage.strategy.logger.warning')
        storage.load('bad.com')
        mock_warn.assert_called_once()

    def test_load_returns_none_on_oserror(self, storage, mocker):
        storage.save('example.com', 'simple')
        mocker.patch('builtins.open', side_effect=OSError('permission denied'))
        assert storage.load('example.com') is None


# ---------------------------------------------------------------------------
# load_all()
# ---------------------------------------------------------------------------


class TestLoadAll:
    def test_load_all_empty_when_no_files(self, storage):
        assert storage.load_all() == {}

    def test_load_all_returns_all_saved(self, storage):
        storage.save('a.com', 'simple')
        storage.save('b.com', 'headful')
        result = storage.load_all()
        assert result == {'a.com': 'simple', 'b.com': 'headful'}

    def test_load_all_strategies_returns_selector_levels(self, storage):
        storage.save('a.com', 'simple')
        storage.save('b.com', 'headful', selector_level='xpath')
        result = storage.load_all_strategies()
        assert result['a.com'].fetcher == 'simple'
        assert result['a.com'].selector_level is None
        assert result['b.com'].fetcher == 'headful'
        assert result['b.com'].selector_level == 'xpath'

    def test_load_all_skips_non_fetch_prefixed_files(self, storage, tmp_path):
        other = tmp_path / 'fetch' / 'other_file.json'
        other.write_text(json.dumps({'domain': 'intruder.com', 'fetcher': 'simple'}))
        assert 'intruder.com' not in storage.load_all()

    def test_load_all_skips_corrupt_files(self, storage, tmp_path):
        storage.save('good.com', 'simple')
        bad = tmp_path / 'fetch' / 'fetch_bad_com.json'
        bad.write_text('NOT JSON')
        result = storage.load_all()
        assert 'good.com' in result
        assert 'bad.com' not in result

    def test_load_all_returns_empty_when_dir_missing(self, storage):
        storage._dir = '/nonexistent/path/that/does/not/exist'
        assert storage.load_all() == {}

    def test_load_all_logs_info_when_cache_populated(self, storage, mocker):
        storage.save('example.com', 'simple')
        mock_info = mocker.patch('yosoi.storage.strategy.logger.info')
        storage.load_all()
        mock_info.assert_called_once()


# ---------------------------------------------------------------------------
# list_domains()
# ---------------------------------------------------------------------------


class TestListDomains:
    def test_list_domains_empty(self, storage):
        assert storage.list_domains() == []

    def test_list_domains_sorted(self, storage):
        storage.save('z.com', 'simple')
        storage.save('a.com', 'headless')
        storage.save('m.com', 'headful')
        assert storage.list_domains() == ['a.com', 'm.com', 'z.com']


# ---------------------------------------------------------------------------
# _filepath()
# ---------------------------------------------------------------------------


class TestFilepath:
    def test_filepath_replaces_dots(self, storage):
        fp = storage._filepath('example.com')
        assert 'example_com' in fp

    def test_filepath_replaces_slashes(self, storage):
        fp = storage._filepath('host/path')
        assert '/' not in fp.split('fetch_')[-1]

    def test_filepath_has_fetch_prefix(self, storage):
        import os

        fp = storage._filepath('example.com')
        assert os.path.basename(fp).startswith('fetch_')

    def test_filepath_ends_with_json(self, storage):
        assert storage._filepath('example.com').endswith('.json')
