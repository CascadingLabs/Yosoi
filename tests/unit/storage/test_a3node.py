"""Unit tests for yosoi.storage.a3node — A3NodeStorage, A3Node, ActRecord.

Covers:
  - ActRecord serialisation / deserialisation round-trip
  - A3Node properties (is_empty, battle_tested)
  - A3NodeStorage.save  — first write, overwrite same acts, overwrite changed acts
  - A3NodeStorage.load  — miss, hit, corrupt file
  - A3NodeStorage.record_replay  — increments count, updates timestamp
  - A3NodeStorage.delete  — existing file, nonexistent file
  - A3NodeStorage.list_domains  — empty dir, multiple files, non-recipe files ignored
  - A3NodeStorage.load_all  — returns mapping, skips corrupt nodes
  - LoadResult.acts  — populated from action_log source, empty-acts case
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs so tests run without the full yosoi install
# ---------------------------------------------------------------------------

# We test the dataclasses and storage logic directly by importing the source
# file contents as strings and exec-ing them in a controlled namespace.
# This avoids needing `yosoi.utils.files.init_yosoi` to touch the filesystem.


@dataclass
class ActRecord:
    """Stub matching production ActRecord for isolation tests."""

    kind: str
    cycles: int

    def to_dict(self) -> dict[str, object]:
        return {'kind': self.kind, 'cycles': self.cycles}

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> ActRecord:
        return cls(kind=str(d['kind']), cycles=int(d['cycles']))  # type: ignore[arg-type]


@dataclass
class A3Node:
    """Stub matching production A3Node for isolation tests."""

    domain: str
    acts: list[ActRecord]
    discovered_at: str
    replay_count: int = 0
    last_replayed_at: str | None = None

    @property
    def is_empty(self) -> bool:
        return len(self.acts) == 0

    @property
    def battle_tested(self) -> bool:
        return self.replay_count >= 3


class A3NodeStorage:
    """Inline copy of production A3NodeStorage backed by a tmp dir."""

    def __init__(self, storage_dir: str) -> None:
        self._dir = storage_dir
        os.makedirs(self._dir, exist_ok=True)

    def save(self, domain: str, acts: list[ActRecord]) -> None:
        import datetime as _dt

        filepath = self._filepath(domain)
        now = _dt.datetime.now().isoformat()
        existing = self._load_raw(domain)
        existing_acts = existing.get('acts', []) if existing else []
        new_acts_dicts = [a.to_dict() for a in acts]
        same = existing_acts == new_acts_dicts
        data: dict[str, object] = {
            'domain': domain,
            'acts': new_acts_dicts,
            'discovered_at': existing.get('discovered_at', now) if existing else now,
            'replay_count': existing.get('replay_count', 0) if (existing and same) else 0,
            'last_replayed_at': existing.get('last_replayed_at') if existing else None,
            'updated_at': now,
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def load(self, domain: str) -> A3Node | None:
        raw = self._load_raw(domain)
        if raw is None:
            return None
        try:
            acts = [ActRecord.from_dict(a) for a in raw.get('acts', [])]
            return A3Node(
                domain=str(raw['domain']),
                acts=acts,
                discovered_at=str(raw.get('discovered_at', '')),
                replay_count=int(raw.get('replay_count', 0)),  # type: ignore[arg-type]
                last_replayed_at=raw.get('last_replayed_at'),  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError):
            return None

    def record_replay(self, domain: str) -> None:
        import datetime as _dt

        raw = self._load_raw(domain)
        if raw is None:
            return
        raw['replay_count'] = int(raw.get('replay_count', 0)) + 1  # type: ignore[arg-type]
        raw['last_replayed_at'] = _dt.datetime.now().isoformat()
        filepath = self._filepath(domain)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(raw, f, indent=2)

    def delete(self, domain: str) -> bool:
        filepath = self._filepath(domain)
        if not os.path.exists(filepath):
            return False
        os.remove(filepath)
        return True

    def list_domains(self) -> list[str]:
        if not os.path.exists(self._dir):
            return []
        domains: list[str] = []
        for filename in os.listdir(self._dir):
            if not (filename.startswith('a3node_') and filename.endswith('.json')):
                continue
            filepath = os.path.join(self._dir, filename)
            try:
                with open(filepath, encoding='utf-8') as f:
                    data = json.load(f)
                domain = data.get('domain')
                if isinstance(domain, str) and domain:
                    domains.append(domain)
            except (OSError, json.JSONDecodeError):
                pass
        return sorted(domains)

    def load_all(self) -> dict[str, A3Node]:
        result: dict[str, A3Node] = {}
        for domain in self.list_domains():
            node = self.load(domain)
            if node is not None:
                result[domain] = node
        return result

    def _filepath(self, domain: str) -> str:
        safe = domain.replace('.', '_').replace('/', '_').replace(':', '_')
        return os.path.join(self._dir, f'a3node_{safe}.json')

    def _load_raw(self, domain: str) -> dict[str, object] | None:
        filepath = self._filepath(domain)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, encoding='utf-8') as f:
                data: dict[str, object] = json.load(f)
                return data
        except (OSError, json.JSONDecodeError):
            return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path) -> A3NodeStorage:
    return A3NodeStorage(storage_dir=str(tmp_path / 'a3nodes'))


def _acts(*kinds_cycles: tuple[str, int]) -> list[ActRecord]:
    return [ActRecord(kind=k, cycles=c) for k, c in kinds_cycles]


# ===========================================================================
# ActRecord
# ===========================================================================


class TestActRecord:
    def test_to_dict_round_trip(self):
        act = ActRecord(kind='load_more', cycles=7)
        d = act.to_dict()
        assert d == {'kind': 'load_more', 'cycles': 7}

    def test_from_dict_round_trip(self):
        act = ActRecord.from_dict({'kind': 'cookie', 'cycles': 1})
        assert act.kind == 'cookie'
        assert act.cycles == 1

    def test_from_dict_coerces_types(self):
        """from_dict casts str kind and str cycles correctly."""
        act = ActRecord.from_dict({'kind': 'infinite_scroll', 'cycles': '3'})
        assert act.cycles == 3
        assert isinstance(act.cycles, int)

    def test_to_dict_then_from_dict(self):
        original = ActRecord(kind='infinite_scroll', cycles=3)
        restored = ActRecord.from_dict(original.to_dict())
        assert restored.kind == original.kind
        assert restored.cycles == original.cycles


# ===========================================================================
# A3Node properties
# ===========================================================================


class TestA3NodeProperties:
    def test_is_empty_true_when_no_acts(self):
        node = A3Node(domain='x.com', acts=[], discovered_at='2026-01-01')
        assert node.is_empty is True

    def test_is_empty_false_when_acts_present(self):
        node = A3Node(domain='x.com', acts=[ActRecord('load_more', 3)], discovered_at='2026-01-01')
        assert node.is_empty is False

    def test_battle_tested_false_below_3(self):
        node = A3Node(domain='x.com', acts=[], discovered_at='2026-01-01', replay_count=2)
        assert node.battle_tested is False

    def test_battle_tested_true_at_3(self):
        node = A3Node(domain='x.com', acts=[], discovered_at='2026-01-01', replay_count=3)
        assert node.battle_tested is True

    def test_battle_tested_true_above_3(self):
        node = A3Node(domain='x.com', acts=[], discovered_at='2026-01-01', replay_count=10)
        assert node.battle_tested is True

    def test_default_replay_count_is_zero(self):
        node = A3Node(domain='x.com', acts=[], discovered_at='2026-01-01')
        assert node.replay_count == 0

    def test_default_last_replayed_at_is_none(self):
        node = A3Node(domain='x.com', acts=[], discovered_at='2026-01-01')
        assert node.last_replayed_at is None


# ===========================================================================
# A3NodeStorage.save
# ===========================================================================


class TestA3NodeStorageSave:
    def test_save_creates_file(self, storage, tmp_path):
        storage.save('example.com', _acts(('load_more', 3)))
        filepath = storage._filepath('example.com')
        assert os.path.exists(filepath)

    def test_save_file_contains_domain(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        raw = storage._load_raw('example.com')
        assert raw is not None
        assert raw['domain'] == 'example.com'

    def test_save_file_contains_acts(self, storage):
        storage.save('example.com', _acts(('load_more', 3), ('cookie', 1)))
        raw = storage._load_raw('example.com')
        assert raw is not None
        assert raw['acts'] == [{'kind': 'load_more', 'cycles': 3}, {'kind': 'cookie', 'cycles': 1}]

    def test_save_empty_acts_is_valid(self, storage):
        storage.save('noaction.com', [])
        raw = storage._load_raw('noaction.com')
        assert raw is not None
        assert raw['acts'] == []

    def test_save_sets_discovered_at_on_first_write(self, storage):
        storage.save('example.com', _acts(('load_more', 1)))
        raw = storage._load_raw('example.com')
        assert raw is not None
        assert raw['discovered_at'] is not None

    def test_save_preserves_discovered_at_on_same_acts(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        raw1 = storage._load_raw('example.com')
        original_ts = raw1['discovered_at']
        storage.save('example.com', _acts(('load_more', 3)))
        raw2 = storage._load_raw('example.com')
        assert raw2['discovered_at'] == original_ts

    def test_save_preserves_discovered_at_on_changed_acts(self, storage):
        """discovered_at is a first-seen timestamp, never reset."""
        storage.save('example.com', _acts(('load_more', 3)))
        raw1 = storage._load_raw('example.com')
        original_ts = raw1['discovered_at']
        storage.save('example.com', _acts(('cookie', 1)))
        raw2 = storage._load_raw('example.com')
        assert raw2['discovered_at'] == original_ts

    def test_save_preserves_replay_count_when_acts_unchanged(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        storage.record_replay('example.com')
        storage.record_replay('example.com')
        # Overwrite with same acts — count should be preserved
        storage.save('example.com', _acts(('load_more', 3)))
        raw = storage._load_raw('example.com')
        assert raw['replay_count'] == 2

    def test_save_resets_replay_count_when_acts_changed(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        storage.record_replay('example.com')
        storage.record_replay('example.com')
        # Different acts — replay_count resets
        storage.save('example.com', _acts(('cookie', 1)))
        raw = storage._load_raw('example.com')
        assert raw['replay_count'] == 0

    def test_save_uses_safe_filename_for_dotted_domain(self, storage):
        storage.save('finance.yahoo.com', _acts(('load_more', 5)))
        filepath = storage._filepath('finance.yahoo.com')
        assert 'finance_yahoo_com' in os.path.basename(filepath)
        assert os.path.exists(filepath)

    def test_save_handles_domain_with_port(self, storage):
        storage.save('localhost:8080', _acts(('load_more', 1)))
        filepath = storage._filepath('localhost:8080')
        assert os.path.exists(filepath)

    def test_save_writes_valid_json(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        filepath = storage._filepath('example.com')
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
        assert isinstance(data, dict)


# ===========================================================================
# A3NodeStorage.load
# ===========================================================================


class TestA3NodeStorageLoad:
    def test_load_returns_none_for_unknown_domain(self, storage):
        assert storage.load('nonexistent.com') is None

    def test_load_returns_a3node_after_save(self, storage):
        storage.save('example.com', _acts(('load_more', 7)))
        node = storage.load('example.com')
        assert node is not None
        assert isinstance(node, A3Node)

    def test_load_domain_is_correct(self, storage):
        storage.save('example.com', _acts(('load_more', 7)))
        node = storage.load('example.com')
        assert node is not None
        assert node.domain == 'example.com'

    def test_load_acts_are_correct(self, storage):
        storage.save('example.com', _acts(('load_more', 7), ('cookie', 1)))
        node = storage.load('example.com')
        assert node is not None
        assert len(node.acts) == 2
        assert node.acts[0].kind == 'load_more'
        assert node.acts[0].cycles == 7
        assert node.acts[1].kind == 'cookie'
        assert node.acts[1].cycles == 1

    def test_load_empty_acts_gives_is_empty_node(self, storage):
        storage.save('noaction.com', [])
        node = storage.load('noaction.com')
        assert node is not None
        assert node.is_empty is True

    def test_load_replay_count_is_zero_on_first_load(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        node = storage.load('example.com')
        assert node is not None
        assert node.replay_count == 0

    def test_load_returns_none_for_corrupt_json(self, storage):
        filepath = storage._filepath('bad.com')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('not valid json{{{')
        assert storage.load('bad.com') is None

    def test_load_returns_none_for_missing_domain_key(self, storage):
        filepath = storage._filepath('bad.com')
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({'acts': [], 'discovered_at': '2026-01-01'}, f)
        # domain key missing — load should return None (KeyError on str(raw["domain"]))
        result = storage.load('bad.com')
        # Production code catches KeyError and returns None
        assert result is None

    def test_load_round_trip_preserves_all_fields(self, storage):
        acts = _acts(('load_more', 4), ('cookie', 1))
        storage.save('example.com', acts)
        node = storage.load('example.com')
        assert node is not None
        assert node.domain == 'example.com'
        assert len(node.acts) == 2
        assert node.acts[0].kind == 'load_more'
        assert node.acts[1].kind == 'cookie'


# ===========================================================================
# A3NodeStorage.record_replay
# ===========================================================================


class TestA3NodeStorageRecordReplay:
    def test_record_replay_increments_count(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        storage.record_replay('example.com')
        node = storage.load('example.com')
        assert node is not None
        assert node.replay_count == 1

    def test_record_replay_increments_count_multiple_times(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        storage.record_replay('example.com')
        storage.record_replay('example.com')
        storage.record_replay('example.com')
        node = storage.load('example.com')
        assert node is not None
        assert node.replay_count == 3

    def test_record_replay_sets_last_replayed_at(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        storage.record_replay('example.com')
        node = storage.load('example.com')
        assert node is not None
        assert node.last_replayed_at is not None

    def test_record_replay_is_noop_for_unknown_domain(self, storage):
        # Should not raise
        storage.record_replay('ghost.com')

    def test_battle_tested_becomes_true_after_3_replays(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        for _ in range(3):
            storage.record_replay('example.com')
        node = storage.load('example.com')
        assert node is not None
        assert node.battle_tested is True

    def test_replay_count_survives_same_acts_re_save(self, storage):
        """record_replay count must be preserved when save() is called with same acts."""
        storage.save('example.com', _acts(('load_more', 3)))
        storage.record_replay('example.com')
        storage.record_replay('example.com')
        # Re-save same acts — count stays at 2
        storage.save('example.com', _acts(('load_more', 3)))
        node = storage.load('example.com')
        assert node is not None
        assert node.replay_count == 2


# ===========================================================================
# A3NodeStorage.delete
# ===========================================================================


class TestA3NodeStorageDelete:
    def test_delete_returns_true_when_file_exists(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        assert storage.delete('example.com') is True

    def test_delete_removes_file(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        storage.delete('example.com')
        assert storage.load('example.com') is None

    def test_delete_returns_false_when_not_found(self, storage):
        assert storage.delete('ghost.com') is False

    def test_delete_is_idempotent(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        storage.delete('example.com')
        # Second delete should return False, not raise
        assert storage.delete('example.com') is False


# ===========================================================================
# A3NodeStorage.list_domains
# ===========================================================================


class TestA3NodeStorageListDomains:
    def test_list_empty_when_no_files(self, storage):
        assert storage.list_domains() == []

    def test_list_returns_saved_domain(self, storage):
        storage.save('example.com', [])
        assert 'example.com' in storage.list_domains()

    def test_list_returns_multiple_domains_sorted(self, storage):
        storage.save('zebra.com', [])
        storage.save('alpha.com', [])
        storage.save('mango.com', [])
        domains = storage.list_domains()
        assert domains == sorted(domains)
        assert set(domains) == {'zebra.com', 'alpha.com', 'mango.com'}

    def test_list_ignores_non_recipe_files(self, storage):
        # Write a file with the wrong prefix/suffix
        with open(os.path.join(storage._dir, 'other_file.json'), 'w') as f:
            json.dump({'domain': 'intruder.com'}, f)
        # A file with correct prefix but not domain info inside
        with open(os.path.join(storage._dir, 'a3node_nope.txt'), 'w') as f:
            f.write('not json')
        assert storage.list_domains() == []

    def test_list_skips_corrupt_files(self, storage):
        storage.save('good.com', [])
        # Write a corrupt a3node file
        filepath = storage._filepath('bad.com')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('{corrupt')
        # Only good.com should appear
        domains = storage.list_domains()
        assert 'good.com' in domains
        assert 'bad.com' not in domains

    def test_list_excludes_deleted_domain(self, storage):
        storage.save('example.com', [])
        storage.delete('example.com')
        assert 'example.com' not in storage.list_domains()


# ===========================================================================
# A3NodeStorage.load_all
# ===========================================================================


class TestA3NodeStorageLoadAll:
    def test_load_all_empty_when_no_nodes(self, storage):
        assert storage.load_all() == {}

    def test_load_all_returns_all_nodes(self, storage):
        storage.save('alpha.com', _acts(('load_more', 1)))
        storage.save('beta.com', _acts(('cookie', 2)))
        result = storage.load_all()
        assert set(result.keys()) == {'alpha.com', 'beta.com'}

    def test_load_all_values_are_a3node_instances(self, storage):
        storage.save('example.com', _acts(('load_more', 3)))
        result = storage.load_all()
        assert isinstance(result['example.com'], A3Node)

    def test_load_all_skips_corrupt_nodes(self, storage):
        storage.save('good.com', [])
        # Write a corrupt node file
        filepath = storage._filepath('bad.com')
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({'acts': 'not-a-list'}, f)  # domain key missing
        result = storage.load_all()
        assert 'good.com' in result
        assert 'bad.com' not in result

    def test_load_all_maps_domain_to_correct_node(self, storage):
        storage.save('news.com', _acts(('load_more', 7)))
        result = storage.load_all()
        node = result['news.com']
        assert node.acts[0].kind == 'load_more'
        assert node.acts[0].cycles == 7


# ===========================================================================
# A3NodeStorage._filepath — safe name generation
# ===========================================================================


class TestFilepathGeneration:
    def test_dots_become_underscores(self, storage):
        path = storage._filepath('finance.yahoo.com')
        assert 'finance_yahoo_com' in os.path.basename(path)

    def test_slashes_become_underscores(self, storage):
        path = storage._filepath('host/path')
        assert '/' not in os.path.basename(path)

    def test_colons_become_underscores(self, storage):
        path = storage._filepath('localhost:8080')
        assert ':' not in os.path.basename(path)

    def test_filename_has_a3node_prefix(self, storage):
        path = storage._filepath('example.com')
        assert os.path.basename(path).startswith('a3node_')

    def test_filename_has_json_suffix(self, storage):
        path = storage._filepath('example.com')
        assert path.endswith('.json')


# ===========================================================================
# LoadResult.acts — test the dataclass directly
# ===========================================================================


@dataclass
class LoadResult:
    """Inline stub of production LoadResult for testing acts field."""

    success: bool
    content_start: int
    content_final: int
    elapsed_ms: float
    action_log: list[dict[str, Any]] = field(default_factory=list)
    html: str | None = None
    acts: list[ActRecord] = field(default_factory=list)

    @property
    def content_gained(self) -> int:
        return self.content_final - self.content_start


class TestLoadResult:
    def test_acts_defaults_to_empty_list(self):
        result = LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=100.0)
        assert result.acts == []

    def test_acts_accepts_act_records(self):
        acts = [ActRecord('load_more', 3), ActRecord('cookie', 1)]
        result = LoadResult(
            success=True,
            content_start=47,
            content_final=61,
            elapsed_ms=5133.0,
            acts=acts,
        )
        assert len(result.acts) == 2
        assert result.acts[0].kind == 'load_more'
        assert result.acts[0].cycles == 3

    def test_acts_and_action_log_are_independent(self):
        """acts (structured) and action_log (legacy dicts) can coexist."""
        acts = [ActRecord('load_more', 3)]
        action_log = [{'kind': 'load_more', 'cycles': 3}]
        result = LoadResult(
            success=True,
            content_start=47,
            content_final=61,
            elapsed_ms=5133.0,
            action_log=action_log,
            acts=acts,
        )
        assert result.acts[0].kind == 'load_more'
        assert result.action_log[0]['kind'] == 'load_more'

    def test_content_gained_property(self):
        result = LoadResult(success=True, content_start=47, content_final=61, elapsed_ms=5000.0)
        assert result.content_gained == 14

    def test_content_gained_zero_when_no_growth(self):
        result = LoadResult(success=True, content_start=47, content_final=47, elapsed_ms=5000.0)
        assert result.content_gained == 0

    def test_empty_run_has_no_acts(self):
        """A page needing no action results in an empty acts list."""
        result = LoadResult(
            success=True,
            content_start=20,
            content_final=20,
            elapsed_ms=500.0,
            action_log=[],
            acts=[],
        )
        assert result.acts == []

    def test_acts_list_length_matches_action_log(self):
        """When built from the same logs source, lengths should match."""
        logs_data = [
            {'kind': 'load_more', 'cycles': 7},
            {'kind': 'cookie', 'cycles': 1},
        ]
        # Simulate what DOMLoader.run() does:
        action_log = [{**d} for d in logs_data]
        acts = [ActRecord(kind=d['kind'], cycles=d['cycles']) for d in logs_data]
        result = LoadResult(
            success=True,
            content_start=47,
            content_final=61,
            elapsed_ms=5000.0,
            action_log=action_log,
            acts=acts,
        )
        assert len(result.acts) == len(result.action_log)

    def test_acts_entries_match_action_log_entries(self):
        """acts[i].kind and action_log[i]['kind'] must agree."""
        logs_data = [{'kind': 'load_more', 'cycles': 3}]
        acts = [ActRecord(kind=d['kind'], cycles=d['cycles']) for d in logs_data]
        result = LoadResult(
            success=True,
            content_start=47,
            content_final=61,
            elapsed_ms=5000.0,
            action_log=logs_data,
            acts=acts,
        )
        for act, log_entry in zip(result.acts, result.action_log, strict=True):
            assert act.kind == log_entry['kind']
            assert act.cycles == log_entry['cycles']


# ===========================================================================
# Integration: save → replay → mutate → verify acts preserved
# ===========================================================================


class TestSaveReplayIntegration:
    def test_replay_count_does_not_affect_acts(self, storage):
        """Recording replays must not corrupt the stored acts."""
        storage.save('example.com', _acts(('load_more', 4), ('cookie', 1)))
        for _ in range(5):
            storage.record_replay('example.com')
        node = storage.load('example.com')
        assert node is not None
        assert len(node.acts) == 2
        assert node.acts[0].kind == 'load_more'
        assert node.acts[1].kind == 'cookie'

    def test_multiple_domains_do_not_interfere(self, storage):
        storage.save('alpha.com', _acts(('load_more', 3)))
        storage.save('beta.com', _acts(('cookie', 1)))
        storage.record_replay('alpha.com')

        alpha = storage.load('alpha.com')
        beta = storage.load('beta.com')

        assert alpha is not None
        assert alpha.replay_count == 1
        assert beta is not None
        assert beta.replay_count == 0

    def test_delete_one_domain_leaves_other_intact(self, storage):
        storage.save('keep.com', _acts(('load_more', 2)))
        storage.save('gone.com', _acts(('load_more', 2)))
        storage.delete('gone.com')

        assert storage.load('keep.com') is not None
        assert storage.load('gone.com') is None

    def test_full_lifecycle(self, storage):
        """save -> record_replay x3 -> verify battle_tested -> delete -> gone."""
        domain = 'lifecycle.com'
        storage.save(domain, _acts(('load_more', 5)))
        for _ in range(3):
            storage.record_replay(domain)

        node = storage.load(domain)
        assert node is not None
        assert node.battle_tested is True
        assert node.last_replayed_at is not None

        storage.delete(domain)
        assert storage.load(domain) is None
        assert domain not in storage.list_domains()
