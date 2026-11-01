"""Review inputs must ignore gold and acceptance must remain source-bound."""

import copy
import json

import pytest
from review_experiment import METHODS, audit_response, choose_proposals, strict_json


def test_proposal_selection_does_not_read_quality_fields():
    rows = [
        {
            "target": target,
            "seed": seed,
            "field": field,
            "method": method,
            "budget": 5,
            "proposal_ids": ["element:000001"],
            "canonical_hit": False,
        }
        for target, seed in (("one", "two"), ("two", "one"))
        for field in ("name", "price", "stock")
        for method in METHODS
    ]
    expected = choose_proposals(rows, ["one", "two"])
    changed = copy.deepcopy(rows)
    for row in changed:
        row.update(canonical_hit=True, qualified_hit=True, status="absent")
    assert choose_proposals(changed, ["one", "two"]) == expected


def sample(quote="£12.00", source="selected:P0", truncated=False):
    payload = {
        "proposals": [
            {
                "id": "P0",
                "selected_source_id": "selected:P0",
                "selected_text_truncated": truncated,
            }
        ],
        "evidence": [
            {"id": "selected:P0", "text": "£12.00"},
            {"id": "other", "text": "£12.00"},
        ],
    }
    body = {"messages": [{"content": "system"}, {"content": json.dumps(payload)}]}
    response = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "decisions": [
                                {
                                    "proposal_id": "P0",
                                    "verdict": "supported",
                                    "reason": "price",
                                    "evidence": [
                                        {"evidence_id": source, "quote": quote}
                                    ],
                                }
                            ]
                        }
                    )
                },
            }
        ]
    }
    return body, response


def test_supported_decision_requires_its_own_literal_source_quote():
    body, response = sample()
    assert audit_response(body, response)["P0"]["effective_verdict"] == "supported"
    for quote, source in (
        ("£99.00", "selected:P0"),
        ("£12.00", "other"),
        (" ", "selected:P0"),
    ):
        body, response = sample(quote, source)
        assert (
            audit_response(body, response)["P0"]["effective_verdict"]
            == "source_evidence_rejected"
        )


def test_truncated_selection_does_not_gain_acceptance_from_a_valid_quote():
    body, response = sample(truncated=True)
    assert (
        audit_response(body, response)["P0"]["effective_verdict"]
        == "source_evidence_rejected"
    )


def test_review_rejects_missing_or_foreign_proposal_ids():
    body, response = sample()
    content = json.loads(response["choices"][0]["message"]["content"])
    content["decisions"][0]["proposal_id"] = "foreign"
    response["choices"][0]["message"]["content"] = json.dumps(content)
    with pytest.raises(ValueError, match="decision IDs"):
        audit_response(body, response)


def test_duplicate_json_keys_and_nonfinite_constants_are_not_repaired():
    with pytest.raises(ValueError, match="duplicate"):
        strict_json('{"decisions":[],"decisions":[]}')
    with pytest.raises(ValueError, match="nonfinite"):
        strict_json('{"value":NaN}')
