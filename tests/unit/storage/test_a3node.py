"""Tests for the REAL yosoi.storage.a3node module.

Add these to tests/unit/storage/test_a3node.py.
The existing tests in that file use an inline stub — these test the real class.
"""

import json

import pytest


@pytest.fixture
def real_storage(tmp_path, mocker):
    mocker.patch('yosoi.storage.a3node.init_yosoi', return_value=tmp_path / 'a3nodes')
    (tmp_path / 'a3nodes').mkdir()
    from yosoi.storage.a3node import A3NodeStorage

    return A3NodeStorage()


def _acts(*kinds):
    from yosoi.storage.a3node import ActRecord

    return [ActRecord(kind=k, cycles=3) for k in kinds]


class TestRealA3NodeStorage:
    async def test_save_and_load_round_trip(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))
        node = await real_storage.load('example.com')
        assert node is not None
        assert node.domain == 'example.com'
        assert node.acts[0].kind == 'load_more'

    async def test_load_returns_none_for_unknown_domain(self, real_storage):
        assert await real_storage.load('unknown.com') is None

    async def test_load_returns_none_for_corrupt_json(self, real_storage):
        fp = real_storage._filepath('bad.com')
        with open(fp, 'w') as f:
            f.write('NOT VALID JSON{{{')
        assert await real_storage.load('bad.com') is None

    async def test_load_returns_none_for_missing_domain_key(self, real_storage):
        fp = real_storage._filepath('bad.com')
        with open(fp, 'w') as f:
            json.dump({'acts': [], 'discovered_at': '2024'}, f)
        assert await real_storage.load('bad.com') is None

    async def test_save_preserves_replay_count_when_acts_unchanged(self, real_storage):
        acts = _acts('load_more')
        await real_storage.save('example.com', acts)
        await real_storage.record_replay('example.com')
        await real_storage.record_replay('example.com')
        await real_storage.save('example.com', acts)  # same acts
        assert (await real_storage.load('example.com')).replay_count == 2

    async def test_save_resets_replay_count_when_acts_change(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))
        await real_storage.record_replay('example.com')
        await real_storage.save('example.com', _acts('cookie'))  # different acts
        assert (await real_storage.load('example.com')).replay_count == 0

    async def test_act_target_round_trips(self, real_storage):
        """A concrete SelectorEntry target survives save -> load (format 2)."""
        from yosoi.models.selectors import SelectorEntry
        from yosoi.storage.a3node import ActRecord

        target = SelectorEntry(type='role', value='button', name='Load more', nth=0)
        await real_storage.save('example.com', [ActRecord('load_more', 3, target=target)])
        node = await real_storage.load('example.com')
        assert node is not None
        assert node.acts[0].target == target

    async def test_save_writes_format_version(self, real_storage):
        import os

        await real_storage.save('example.com', _acts('load_more'))
        with open(real_storage._filepath('example.com'), encoding='utf-8') as f:
            assert json.load(f)['format'] == 2
        assert os.path.exists(real_storage._filepath('example.com'))

    async def test_adding_target_preserves_replay_count(self, real_storage):
        """Format-1 -> format-2 upgrade (same kind/cycles, target added) keeps stats."""
        from yosoi.models.selectors import SelectorEntry
        from yosoi.storage.a3node import ActRecord

        await real_storage.save('example.com', [ActRecord('load_more', 3)])  # no target
        await real_storage.record_replay('example.com')
        await real_storage.record_replay('example.com')
        target = SelectorEntry(type='role', value='button', name='Load more', nth=0)
        await real_storage.save('example.com', [ActRecord('load_more', 3, target=target)])  # refined
        assert (await real_storage.load('example.com')).replay_count == 2

    async def test_legacy_record_without_target_loads(self, real_storage):
        """A format-1 file on disk (no 'format', no 'target') still loads cleanly."""
        path = real_storage._filepath('legacy.com')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'domain': 'legacy.com', 'acts': [{'kind': 'load_more', 'cycles': 4}]}, f)
        node = await real_storage.load('legacy.com')
        assert node is not None
        assert node.acts[0].kind == 'load_more'
        assert node.acts[0].target is None

    async def test_save_oserror_does_not_raise(self, real_storage, mocker):
        mocker.patch(
            'yosoi.storage.a3node.atomic_write_json_async',
            side_effect=OSError('disk full'),
        )
        await real_storage.save('example.com', _acts('load_more'))  # should not raise

    async def test_record_replay_increments_count(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))
        await real_storage.record_replay('example.com')
        assert (await real_storage.load('example.com')).replay_count == 1

    async def test_record_replay_sets_last_replayed_at(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))
        await real_storage.record_replay('example.com')
        assert (await real_storage.load('example.com')).last_replayed_at is not None

    async def test_record_replay_noop_for_unknown_domain(self, real_storage):
        await real_storage.record_replay('nonexistent.com')  # should not raise

    async def test_record_replay_oserror_does_not_raise(self, real_storage, mocker):
        await real_storage.save('example.com', _acts('load_more'))
        mocker.patch(
            'yosoi.storage.a3node.atomic_write_json_async',
            side_effect=OSError('disk full'),
        )
        # OSError on write is swallowed and logged.
        await real_storage.record_replay('example.com')  # should not raise

    async def test_record_replay_oserror_logs_warning(self, real_storage, mocker):
        await real_storage.save('example.com', _acts('load_more'))
        mocker.patch(
            'yosoi.storage.a3node.atomic_write_json_async',
            side_effect=OSError('disk full'),
        )
        mock_warn = mocker.patch('yosoi.storage.a3node.logger.warning')
        await real_storage.record_replay('example.com')
        mock_warn.assert_called_once()

    async def test_delete_returns_true_and_removes_file(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))
        assert await real_storage.delete('example.com') is True
        assert await real_storage.load('example.com') is None

    async def test_delete_returns_false_for_nonexistent(self, real_storage):
        assert await real_storage.delete('nonexistent.com') is False

    async def test_delete_oserror_returns_false(self, real_storage, mocker):
        await real_storage.save('example.com', _acts('load_more'))
        mocker.patch(
            'yosoi.storage.a3node.os.remove',
            side_effect=OSError('permission denied'),
        )
        # Failure to remove is swallowed and reported as False.
        assert await real_storage.delete('example.com') is False

    async def test_list_domains_empty(self, real_storage):
        assert await real_storage.list_domains() == []

    async def test_list_domains_returns_saved_sorted(self, real_storage):
        await real_storage.save('beta.com', _acts('load_more'))
        await real_storage.save('alpha.com', _acts('load_more'))
        domains = await real_storage.list_domains()
        assert domains == ['alpha.com', 'beta.com']

    async def test_list_domains_skips_non_a3node_files(self, real_storage, tmp_path):
        other = tmp_path / 'a3nodes' / 'other_file.json'
        other.write_text(json.dumps({'domain': 'intruder.com'}))
        assert 'intruder.com' not in await real_storage.list_domains()

    async def test_list_domains_skips_corrupt_files(self, real_storage, tmp_path):
        await real_storage.save('good.com', _acts('load_more'))
        bad = tmp_path / 'a3nodes' / 'a3node_bad_com.json'
        bad.write_text('NOT JSON')
        domains = await real_storage.list_domains()
        assert 'good.com' in domains
        assert 'bad.com' not in domains

    async def test_list_domains_returns_empty_when_dir_missing(self, real_storage):
        real_storage._dir = '/nonexistent/path/that/does/not/exist'
        assert await real_storage.list_domains() == []

    async def test_list_domains_skips_files_with_missing_domain_key(self, real_storage, tmp_path):
        await real_storage.save('good.com', _acts('load_more'))
        # Valid a3node-prefixed JSON but no usable 'domain' value — must be skipped.
        empty_domain = tmp_path / 'a3nodes' / 'a3node_empty.json'
        empty_domain.write_text(json.dumps({'domain': '', 'acts': []}))
        no_domain = tmp_path / 'a3nodes' / 'a3node_none.json'
        no_domain.write_text(json.dumps({'acts': []}))
        domains = await real_storage.list_domains()
        assert domains == ['good.com']

    async def test_load_all_skips_unloadable_nodes(self, real_storage, tmp_path):
        await real_storage.save('good.com', _acts('load_more'))
        # A file that list_domains accepts (has a domain) but load() rejects as
        # corrupt because 'acts' is not iterable into ActRecords.
        bad = tmp_path / 'a3nodes' / 'a3node_broken_com.json'
        bad.write_text(json.dumps({'domain': 'broken.com', 'acts': [{'kind': 'x'}]}))
        result = await real_storage.load_all()
        assert 'good.com' in result
        assert 'broken.com' not in result

    async def test_load_all_returns_all_nodes(self, real_storage):
        await real_storage.save('a.com', _acts('load_more'))
        await real_storage.save('b.com', _acts('cookie'))
        result = await real_storage.load_all()
        assert set(result.keys()) == {'a.com', 'b.com'}

    async def test_load_all_empty_when_no_files(self, real_storage):
        assert await real_storage.load_all() == {}

    def test_filepath_replaces_dots_with_underscores(self, real_storage):
        fp = real_storage._filepath('finance.yahoo.com')
        assert 'finance_yahoo_com' in fp
        assert fp.endswith('.json')

    async def test_load_raw_returns_none_for_missing(self, real_storage):
        assert await real_storage._load_raw('nonexistent.com') is None

    def test_a3node_is_empty_true(self):
        from yosoi.storage.a3node import A3Node

        node = A3Node(domain='x.com', acts=[], discovered_at='2024')
        assert node.is_empty is True

    def test_a3node_is_empty_false(self):
        from yosoi.storage.a3node import A3Node, ActRecord

        node = A3Node(domain='x.com', acts=[ActRecord('load_more', 3)], discovered_at='2024')
        assert node.is_empty is False

    def test_a3node_battle_tested_at_3(self):
        from yosoi.storage.a3node import A3Node

        node = A3Node(domain='x.com', acts=[], discovered_at='2024', replay_count=3)
        assert node.battle_tested is True

    def test_a3node_not_battle_tested_below_3(self):
        from yosoi.storage.a3node import A3Node

        node = A3Node(domain='x.com', acts=[], discovered_at='2024', replay_count=2)
        assert node.battle_tested is False
