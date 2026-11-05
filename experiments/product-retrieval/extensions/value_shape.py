"""Value-form fingerprints based only on Unicode character shape."""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

FAMILY_VERSION = "unicode-character-form-v1"
_FAMILIES = ("letter", "mark", "digit", "punctuation", "symbol", "space", "other")
_METHOD_AGGREGATION = {
    "value_shape_jaccard_max": ("weighted_jaccard", "max"),
    "value_shape_jaccard_mean": ("weighted_jaccard", "mean"),
    "value_shape_cosine_max": ("cosine", "max"),
    "value_shape_cosine_mean": ("cosine", "mean"),
}

METHOD_METADATA: dict[str, dict[str, Any]] = {
    method: {
        "family": "form",
        "comparison": (
            "Unicode character-form fingerprint of candidate "
            "text to seed value prototypes"
        ),
        "reference_aggregation": aggregation,
        "similarity": similarity,
        "input": (
            "candidate.text only; query, context, structure, "
            "attributes and IDs are ignored"
        ),
        "profile": FAMILY_VERSION,
        "unicode_database_version": unicodedata.unidata_version,
        "empty_evidence": "score zero; no vacuous all-empty match",
        "semantic_claim": False,
    }
    for method, (similarity, aggregation) in _METHOD_AGGREGATION.items()
}
METHODS = list(METHOD_METADATA)

GATE_METADATA = {
    "formula": "base_score * ((1 - strength) + strength * shape_similarity)",
    "strength_range": [0.0, 1.0],
    "output_is_probability": False,
    "interpretation": (
        "ranking-only multiplicative adjustment; strength is not calibrated"
    ),
}


def profile_provenance() -> dict[str, Any]:
    """Return the version data required to reproduce Unicode category features."""
    return {
        "profile": FAMILY_VERSION,
        "unicode_database_version": unicodedata.unidata_version,
        "families": list(_FAMILIES),
        "features": [
            "coarse category fractions",
            "collapsed category-run family and length bins",
            "adjacent category-run transitions",
            "Unicode-code-point length bin",
        ],
        "text_policy": (
            "Use candidate.text verbatim; do not lowercase, "
            "normalize, tokenize or interpret values."
        ),
    }


def form_features(text: str) -> dict[str, float]:
    """Extract a sparse, nonnegative, content-free form vector from one string.

    Features encode only Unicode general-category families, coarse run lengths,
    transitions between those families, and the number of Unicode code points.
    Different product names with the same shape intentionally receive the same
    vector; this is not a semantic or correctness signal.
    """
    if not isinstance(text, str):
        return {}
    if not text:
        return {}

    categories = [_category_family(character) for character in text]
    length = len(categories)
    features: dict[str, float] = {f"length:{_length_bin(length)}": 1.0}
    counts = Counter(categories)
    for family in _FAMILIES:
        count = counts.get(family, 0)
        if count:
            features[f"fraction:{family}"] = count / length

    runs: list[tuple[str, int]] = []
    current = categories[0]
    run_length = 1
    for family in categories[1:]:
        if family == current:
            run_length += 1
        else:
            runs.append((current, run_length))
            current = family
            run_length = 1
    runs.append((current, run_length))

    for family, size in runs:
        feature = f"run:{family}:{_run_length_bin(size)}"
        features[feature] = features.get(feature, 0.0) + 1.0 / len(runs)
    if len(runs) > 1:
        transition_counts = Counter(
            f"transition:{left}>{right}"
            for (left, _), (right, _) in zip(runs, runs[1:], strict=False)
        )
        transition_count = len(runs) - 1
        for feature, count in transition_counts.items():
            features[feature] = count / transition_count
    return features


def build_reference_prototypes(
    references: Sequence[Mapping[str, Any]],
) -> list[dict[str, float]]:
    """Build one form prototype per seed value, reading only reference text."""
    prototypes: list[dict[str, float]] = []
    for candidate in references:
        if not isinstance(candidate, Mapping):
            continue
        prototype = form_features(candidate.get("text", ""))
        if prototype:
            prototypes.append(prototype)
    return prototypes


def score_candidates(
    method: str,
    query: dict[str, Any],
    candidates: list[dict[str, Any]],
    references: list[dict[str, Any]],
    representation: str = "context",
    semantic_vectors: dict[str, Sequence[float]] | None = None,
) -> list[float]:
    """Score candidate value shapes against seed-value form prototypes.

    This follows the shared candidate scorer API. Query text and all candidate
    fields other than ``text`` are ignored. Reference scores aggregate by the
    max or mean specified by the method ID. Empty candidate/reference evidence
    returns zero rather than a vacuous match.
    """
    del query, representation, semantic_vectors
    if method not in _METHOD_AGGREGATION:
        raise ValueError(f"unknown value-shape method: {method}")
    similarity, aggregation = _METHOD_AGGREGATION[method]
    reference_features = build_reference_prototypes(references)
    if not candidates:
        return []
    if not reference_features:
        return [0.0] * len(candidates)

    result: list[float] = []
    for candidate in candidates:
        candidate_features = form_features(candidate.get("text", ""))
        if not candidate_features:
            result.append(0.0)
            continue
        similarities = [
            _weighted_jaccard(candidate_features, reference)
            if similarity == "weighted_jaccard"
            else _cosine(candidate_features, reference)
            for reference in reference_features
        ]
        result.append(
            max(similarities)
            if aggregation == "max"
            else sum(similarities) / len(similarities)
        )
    return result


def multiplicative_shape_gate(
    base_scores: Sequence[float],
    shape_scores: Sequence[float],
    *,
    strength: float = 0.25,
) -> list[float]:
    """Apply a bounded ranking-only form adjustment to nonnegative scores.

    ``strength`` is an explicit sensitivity knob, not a probability or a
    calibrated confidence. The output remains on the base score's scale.
    """
    if len(base_scores) != len(shape_scores):
        raise ValueError("base and shape score counts must match")
    strength = float(strength)
    if not math.isfinite(strength) or not 0.0 <= strength <= 1.0:
        raise ValueError("strength must be finite and between zero and one")
    result = []
    for base_score, shape_score in zip(base_scores, shape_scores, strict=True):
        base = float(base_score)
        shape = float(shape_score)
        if not math.isfinite(base) or base < 0.0:
            raise ValueError("base scores must be finite and nonnegative")
        if not math.isfinite(shape) or not 0.0 <= shape <= 1.0:
            raise ValueError("shape scores must be finite similarities in [0, 1]")
        result.append(base * ((1.0 - strength) + strength * shape))
    return result


def _category_family(character: str) -> str:
    if character.isspace():
        return "space"
    major = unicodedata.category(character)[0]
    return {
        "L": "letter",
        "M": "mark",
        "N": "digit",
        "P": "punctuation",
        "S": "symbol",
        "Z": "space",
    }.get(major, "other")


def _length_bin(length: int) -> str:
    if length <= 1:
        return "1"
    if length <= 4:
        return "2-4"
    if length <= 8:
        return "5-8"
    if length <= 16:
        return "9-16"
    if length <= 32:
        return "17-32"
    if length <= 64:
        return "33-64"
    return "65+"


def _run_length_bin(length: int) -> str:
    if length == 1:
        return "1"
    if length <= 4:
        return "2-4"
    if length <= 8:
        return "5-8"
    return "9+"


def _weighted_jaccard(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = set(left) | set(right)
    denominator = sum(max(left.get(key, 0.0), right.get(key, 0.0)) for key in keys)
    if denominator <= 0.0:
        return 0.0
    numerator = sum(min(left.get(key, 0.0), right.get(key, 0.0)) for key in keys)
    return numerator / denominator


def _cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = set(left) | set(right)
    left_norm = math.sqrt(sum(left.get(key, 0.0) ** 2 for key in keys))
    right_norm = math.sqrt(sum(right.get(key, 0.0) ** 2 for key in keys))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    dot = sum(left.get(key, 0.0) * right.get(key, 0.0) for key in keys)
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))
