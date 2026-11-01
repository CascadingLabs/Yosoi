"""Explicit exact memoization for reusable fingerprint construction and comparison.

This changes compute reuse, not the feature definitions or score formulas. Cold
construction misses and hot cache hits are counted separately. Use only with
immutable corpus/vector inputs; install within a single experiment process.
"""

from __future__ import annotations

import time
from collections import defaultdict
from functools import lru_cache

import advanced_methods
import methods
import run_matrix


class ExactCaches:
    def __init__(self):
        self.originals = []
        self.caches = {}
        self.misses = defaultdict(lambda: {"calls": 0, "wall_ns": 0})
        self.vector_maps = {}

    def install(self):
        self._mapping_call(methods, "_simhash", 8192)
        self._mapping_call(advanced_methods, "_cws_signature", 8192)
        self._simple_call(advanced_methods, "_cws_uniforms", 32768)
        self._simple_call(methods, "_word_count", 8192)
        self._simple_call(methods, "_char_ngram_count", 2048)
        self._semantic()
        return self

    def _replace(self, module, name, replacement):
        self.originals.append((module, name, getattr(module, name)))
        setattr(module, name, replacement)

    def _measure(self, label, function, *args):
        started = time.perf_counter_ns()
        value = function(*args)
        self.misses[label]["calls"] += 1
        self.misses[label]["wall_ns"] += time.perf_counter_ns() - started
        return value

    def _simple_call(self, module, name, limit):
        original = getattr(module, name)

        @lru_cache(maxsize=limit)
        def cached(*args):
            return self._measure(name, original, *args)

        self.caches[name] = cached
        self._replace(module, name, cached)

    def _mapping_call(self, module, name, limit):
        original = getattr(module, name)

        @lru_cache(maxsize=limit)
        def cached(items, parameter):
            return self._measure(name, original, dict(items), parameter)

        def wrapper(mapping, parameter):
            return cached(tuple(sorted(mapping.items())), parameter)

        self.caches[name] = cached
        self._replace(module, name, wrapper)

    def _semantic(self):
        original_vector = methods._semantic_vector
        original_cosine = methods._semantic_cosine

        @lru_cache(maxsize=32768)
        def vector(mapping_id, text):
            result = self._measure(
                "semantic_vector", original_vector, self.vector_maps[mapping_id], text
            )
            return tuple(result) if result is not None else None

        def vector_wrapper(mapping, text):
            if mapping is None:
                return None
            mapping_id = id(mapping)
            self.vector_maps[mapping_id] = mapping
            return vector(mapping_id, text)

        @lru_cache(maxsize=131072)
        def cosine(left, right):
            return self._measure("semantic_cosine", original_cosine, left, right)

        def cosine_wrapper(left, right):
            return cosine(
                tuple(left) if left is not None else None,
                tuple(right) if right is not None else None,
            )

        self.caches["semantic_vector"] = vector
        self.caches["semantic_cosine"] = cosine
        self._replace(methods, "_semantic_vector", vector_wrapper)
        self._replace(methods, "_semantic_cosine", cosine_wrapper)
        original_rank = run_matrix.rank

        @lru_cache(maxsize=2048)
        def ranked(scores, identities):
            return tuple(
                self._measure(
                    "rank",
                    original_rank,
                    scores,
                    [{"id": identity} for identity in identities],
                )
            )

        def rank_wrapper(scores, candidates):
            return ranked(tuple(scores), tuple(c["id"] for c in candidates))

        self.caches["rank"] = ranked
        self._replace(run_matrix, "rank", rank_wrapper)

    def ledger(self):
        return {
            name: {**self.misses[name], **cached.cache_info()._asdict()}
            for name, cached in self.caches.items()
        }

    def close(self):
        for module, name, original in reversed(self.originals):
            setattr(module, name, original)
        self.originals.clear()
        for cached in self.caches.values():
            cached.cache_clear()
        self.vector_maps.clear()

    def __enter__(self):
        return self.install()

    def __exit__(self, *args):
        self.close()
