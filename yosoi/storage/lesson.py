"""Contract-keyed storage for MCP discovery lessons."""

from __future__ import annotations

import json
import logging
import os

from yosoi.models.replay import DiscoveryLesson, LessonKey, ReplayStatus, utc_now
from yosoi.utils.files import init_yosoi

logger = logging.getLogger(__name__)


class LessonStorage:
    """Persist and load replay-first discovery lessons.

    Lessons are keyed by domain, contract signature, page profile, and mode so
    separate contracts on the same domain cannot poison each other's selectors
    or action plans.
    """

    def __init__(self, storage_dir: str = 'lessons') -> None:
        """Initialise storage under ``.yosoi/lessons``."""
        self._dir = str(init_yosoi(storage_dir))

    def save(self, lesson: DiscoveryLesson) -> str:
        """Persist a discovery lesson and return the file path."""
        filepath = self._filepath(lesson.key)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(lesson.model_dump(mode='json'), f, indent=2, ensure_ascii=False)
        logger.info('Saved discovery lesson to: %s', filepath)
        return filepath

    def load(self, key: LessonKey) -> DiscoveryLesson | None:
        """Load a lesson by key, or return None if absent/corrupt."""
        filepath = self._filepath(key)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, encoding='utf-8') as f:
                data = json.load(f)
            return DiscoveryLesson.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning('Could not load discovery lesson %s: %s', key.storage_key, exc)
            return None

    def load_active(self, key: LessonKey) -> DiscoveryLesson | None:
        """Load an active lesson that still meets its validation threshold."""
        lesson = self.load(key)
        if lesson is None or not lesson.is_active:
            return None
        return lesson

    def record_replay(self, key: LessonKey, *, verified: bool) -> None:
        """Update replay counters after executing a lesson."""
        lesson = self.load(key)
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
        self.save(lesson)

    def mark_stale(self, key: LessonKey, reason: str) -> None:
        """Mark a lesson stale so replay-first execution will not use it."""
        lesson = self.load(key)
        if lesson is None:
            return
        lesson.status = ReplayStatus.STALE
        lesson.status_reason = reason
        lesson.stats.last_failed_at = utc_now()
        self.save(lesson)

    def delete(self, key: LessonKey) -> bool:
        """Delete a lesson by key."""
        filepath = self._filepath(key)
        if not os.path.exists(filepath):
            return False
        os.remove(filepath)
        return True

    def _filepath(self, key: LessonKey) -> str:
        return os.path.join(self._dir, f'lesson_{key.storage_key}.json')
