"""Native Request, Map, and Search failures retain their SDK identity."""

import asyncio
import json

import pytest

import yosoi as ys
import yosoi._native as native
from yosoi.errors import (
    MapError,
    PolicyError,
    RequestError,
    SearchError,
    rust_error_details,
)


def test_request_preparation_errors_keep_exception_category_and_metadata() -> None:
    request = ys.request.new("ftp://example.com")

    with pytest.raises(RequestError) as direct_caught:
        request.check()
    direct_detail = rust_error_details(direct_caught.value)
    assert direct_detail is not None
    assert direct_detail.rust_type == "yosoi::request::RequestPreparationError"
    assert direct_detail.variant is None
    assert direct_detail.details == {"opaque": True}

    async def run() -> None:
        with pytest.raises(RequestError) as caught:
            await request.send()

        detail = rust_error_details(caught.value)
        assert detail is not None
        assert detail.rust_type == "yosoi::request::RequestSendError"
        assert detail.variant is None
        assert detail.details == {"opaque": True}
        assert str(caught.value) == "invalid request target"

    asyncio.run(run())


def test_map_async_preflight_error_is_identified_as_opaque_public_wrapper() -> None:
    operation = ys.map.new("ftp://example.com")

    async def run() -> None:
        with pytest.raises(MapError) as caught:
            await operation.send()

        detail = rust_error_details(caught.value)
        assert detail is not None
        assert detail.rust_type == "yosoi::map::MapError"
        assert detail.variant is None
        assert detail.details == {"opaque": True}
        assert str(caught.value).startswith("invalid Map seed or scope:")

    asyncio.run(run())


def test_search_query_and_operation_errors_expose_public_variants_and_payloads() -> (
    None
):
    with pytest.raises(SearchError) as empty_query:
        ys.search.new(" \n")
    empty_detail = rust_error_details(empty_query.value)
    assert empty_detail is not None
    assert empty_detail.rust_type == "yosoi::search::SearchQueryError"
    assert empty_detail.variant == "Empty"
    assert empty_detail.details == {}
    assert str(empty_query.value) == "search query must contain non-whitespace text"

    with pytest.raises(SearchError) as long_query:
        ys.search.new("x" * 513)
    long_detail = rust_error_details(long_query.value)
    assert long_detail is not None
    assert long_detail.variant == "TooLong"
    assert long_detail.details == {"maximum": 512, "observed": 513}

    request = ys.search.new("rust")
    policy = ys.Policy(search=ys.policy.Search.disabled())
    with pytest.raises(SearchError) as no_provider:
        request.bind(policy).check()
    operation_detail = rust_error_details(no_provider.value)
    assert operation_detail is not None
    assert operation_detail.rust_type == "yosoi::search::SearchSendError"
    assert operation_detail.variant == "NoProviderConfigured"
    assert operation_detail.details == {}
    assert str(no_provider.value) == "Search policy has no selected providers"

    policy_value = json.loads(ys.Policy().to_json())
    policy_value["search"]["providers"][1] = policy_value["search"]["providers"][0]
    with pytest.raises(PolicyError) as invalid_policy:
        native.SearchRequest("rust").validate(json.dumps(policy_value))
    policy_detail = rust_error_details(invalid_policy.value)
    assert policy_detail is not None
    assert policy_detail.rust_type == "serde_json::Error"
    assert policy_detail.variant == "Data"
    assert policy_detail.details["category"] == "data"


def test_policy_json_decode_keeps_serde_metadata_at_operation_boundary() -> None:
    request = native.PageRequest("https://example.com")

    with pytest.raises(PolicyError) as caught:
        request.validate("{")

    detail = rust_error_details(caught.value)
    assert detail is not None
    assert detail.rust_type == "serde_json::Error"
    assert detail.variant == "Eof"
    assert detail.details["category"] == "eof"
