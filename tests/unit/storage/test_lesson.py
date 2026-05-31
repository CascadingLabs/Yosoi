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
    async def test_save_and_load_round_trip(self, storage):
        lesson = _lesson()
        await storage.save(lesson)

        loaded = await storage.load(lesson.key)

        assert loaded is not None
        assert loaded.key == lesson.key
        assert loaded.selectors['title'].primary == 'h1'

    async def test_contract_signature_is_part_of_key(self, storage):
        first = _lesson(contract_sig='listing')
        second = _lesson(contract_sig='comments')
        second.selectors['body'] = second.selectors.pop('title')

        await storage.save(first)
        await storage.save(second)

        assert (await storage.load(first.key)).selectors.keys() == {'title'}  # type: ignore[union-attr]
        assert (await storage.load(second.key)).selectors.keys() == {'body'}  # type: ignore[union-attr]

    async def test_load_missing_returns_none(self, storage):
        assert await storage.load(LessonKey(domain='missing.com', contract_signature='sig')) is None

    async def test_load_active_omits_stale(self, storage):
        lesson = _lesson()
        lesson.status = ReplayStatus.STALE
        await storage.save(lesson)

        assert await storage.load_active(lesson.key) is None

    async def test_load_active_returns_active_lesson(self, storage):
        lesson = _lesson()
        await storage.save(lesson)

        loaded = await storage.load_active(lesson.key)

        assert loaded is not None
        assert loaded.key == lesson.key
        assert loaded.is_active is True

    async def test_load_active_missing_returns_none(self, storage):
        key = LessonKey(domain='missing.com', contract_signature='sig')
        assert await storage.load_active(key) is None

    async def test_load_corrupt_file_returns_none(self, storage):
        lesson = _lesson()
        filepath = storage._filepath(lesson.key)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('}{ not valid json at all')

        assert await storage.load(lesson.key) is None

    async def test_record_replay_noop_when_absent(self, storage):
        key = LessonKey(domain='missing.com', contract_signature='sig')

        # Lesson does not exist — should be a no-op that returns None.
        assert await storage.record_replay(key, verified=True) is None
        assert await storage.load(key) is None

    async def test_mark_stale_noop_when_absent(self, storage):
        key = LessonKey(domain='missing.com', contract_signature='sig')

        assert await storage.mark_stale(key, 'gone') is None
        assert await storage.load(key) is None

    async def test_delete_missing_returns_false(self, storage):
        key = LessonKey(domain='missing.com', contract_signature='sig')
        assert await storage.delete(key) is False

    async def test_record_replay_verified_updates_counters(self, storage):
        lesson = _lesson()
        await storage.save(lesson)

        await storage.record_replay(lesson.key, verified=True)

        loaded = await storage.load(lesson.key)
        assert loaded is not None
        assert loaded.stats.replay_count == 1
        assert loaded.stats.failure_count == 0
        assert loaded.stats.last_verified_at is not None

    async def test_record_replay_failed_updates_failure_count(self, storage):
        lesson = _lesson()
        await storage.save(lesson)

        await storage.record_replay(lesson.key, verified=False)

        loaded = await storage.load(lesson.key)
        assert loaded is not None
        assert loaded.stats.replay_count == 1
        assert loaded.stats.failure_count == 1
        assert loaded.stats.last_failed_at is not None

    async def test_mark_stale(self, storage):
        lesson = _lesson()
        await storage.save(lesson)

        await storage.mark_stale(lesson.key, 'assertion failed')

        loaded = await storage.load(lesson.key)
        assert loaded is not None
        assert loaded.status == ReplayStatus.STALE
        assert loaded.status_reason == 'assertion failed'

    async def test_delete(self, storage):
        lesson = _lesson()
        await storage.save(lesson)

        assert await storage.delete(lesson.key) is True
        assert await storage.load(lesson.key) is None
