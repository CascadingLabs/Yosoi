"""Contract-keyed storage for MCP discovery lessons."""

from __future__ import annotations

import json
import logging
import os

from yosoi.models.replay import DiscoveryLesson, LessonKey, ReplayStatus, utc_now
from yosoi.utils.files import atomic_write_json_async, get_yosoi_storage_path, init_yosoi

logger = logging.getLogger(__name__)


class LessonStorage:
    """Persist and load replay-first discovery lessons.

    Lessons are keyed by domain, contract signature, page profile, and mode so
    separate contracts on the same domain cannot poison each other's selectors
    or action plans.
    """

    def __init__(self, storage_dir: str = 'lessons') -> None:
        """Initialise storage under ``.yosoi/lessons`` without creating it until write."""
        self._storage_dir = storage_dir
        self._dir = str(get_yosoi_storage_path(storage_dir))

    async def save(self, lesson: DiscoveryLesson) -> str:
        """Persist a discovery lesson and return the file path."""
        filepath = self._filepath(lesson.key, create=True)
        await atomic_write_json_async(filepath, lesson.model_dump(mode='json'), ensure_ascii=False)
        logger.info('Saved discovery lesson to: %s', filepath)
        return filepath

    async def load(self, key: LessonKey) -> DiscoveryLesson | None:
        """Load a lesson by key, or return None if absent/corrupt."""
        return self._load_sync(key)

    async def load_active(self, key: LessonKey) -> DiscoveryLesson | None:
        """Load an active lesson that still meets its validation threshold."""
        lesson = await self.load(key)
        if lesson is None or not lesson.is_active:
            return None
        return lesson

    async def record_replay(self, key: LessonKey, *, verified: bool) -> None:
        """Update replay counters after executing a lesson."""
        lesson = await self.load(key)
        if lesson is None:
            return

        now = utc_now()
        lesson.stats.replay_count += 1
        lesson.stats.last_replayed_at = now
        if verified:
            lesson.stats.failure_count = 0
            lesson.stats.last_verified_at = now
        else:
            lesson.stats.failure_count += 1
            lesson.stats.last_failed_at = now
        await self.save(lesson)

    async def mark_stale(self, key: LessonKey, reason: str) -> None:
        """Mark a lesson stale so replay-first execution will not use it."""
        lesson = await self.load(key)
        if lesson is None:
            return
        lesson.status = ReplayStatus.STALE
        lesson.status_reason = reason
        lesson.stats.last_failed_at = utc_now()
        await self.save(lesson)

    async def list_stale_by_scheme(self) -> list[str]:
        """Return storage keys of lessons whose signature scheme is out of date.

        After a :data:`~yosoi.utils.signatures.SIGNATURE_SCHEME_VERSION` bump the
        contract signature — hence the lesson filename — changes, so replay would
        silently miss the old lesson and re-discover. Scanning for lessons whose
        recorded ``key.sig_version`` differs from the current scheme makes that
        flush observable: callers can report/mark them STALE rather than treat the
        miss as a brand-new contract.
        """
        return self._list_stale_by_scheme_sync()

    def _list_stale_by_scheme_sync(self) -> list[str]:
        """Scan the small local lesson cache for stale signature schemes."""
        from yosoi.utils.signatures import SIGNATURE_SCHEME_VERSION

        try:
            names = os.listdir(self._dir)
        except OSError:
            return []
        stale: list[str] = []
        for name in names:
            if not (name.startswith('lesson_') and name.endswith('.json')):
                continue
            try:
                with open(os.path.join(self._dir, name), encoding='utf-8') as f:
                    data = json.loads(f.read())
                key = LessonKey.model_validate(data['key'])
            except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
                continue
            if key.sig_version != SIGNATURE_SCHEME_VERSION:
                stale.append(key.storage_key)
        return stale

    async def delete(self, key: LessonKey) -> bool:
        """Delete a lesson by key."""
        return self._delete_sync(key)

    def _load_sync(self, key: LessonKey) -> DiscoveryLesson | None:
        filepath = self._filepath(key)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, encoding='utf-8') as f:
                data = json.loads(f.read())
            return DiscoveryLesson.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning('Could not load discovery lesson %s: %s', key.storage_key, exc)
            return None

    def _delete_sync(self, key: LessonKey) -> bool:
        filepath = self._filepath(key)
        if not os.path.exists(filepath):
            return False
        os.remove(filepath)
        return True

    def _filepath(self, key: LessonKey, *, create: bool = False) -> str:
        if create:
            self._dir = str(init_yosoi(self._storage_dir))
        return os.path.join(self._dir, f'lesson_{key.storage_key}.json')
