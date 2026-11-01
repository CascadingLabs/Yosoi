"""Target pages must be disjoint from the supplied same-site references."""

import json

from same_site_wave import heldout_cases


def test_two_reference_pages_are_never_evaluated_as_site_targets(tmp_path):
    (tmp_path / "frozen.json").write_text(
        json.dumps({"reference_groups": [{"id": "site/2", "cases": ["one", "two"]}]})
    )
    (tmp_path / "corpus.json").write_text(
        json.dumps(
            {
                "cases": [
                    {"id": name, "family": "site", "split": "fresh_cross_site"}
                    for name in ("one", "two", "three", "four")
                ]
            }
        )
    )
    result = heldout_cases(tmp_path)
    assert [case["case"] for case in result] == ["three", "four"]
    assert all(case["group"] == "site/2" for case in result)
