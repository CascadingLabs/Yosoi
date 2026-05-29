"""Pydantic models for selectors and results."""

from yosoi.models.contract import Contract, ContractBuilder
from yosoi.models.defaults import NewsArticle
from yosoi.models.replay import (
    ActKind,
    AssertKind,
    DiscoveryLesson,
    LessonKey,
    LessonProvenance,
    LessonStats,
    LessonTrace,
    LessonValidation,
    ReplayAct,
    ReplayCondition,
    ReplayNode,
    ReplayPlan,
    ReplayStatus,
    VerifyReport,
)
from yosoi.models.results import (
    ContentMetadata,
    FetchResult,
    FieldVerificationResult,
    SelectorFailure,
    VerificationResult,
)
from yosoi.models.selectors import FieldSelectors, SelectorEntry, SelectorLevel
from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot, SnapshotMap, SnapshotStatus

__all__ = [
    'ActKind',
    'AssertKind',
    'CacheVerdict',
    'ContentMetadata',
    'Contract',
    'ContractBuilder',
    'DiscoveryLesson',
    'FetchResult',
    'FieldSelectors',
    'FieldVerificationResult',
    'LessonKey',
    'LessonProvenance',
    'LessonStats',
    'LessonTrace',
    'LessonValidation',
    'NewsArticle',
    'ReplayAct',
    'ReplayCondition',
    'ReplayNode',
    'ReplayPlan',
    'ReplayStatus',
    'SelectorEntry',
    'SelectorFailure',
    'SelectorLevel',
    'SelectorSnapshot',
    'SnapshotMap',
    'SnapshotStatus',
    'VerificationResult',
    'VerifyReport',
]
