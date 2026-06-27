"""Tests for yosoi.storage.strategy — FetchStrategyStorage."""

import json

import pytest


@pytest.fixture
def storage(tmp_path, mocker):
    fetch_dir = tmp_path / 'fetch'
    mocker.patch('yosoi.storage.strategy.get_yosoi_storage_path', return_value=fetch_dir)
    mocker.patch('yosoi.storage.strategy.init_yosoi', return_value=fetch_dir)
    fetch_dir.mkdir()
    from yosoi.storage.strategy import FetchStrategyStorage

    return FetchStrategyStorage()


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------


class TestSave:
    async def test_default_dir_is_created_lazily(self, tmp_path, mocker):
        fetch_dir = tmp_path / 'fetch'
        mocker.patch('yosoi.storage.strategy.get_yosoi_storage_path', return_value=fetch_dir)
        mocker.patch('yosoi.storage.strategy.init_yosoi', return_value=fetch_dir)
        from yosoi.storage.strategy import FetchStrategyStorage

        storage = FetchStrategyStorage()

        assert not fetch_dir.exists()
        assert await storage.load('example.com') is None
        assert not fetch_dir.exists()

        await storage.save('example.com', 'simple')
        assert fetch_dir.is_dir()

    async def test_save_valid_fetcher_creates_file(self, storage):
        import os

        await storage.save('example.com', 'simple')
        fp = storage._filepath('example.com')
        assert os.path.exists(fp)

    async def test_save_headless(self, storage):
        await storage.save('example.com', 'headless')
        assert await storage.load('example.com') == 'headless'

    async def test_save_headful(self, storage):
        await storage.save('example.com', 'headful')
        assert await storage.load('example.com') == 'headful'

    async def test_save_selector_level(self, storage):
        await storage.save('example.com', 'headless', selector_level='xpath')
        strategy = await storage.load_strategy('example.com')
        assert strategy is not None
        assert strategy.fetcher == 'headless'
        assert strategy.selector_level == 'xpath'

    async def test_save_higher_tier_selector_levels_round_trip(self, storage):
        """Regression: attr/global_id/role/visual were silently dropped by a stale
        VALID_SELECTOR_LEVELS subset; they must now persist (AX/role discovery, CAS-79)."""
        for level in ('attr', 'global_id', 'role', 'visual'):
            await storage.save('example.com', 'headless', selector_level=level)
            strategy = await storage.load_strategy('example.com')
            assert strategy is not None
            assert strategy.selector_level == level

    async def test_save_invalid_selector_level_is_dropped(self, storage):
        await storage.save('example.com', 'headless', selector_level='not_a_level')
        strategy = await storage.load_strategy('example.com')
        assert strategy is not None
        assert strategy.fetcher == 'headless'
        # Unknown selector level is discarded rather than persisted.
        assert strategy.selector_level is None

    async def test_save_invalid_selector_level_logs_warning(self, storage, mocker):
        mock_warn = mocker.patch('yosoi.storage.strategy.logger.warning')
        await storage.save('example.com', 'headless', selector_level='not_a_level')
        mock_warn.assert_called_once()

    async def test_save_identity_id_round_trips(self, storage):
        """W2: the cascade-winning identity persists and reloads on FetchStrategy."""
        await storage.save('google.com', 'headful', identity_id='trusted_profile')
        strategy = await storage.load_strategy('google.com')
        assert strategy is not None
        assert strategy.fetcher == 'headful'
        assert strategy.identity_id == 'trusted_profile'

    async def test_load_strategy_tolerates_missing_identity_id(self, storage):
        """Old fetch_<domain>.json files predate identity_id — parse defaults to None."""
        fp = storage._filepath('legacy.com')
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(
                {'domain': 'legacy.com', 'fetcher': 'headful', 'selector_level': 'css'},
                f,
            )
        strategy = await storage.load_strategy('legacy.com')
        assert strategy is not None
        assert strategy.fetcher == 'headful'
        assert strategy.identity_id is None

    async def test_load_all_tolerates_missing_identity_id(self, storage):
        fp = storage._filepath('legacy2.com')
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump({'domain': 'legacy2.com', 'fetcher': 'headless'}, f)
        all_strats = await storage.load_all_strategies()
        assert all_strats['legacy2.com'].identity_id is None

    async def test_save_invalid_fetcher_returns_early(self, storage):
        await storage.save('example.com', 'invalid_tier')
        assert await storage.load('example.com') is None

    async def test_save_invalid_fetcher_logs_warning(self, storage, mocker):
        mock_warn = mocker.patch('yosoi.storage.strategy.logger.warning')
        await storage.save('example.com', 'bad_value')
        mock_warn.assert_called_once()

    async def test_save_overwrites_existing(self, storage):
        await storage.save('example.com', 'simple')
        await storage.save('example.com', 'headful')
        assert await storage.load('example.com') == 'headful'

    async def test_save_oserror_does_not_raise(self, storage, mocker):
        mocker.patch(
            'yosoi.storage.strategy.atomic_write_json_async',
            side_effect=OSError('disk full'),
        )
        await storage.save('example.com', 'simple')  # should not raise

    async def test_save_oserror_logs_warning(self, storage, mocker):
        mocker.patch(
            'yosoi.storage.strategy.atomic_write_json_async',
            side_effect=OSError('disk full'),
        )
        mock_warn = mocker.patch('yosoi.storage.strategy.logger.warning')
        await storage.save('example.com', 'simple')
        mock_warn.assert_called_once()


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------


class TestLoad:
    async def test_load_returns_none_for_unknown_domain(self, storage):
        assert await storage.load('unknown.com') is None

    async def test_load_returns_saved_tier(self, storage):
        await storage.save('example.com', 'headless')
        assert await storage.load('example.com') == 'headless'

    async def test_load_strategy_supports_legacy_file_without_selector_level(self, storage):
        fp = storage._filepath('legacy.com')
        with open(fp, 'w') as f:
            json.dump({'domain': 'legacy.com', 'fetcher': 'headless'}, f)
        strategy = await storage.load_strategy('legacy.com')
        assert strategy is not None
        assert strategy.fetcher == 'headless'
        assert strategy.selector_level is None

    async def test_load_returns_none_for_corrupt_json(self, storage):
        fp = storage._filepath('bad.com')
        with open(fp, 'w') as f:
            f.write('NOT VALID JSON')
        assert await storage.load('bad.com') is None

    async def test_load_returns_none_for_invalid_fetcher_in_file(self, storage):
        fp = storage._filepath('bad.com')
        with open(fp, 'w') as f:
            json.dump({'domain': 'bad.com', 'fetcher': 'unknown_tier'}, f)
        assert await storage.load('bad.com') is None

    async def test_load_logs_warning_for_invalid_fetcher_in_file(self, storage, mocker):
        fp = storage._filepath('bad.com')
        with open(fp, 'w') as f:
            json.dump({'domain': 'bad.com', 'fetcher': 'unknown_tier'}, f)
        mock_warn = mocker.patch('yosoi.storage.strategy.logger.warning')
        await storage.load('bad.com')
        mock_warn.assert_called_once()

    async def test_load_returns_none_on_oserror(self, storage, mocker):
        await storage.save('example.com', 'simple')
        mocker.patch('yosoi.storage.strategy.open', side_effect=OSError('permission denied'))
        assert await storage.load('example.com') is None


# ---------------------------------------------------------------------------
# load_all()
# ---------------------------------------------------------------------------


class TestLoadAll:
    async def test_load_all_empty_when_no_files(self, storage):
        assert await storage.load_all() == {}

    async def test_load_all_returns_all_saved(self, storage):
        await storage.save('a.com', 'simple')
        await storage.save('b.com', 'headful')
        result = await storage.load_all()
        assert result == {'a.com': 'simple', 'b.com': 'headful'}

    async def test_load_all_strategies_returns_selector_levels(self, storage):
        await storage.save('a.com', 'simple')
        await storage.save('b.com', 'headful', selector_level='xpath')
        result = await storage.load_all_strategies()
        assert result['a.com'].fetcher == 'simple'
        assert result['a.com'].selector_level is None
        assert result['b.com'].fetcher == 'headful'
        assert result['b.com'].selector_level == 'xpath'

    async def test_load_all_skips_non_fetch_prefixed_files(self, storage, tmp_path):
        other = tmp_path / 'fetch' / 'other_file.json'
        other.write_text(json.dumps({'domain': 'intruder.com', 'fetcher': 'simple'}))
        assert 'intruder.com' not in await storage.load_all()

    async def test_load_all_skips_corrupt_files(self, storage, tmp_path):
        await storage.save('good.com', 'simple')
        bad = tmp_path / 'fetch' / 'fetch_bad_com.json'
        bad.write_text('NOT JSON')
        result = await storage.load_all()
        assert 'good.com' in result
        assert 'bad.com' not in result

    async def test_load_all_returns_empty_when_dir_missing(self, storage):
        storage._dir = '/nonexistent/path/that/does/not/exist'
        assert await storage.load_all() == {}

    async def test_load_all_logs_info_when_cache_populated(self, storage, mocker):
        await storage.save('example.com', 'simple')
        mock_info = mocker.patch('yosoi.storage.strategy.logger.info')
        await storage.load_all()
        mock_info.assert_called_once()


# ---------------------------------------------------------------------------
# list_domains()
# ---------------------------------------------------------------------------


class TestListDomains:
    async def test_list_domains_empty(self, storage):
        assert await storage.list_domains() == []

    async def test_list_domains_sorted(self, storage):
        await storage.save('z.com', 'simple')
        await storage.save('a.com', 'headless')
        await storage.save('m.com', 'headful')
        assert await storage.list_domains() == ['a.com', 'm.com', 'z.com']


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
