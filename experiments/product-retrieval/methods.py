"""Small, dependency-free candidate scoring methods for retrieval experiments."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

REPRESENTATIONS = ["value", "context", "structure_context"]

METHOD_METADATA: dict[str, dict[str, str]] = {
    "structural_jaccard": {
        "family": "structure",
        "comparison": "candidate to each reference",
        "reference_aggregation": "max",
        "features": "weighted exact path, local motifs, tag, and attribute names",
    },
    "hierarchical_jaccard": {
        "family": "structure",
        "comparison": "candidate to each reference",
        "reference_aggregation": "max",
        "features": "path prefixes, local motifs, tag, and attribute names by category",
    },
    "local_jaccard": {
        "family": "structure",
        "comparison": "candidate local motifs to each reference",
        "reference_aggregation": "max",
        "features": "unique local motif strings",
    },
    "token_jaccard": {
        "family": "lexical",
        "comparison": "candidate representation to field and description tokens",
        "reference_aggregation": "none",
        "features": "unique normalized word tokens",
    },
    "bm25": {
        "family": "lexical",
        "comparison": "field and description query against candidate representations",
        "reference_aggregation": "none",
        "features": "word-token BM25, normalized by the best candidate score",
    },
    "tfidf_cosine": {
        "family": "lexical",
        "comparison": "candidate representation to field and description tokens",
        "reference_aggregation": "none",
        "features": "word-token TF-IDF cosine",
    },
    "semantic_query": {
        "family": "semantic",
        "comparison": "candidate representation to the exact query description vector",
        "reference_aggregation": "none",
        "features": "caller-supplied vectors; missing or invalid vectors score zero",
    },
    "semantic_reference": {
        "family": "semantic",
        "comparison": "candidate representation to each reference vector",
        "reference_aggregation": "max",
        "features": "caller-supplied vectors; missing or invalid vectors score zero",
    },
    "path_edit": {
        "family": "structure",
        "comparison": "candidate path to each reference path",
        "reference_aggregation": "max",
        "features": "normalized Levenshtein similarity over path tag sequences",
    },
    "structural_weighted_jaccard": {
        "family": "structure",
        "comparison": "candidate to each reference",
        "reference_aggregation": "max",
        "features": "exact path, local motifs, tag, and attribute names",
    },
    "structural_weighted_jaccard_avg": {
        "family": "structure",
        "comparison": "candidate to each reference",
        "reference_aggregation": "mean",
        "features": "exact path, local motifs, tag, and attribute names",
    },
    "hierarchical_structure": {
        "family": "structure",
        "comparison": "candidate to each reference",
        "reference_aggregation": "max",
        "features": "path prefixes, local motifs, tag, and attribute names by category",
    },
    "lexical_token_jaccard_query": {
        "family": "lexical",
        "comparison": "candidate representation to field and description tokens",
        "reference_aggregation": "none",
        "features": "unique normalized word tokens",
    },
    "lexical_token_jaccard_reference": {
        "family": "lexical",
        "comparison": "candidate representation to each reference",
        "reference_aggregation": "max",
        "features": "unique normalized word tokens",
    },
    "lexical_bm25_query": {
        "family": "lexical",
        "comparison": "field and description query against candidate representations",
        "reference_aggregation": "none",
        "features": "word-token BM25, normalized by the best candidate score",
    },
    "lexical_bm25_reference": {
        "family": "lexical",
        "comparison": (
            "each reference representation as a BM25 query against candidates"
        ),
        "reference_aggregation": "max",
        "features": "word-token BM25, normalized by the best score per reference",
    },
    "lexical_tfidf_cosine_query": {
        "family": "lexical",
        "comparison": "candidate representation to field and description tokens",
        "reference_aggregation": "none",
        "features": "word-token TF-IDF cosine",
    },
    "lexical_tfidf_cosine_reference": {
        "family": "lexical",
        "comparison": "candidate representation to each reference",
        "reference_aggregation": "max",
        "features": "word-token TF-IDF cosine",
    },
    "lexical_char_ngram_cosine_query": {
        "family": "lexical",
        "comparison": "candidate representation to field and description",
        "reference_aggregation": "none",
        "features": "character 3-gram TF-IDF cosine",
    },
    "lexical_char_ngram_cosine_reference": {
        "family": "lexical",
        "comparison": "candidate representation to each reference",
        "reference_aggregation": "max",
        "features": "character 3-gram TF-IDF cosine",
    },
    "semantic_query_cosine": {
        "family": "semantic",
        "comparison": "candidate representation to the query description vector",
        "reference_aggregation": "none",
        "features": "caller-supplied vectors; missing or invalid vectors score zero",
    },
    "semantic_reference_cosine": {
        "family": "semantic",
        "comparison": "candidate representation to each reference vector",
        "reference_aggregation": "max",
        "features": "caller-supplied vectors; missing or invalid vectors score zero",
    },
    "simhash64_lexical_reference": {
        "family": "simhash",
        "comparison": "candidate representation to each reference",
        "reference_aggregation": "max",
        "features": "deterministic 64-bit SimHash over sparse word counts",
    },
    "simhash128_lexical_reference": {
        "family": "simhash",
        "comparison": "candidate representation to each reference",
        "reference_aggregation": "max",
        "features": "deterministic 128-bit SimHash over sparse word counts",
    },
    "simhash64_structure_reference": {
        "family": "simhash",
        "comparison": "candidate structure to each reference structure",
        "reference_aggregation": "max",
        "features": "deterministic 64-bit SimHash over sparse structural features",
    },
    "simhash128_structure_reference": {
        "family": "simhash",
        "comparison": "candidate structure to each reference structure",
        "reference_aggregation": "max",
        "features": "deterministic 128-bit SimHash over sparse structural features",
    },
    "tree_path_edit_reference": {
        "family": "structure",
        "comparison": "candidate path to each reference path",
        "reference_aggregation": "max",
        "features": "normalized Levenshtein similarity over path tag sequences",
    },
}

METHODS = list(METHOD_METADATA)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+", re.UNICODE)
_STRUCTURE_CATEGORY_WEIGHTS = {
    "path": 0.40,
    "motif": 0.30,
    "tag": 0.15,
    "attribute": 0.15,
}


def _text(value: Any) -> str:
    """Return strings only; arbitrary object reprs are not evidence."""
    return value if isinstance(value, str) else ""


def _normalize_whitespace(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip()


def representation_text(
    candidate: Mapping[str, Any], representation: str = "context"
) -> str:
    """Build the stable text key used by lexical and caller-supplied semantic methods.

    ``value`` uses only candidate text. ``context`` appends captured surrounding
    text. ``structure_context`` also adds tag/path/motif and attribute *names*;
    it deliberately omits node IDs, ancestor IDs, and attribute values.
    """
    if representation not in REPRESENTATIONS:
        raise ValueError(f"unknown representation: {representation}")

    text = _normalize_whitespace(_text(candidate.get("text")))
    if representation == "value":
        return text

    context = _normalize_whitespace(_text(candidate.get("context")))
    parts = [part for part in (text, context) if part]
    if representation == "context":
        return "\n".join(parts)

    tag = _normalize_whitespace(_text(candidate.get("tag"))).lower()
    path = _path_tags(candidate)
    motifs = _motifs(candidate)
    attribute_names = _attribute_names(candidate)
    structural_parts: list[str] = []
    if tag:
        structural_parts.append(f"tag {tag}")
    if path:
        structural_parts.append(f"path {'/'.join(path)}")
    if motifs:
        structural_parts.extend(f"motif {motif}" for motif in motifs)
    if attribute_names:
        structural_parts.append(f"attributes {' '.join(attribute_names)}")
    return "\n".join(parts + structural_parts)


def _query_text(query: Mapping[str, Any]) -> str:
    field = _normalize_whitespace(_text(query.get("field")))
    description = _normalize_whitespace(_text(query.get("description")))
    return " ".join(part for part in (field, description) if part)


def _query_description(query: Mapping[str, Any]) -> str:
    description = _text(query.get("description"))
    if description:
        return description
    return _text(query.get("field"))


def _tokens(value: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(value)]


def _path_tags(candidate: Mapping[str, Any]) -> list[str]:
    path = candidate.get("path")
    if not isinstance(path, Sequence) or isinstance(path, (str, bytes)):
        return []
    return [
        normalized
        for item in path
        if (normalized := _normalize_whitespace(_text(item)).casefold())
    ]


def _motifs(candidate: Mapping[str, Any]) -> list[str]:
    motifs = candidate.get("motifs")
    if not isinstance(motifs, Sequence) or isinstance(motifs, (str, bytes)):
        return []
    return [
        normalized
        for item in motifs
        if (normalized := _normalize_whitespace(_text(item)).casefold())
    ]


def _attribute_names(candidate: Mapping[str, Any]) -> list[str]:
    attributes = candidate.get("attributes")
    if not isinstance(attributes, Mapping):
        return []
    return sorted(
        normalized
        for key in attributes
        if (normalized := _normalize_whitespace(_text(key)).casefold())
    )


def _tag(candidate: Mapping[str, Any]) -> str:
    return _normalize_whitespace(_text(candidate.get("tag"))).casefold()


def _path_feature(candidate: Mapping[str, Any]) -> str:
    return "/".join(_path_tags(candidate))


def _structural_weight_map(candidate: Mapping[str, Any]) -> dict[str, float]:
    features: dict[str, float] = {}
    path = _path_feature(candidate)
    if path:
        features[f"path:{path}"] = 3.0
    tag = _tag(candidate)
    if tag:
        features[f"tag:{tag}"] = 0.75
    for motif in set(_motifs(candidate)):
        features[f"motif:{motif}"] = 1.0
    for attribute in set(_attribute_names(candidate)):
        features[f"attribute:{attribute}"] = 0.5
    return features


def _hierarchical_categories(candidate: Mapping[str, Any]) -> dict[str, set[str]]:
    tags = _path_tags(candidate)
    path_features: set[str] = set()
    for depth in range(1, len(tags) + 1):
        path_features.add(f"prefix:{'/'.join(tags[:depth])}")
    return {
        "path": path_features,
        "motif": {f"motif:{motif}" for motif in _motifs(candidate)},
        "tag": {f"tag:{_tag(candidate)}"} if _tag(candidate) else set(),
        "attribute": {f"attribute:{name}" for name in _attribute_names(candidate)},
    }


def _weighted_jaccard(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = set(left) | set(right)
    denominator = sum(max(left.get(key, 0.0), right.get(key, 0.0)) for key in keys)
    if denominator <= 0.0:
        return 0.0
    numerator = sum(min(left.get(key, 0.0), right.get(key, 0.0)) for key in keys)
    return numerator / denominator


def _set_jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _structural_similarity(
    candidate: Mapping[str, Any], reference: Mapping[str, Any]
) -> float:
    return _weighted_jaccard(
        _structural_weight_map(candidate), _structural_weight_map(reference)
    )


def _hierarchical_similarity(
    candidate: Mapping[str, Any], reference: Mapping[str, Any]
) -> float:
    candidate_categories = _hierarchical_categories(candidate)
    reference_categories = _hierarchical_categories(reference)
    weighted_total = 0.0
    active_weight = 0.0
    for category, weight in _STRUCTURE_CATEGORY_WEIGHTS.items():
        left = candidate_categories[category]
        right = reference_categories[category]
        if not left and not right:
            continue
        weighted_total += weight * _set_jaccard(left, right)
        active_weight += weight
    return weighted_total / active_weight if active_weight else 0.0


def _local_motif_similarity(
    candidate: Mapping[str, Any], reference: Mapping[str, Any]
) -> float:
    return _set_jaccard(set(_motifs(candidate)), set(_motifs(reference)))


def _reference_aggregate(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    similarity: Callable[[Mapping[str, Any], Mapping[str, Any]], float],
    aggregation: str = "max",
) -> list[float]:
    if not references:
        return [0.0] * len(candidates)
    scores: list[float] = []
    for candidate in candidates:
        values = [similarity(candidate, reference) for reference in references]
        if aggregation == "mean":
            scores.append(sum(values) / len(values))
        else:
            scores.append(max(values, default=0.0))
    return scores


def _cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, dot / (left_norm * right_norm))


def _idf(documents: Sequence[Mapping[str, float]]) -> dict[str, float]:
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(document.keys())
    count = len(documents)
    return {
        term: math.log((1.0 + count) / (1.0 + frequency)) + 1.0
        for term, frequency in document_frequency.items()
    }


def _tfidf_vector(
    counts: Mapping[str, float], idf: Mapping[str, float]
) -> dict[str, float]:
    return {
        term: (1.0 + math.log(count)) * idf.get(term, 1.0)
        for term, count in counts.items()
        if count > 0
    }


def _word_count(value: str) -> Counter[str]:
    return Counter(_tokens(value))


def _char_ngram_count(value: str, n: int = 3) -> Counter[str]:
    normalized = _normalize_whitespace(value).casefold()
    if not normalized:
        return Counter()
    padded = f"  {normalized}  "
    return Counter(padded[index : index + n] for index in range(len(padded) - n + 1))


def _normalized_max(scores: Sequence[float]) -> list[float]:
    maximum = max(scores, default=0.0)
    if maximum <= 0.0:
        return [0.0] * len(scores)
    return [score / maximum for score in scores]


def _bm25_one(
    query_counts: Mapping[str, int], documents: Sequence[Mapping[str, int]]
) -> list[float]:
    if not query_counts or not documents:
        return [0.0] * len(documents)
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(document.keys())
    document_count = len(documents)
    average_length = (
        sum(sum(document.values()) for document in documents) / document_count
    )
    if average_length <= 0.0:
        return [0.0] * len(documents)

    k1 = 1.5
    b = 0.75
    scores: list[float] = []
    for document in documents:
        length = sum(document.values())
        score = 0.0
        for term, query_frequency in query_counts.items():
            term_frequency = document.get(term, 0)
            if not term_frequency:
                continue
            frequency = document_frequency[term]
            inverse_document_frequency = math.log1p(
                (document_count - frequency + 0.5) / (frequency + 0.5)
            )
            saturation = (term_frequency * (k1 + 1.0)) / (
                term_frequency + k1 * (1.0 - b + b * length / average_length)
            )
            score += query_frequency * inverse_document_frequency * saturation
        scores.append(score)
    return scores


def _simhash(features: Mapping[str, float], bits: int) -> int | None:
    if not features or bits not in (64, 128):
        return None
    accumulators = [0.0] * bits
    for feature, weight in features.items():
        if weight <= 0.0:
            continue
        digest = hashlib.blake2b(
            feature.encode("utf-8"), digest_size=bits // 8, person=b"ys-fp-v1"
        ).digest()
        for bit_index in range(bits):
            byte = digest[bit_index // 8]
            bit = (byte >> (7 - bit_index % 8)) & 1
            accumulators[bit_index] += weight if bit else -weight
    if not any(accumulators):
        return None
    result = 0
    for accumulator in accumulators:
        result = (result << 1) | int(accumulator >= 0.0)
    return result


def _simhash_similarity(
    left: Mapping[str, float], right: Mapping[str, float], bits: int
) -> float:
    left_hash = _simhash(left, bits)
    right_hash = _simhash(right, bits)
    if left_hash is None or right_hash is None:
        return 0.0
    hamming_distance = (left_hash ^ right_hash).bit_count()
    return 1.0 - hamming_distance / bits


def _path_edit_similarity(
    candidate: Mapping[str, Any], reference: Mapping[str, Any]
) -> float:
    left = _path_tags(candidate)
    right = _path_tags(reference)
    if not left or not right:
        return 0.0
    previous = list(range(len(right) + 1))
    for left_index, left_tag in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_tag in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_tag != right_tag),
                )
            )
        previous = current
    distance = previous[-1]
    return max(0.0, 1.0 - distance / max(len(left), len(right)))


def _semantic_vector(
    semantic_vectors: Mapping[str, Sequence[float]] | None, text: str
) -> list[float] | None:
    if semantic_vectors is None or not text:
        return None
    vector = semantic_vectors.get(text)
    if (
        not isinstance(vector, Sequence)
        or isinstance(vector, (str, bytes))
        or not vector
    ):
        return None
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(value) for value in values):
        return None
    if math.sqrt(sum(value * value for value in values)) == 0.0:
        return None
    return values


def _semantic_cosine(
    left: Sequence[float] | None, right: Sequence[float] | None
) -> float:
    if left is None or right is None or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _text_reference_similarity(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    representation: str,
    metric: Callable[[str, str], float],
    aggregation: str = "max",
) -> list[float]:
    return _reference_aggregate(
        candidates,
        references,
        lambda candidate, reference: metric(
            representation_text(candidate, representation),
            representation_text(reference, representation),
        ),
        aggregation,
    )


def _tfidf_query_scores(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    representation: str,
    query_text: str,
    char_ngrams: bool = False,
) -> list[float]:
    counter = _char_ngram_count if char_ngrams else _word_count
    candidate_vectors = [
        counter(representation_text(item, representation)) for item in candidates
    ]
    query_vector = counter(query_text)
    # Query-only retrieval must not change with the supplied reference budget.
    idf = _idf([*candidate_vectors, query_vector])
    weighted_query = _tfidf_vector(query_vector, idf)
    scores = [
        _cosine(_tfidf_vector(candidate, idf), weighted_query)
        for candidate in candidate_vectors
    ]
    return scores


def _tfidf_reference_scores(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    representation: str,
    char_ngrams: bool = False,
) -> list[float]:
    counter = _char_ngram_count if char_ngrams else _word_count
    candidate_vectors = [
        counter(representation_text(item, representation)) for item in candidates
    ]
    reference_vectors = [
        counter(representation_text(item, representation)) for item in references
    ]
    idf = _idf([*candidate_vectors, *reference_vectors])
    weighted_candidates = [_tfidf_vector(vector, idf) for vector in candidate_vectors]
    weighted_references = [_tfidf_vector(vector, idf) for vector in reference_vectors]
    if not weighted_references:
        return [0.0] * len(candidates)
    return [
        max(
            (_cosine(candidate, reference) for reference in weighted_references),
            default=0.0,
        )
        for candidate in weighted_candidates
    ]


def _bm25_query_scores(
    candidates: Sequence[Mapping[str, Any]], representation: str, query_text: str
) -> list[float]:
    documents = [
        _word_count(representation_text(item, representation)) for item in candidates
    ]
    return _normalized_max(_bm25_one(_word_count(query_text), documents))


def _bm25_reference_scores(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    representation: str,
) -> list[float]:
    documents = [
        _word_count(representation_text(item, representation)) for item in candidates
    ]
    if not references:
        return [0.0] * len(candidates)
    per_reference = [
        _normalized_max(
            _bm25_one(
                _word_count(representation_text(reference, representation)), documents
            )
        )
        for reference in references
    ]
    return [
        max((scores[index] for scores in per_reference), default=0.0)
        for index in range(len(candidates))
    ]


def _semantic_query_scores(
    candidates: Sequence[Mapping[str, Any]],
    query: Mapping[str, Any],
    representation: str,
    semantic_vectors: Mapping[str, Sequence[float]] | None,
) -> list[float]:
    query_vector = _semantic_vector(semantic_vectors, _query_description(query))
    return [
        _semantic_cosine(
            _semantic_vector(
                semantic_vectors, representation_text(candidate, representation)
            ),
            query_vector,
        )
        for candidate in candidates
    ]


def _semantic_reference_scores(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    representation: str,
    semantic_vectors: Mapping[str, Sequence[float]] | None,
) -> list[float]:
    return _reference_aggregate(
        candidates,
        references,
        lambda candidate, reference: _semantic_cosine(
            _semantic_vector(
                semantic_vectors, representation_text(candidate, representation)
            ),
            _semantic_vector(
                semantic_vectors, representation_text(reference, representation)
            ),
        ),
    )


def _simhash_reference_scores(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    representation: str,
    bits: int,
    structural: bool,
) -> list[float]:
    def features(item: Mapping[str, Any]) -> Mapping[str, float]:
        if structural:
            return _structural_weight_map(item)
        return {
            f"token:{token}": float(count)
            for token, count in _word_count(
                representation_text(item, representation)
            ).items()
        }

    return _reference_aggregate(
        candidates,
        references,
        lambda candidate, reference: _simhash_similarity(
            features(candidate), features(reference), bits
        ),
    )


def _all_finite_nonnegative(scores: Sequence[float]) -> list[float]:
    return [
        min(1.0, float(value)) if math.isfinite(value) and value >= 0.0 else 0.0
        for value in scores
    ]


def score_candidates(
    method: str,
    query: dict[str, Any],
    candidates: list[dict[str, Any]],
    references: list[dict[str, Any]],
    representation: str = "context",
    semantic_vectors: dict[str, Sequence[float]] | None = None,
) -> list[float]:
    """Score candidates in input order using one named, reproducible method.

    Methods marked ``query`` use only the field intent and candidates. Methods
    marked ``reference`` compare candidate evidence with archived seed candidates;
    those aggregate by maximum unless metadata explicitly says ``mean``. Candidate
    IDs, ancestor IDs, reference IDs, labels, and oracle values are never used.
    Missing evidence abstains with score zero. Semantic vectors are optional and
    keyed by ``representation_text(candidate, representation)`` or by the query
    description (falling back to its field name when the description is empty).
    """
    if method not in METHOD_METADATA:
        raise ValueError(f"unknown method: {method}")
    if representation not in REPRESENTATIONS:
        raise ValueError(f"unknown representation: {representation}")
    if not candidates:
        return []

    query_text = _query_text(query)
    candidate_texts = [
        representation_text(candidate, representation) for candidate in candidates
    ]

    if method in ("structural_weighted_jaccard", "structural_jaccard"):
        scores = _reference_aggregate(candidates, references, _structural_similarity)
    elif method == "hierarchical_jaccard":
        scores = _reference_aggregate(candidates, references, _hierarchical_similarity)
    elif method == "local_jaccard":
        scores = _reference_aggregate(candidates, references, _local_motif_similarity)
    elif method == "structural_weighted_jaccard_avg":
        scores = _reference_aggregate(
            candidates, references, _structural_similarity, aggregation="mean"
        )
    elif method == "hierarchical_structure":
        scores = _reference_aggregate(candidates, references, _hierarchical_similarity)
    elif method in ("lexical_token_jaccard_query", "token_jaccard"):
        query_tokens = set(_tokens(query_text))
        scores = [
            _set_jaccard(set(_tokens(text)), query_tokens)
            if text and query_tokens
            else 0.0
            for text in candidate_texts
        ]
    elif method == "lexical_token_jaccard_reference":
        scores = _text_reference_similarity(
            candidates,
            references,
            representation,
            lambda left, right: _set_jaccard(set(_tokens(left)), set(_tokens(right))),
        )
    elif method in ("lexical_bm25_query", "bm25"):
        scores = _bm25_query_scores(candidates, representation, query_text)
    elif method == "lexical_bm25_reference":
        scores = _bm25_reference_scores(candidates, references, representation)
    elif method in ("lexical_tfidf_cosine_query", "tfidf_cosine"):
        scores = _tfidf_query_scores(candidates, references, representation, query_text)
    elif method == "lexical_tfidf_cosine_reference":
        scores = _tfidf_reference_scores(candidates, references, representation)
    elif method == "lexical_char_ngram_cosine_query":
        scores = _tfidf_query_scores(
            candidates, references, representation, query_text, char_ngrams=True
        )
    elif method == "lexical_char_ngram_cosine_reference":
        scores = _tfidf_reference_scores(
            candidates, references, representation, char_ngrams=True
        )
    elif method in ("semantic_query_cosine", "semantic_query"):
        scores = _semantic_query_scores(
            candidates, query, representation, semantic_vectors
        )
    elif method in ("semantic_reference_cosine", "semantic_reference"):
        scores = _semantic_reference_scores(
            candidates, references, representation, semantic_vectors
        )
    elif method == "simhash64_lexical_reference":
        scores = _simhash_reference_scores(
            candidates, references, representation, bits=64, structural=False
        )
    elif method == "simhash128_lexical_reference":
        scores = _simhash_reference_scores(
            candidates, references, representation, bits=128, structural=False
        )
    elif method == "simhash64_structure_reference":
        scores = _simhash_reference_scores(
            candidates, references, representation, bits=64, structural=True
        )
    elif method == "simhash128_structure_reference":
        scores = _simhash_reference_scores(
            candidates, references, representation, bits=128, structural=True
        )
    elif method in ("tree_path_edit_reference", "path_edit"):
        scores = _reference_aggregate(candidates, references, _path_edit_similarity)
    else:  # METHOD_METADATA and dispatch must remain in sync.
        raise AssertionError(f"missing method implementation: {method}")

    return _all_finite_nonnegative(scores)
