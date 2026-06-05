"""Pydantic models for selectors and results.

Lazy (PEP 562) — importing one model module (or ``import yosoi.models``) no longer
eagerly builds every model in the package. See ``CLAUDE.md`` ("Lazy loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.models.contract import Contract as Contract
    from yosoi.models.contract import ContractBuilder as ContractBuilder
    from yosoi.models.defaults import NewsArticle as NewsArticle
    from yosoi.models.replay import ActKind as ActKind
    from yosoi.models.replay import AssertKind as AssertKind
    from yosoi.models.replay import DiscoveryLesson as DiscoveryLesson
    from yosoi.models.replay import LessonKey as LessonKey
    from yosoi.models.replay import LessonProvenance as LessonProvenance
    from yosoi.models.replay import LessonStats as LessonStats
    from yosoi.models.replay import LessonTrace as LessonTrace
    from yosoi.models.replay import LessonValidation as LessonValidation
    from yosoi.models.replay import ReplayAct as ReplayAct
    from yosoi.models.replay import ReplayCondition as ReplayCondition
    from yosoi.models.replay import ReplayNode as ReplayNode
    from yosoi.models.replay import ReplayPlan as ReplayPlan
    from yosoi.models.replay import ReplayStatus as ReplayStatus
    from yosoi.models.replay import TeleportSpec as TeleportSpec
    from yosoi.models.replay import VerifyReport as VerifyReport
    from yosoi.models.results import ContentMetadata as ContentMetadata
    from yosoi.models.results import FetchResult as FetchResult
    from yosoi.models.results import FieldVerificationResult as FieldVerificationResult
    from yosoi.models.results import SelectorFailure as SelectorFailure
    from yosoi.models.results import VerificationResult as VerificationResult
    from yosoi.models.selectors import FieldSelectors as FieldSelectors
    from yosoi.models.selectors import SelectorEntry as SelectorEntry
    from yosoi.models.selectors import SelectorLevel as SelectorLevel
    from yosoi.models.snapshot import CacheVerdict as CacheVerdict
    from yosoi.models.snapshot import SelectorSnapshot as SelectorSnapshot
    from yosoi.models.snapshot import SnapshotMap as SnapshotMap
    from yosoi.models.snapshot import SnapshotStatus as SnapshotStatus

_REPLAY = 'yosoi.models.replay'
_RESULTS = 'yosoi.models.results'
_SELECTORS = 'yosoi.models.selectors'
_SNAPSHOT = 'yosoi.models.snapshot'
_LAZY: dict[str, str] = {
    'Contract': 'yosoi.models.contract',
    'ContractBuilder': 'yosoi.models.contract',
    'NewsArticle': 'yosoi.models.defaults',
    'ActKind': _REPLAY,
    'AssertKind': _REPLAY,
    'DiscoveryLesson': _REPLAY,
    'LessonKey': _REPLAY,
    'LessonProvenance': _REPLAY,
    'LessonStats': _REPLAY,
    'LessonTrace': _REPLAY,
    'LessonValidation': _REPLAY,
    'ReplayAct': _REPLAY,
    'ReplayCondition': _REPLAY,
    'ReplayNode': _REPLAY,
    'ReplayPlan': _REPLAY,
    'ReplayStatus': _REPLAY,
    'TeleportSpec': _REPLAY,
    'VerifyReport': _REPLAY,
    'ContentMetadata': _RESULTS,
    'FetchResult': _RESULTS,
    'FieldVerificationResult': _RESULTS,
    'SelectorFailure': _RESULTS,
    'VerificationResult': _RESULTS,
    'FieldSelectors': _SELECTORS,
    'SelectorEntry': _SELECTORS,
    'SelectorLevel': _SELECTORS,
    'CacheVerdict': _SNAPSHOT,
    'SelectorSnapshot': _SNAPSHOT,
    'SnapshotMap': _SNAPSHOT,
    'SnapshotStatus': _SNAPSHOT,
}

__all__ = sorted(_LAZY)

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
