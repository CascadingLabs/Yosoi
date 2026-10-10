"""Provider-neutral Search forwards intent to Rust and keeps every provider slot."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, GetCoreSchemaHandler, PrivateAttr
from pydantic_core import CoreSchema, core_schema

from . import _native
from ._models import ImmutableModel, NativeAuthoringModel
from .cancellation import CancellationToken
from .diagnostics import SearchAttemptDiagnostic as SearchAttemptDiagnostic
from .policy import AcquisitionKind, Policy, PolicyIdentity, ProviderDefaultsStatus
from .request import _token

Provider = Literal["brave", "bing", "duck_duck_go"]


class SearchResultUrl(str):
    """An absolute HTTP(S) destination validated by Rust; no I/O occurs."""

    @classmethod
    def parse(cls, value: str) -> SearchResultUrl:
        return str.__new__(cls, _native.search_result_url(value))

    def __new__(cls, value: str) -> SearchResultUrl:
        return cls.parse(value)

    def as_str(self) -> str:
        return str(self)

    def as_request_target(self) -> str:
        return str(self)

    def __repr__(self) -> str:
        return "SearchResultUrl(<redacted>)"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: object, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.parse,
            core_schema.str_schema(strict=True),
            serialization=core_schema.to_string_ser_schema(),
        )


Rank = Annotated[int, Field(ge=1, le=65535, strict=True)]


class SearchHitMetadata(ImmutableModel):
    title: str | None = Field(default=None, repr=False)
    snippet: str | None = Field(default=None, repr=False)
    display_url: str | None = Field(default=None, repr=False)
    publisher: str | None = Field(default=None, repr=False)
    published_at: str | None = Field(default=None, repr=False)
    thumbnail_url: SearchResultUrl | None = Field(default=None, repr=False)

    def __repr__(self) -> str:
        return (
            "SearchHitMetadata("
            f"title_present={self.title is not None}, "
            f"snippet_present={self.snippet is not None}, "
            f"display_url_present={self.display_url is not None}, "
            f"publisher_present={self.publisher is not None}, "
            f"published_at_present={self.published_at is not None}, "
            f"thumbnail_present={self.thumbnail_url is not None})"
        )

    __str__ = __repr__


class SearchHit(ImmutableModel):
    url: SearchResultUrl = Field(repr=False)
    organic_rank: Rank
    placement_index: Rank
    metadata: SearchHitMetadata = Field(repr=False)

    def __repr__(self) -> str:
        return (
            "SearchHit("
            f"organic_rank={self.organic_rank!r}, "
            f"placement_index={self.placement_index!r}, "
            "url='<redacted>', ...)"
        )

    __str__ = __repr__

    @property
    def title(self) -> str | None:
        return self.metadata.title

    @property
    def snippet(self) -> str | None:
        return self.metadata.snippet

    @property
    def display_url(self) -> str | None:
        return self.metadata.display_url

    @property
    def publisher(self) -> str | None:
        return self.metadata.publisher

    @property
    def published_at(self) -> str | None:
        return self.metadata.published_at

    @property
    def thumbnail_url(self) -> str | None:
        return self.metadata.thumbnail_url


class SearchCoverage(ImmutableModel):
    web: Literal["complete", "partial"]
    rich_features: Literal["not_collected", "collected", "partial"]


class ImageResult(ImmutableModel):
    image_url: SearchResultUrl = Field(repr=False)
    source_page_url: SearchResultUrl = Field(repr=False)

    def __repr__(self) -> str:
        return "ImageResult(<redacted>)"

    __str__ = __repr__


class LocalPlace(ImmutableModel):
    name: str = Field(repr=False)
    place_url: SearchResultUrl = Field(repr=False)

    def __repr__(self) -> str:
        return "LocalPlace(<redacted>)"

    __str__ = __repr__


class Sponsored(ImmutableModel):
    kind: Literal["sponsored"]
    placement_index: Rank
    destination: SearchResultUrl = Field(repr=False)
    label: str | None = Field(repr=False)

    def __repr__(self) -> str:
        return f"Sponsored(placement_index={self.placement_index!r}, ...)"

    __str__ = __repr__


class Answer(ImmutableModel):
    kind: Literal["answer"]
    placement_index: Rank
    text: str = Field(repr=False)
    citations: tuple[SearchResultUrl, ...] = Field(repr=False)

    def __repr__(self) -> str:
        return (
            f"Answer(placement_index={self.placement_index!r}, "
            f"citation_count={len(self.citations)}, ...)"
        )

    __str__ = __repr__


class ImageGallery(ImmutableModel):
    kind: Literal["image_gallery"]
    placement_index: Rank
    images: tuple[ImageResult, ...] = Field(repr=False)

    def __repr__(self) -> str:
        return (
            f"ImageGallery(placement_index={self.placement_index!r}, "
            f"image_count={len(self.images)})"
        )

    __str__ = __repr__


class LocalPack(ImmutableModel):
    kind: Literal["local_pack"]
    placement_index: Rank
    places: tuple[LocalPlace, ...] = Field(repr=False)
    map_url: SearchResultUrl | None = Field(repr=False)

    def __repr__(self) -> str:
        return (
            f"LocalPack(placement_index={self.placement_index!r}, "
            f"place_count={len(self.places)}, ...)"
        )

    __str__ = __repr__


SearchFeature = Annotated[
    Sponsored | Answer | ImageGallery | LocalPack, Field(discriminator="kind")
]


class SearchIssue(ImmutableModel):
    placement_index: Rank | None
    kind: Literal[
        "invalid_destination",
        "duplicate_destination",
        "missing_required_field",
        "unrecognized_result_row",
        "output_limit",
        "query_relaxed",
    ]


class SearchPage(ImmutableModel):
    hits: tuple[SearchHit, ...] = Field(repr=False)
    features: tuple[SearchFeature, ...] = Field(repr=False)
    coverage: SearchCoverage
    issues: tuple[SearchIssue, ...] = Field(repr=False)

    def __repr__(self) -> str:
        return (
            "SearchPage("
            f"hit_count={len(self.hits)}, "
            f"feature_count={len(self.features)}, "
            f"issue_count={len(self.issues)}, "
            f"coverage={self.coverage!r})"
        )

    __str__ = __repr__


class Results(ImmutableModel):
    status: Literal["results"]
    value: SearchPage


class Empty(ImmutableModel):
    status: Literal["empty"]


class Failed(ImmutableModel):
    status: Literal["failed"]
    value: Literal[
        "rate_limited",
        "challenge",
        "provider_unavailable",
        "malformed_response",
        "query_mismatch",
        "transport_failure",
        "budget_exhausted",
    ]


class Cancelled(ImmutableModel):
    status: Literal["cancelled"]


class NotStarted(ImmutableModel):
    status: Literal["not_started"]
    value: Literal[
        "default_uncertified",
        "adapter_unavailable",
        "unsupported_capability",
        "request_setup_failed",
        "cancelled",
        "deadline_reached",
    ]


ProviderOutcome = Annotated[
    Results | Empty | Failed | Cancelled | NotStarted, Field(discriminator="status")
]


class ProviderIdentity(ImmutableModel):
    provider: Provider
    endpoint: str | None
    adapter_version: str | None
    parser_version: str | None


class SearchProfileFacts(ImmutableModel):
    acquisition: AcquisitionKind | None
    defaults_status: ProviderDefaultsStatus
    defaults_version: int | None
    effective_request_policy: PolicyIdentity | None


class RequestAttemptSummary(ImmutableModel):
    request_id: str
    capture_id: str
    acquisition: AcquisitionKind
    http_status: int | None
    source_bytes: int | None
    diagnostic: SearchAttemptDiagnostic | None
    terminal: Literal["completed", "failed", "not_started"]


class ChargeAmount(ImmutableModel):
    currency: str
    amount: str


class ProviderCharge(ImmutableModel):
    status: Literal["unknown", "known"]
    value: ChargeAmount | None = None


class ProviderResult(ImmutableModel):
    provider: Provider
    identity: ProviderIdentity
    profile: SearchProfileFacts
    request_id: str | None
    recovery_query: str | None = Field(repr=False)
    attempts: tuple[RequestAttemptSummary, ...] = Field(repr=False)
    outcome: ProviderOutcome
    charge: ProviderCharge

    def __repr__(self) -> str:
        return (
            "ProviderResult("
            f"identity={self.identity!r}, "
            f"profile={self.profile!r}, "
            f"request_id={self.request_id!r}, "
            f"recovery_attempted={self.recovery_query is not None}, "
            f"attempt_count={len(self.attempts)}, "
            f"outcome={self.outcome!r}, "
            f"charge={self.charge!r})"
        )

    __str__ = __repr__

    @property
    def hits(self) -> tuple[SearchHit, ...]:
        return self.outcome.value.hits if isinstance(self.outcome, Results) else ()


class SearchResponse(ImmutableModel):
    request_id: str
    policy_identity: PolicyIdentity
    termination: Literal["completed", "cancelled", "deadline_reached"]
    providers: tuple[ProviderResult, ...] = Field(repr=False)

    def __repr__(self) -> str:
        return (
            "SearchResponse("
            f"request_id={self.request_id!r}, "
            f"policy_identity={self.policy_identity!r}, "
            f"provider_count={len(self.providers)}, "
            f"termination={self.termination!r})"
        )

    __str__ = __repr__


class SearchRequest(NativeAuthoringModel):
    query: str = Field(repr=False)
    _handle: _native.SearchRequest = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        self._handle = _native.SearchRequest(self.query)

    @property
    def id(self) -> str:
        return self._handle.id

    def bind(self, policy: Policy) -> BoundSearchRequest:
        return BoundSearchRequest(self, policy)

    def check(self) -> None:
        self._handle.validate()

    async def send(
        self, *, cancellation: CancellationToken | None = None
    ) -> SearchResponse:
        value = await self._handle.send(cancellation=_token(cancellation))
        return SearchResponse.model_validate_json(value)


class BoundSearchRequest:
    def __init__(self, request: SearchRequest, policy: Policy) -> None:
        self.request = request
        self._policy_json = policy.to_json()

    @property
    def id(self) -> str:
        return self.request.id

    @property
    def query(self) -> str:
        return self.request.query

    @property
    def policy(self) -> Policy:
        return Policy.model_validate_json(self._policy_json)

    def check(self) -> None:
        self.request._handle.validate(self._policy_json)

    async def send(
        self, *, cancellation: CancellationToken | None = None
    ) -> SearchResponse:
        value = await self.request._handle.send(self._policy_json, _token(cancellation))
        return SearchResponse.model_validate_json(value)


def new(query: str) -> SearchRequest:
    return SearchRequest(query=query)
