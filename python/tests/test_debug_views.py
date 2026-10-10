"""Default Python displays redact the same nested search/request secrets."""

import json

from yosoi.map import MapOutcome, MapTermination, RetainedCapture, Summary
from yosoi.policy import Policy, PolicyIdentity
from yosoi.request import Attempt, Response
from yosoi.search import (
    Answer,
    ImageGallery,
    ImageResult,
    LocalPack,
    LocalPlace,
    ProviderCharge,
    ProviderDefaultsStatus,
    ProviderIdentity,
    ProviderResult,
    RequestAttemptSummary,
    Results,
    SearchCoverage,
    SearchHit,
    SearchHitMetadata,
    SearchPage,
    SearchProfileFacts,
    SearchResponse,
    SearchResultUrl,
    Sponsored,
)


def _assert_hidden_from_display(value: object, *secrets: str) -> None:
    for rendered in (repr(value), str(value)):
        for secret in secrets:
            assert secret not in rendered


def test_search_result_url_redacts_repr_but_keeps_display_and_explicit_access() -> None:
    raw_url = "https://results.example/path/secret-search-url"
    result_url = SearchResultUrl(raw_url)

    assert "secret-search-url" not in repr(result_url)
    assert str(result_url) == raw_url
    assert result_url.as_str() == raw_url
    assert result_url.as_request_target() == raw_url


def test_search_payload_models_redact_repr_and_str_without_hiding_data() -> None:
    secrets = (
        "secret-title",
        "secret-snippet",
        "secret-display-url",
        "secret-publisher",
        "secret-date",
        "secret-thumbnail",
        "secret-organic-url",
        "secret-sponsored-destination",
        "secret-sponsored-label",
        "secret-answer-text",
        "secret-citation-url",
        "secret-image-url",
        "secret-image-source",
        "secret-place-name",
        "secret-place-url",
        "secret-map-url",
    )
    metadata = SearchHitMetadata(
        title=secrets[0],
        snippet=secrets[1],
        display_url=secrets[2],
        publisher=secrets[3],
        published_at=secrets[4],
        thumbnail_url=SearchResultUrl("https://images.example/secret-thumbnail"),
    )
    hit = SearchHit(
        url=SearchResultUrl("https://results.example/secret-organic-url"),
        organic_rank=1,
        placement_index=2,
        metadata=metadata,
    )
    features = (
        Sponsored(
            kind="sponsored",
            placement_index=3,
            destination=SearchResultUrl(
                "https://ads.example/secret-sponsored-destination"
            ),
            label=secrets[8],
        ),
        Answer(
            kind="answer",
            placement_index=4,
            text=secrets[9],
            citations=(
                SearchResultUrl("https://citations.example/secret-citation-url"),
            ),
        ),
        ImageGallery(
            kind="image_gallery",
            placement_index=5,
            images=(
                ImageResult(
                    image_url=SearchResultUrl(
                        "https://images.example/secret-image-url"
                    ),
                    source_page_url=SearchResultUrl(
                        "https://source.example/secret-image-source"
                    ),
                ),
            ),
        ),
        LocalPack(
            kind="local_pack",
            placement_index=6,
            places=(
                LocalPlace(
                    name=secrets[13],
                    place_url=SearchResultUrl(
                        "https://places.example/secret-place-url"
                    ),
                ),
            ),
            map_url=SearchResultUrl("https://maps.example/secret-map-url"),
        ),
    )
    page = SearchPage(
        hits=(hit,),
        features=features,
        coverage=SearchCoverage(web="complete", rich_features="collected"),
        issues=(),
    )
    result = Results(status="results", value=page)

    for view in (metadata, hit, *features, page, result):
        _assert_hidden_from_display(view, *secrets)

    wire = json.dumps(page.model_dump(mode="json"))
    for secret in secrets:
        assert secret in wire
    assert metadata.title == secrets[0]
    assert hit.url.as_str().endswith("secret-organic-url")


def test_provider_and_search_response_summarize_nested_results() -> None:
    secret_query = "secret-recovery-query"
    hit = SearchHit(
        url=SearchResultUrl("https://results.example/secret-provider-hit"),
        organic_rank=1,
        placement_index=1,
        metadata=SearchHitMetadata(
            title="secret-provider-title",
            snippet=None,
            display_url=None,
            publisher=None,
            published_at=None,
            thumbnail_url=None,
        ),
    )
    page = SearchPage(
        hits=(hit,),
        features=(),
        coverage=SearchCoverage(web="complete", rich_features="not_collected"),
        issues=(),
    )
    provider = ProviderResult(
        provider="bing",
        identity=ProviderIdentity(
            provider="bing",
            endpoint="https://provider.example/search",
            adapter_version="adapter-v1",
            parser_version="parser-v1",
        ),
        profile=SearchProfileFacts(
            acquisition=None,
            defaults_status=ProviderDefaultsStatus(status="exact"),
            defaults_version=None,
            effective_request_policy=None,
        ),
        request_id="request-id",
        recovery_query=secret_query,
        attempts=(
            RequestAttemptSummary(
                request_id="secret-attempt-request-id",
                capture_id="secret-attempt-capture-id",
                acquisition={"kind": "direct_http"},
                http_status=200,
                source_bytes=16,
                diagnostic=None,
                terminal="completed",
            ),
        ),
        outcome=Results(status="results", value=page),
        charge=ProviderCharge(status="unknown"),
    )
    response = SearchResponse(
        request_id="search-request-id",
        policy_identity=PolicyIdentity(version=1, sha256="a" * 64),
        termination="completed",
        providers=(provider,),
    )

    for view in (provider, response):
        _assert_hidden_from_display(
            view,
            secret_query,
            "secret-attempt-request-id",
            "secret-attempt-capture-id",
            "secret-provider-hit",
            "secret-provider-title",
        )
    wire = json.dumps(response.model_dump(mode="json"))
    for secret in (
        secret_query,
        "secret-attempt-request-id",
        "secret-attempt-capture-id",
        "secret-provider-hit",
        "secret-provider-title",
    ):
        assert secret in wire


def test_response_and_map_captures_hide_nested_request_targets() -> None:
    secret_target = "https://private.example/path?token=secret-response-target"
    secret_attempt_target = (
        "https://private.example/attempt?token=secret-attempt-target"
    )
    snapshot = Policy().snapshot()
    attempt = Attempt(
        capture_id="capture-id",
        acquisition={"kind": "direct_http"},
        authored_selection="exact",
        requested_target=secret_attempt_target,
        http_status=200,
        state="completed",
        failure_kind=None,
        not_started_reason=None,
        diagnostic=None,
        documents=(),
    )
    response = Response(
        request_id="request-id",
        requested_target=secret_target,
        policy_snapshot=snapshot,
        termination="completed",
        attempts=(attempt,),
    )
    capture = RetainedCapture(url="https://map.example/public-path", response=response)
    outcome = MapOutcome(
        policy_snapshot=snapshot,
        hosts=(),
        pages=(),
        relationships=(),
        frontier=(),
        support_documents=(),
        sources=(),
        tree=(),
        captures=(capture,),
        wildcard_names=(),
        wildcards=(),
        request_trace=(),
        termination=MapTermination(kind="exhausted"),
        omissions=(),
        summary=Summary(
            requests=1,
            provider_concurrency_peak=1,
            page_concurrency_peak=1,
            unused_page_prefetches=0,
            response_bytes=16,
            inventory_bytes=1,
            observations=0,
            omitted=0,
            retained_document_bytes=0,
        ),
    )

    for view in (response, capture, outcome):
        _assert_hidden_from_display(
            view, "secret-response-target", "secret-attempt-target"
        )

    wire = json.dumps(outcome.model_dump(mode="json"))
    assert "secret-response-target" in wire
    assert "secret-attempt-target" in wire
    assert response.requested_target == secret_target
    assert response.attempts[0].requested_target == secret_attempt_target
