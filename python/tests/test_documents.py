import gc
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.errors import ClosedResourceError, DocumentError, LocatorError, ParseError
from yosoi.policy import Documents, Policy


def heading_plan() -> ys.Plan:
    return ys.Plan(outputs=[ys.output("title", ys.css("h1").text())])


def test_html_document_and_parsed_reuse_have_identical_evidence() -> None:
    document = ys.Document.html("page", "<main><h1>Hello</h1><p>body</p></main>")
    plan = heading_plan()
    direct = document.locate(plan)
    with document.parse() as parsed:
        assert parsed.locate(plan) == direct
        assert parsed.locate(plan).values("title") == ["Hello"]
    assert parsed.closed
    with pytest.raises(ClosedResourceError):
        parsed.locate(plan)
    parsed.close()


def test_parsed_representation_retains_source_after_python_owner_is_deleted() -> None:
    document = ys.Document.text("retained", "café world")
    parsed = document.parse()
    del document
    gc.collect()
    plan = ys.Plan(outputs=[ys.output("match", ys.text_literal("café").text())])
    try:
        outcome = parsed.locate(plan)
        assert outcome.values() == ["café"]
        assert outcome.findings[0].document_id == "retained"
    finally:
        parsed.close()


def test_shared_parse_supports_concurrent_calls() -> None:
    document = ys.Document.html("shared", "<h1>Thread safe</h1>")
    plan = heading_plan()
    with document.parse() as parsed, ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: parsed.locate(plan).values(), range(16)))
    assert outcomes == [["Thread safe"]] * 16
    assert parsed.closed


def test_no_match_and_parse_failure_remain_distinct_outcomes() -> None:
    missing = ys.Document.html("empty", "<p>body</p>").locate(heading_plan())
    assert missing.status == "no_match"
    broken = ys.Document.from_json("broken", b"{")
    plan = ys.Plan(outputs=[ys.output("value", ys.json_pointer("").value())])
    assert broken.locate(plan).status == "failed"
    with pytest.raises(ParseError):
        broken.parse()


def test_bound_policy_is_snapshotted_and_enforces_rust_parser_limits() -> None:
    policy = Policy(documents=Documents(max_input_bytes=1))
    document = ys.Document.html("bounded", "<h1>Hello</h1>")
    bound = document.bind(policy)
    policy.documents.max_input_bytes = 1_000
    outcome = bound.locate(heading_plan())
    assert outcome.status == "failed"
    assert document.bind(policy).locate(heading_plan()).status == "matched"


def test_copying_document_or_plan_rebuilds_native_state() -> None:
    original = ys.Document.html("copy", "<h1>Before</h1><p>Other</p>")
    changed = original.model_copy(update={"data": b"<h1>After</h1>"})
    assert changed.locate(heading_plan()).values() == ["After"]
    assert original.locate(heading_plan()).values() == ["Before"]
    assert original == original.model_copy(deep=True)
    plan = heading_plan().model_copy(
        update={
            "outputs": [ys.output("other", ys.css("p").text())],
        }
    )
    assert original.locate(plan).values() == ["Other"]
    assert plan == plan.model_copy(deep=True)


def test_invalid_authoring_is_rejected_before_location() -> None:
    with pytest.raises(LocatorError):
        ys.Plan(outputs=[ys.output("title", ys.css("h1").value())])
    with pytest.raises(LocatorError):
        ys.Plan(outputs=[])
    with pytest.raises(DocumentError):
        ys.Document.rendered_dom("dom", 0, "{}")
    with pytest.raises(ValidationError):
        Policy(documents=Documents(max_input_bytes=0))


def test_xml_namespace_binding_survives_pydantic_copy() -> None:
    document = ys.Document.xml("xml", '<r xmlns="urn:test"><name>Rust</name></r>')
    query = ys.xpath("//t:name").with_namespace("t", "urn:test")
    plan = ys.Plan(outputs=[ys.output("name", query.text())]).model_copy(deep=True)
    assert document.locate(plan).values() == ["Rust"]


def test_repeated_regions_preserve_order_and_native_lineage() -> None:
    document = ys.Document.html(
        "rows", "<article><h2>A</h2></article><article><h2>B</h2></article>"
    )
    rows = ys.css("article").each_as_region("rows")
    plan = ys.Plan(outputs=[ys.output("name", rows.find(ys.css("h2")).text())])
    outcome = document.locate(plan)
    assert outcome.values() == ["A", "B"]
    assert [
        item.parent_region.region_ordinal
        for item in outcome.findings
        if item.parent_region is not None
    ] == [1, 2]
