"""Layout scoring must use only declared source features and keep missing evidence."""

import copy

import pytest
from layout_retrieval import (
    build_candidates,
    comparison_condition,
    layout_scores,
    quality,
    tie_hit_bounds,
)


def fixture():
    nodes = []
    for ordinal, parent, tag, width, height in (
        (0, None, "html", 1000, 800),
        (1, 0, "main", 500, 400),
        (2, 1, "h1", 300, 50),
    ):
        nodes.append(
            {
                "ordinal": ordinal,
                "parentOrdinal": parent,
                "tag": tag,
                "path": "/".join(
                    [
                        "html[0]",
                        *(["main[0]"] if ordinal else []),
                        *(["h1[0]"] if ordinal == 2 else []),
                    ]
                ),
                "text": "Example",
                "textTruncated": False,
                "attributes": [],
                "box": {"x": 10, "y": 20, "width": width, "height": height},
                "styles": {
                    "font-size": "20px",
                    "line-height": "24px",
                    "font-weight": "400",
                    "font-style": "normal",
                    "color": "rgb(20, 40, 60)",
                    "display": "block",
                    "visibility": "visible",
                    "opacity": "1",
                },
            }
        )
    return {"nodes": nodes, "viewport": {"width": 1000, "height": 800}}


def test_global_scaling_preserves_normalized_geometry_and_typography():
    original = fixture()
    scaled = copy.deepcopy(original)
    for row in scaled["nodes"]:
        row["box"] = {key: value * 2 for key, value in row["box"].items()}
        row["styles"].update({"font-size": "40px", "line-height": "48px"})
    scaled["viewport"] = {"width": 2000, "height": 1600}
    a, b = build_candidates(original), build_candidates(scaled)
    assert [x["layout_features"] for x in a] == [x["layout_features"] for x in b]


def test_layout_scores_ignore_text_ids_and_attribute_values():
    candidates = build_candidates(fixture())
    reference = copy.deepcopy(candidates[-1])
    before = layout_scores("layout_parent_typography", candidates, [reference])
    for candidate in candidates:
        candidate.update(text="different", id="irrelevant", attributes={"any": "new"})
    assert layout_scores("layout_parent_typography", candidates, [reference]) == before
    assert layout_scores("layout_font", candidates, []) == [0, 0, 0]


def test_hidden_ancestor_excludes_child_and_invalid_ancestry_rejects():
    source = fixture()
    source["nodes"][0]["styles"]["opacity"] = "0"
    assert build_candidates(source) == []
    source["nodes"][0]["parentOrdinal"] = 2
    with pytest.raises(ValueError, match="ancestry"):
        build_candidates(source)


def test_missing_font_dimension_does_not_invent_evidence():
    source = fixture()
    for row in source["nodes"]:
        row["styles"]["line-height"] = "normal"
    candidates = build_candidates(source)
    assert all("line_height" not in c["layout_features"] for c in candidates)
    assert layout_scores("layout_font", [candidates[0]], [candidates[1]]) == [1]


def test_gold_outside_candidate_universe_is_an_operational_miss():
    result = quality(
        [],
        {
            "status": "present_dom",
            "canonical_ordinals": [404],
            "qualified_alternative_ordinals": [],
        },
        {},
    )
    assert not result["canonical_hit"]
    assert not result["gold_in_universe"]
    assert result["status"] == "present_dom"


def test_tie_expectation_uses_full_tie_instead_of_retained_top_five():
    candidates = [{"id": str(i)} for i in range(7)]
    result = tie_hit_bounds([0.5] * 7, candidates, {"6"}, 5)
    assert result["expected"] == pytest.approx(5 / 7)
    assert result["worst"] == 0
    assert result["best"] == 1
    assert tie_hit_bounds([0] * 7, candidates, {"6"}, 5)["expected"] == 0


def test_same_page_viewport_shift_is_not_a_self_match():
    wide = {"id": "same", "viewport": {"width": 1920}, "source_hashes": {"png": "a"}}
    narrow = {"id": "same", "viewport": {"width": 390}, "source_hashes": {"png": "b"}}
    assert comparison_condition(wide, wide) == "self_diagnostic"
    assert comparison_condition(narrow, wide) == "same_page_viewport_shift"
    narrow["id"] = "another"
    assert comparison_condition(narrow, wide) == "cross_template_viewport_shift"
