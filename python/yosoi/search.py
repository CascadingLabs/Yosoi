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
"""Supported provider-neutral search routes: Brave, Bing, and DuckDuckGo. Selection
does not guarantee provider availability or usable results.
"""


class SearchResultUrl(str):
    """An absolute HTTP(S) destination validated by Rust; no I/O occurs."""

    @classmethod
    def parse(cls, value: str) -> SearchResultUrl:
        """Validate an absolute HTTP(S) destination without fetching it.

        Args:
            value: URL text without embedded credentials.

        Returns:
            A validated string value; validation does not establish destination trust.

        Raises:
            SearchError: The URL is invalid, uses an unsupported scheme, or embeds
                credentials.
        """
        return str.__new__(cls, _native.search_result_url(value))

    def __new__(cls, value: str) -> SearchResultUrl:
        """Construct a URL value using the same validation as parse.

        Args:
            value: Absolute HTTP(S) URL text without embedded credentials.

        Raises:
            SearchError: Rust URL validation rejects the destination.
        """
        return cls.parse(value)

    def as_str(self) -> str:
        """Return validated URL text without performing I/O."""
        return str(self)

    def as_request_target(self) -> str:
        """Return URL text for a later request without sending one."""
        return str(self)

    def __repr__(self) -> str:
        """Return a representation that redacts the destination URL."""
        return "SearchResultUrl(<redacted>)"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: object, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Validate strict string inputs through Rust and serialize as URL text."""
        return core_schema.no_info_after_validator_function(
            cls.parse,
            core_schema.str_schema(strict=True),
            serialization=core_schema.to_string_ser_schema(),
        )


Rank = Annotated[int, Field(ge=1, le=65535, strict=True)]
"""Strict one-based u16 position. Organic rank and provider placement are different
coordinates and can contain gaps.
"""


class SearchHitMetadata(ImmutableModel):
    """Provider-displayed metadata; destination content is not fetched or verified.

    Attributes:
        title: Displayed result title, absent when unavailable.
        snippet: Displayed excerpt, without verification against the destination.
        display_url: Human-readable address, which can differ from the actual
            destination.
        publisher: Displayed publisher label, without independent identity verification.
        published_at: Displayed date text, not a verified publication date.
        thumbnail_url: Validated thumbnail destination; no image fetch is implied.
    """

    title: str | None = Field(default=None, repr=False)
    snippet: str | None = Field(default=None, repr=False)
    display_url: str | None = Field(default=None, repr=False)
    publisher: str | None = Field(default=None, repr=False)
    published_at: str | None = Field(default=None, repr=False)
    thumbnail_url: SearchResultUrl | None = Field(default=None, repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
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
    """An accepted organic result in provider order, with possible rank gaps.

    Attributes:
        url: Validated HTTP(S) destination for an explicit later request.
        organic_rank: One-based organic row rank; rejected or duplicate rows can leave
            gaps.
        placement_index: One-based placement on the provider page, including rich
            features.
        metadata: Optional provider-displayed details, without a destination fetch.
    """

    url: SearchResultUrl = Field(repr=False)
    organic_rank: Rank
    placement_index: Rank
    metadata: SearchHitMetadata = Field(repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
        return (
            "SearchHit("
            f"organic_rank={self.organic_rank!r}, "
            f"placement_index={self.placement_index!r}, "
            "url='<redacted>', ...)"
        )

    __str__ = __repr__

    @property
    def title(self) -> str | None:
        """Return the provider-displayed title, or None when unavailable."""
        return self.metadata.title

    @property
    def snippet(self) -> str | None:
        """Return the provider excerpt without fetching or verifying the destination."""
        return self.metadata.snippet

    @property
    def display_url(self) -> str | None:
        """Return the displayed address, which can differ from the destination."""
        return self.metadata.display_url

    @property
    def publisher(self) -> str | None:
        """Return the unverified provider-displayed publisher label."""
        return self.metadata.publisher

    @property
    def published_at(self) -> str | None:
        """Return displayed date text, not a verified publication date."""
        return self.metadata.published_at

    @property
    def thumbnail_url(self) -> str | None:
        """Return the validated thumbnail destination, without fetching an image."""
        return self.metadata.thumbnail_url


class SearchCoverage(ImmutableModel):
    """Independent extraction coverage for organic results and rich features.

    Attributes:
        web: complete means supported extraction finished; partial means evidence was
            omitted or query recovery was used. Neither proves exhaustive web search.
        rich_features: not_collected means extraction was not attempted; collected can
            include an empty result; partial records incomplete feature evidence.
    """

    web: Literal["complete", "partial"]
    rich_features: Literal["not_collected", "collected", "partial"]


class ImageResult(ImmutableModel):
    """An image destination paired with its reported hosting page.

    Attributes:
        image_url: Validated image destination; no bytes are downloaded by this model.
        source_page_url: Validated source-page destination reported by the provider.
    """

    image_url: SearchResultUrl = Field(repr=False)
    source_page_url: SearchResultUrl = Field(repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
        return "ImageResult(<redacted>)"

    __str__ = __repr__


class LocalPlace(ImmutableModel):
    """A provider-reported local place, without independent business verification.

    Attributes:
        name: Place name displayed by the provider.
        place_url: Validated destination for the place, which has not been fetched.
    """

    name: str = Field(repr=False)
    place_url: SearchResultUrl = Field(repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
        return "LocalPlace(<redacted>)"

    __str__ = __repr__


class Sponsored(ImmutableModel):
    """A provider placement identified as sponsored content, without an organic rank.

    Attributes:
        kind: Discriminator fixed to sponsored for tagged decoding.
        placement_index: One-based position among provider-page placements.
        destination: Validated HTTP(S) destination, without a subsequent fetch.
        label: Provider-displayed sponsorship label, or None when unavailable.
    """

    kind: Literal["sponsored"]
    placement_index: Rank
    destination: SearchResultUrl = Field(repr=False)
    label: str | None = Field(repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
        return f"Sponsored(placement_index={self.placement_index!r}, ...)"

    __str__ = __repr__


class Answer(ImmutableModel):
    """A provider-displayed answer with reported citation destinations.

    Attributes:
        kind: Discriminator fixed to answer for tagged decoding.
        placement_index: One-based position among provider-page placements.
        text: Displayed answer text, without factual verification.
        citations: Validated citation destinations; their contents have not been
            fetched.
    """

    kind: Literal["answer"]
    placement_index: Rank
    text: str = Field(repr=False)
    citations: tuple[SearchResultUrl, ...] = Field(repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
        return (
            f"Answer(placement_index={self.placement_index!r}, "
            f"citation_count={len(self.citations)}, ...)"
        )

    __str__ = __repr__


class ImageGallery(ImmutableModel):
    """A provider-displayed collection of image results, without an organic rank.

    Attributes:
        kind: Discriminator fixed to image_gallery for tagged decoding.
        placement_index: One-based position of the gallery among provider-page
            placements.
        images: Image and source-page destinations extracted from the gallery.
    """

    kind: Literal["image_gallery"]
    placement_index: Rank
    images: tuple[ImageResult, ...] = Field(repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
        return (
            f"ImageGallery(placement_index={self.placement_index!r}, "
            f"image_count={len(self.images)})"
        )

    __str__ = __repr__


class LocalPack(ImmutableModel):
    """A provider-displayed collection of local places and an optional map.

    Attributes:
        kind: Discriminator fixed to local_pack for tagged decoding.
        placement_index: One-based position of the pack among provider-page placements.
        places: Provider-reported places, without independent business verification.
        map_url: Validated map destination, or None when unavailable.
    """

    kind: Literal["local_pack"]
    placement_index: Rank
    places: tuple[LocalPlace, ...] = Field(repr=False)
    map_url: SearchResultUrl | None = Field(repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
        return (
            f"LocalPack(placement_index={self.placement_index!r}, "
            f"place_count={len(self.places)}, ...)"
        )

    __str__ = __repr__


SearchFeature = Annotated[
    Sponsored | Answer | ImageGallery | LocalPack, Field(discriminator="kind")
]
"""Tagged rich placements separate from organic rank: sponsored content, answers, image
galleries, and local packs. Reported destinations are not fetched by these values.
"""


class SearchIssue(ImmutableModel):
    """A bounded structural extraction issue without raw response excerpts.

    Attributes:
        placement_index: One-based affected placement, or None for a response-wide
            issue.
        kind: Classifies invalid or duplicate destinations, missing fields, unrecognized
            rows, output limits, or query relaxation. Inspect coverage before claiming
            completeness.
    """

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
    """Normalized content extracted from one provider response.

    Attributes:
        hits: Accepted organic results in provider order; ranks can contain gaps.
        features: Supported rich placements, independent of organic ranks.
        coverage: Independent organic and rich-feature extraction coverage claims.
        issues: Retained nonfatal issues; configured budgets can bound their count.
    """

    hits: tuple[SearchHit, ...] = Field(repr=False)
    features: tuple[SearchFeature, ...] = Field(repr=False)
    coverage: SearchCoverage
    issues: tuple[SearchIssue, ...] = Field(repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
        return (
            "SearchPage("
            f"hit_count={len(self.hits)}, "
            f"feature_count={len(self.features)}, "
            f"issue_count={len(self.issues)}, "
            f"coverage={self.coverage!r})"
        )

    __str__ = __repr__


class Results(ImmutableModel):
    """Usable normalized provider results whose coverage may still be partial.

    Attributes:
        status: Discriminator fixed to results for tagged decoding.
        value: Normalized provider page; inspect its coverage and issues.
    """

    status: Literal["results"]
    value: SearchPage


class Empty(ImmutableModel):
    """A parsed provider response with no accepted results.

    Attributes:
        status: Discriminator fixed to empty for tagged decoding.
    """

    status: Literal["empty"]


class Failed(ImmutableModel):
    """Started provider work ended without a usable normalized response.

    Attributes:
        status: Discriminator fixed to failed for tagged decoding.
        value: Failure classification: throttling, access challenge, provider
            availability, malformed or off-query content, transport failure, or
            exhausted output budget.
    """

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
    """Started provider work observed caller cancellation without rollback.

    Attributes:
        status: Discriminator fixed to cancelled for tagged decoding.
    """

    status: Literal["cancelled"]


class NotStarted(ImmutableModel):
    """An authored provider slot retained even though no provider Request started.

    Attributes:
        status: Discriminator fixed to not_started for tagged decoding.
        value: Reason execution did not start: uncertified defaults, unavailable
            adapter, unsupported capability, setup failure, cancellation, or deadline.
    """

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
"""Tagged provider result distinguishing usable results, empty response, failure,
observed cancellation, and work that never started.
"""


class ProviderIdentity(ImmutableModel):
    """Provider and adapter identities recorded when an adapter actually ran.

    Attributes:
        provider: Provider selected for this authored policy slot.
        endpoint: Adapter endpoint label, absent when the adapter did not run.
        adapter_version: Adapter implementation version, absent when the adapter did not
            run.
        parser_version: Response parser version, absent when the adapter did not run.
    """

    provider: Provider
    endpoint: str | None
    adapter_version: str | None
    parser_version: str | None


class SearchProfileFacts(ImmutableModel):
    """Content-free route-selection and effective-policy facts for one provider.

    Attributes:
        acquisition: Selected acquisition mechanism, absent when no route resolved.
        defaults_status: Certification state of the defaults used for route selection.
        defaults_version: Package-owned defaults version, absent for routes without such
            defaults.
        effective_request_policy: Resolved Requests policy identity, absent when no
            Request was prepared.
    """

    acquisition: AcquisitionKind | None
    defaults_status: ProviderDefaultsStatus
    defaults_version: int | None
    effective_request_policy: PolicyIdentity | None


class RequestAttemptSummary(ImmutableModel):
    """A bounded summary of an underlying acquisition, including recovery attempts.

    Attributes:
        request_id: Parent Request identity, including a recovery Request.
        capture_id: Identity allocated to this acquisition capture.
        acquisition: Mechanism selected by the resolved policy.
        http_status: Observed HTTP status, absent when none was recorded.
        source_bytes: Exact retained source-artifact byte count, when recorded.
        diagnostic: Typed bounded failure details, absent when none were recorded.
        terminal: Acquisition completed, failed, or never started; completion does not
            establish provider parsing success.
    """

    request_id: str
    capture_id: str
    acquisition: AcquisitionKind
    http_status: int | None
    source_bytes: int | None
    diagnostic: SearchAttemptDiagnostic | None
    terminal: Literal["completed", "failed", "not_started"]


class ChargeAmount(ImmutableModel):
    """Provider-reported monetary amount without conversion or estimation.

    Attributes:
        currency: Provider-reported currency identifier.
        amount: Reported amount retained as text to avoid floating-point rounding.
    """

    currency: str
    amount: str


class ProviderCharge(ImmutableModel):
    """Reported monetary charge facts; unknown is not evidence of zero cost.

    Attributes:
        status: unknown when no charge was reported; known for a reported amount.
        value: Reported amount for a known charge, otherwise None.
    """

    status: Literal["unknown", "known"]
    value: ChargeAmount | None = None


class ProviderResult(ImmutableModel):
    """One selected provider slot, retained in authored policy order.

    Attributes:
        provider: Provider selected for this policy slot.
        identity: Recorded provider and adapter identities.
        profile: Route-selection and effective-policy facts.
        request_id: Underlying Request identity, absent if no Request started.
        recovery_query: Shorter query used for off-query recovery, when attempted; may
            contain user content.
        attempts: Underlying acquisitions, including any recovery Request attempts.
        outcome: Terminal provider interpretation, independent of acquisition success.
        charge: Reported monetary charge facts; unknown does not mean zero.
    """

    provider: Provider
    identity: ProviderIdentity
    profile: SearchProfileFacts
    request_id: str | None
    recovery_query: str | None = Field(repr=False)
    attempts: tuple[RequestAttemptSummary, ...] = Field(repr=False)
    outcome: ProviderOutcome
    charge: ProviderCharge

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
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
        """Return organic hits for a results outcome, otherwise an empty tuple.

        Use outcome to distinguish an empty response from failure, cancellation, or
        unstarted work; this convenience accessor alone cannot establish absence.
        """
        return self.outcome.value.hits if isinstance(self.outcome, Results) else ()


class SearchResponse(ImmutableModel):
    """A cross-provider result retaining failed and unstarted slots.

    Attributes:
        request_id: Identity assigned to the authored search.
        policy_identity: Resolved policy identity used for execution.
        termination: completed means the scheduler finished without observed
            cancellation or deadline; individual providers can still fail. cancelled and
            deadline_reached preserve retained outcomes.
        providers: One result per selected provider in authored policy order, not
            completion order.
    """

    request_id: str
    policy_identity: PolicyIdentity
    termination: Literal["completed", "cancelled", "deadline_reached"]
    providers: tuple[ProviderResult, ...] = Field(repr=False)

    def __repr__(self) -> str:
        """Return structural diagnostics with retained content redacted."""
        return (
            "SearchResponse("
            f"request_id={self.request_id!r}, "
            f"policy_identity={self.policy_identity!r}, "
            f"provider_count={len(self.providers)}, "
            f"termination={self.termination!r})"
        )

    __str__ = __repr__


class SearchRequest(NativeAuthoringModel):
    """Authored query intent backed by Rust, independent of provider selection.

    Attributes:
        query: Original nonblank query of at most 512 UTF-8 bytes. Constructing the
            request validates it without provider I/O.
    """

    query: str = Field(repr=False)
    _handle: _native.SearchRequest = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        """Validate the query in Rust and initialize its immutable native handle."""
        self._handle = _native.SearchRequest(self.query)

    @property
    def id(self) -> str:
        """Return the retained query identity shared by bindings and sends."""
        return self._handle.id

    def bind(self, policy: Policy) -> BoundSearchRequest:
        """Bind this request to a snapshot of the supplied policy without provider I/O.

        Args:
            policy: Complete policy declaration to serialize at binding time.

        Returns:
            A binding unaffected by later edits to the caller policy.
        """
        return BoundSearchRequest(self, policy)

    def check(self) -> None:
        """Validate against package defaults without sending provider requests.

        Raises:
            SearchError: Provider selection, policy resolution, or execution setup is
                invalid.
        """
        self._handle.validate()

    async def send(
        self, *, cancellation: CancellationToken | None = None
    ) -> SearchResponse:
        """Run selected providers with package defaults and retain every provider slot.

        Args:
            cancellation: Optional shared cooperative cancellation token. Completed
                provider outcomes remain available when cancellation is observed.

        Returns:
            Typed response in authored provider order. A completed scheduler can
            contain failed providers or partial extraction; inspect outcomes and
            coverage.

        Raises:
            SearchError: Policy resolution or execution setup fails before a response.
            pydantic.ValidationError: Native response data cannot form a typed result.
        """
        value = await self._handle.send(cancellation=_token(cancellation))
        return SearchResponse.model_validate_json(value)


class BoundSearchRequest:
    """A request with a serialized snapshot of a complete policy declaration.

    Attributes:
        request: Retained query request. Changing the caller policy later does not
            affect this binding.
    """

    def __init__(self, request: SearchRequest, policy: Policy) -> None:
        """Retain the query request and serialize the policy without provider I/O.

        Args:
            request: Authored query request to retain.
            policy: Complete declaration to snapshot for subsequent checks and sends.
        """
        self.request = request
        self._policy_json = policy.to_json()

    @property
    def id(self) -> str:
        """Return the identity of the retained query request."""
        return self.request.id

    @property
    def query(self) -> str:
        """Return the original authored query; it can contain user-sensitive text."""
        return self.request.query

    @property
    def policy(self) -> Policy:
        """Return a policy copy whose edits do not affect this binding."""
        return Policy.model_validate_json(self._policy_json)

    def check(self) -> None:
        """Validate against the bound policy snapshot without sending provider requests.

        Raises:
            SearchError: Provider selection, policy resolution, or execution setup is
                invalid.
        """
        self.request._handle.validate(self._policy_json)

    async def send(
        self, *, cancellation: CancellationToken | None = None
    ) -> SearchResponse:
        """Run providers selected by the bound policy snapshot.

        Args:
            cancellation: Optional cooperative token shared with other operations.
                Observed cancellation retains completed results and unstarted slots.

        Returns:
            Typed response in authored provider order, including failures and partial
            results. Inspect termination separately from each provider outcome.

        Raises:
            SearchError: Policy resolution or execution setup fails before a response.
            pydantic.ValidationError: Native response data cannot form a typed result.
        """
        value = await self.request._handle.send(self._policy_json, _token(cancellation))
        return SearchResponse.model_validate_json(value)


def new(query: str) -> SearchRequest:
    """Author a search request without provider I/O.

    Args:
        query: Original nonblank query, limited to 512 UTF-8 bytes.

    Returns:
        A request with a fresh activity identity and package-default behavior until
        bound.

    Raises:
        pydantic.ValidationError: The query is not a string.
        SearchError: The query is blank or exceeds the Rust UTF-8 byte limit.
    """
    return SearchRequest(query=query)
