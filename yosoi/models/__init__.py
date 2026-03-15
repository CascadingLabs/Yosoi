"""Pydantic models for selectors and results."""

from yosoi.models.contract import Contract, ContractBuilder
from yosoi.models.defaults import NewsArticle
from yosoi.models.results import (
    ContentMetadata,
    FetchResult,
    FieldVerificationResult,
    SelectorFailure,
    VerificationResult,
)
from yosoi.models.selectors import FieldSelectors, SelectorEntry, SelectorLevel
from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot, SnapshotMap

__all__ = [
    'CacheVerdict',
    'ContentMetadata',
    'Contract',
    'ContractBuilder',
    'FetchResult',
    'FieldSelectors',
    'FieldVerificationResult',
    'NewsArticle',
    'SelectorEntry',
    'SelectorFailure',
    'SelectorLevel',
    'SelectorSnapshot',
    'SnapshotMap',
    'VerificationResult',
]
