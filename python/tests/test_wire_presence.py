from yosoi.locators import QueryAtom, QuerySpec
from yosoi.map import MapTermination
from yosoi.outcomes import ExpandedNamePathSegment, Failure, TreeCoordinate


def test_tree_coordinate_preserves_null_and_omits_skipped_option() -> None:
    expected = {"child_path": [1], "source_bytes": None}

    assert TreeCoordinate.try_new((1,)).model_dump(mode="json") == expected
    assert (
        TreeCoordinate.model_validate_json(
            '{"child_path":[1],"source_bytes":null,"expanded_name_path":null}'
        ).model_dump(mode="json")
        == expected
    )
    assert (
        TreeCoordinate.model_validate_json('{"child_path":[1]}').model_dump(mode="json")
        == expected
    )

    segment = ExpandedNamePathSegment.try_new(None, "x", 1)
    assert segment.model_dump(mode="json") == {
        "namespace_uri": None,
        "local_name": "x",
        "same_name_sibling_index": 1,
    }
    with_path = TreeCoordinate.with_expanded_name_path((1,), None, (segment,))
    assert with_path.model_dump(mode="json") == {
        "child_path": [1],
        "source_bytes": None,
        "expanded_name_path": [
            {
                "namespace_uri": None,
                "local_name": "x",
                "same_name_sibling_index": 1,
            }
        ],
    }


def test_query_spec_omits_only_empty_namespace_bindings() -> None:
    expected = {
        "atom": {"kind": "css", "value": "a"},
        "result_shape": "tree_nodes",
    }

    for wire in (
        expected,
        {**expected, "namespace_bindings": []},
    ):
        query = QuerySpec.model_validate(wire)
        assert query.model_dump(mode="json") == expected

    query = QuerySpec.new(QueryAtom(kind="css", value="a"), "tree_nodes")
    namespaced = query.with_namespace("t", "urn:test")
    assert namespaced.model_dump(mode="json") == {
        **expected,
        "namespace_bindings": [{"prefix": "t", "namespace_uri": "urn:test"}],
    }


def test_map_termination_omits_unit_variant_content_but_keeps_payloads() -> None:
    exhausted = MapTermination.model_validate({"kind": "exhausted", "value": None})
    assert exhausted.model_dump(mode="json") == {"kind": "exhausted"}

    limit = MapTermination(kind="limit", value="hosts")
    assert limit.model_dump(mode="json") == {"kind": "limit", "value": "hosts"}


def test_locate_failure_omits_other_variants_fields_and_keeps_payloads() -> None:
    assert Failure.model_validate(
        {
            "kind": "unsupported_combination",
            "document": "source_html",
            "code": None,
            "limit": None,
            "maximum": None,
            "observed": None,
        }
    ).model_dump(mode="json") == {
        "kind": "unsupported_combination",
        "document": "source_html",
    }
    assert Failure(
        kind="limit_exhausted", limit="matches", maximum=3, observed=4
    ).model_dump(mode="json") == {
        "kind": "limit_exhausted",
        "limit": "matches",
        "maximum": 3,
        "observed": 4,
    }
    assert Failure(kind="parse_failed", code="malformed_xml").model_dump(
        mode="json"
    ) == {"kind": "parse_failed", "code": "malformed_xml"}
