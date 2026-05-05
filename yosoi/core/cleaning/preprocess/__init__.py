"""Page-level HTML preprocessing.

Spike CAS-18: a tier-1 + tier-2 preprocessor that runs after
:class:`yosoi.core.cleaning.cleaner.HTMLCleaner` to shave tokens off every
LLM call. Behind feature flag ``use_experimental_preprocess`` on
:class:`yosoi.core.configs.YosoiConfig` (default ``False``).

The :mod:`yosoi.core.cleaning.preprocess.anchor_hash` submodule provides
the stretch-goal building blocks for hash-free re-scrape recomputation —
canonicalization plus ``anchor_hash_partial`` / ``anchor_hash_full``.
"""

from yosoi.core.cleaning.preprocess.anchor_hash import (
    AnchorHashes,
    compute_anchor_hashes,
    find_anchor_subtree,
    hash_subtree,
    normalize_text,
)
from yosoi.core.cleaning.preprocess.preprocessor import HTMLPreprocessor, PreprocessResult

__all__ = [
    'AnchorHashes',
    'HTMLPreprocessor',
    'PreprocessResult',
    'compute_anchor_hashes',
    'find_anchor_subtree',
    'hash_subtree',
    'normalize_text',
]
