"""Public Rust catalogs and scalar invariants remain available in Python."""

import pytest
from pydantic import TypeAdapter, ValidationError

import yosoi as ys
from yosoi.map import DiscoverySource, PublicProvider
from yosoi.search import SearchHit, SearchResultUrl


def test_public_provider_catalog_and_bounded_endpoint_authoring():
    assert [provider.value for provider in PublicProvider.all()] == [
        "crt_sh",
        "hacker_target",
        "subdomain_center",
        "wayback_archive",
    ]
    assert PublicProvider.crt_sh.name == "crtsh"
    assert "example.org" in PublicProvider.crt_sh.endpoint("example.org")
    assert "example.org" in PublicProvider.wayback_archive.endpoint("example.org")
    assert DiscoverySource(kind="passive_provider", value="crt_sh").is_passive
    assert DiscoverySource(kind="passive_certificate").is_passive
    assert not DiscoverySource(kind="html_link").is_passive
    with pytest.raises(ys._native.MapError):
        PublicProvider.crt_sh.endpoint("not a domain")


def test_search_url_and_rank_invariants_are_checked_without_requests():
    url = TypeAdapter(SearchResultUrl)
    assert url.validate_python("https://example.org/path") == "https://example.org/path"
    for invalid in (
        "/relative",
        "ftp://example.org",
        "https://user:password@example.org",
    ):
        with pytest.raises((ys._native.SearchError, ValidationError)):
            url.validate_python(invalid)
    metadata = dict.fromkeys(
        (
            "title",
            "snippet",
            "display_url",
            "publisher",
            "published_at",
            "thumbnail_url",
        )
    )
    hit = SearchHit(
        url="https://example.org",
        organic_rank=1,
        placement_index=2,
        metadata={**metadata, "publisher": "Example"},
    )
    assert hit.publisher == "Example"
    assert hit.display_url is None
    with pytest.raises(ValidationError):
        SearchHit(url=hit.url, organic_rank=0, placement_index=2, metadata=metadata)
    with pytest.raises(ValidationError):
        SearchHit(url=hit.url, organic_rank=1, placement_index=65536, metadata=metadata)


def test_invalid_query_fails_at_authoring_like_rust_constructor():
    with pytest.raises(ys._native.LocatorError):
        ys.css("")
    with pytest.raises(ys._native.LocatorError):
        ys.xpath("")
    # Rust permits an empty regex expression and rejects invalid syntax.
    assert ys.regex("").expression == ""
    with pytest.raises(ys._native.LocatorError):
        ys.regex("[")


def test_namespace_constructors_distinguish_named_and_default_bindings():
    named_empty = ys.xpath("//title").with_namespace("", "urn:books")
    assert named_empty.namespaces[0].prefix == ""
    with pytest.raises(ys._native.LocatorError):
        ys.xpath("//title").with_default_namespace("urn:books")
    document = ys.Document.xml(
        "xml-default", '<r xmlns="urn:books"><title>Ada</title></r>'
    )
    plan = ys.Plan(
        outputs=[
            ys.output(
                "title", ys.css("title").with_default_namespace("urn:books").text()
            )
        ]
    )
    assert document.locate(plan).values() == ["Ada"]
    with pytest.raises((ys._native.LocatorError, ValidationError)):
        ys.css("article").each_as_region("")
    with pytest.raises((ys._native.LocatorError, ValidationError)):
        ys.output("", ys.css("h1").text())


def test_projection_arguments_fail_at_the_rust_constructor_boundary():
    from yosoi.locators import Locator, Query

    with pytest.raises(ys._native.LocatorError):
        ys.css("a").attribute("")
    with pytest.raises(ys._native.LocatorError):
        Query(kind="css", expression="a", state=True)
    with pytest.raises(ys._native.LocatorError):
        Locator(query=ys.css("a"), projection="text", attribute="href")
    with pytest.raises(ys._native.LocatorError):
        Locator(query=ys.regex("(?P<word>a)"), projection="text", captures=("word",))


def test_query_metadata_and_portable_plan_import_preserve_rust_semantics():
    query = ys.xpath("//t:name").with_namespace("t", "urn:test")
    assert query.atom.expression == "//t:name"
    assert query.result_shape == "tree_nodes"
    assert query.namespace_bindings[0].namespace_uri == "urn:test"
    assert query.query_bytes == len("//t:name") + len("t") + len("urn:test")
    spec = query.compiled()
    assert spec.to_query() == query
    # QuerySpec::new permits an explicit result shape independently of the atom.
    # Import must preserve it instead of silently replacing it with the DSL default.
    explicit = ys.locators.QuerySpec.new(ys.css("article").atom, "json_values")
    assert explicit.to_query().compiled() == explicit
    assert explicit.to_query().model_copy(deep=True).compiled() == explicit
    first = (
        ys.xpath("//x:name").with_namespace("z", "urn:z").with_namespace("x", "urn:x")
    )
    second = (
        ys.xpath("//x:name").with_namespace("x", "urn:x").with_namespace("z", "urn:z")
    )
    assert first == second
    assert first.compiled() == second.compiled()
    assert ys.locators.QuerySpec.new(spec.atom, spec.result_shape).query_bytes == len(
        "//t:name"
    )
    document = ys.Document.xml("portable", '<r xmlns="urn:test"><name>Ada</name></r>')
    plan = ys.Plan(outputs=[ys.output("name", query.text())])
    restored = ys.Plan.from_compiled(plan.compiled())
    assert restored.compiled() == plan.compiled()
    assert restored.outputs == plan.outputs
    assert document.locate(restored) == document.locate(plan)
    # Rust validates the serialized requirement, rather than trusting the caller.
    forged = plan.compiled()
    requirement = forged["requirement"]
    assert isinstance(requirement, dict)
    requirement["accepted_documents"] = ["source_json"]
    with pytest.raises(ys._native.LocatorError):
        ys.Plan.from_compiled(forged)


def test_portable_repeated_root_and_regex_capture_import():
    document = ys.Document.html(
        "rows", "<article><h2>Ada</h2></article><article></article>"
    )
    region = ys.css("article").each_as_region("rows")
    plan = ys.Plan(outputs=[ys.output("name", region.find(ys.css("h2")).text())])
    restored = ys.Plan.from_compiled(plan.compiled())
    assert restored.compiled() == plan.compiled()
    assert document.locate(restored) == document.locate(plan)
    text = ys.Document.text("text", "Hello world")
    capture = ys.Plan(
        outputs=[ys.output("word", ys.regex("(?P<word>Hello)").captures("word"))]
    )
    restored = ys.Plan.from_compiled(capture.compiled())
    assert text.locate(restored) == text.locate(capture)
