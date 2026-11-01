"""Alternative evidence remains evaluation-only and must match retained source."""

import pytest
from evaluate_witnesses import qualified_map


def test_only_reviewed_source_bound_candidates_are_qualified():
    candidate = {
        "id": "alt",
        "node_id": "n",
        "projection": "@alt",
        "text": "Book",
        "ancestors": ["owner"],
    }
    cases = {"case": {"owning_root_id": "owner", "candidates": [candidate]}}
    entry = {
        "decision": "qualified",
        "include_in_qualified_alternative_set": True,
        "candidate_id": "alt",
        "candidate_node_id": "n",
        "projection": "@alt",
        "candidate_exact_value": "Book",
    }
    annotations = {
        "cases": {
            "case": {
                "fields": {
                    "name": {
                        "qualified_alternatives": [entry],
                        "uncertain_candidates": [{"candidate_id": "tag"}],
                    }
                }
            }
        }
    }
    assert qualified_map(annotations, cases) == {("case", "name"): {"alt"}}
    entry["candidate_exact_value"] = "Invented"
    with pytest.raises(ValueError, match="disagrees"):
        qualified_map(annotations, cases)
