"""Tests for contract-keyed discovery lesson storage."""

from datetime import datetime, timezone

import pytest

from yosoi.models.replay import DiscoveryLesson, LessonKey, ReplayPlan, ReplayStatus
from yosoi.models.snapshot import SelectorSnapshot
from yosoi.storage.lesson import LessonStorage


@pytest.fixture
def storage(tmp_path, mocker):
    lesson_dir = tmp_path / 'lessons'
    lesson_dir.mkdir()
    mocker.patch('yosoi.storage.lesson.init_yosoi', return_value=lesson_dir)
    return LessonStorage()


def _lesson(domain: str = 'example.com', contract_sig: str = 'sig') -> DiscoveryLesson:
    now = datetime.now(timezone.utc)
    return DiscoveryLesson(
        key=LessonKey(domain=domain, contract_signature=contract_sig),
        replay_plan=ReplayPlan(),
        selectors={'title': SelectorSnapshot(primary='h1', discovered_at=now)},
    )


class TestLessonStorage:
    def test_save_and_load_round_trip(self, storage):
        lesson = _lesson()
        storage.save(lesson)

        loaded = storage.load(lesson.key)

        assert loaded is not None
        assert loaded.key == lesson.key
        assert loaded.selectors['title'].primary == 'h1'

    def test_contract_signature_is_part_of_key(self, storage):
        first = _lesson(contract_sig='listing')
        second = _lesson(contract_sig='comments')
        second.selectors['body'] = second.selectors.pop('title')

        storage.save(first)
        storage.save(second)

        assert storage.load(first.key).selectors.keys() == {'title'}  # type: ignore[union-attr]
        assert storage.load(second.key).selectors.keys() == {'body'}  # type: ignore[union-attr]

    def test_load_missing_returns_none(self, storage):
        assert storage.load(LessonKey(domain='missing.com', contract_signature='sig')) is None

    def test_load_active_omits_stale(self, storage):
        lesson = _lesson()
        lesson.status = ReplayStatus.STALE
        storage.save(lesson)

        assert storage.load_active(lesson.key) is None

    def test_record_replay_verified_updates_counters(self, storage):
        lesson = _lesson()
        storage.save(lesson)

        storage.record_replay(lesson.key, verified=True)

        loaded = storage.load(lesson.key)
        assert loaded is not None
        assert loaded.stats.replay_count == 1
        assert loaded.stats.failure_count == 0
        assert loaded.stats.last_verified_at is not None

    def test_record_replay_failed_updates_failure_count(self, storage):
        lesson = _lesson()
        storage.save(lesson)

        storage.record_replay(lesson.key, verified=False)

        loaded = storage.load(lesson.key)
        assert loaded is not None
        assert loaded.stats.replay_count == 1
        assert loaded.stats.failure_count == 1
        assert loaded.stats.last_failed_at is not None

    def test_mark_stale(self, storage):
        lesson = _lesson()
        storage.save(lesson)

        storage.mark_stale(lesson.key, 'assertion failed')

        loaded = storage.load(lesson.key)
        assert loaded is not None
        assert loaded.status == ReplayStatus.STALE
        assert loaded.status_reason == 'assertion failed'

    def test_delete(self, storage):
        lesson = _lesson()
        storage.save(lesson)

        assert storage.delete(lesson.key) is True
        assert storage.load(lesson.key) is None
