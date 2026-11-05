"""Memoization must preserve actual score vectors, not merely rankings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

import advanced_methods
import methods
from acceleration import ExactCaches
from test_methods import item


def test_scores_identical_with_exact_caches():
    candidates = [
        item(
            text="current purchase price",
            context="Product offer",
            tag="span",
            path=["html", "main", "span"],
            motifs=["child:span"],
        ),
        item(
            text="shipping price",
            context="delivery",
            tag="p",
            path=["html", "aside", "p"],
            motifs=["child:p"],
        ),
    ]
    refs = candidates[:1]
    query = {"field": "price", "description": "purchase price"}
    vectors = {
        "purchase price": [1.0, 0.1],
        **{
            methods.representation_text(c, "context"): [1.0, float(i)]
            for i, c in enumerate(candidates)
        },
    }
    names = [
        "structural_jaccard",
        "bm25",
        "tfidf_cosine",
        "lexical_char_ngram_cosine_query",
        "simhash64_structure_reference",
        "simhash128_lexical_reference",
        "semantic_query",
        "semantic_reference",
    ]
    expected = {
        name: methods.score_candidates(
            name, query, candidates, refs, "context", vectors
        )
        for name in names
    }
    expected_cws = advanced_methods.score_candidates(
        "weighted_minhash_64", query, candidates, refs
    )
    original = methods._simhash
    with ExactCaches() as cache:
        for _ in range(2):
            for name in names:
                assert (
                    methods.score_candidates(
                        name, query, candidates, refs, "context", vectors
                    )
                    == expected[name]
                )
            assert (
                advanced_methods.score_candidates(
                    "weighted_minhash_64", query, candidates, refs
                )
                == expected_cws
            )
        ledger = cache.ledger()
        assert ledger["_simhash"]["hits"] > 0
        assert ledger["semantic_cosine"]["hits"] > 0
        assert ledger["_cws_signature"]["hits"] > 0
    assert methods._simhash is original
