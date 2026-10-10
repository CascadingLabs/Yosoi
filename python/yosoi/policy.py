"""Typed policy authoring with Rust-owned defaults and validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, Field, model_serializer, model_validator

from . import _native
from ._models import ImmutableModel, Model
from .scalars import (
    AccessibilityNodeLimit,
    AddressableByteLimit,
    Budget,
    CountLimit,
    EventLimit,
    MaximumElapsed,
    ProviderDefaultsVersion,
    RedirectHopLimit,
    ResourceLimit,
    StepLimit,
)

U16 = Annotated[int, Field(strict=True, ge=0, le=(1 << 16) - 1)]
U64 = Annotated[int, Field(strict=True, ge=0, le=(1 << 64) - 1)]
PositiveU16 = Annotated[int, Field(strict=True, gt=0, le=(1 << 16) - 1)]
PositiveU32 = Annotated[int, Field(strict=True, gt=0, le=(1 << 32) - 1)]
PositiveU64 = Annotated[int, Field(strict=True, gt=0, le=(1 << 64) - 1)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]

DocumentRequest = Literal[
    "response_document", "rendered_dom", "accessibility_tree", "network_tree"
]
DocumentSelectionKind = Literal["current", "exact"]
BrowserMode = Literal["headless", "headful"]
DirectHttpRedirectTargets = Literal["allow_http_and_https", "same_origin"]
DiscoveryDocuments = Literal["discard_after_inspection", "retain_within_budget"]
HostScope = Literal["seed_host", "registrable_domain"]
PathScope = Literal["seed_subtree", "entire_origin"]
PageDiscovery = Literal["disabled", "explore"]
Robots = Literal["ignore", "respect"]
Subdomains = Literal["disabled", "passive"]
TuningMode = Literal["default"]
ProfileSelectionKind = Literal["current", "exact"]


def _scalar_validator[IntegerScalar: int](
    scalar: type[IntegerScalar],
) -> Callable[[int], IntegerScalar]:
    def validate(value: int) -> IntegerScalar:
        try:
            return scalar(value)
        except _native.PolicyError as error:
            raise ValueError(str(error)) from error

    return validate


CountLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(CountLimit))
]
StepLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(StepLimit))
]
AddressableByteLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(AddressableByteLimit))
]
EventLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(EventLimit))
]
ResourceLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(ResourceLimit))
]
AccessibilityNodeLimitValue = Annotated[
    int,
    Field(strict=True),
    AfterValidator(_scalar_validator(AccessibilityNodeLimit)),
]
MaximumElapsedValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(MaximumElapsed))
]
RedirectHopLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(RedirectHopLimit))
]
BudgetValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(Budget))
]


def _field(*path: str) -> Any:
    def default() -> Any:
        value = json.loads(_native.default_policy())
        for key in path:
            value = value[key]
        return value

    return Field(default_factory=default)


def _rust_component(
    kind: str,
    component_json: str | None,
    operation: str,
    arguments: Any | None = None,
) -> Any:
    arguments_json = (
        None if arguments is None else json.dumps(arguments, separators=(",", ":"))
    )
    return json.loads(
        _native.policy_component(kind, component_json, operation, arguments_json)
    )


class DocumentSelection(Model):
    kind: DocumentSelectionKind = "current"
    documents: (
        Annotated[
            tuple[
                DocumentRequest,
                ...,
            ],
            Field(max_length=4),
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def _validate_variant(self) -> Self:
        if (self.kind == "current") != (self.documents is None):
            raise ValueError("document selection fields do not match its kind")
        return self


class Acquisition(Model):
    kind: Literal["direct_http", "browser"] = "direct_http"
    mode: BrowserMode | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    documents: DocumentSelection = Field(default_factory=DocumentSelection)

    @model_validator(mode="after")
    def _validate_variant(self) -> Self:
        if self.kind == "browser" and self.mode is None:
            raise ValueError("browser acquisition requires a mode")
        if self.kind == "direct_http" and self.mode is not None:
            raise ValueError("direct HTTP acquisition does not accept a mode")
        if self.kind == "direct_http" and self.documents.documents not in (
            None,
            (),
            ("response_document",),
        ):
            raise ValueError("direct HTTP supports only the response document")
        return self

    @classmethod
    def direct_http(cls) -> Self:
        return cls()

    @classmethod
    def browser(cls, mode: Literal["headless", "headful"] = "headless") -> Self:
        return cls(kind="browser", mode=mode)

    def with_documents(self, documents: list[str] | tuple[str, ...]) -> Self:
        value = _rust_component(
            "acquisition",
            self.model_dump_json(exclude_none=True),
            "with_documents",
            documents,
        )
        return type(self).model_validate(value)

    @property
    def exact_documents(self) -> tuple[str, ...] | None:
        value = _rust_component(
            "acquisition",
            self.model_dump_json(exclude_none=True),
            "exact_documents",
        )
        return None if value is None else tuple(value)

    @property
    def selection_kind(self) -> Literal["current", "exact"]:
        return _rust_component(
            "acquisition",
            self.model_dump_json(exclude_none=True),
            "selection_kind",
        )


class Page(Model):
    acquisitions: Annotated[list[Acquisition], Field(max_length=3)] = _field(
        "page", "acquisitions"
    )


class SourceLimits(Model):
    content_coded_bytes: AddressableByteLimitValue = _field(
        "request", "source", "content_coded_bytes"
    )
    representation_bytes: AddressableByteLimitValue = _field(
        "request", "source", "representation_bytes"
    )
    unicode_utf8_bytes: AddressableByteLimitValue = _field(
        "request", "source", "unicode_utf8_bytes"
    )


class BrowserLimits(Model):
    dom_utf8_bytes: AddressableByteLimitValue = _field(
        "request", "browser", "dom_utf8_bytes"
    )
    ax_json_utf8_bytes: AddressableByteLimitValue = _field(
        "request", "browser", "ax_json_utf8_bytes"
    )
    max_events: EventLimitValue = _field("request", "browser", "max_events")
    max_resources: ResourceLimitValue = _field("request", "browser", "max_resources")
    max_accessibility_nodes: AccessibilityNodeLimitValue = _field(
        "request", "browser", "max_accessibility_nodes"
    )


class Redirects(Model):
    kind: Literal["disabled", "follow"]
    max_hops: RedirectHopLimitValue | None = None
    targets: DirectHttpRedirectTargets | None = None

    @classmethod
    def default(cls) -> Self:
        return cls.model_validate_json(
            _native.validate_domain_model("direct_http_redirects_default", "null")
        )

    @model_validator(mode="after")
    def _validate_variant(self) -> Self:
        if self.kind == "disabled" and (
            self.max_hops is not None or self.targets is not None
        ):
            raise ValueError("disabled redirects do not accept follow settings")
        if self.kind == "follow" and (self.max_hops is None or self.targets is None):
            raise ValueError("follow redirects require hop and target settings")
        return self


class Request(Model):
    maximum_elapsed: MaximumElapsedValue = _field("request", "maximum_elapsed")
    source: SourceLimits = _field("request", "source")
    browser: BrowserLimits = _field("request", "browser")
    direct_http_redirects: Redirects = _field("request", "direct_http_redirects")


class Documents(Model):
    max_input_bytes: AddressableByteLimitValue = _field("documents", "max_input_bytes")
    max_nodes: CountLimitValue = _field("documents", "max_nodes")
    max_depth: StepLimitValue = _field("documents", "max_depth")


class Locators(Model):
    max_selector_visits: CountLimitValue = _field("locators", "max_selector_visits")
    max_query_bytes: AddressableByteLimitValue = _field("locators", "max_query_bytes")
    max_query_steps: StepLimitValue = _field("locators", "max_query_steps")
    max_regions: StepLimitValue = _field("locators", "max_regions")
    max_matches: CountLimitValue = _field("locators", "max_matches")
    max_captures: CountLimitValue = _field("locators", "max_captures")
    max_output_bytes: AddressableByteLimitValue = _field("locators", "max_output_bytes")


class Duration(Model):
    seconds: U64
    nanoseconds: Annotated[int, Field(strict=True, ge=0, lt=1_000_000_000)] = 0


class Scope(Model):
    hosts: HostScope = _field("map", "scope", "hosts")
    paths: PathScope = _field("map", "scope", "paths")


class MapLimits(Model):
    max_link_depth: U16 = _field("map", "limits", "max_link_depth")
    max_hosts: BudgetValue = _field("map", "limits", "max_hosts")
    max_urls: BudgetValue = _field("map", "limits", "max_urls")
    max_relationships: BudgetValue = _field("map", "limits", "max_relationships")
    max_observations: BudgetValue = _field("map", "limits", "max_observations")
    max_pending: BudgetValue = _field("map", "limits", "max_pending")
    max_requests: BudgetValue = _field("map", "limits", "max_requests")
    max_sitemaps: BudgetValue = _field("map", "limits", "max_sitemaps")
    max_sitemap_depth: U16 = _field("map", "limits", "max_sitemap_depth")
    max_response_bytes: BudgetValue = _field("map", "limits", "max_response_bytes")
    max_total_response_bytes: BudgetValue = _field(
        "map", "limits", "max_total_response_bytes"
    )
    max_retained_document_bytes: BudgetValue = _field(
        "map", "limits", "max_retained_document_bytes"
    )
    max_concurrency: BudgetValue = _field("map", "limits", "max_concurrency")
    maximum_elapsed: Duration = _field("map", "limits", "maximum_elapsed")
    max_url_bytes: BudgetValue = _field("map", "limits", "max_url_bytes")
    max_inventory_bytes: BudgetValue = _field("map", "limits", "max_inventory_bytes")
    max_parser_entries: BudgetValue = _field("map", "limits", "max_parser_entries")
    max_hostname_bytes: BudgetValue = _field("map", "limits", "max_hostname_bytes")


class Filters(Model):
    excluded_query_keys: list[str] = _field("map", "filters", "excluded_query_keys")
    excluded_path_prefixes: list[str] = _field(
        "map", "filters", "excluded_path_prefixes"
    )

    def check(self) -> None:
        _rust_component("filters", self.model_dump_json(exclude_none=True), "validate")


class Map(Model):
    scope: Scope = _field("map", "scope")
    pages: PageDiscovery = _field("map", "pages")
    robots: Robots = _field("map", "robots")
    subdomains: Subdomains = _field("map", "subdomains")
    limits: MapLimits = _field("map", "limits")
    documents: DiscoveryDocuments = _field("map", "documents")
    filters: Filters = _field("map", "filters")

    def check(self) -> None:
        _rust_component("map", self.model_dump_json(exclude_none=True), "validate")


class ProviderRequestProfile(Model):
    page: Page = Field(default_factory=Page)
    request: Request = Field(default_factory=Request)
    documents: Documents = Field(default_factory=Documents)


class ProfileSelection(Model):
    kind: ProfileSelectionKind = "current"
    profile: ProviderRequestProfile | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def _validate_variant(self) -> Self:
        if (self.kind == "current") != (self.profile is None):
            raise ValueError("profile selection fields do not match its kind")
        return self


class Provider(StrEnum):
    brave = "brave"
    bing = "bing"
    duck_duck_go = "duck_duck_go"

    def defaults_status(self) -> ProviderDefaultsStatus:
        value = _rust_component("provider", json.dumps(self.value), "defaults_status")
        return ProviderDefaultsStatus.model_validate(value)


class ProviderSelection(Model):
    provider: Provider
    profile: ProfileSelection = Field(default_factory=ProfileSelection)

    @classmethod
    def current(cls, provider: Provider | str) -> Self:
        value = _rust_component(
            "provider_selection",
            None,
            "current",
            {"provider": str(provider)},
        )
        return cls.model_validate(value)

    @classmethod
    def exact(cls, provider: Provider | str, profile: ProviderRequestProfile) -> Self:
        value = _rust_component(
            "provider_selection",
            None,
            "exact",
            {
                "provider": str(provider),
                "profile": profile.model_dump(mode="json", exclude_none=True),
            },
        )
        return cls.model_validate(value)


class Search(Model):
    providers: Annotated[list[ProviderSelection], Field(max_length=3)] = _field(
        "search", "providers"
    )
    max_in_flight: PositiveInt = _field("search", "max_in_flight")
    max_browser_in_flight: PositiveInt = _field("search", "max_browser_in_flight")
    max_results_per_provider: PositiveU16 = _field("search", "max_results_per_provider")
    max_total_results: PositiveU32 = _field("search", "max_total_results")
    max_retained_content_bytes: AddressableByteLimitValue = _field(
        "search", "max_retained_content_bytes"
    )
    maximum_elapsed: MaximumElapsedValue = _field("search", "maximum_elapsed")

    @classmethod
    def disabled(cls) -> Self:
        return cls.model_validate(_rust_component("search", None, "disabled"))

    def is_enabled(self) -> bool:
        return _rust_component(
            "search", self.model_dump_json(exclude_none=True), "is_enabled"
        )

    def with_max_in_flight(self, value: int) -> Self:
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_max_in_flight",
                value,
            )
        )

    def with_max_browser_in_flight(self, value: int) -> Self:
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_max_browser_in_flight",
                value,
            )
        )

    def per_provider_limit(self, value: int) -> Self:
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "per_provider_limit",
                value,
            )
        )

    def with_result_limits(self, per_provider: int, total: int) -> Self:
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_result_limits",
                {"per_provider": per_provider, "total": total},
            )
        )

    def with_max_total_results(self, value: int) -> Self:
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_max_total_results",
                value,
            )
        )

    def with_max_retained_content_bytes(self, value: int) -> Self:
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_max_retained_content_bytes",
                value,
            )
        )

    def with_maximum_elapsed(self, value: int) -> Self:
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_maximum_elapsed",
                value,
            )
        )


class Tuning(Model):
    mode: TuningMode = "default"

    def is_default(self) -> bool:
        return _rust_component("tuning", self.model_dump_json(), "is_default")


class PolicyIdentity(ImmutableModel):
    version: PositiveU16
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AcquisitionKind(ImmutableModel):
    kind: Literal["direct_http", "browser"]
    mode: Literal["headless", "headful"] | None = None

    @model_validator(mode="after")
    def _validate_variant(self) -> Self:
        if (self.kind == "browser") != (self.mode is not None):
            raise ValueError("acquisition kind fields do not match its kind")
        return self


class EffectiveAcquisition(ImmutableModel):
    acquisition: AcquisitionKind
    authored_selection: Literal["current", "exact"]
    documents: tuple[
        Literal[
            "response_document", "rendered_dom", "accessibility_tree", "network_tree"
        ],
        ...,
    ]


class EffectivePage(ImmutableModel):
    acquisitions: tuple[EffectiveAcquisition, ...]


class ProviderDefaultsStatus(ImmutableModel):
    status: Literal["unavailable", "preview", "certified", "exact"]
    registry_version: U16 | None = None
    version: ProviderDefaultsVersion | None = None

    @model_validator(mode="after")
    def _validate_variant(self) -> Self:
        valid = {
            "unavailable": self.registry_version is not None and self.version is None,
            "preview": self.registry_version is None and self.version is not None,
            "certified": self.registry_version is None and self.version is not None,
            "exact": self.registry_version is None and self.version is None,
        }[self.status]
        if not valid:
            raise ValueError("provider defaults fields do not match its status")
        return self


class EffectiveProviderRoute(ImmutableModel):
    provider: Provider
    profile: ProviderRequestProfile | None
    profile_selection_kind: Literal["current", "exact"]
    defaults_status: ProviderDefaultsStatus

    @property
    def page(self) -> Page | None:
        value = _rust_component(
            "effective_provider_route",
            self.model_dump_json(exclude_none=True),
            "page",
        )
        return None if value is None else Page.model_validate(value)

    @property
    def request(self) -> Request | None:
        value = _rust_component(
            "effective_provider_route",
            self.model_dump_json(exclude_none=True),
            "request",
        )
        return None if value is None else Request.model_validate(value)

    @property
    def documents(self) -> Documents | None:
        value = _rust_component(
            "effective_provider_route",
            self.model_dump_json(exclude_none=True),
            "documents",
        )
        return None if value is None else Documents.model_validate(value)

    @property
    def defaults_version(self) -> ProviderDefaultsVersion | None:
        value = _rust_component(
            "effective_provider_route",
            self.model_dump_json(exclude_none=True),
            "defaults_version",
        )
        return None if value is None else ProviderDefaultsVersion(value)


class EffectiveSearch(ImmutableModel):
    providers: tuple[EffectiveProviderRoute, ...]
    max_in_flight: PositiveInt
    max_browser_in_flight: PositiveInt
    max_results_per_provider: PositiveU16
    max_total_results: PositiveU32
    max_retained_content_bytes: AddressableByteLimit
    maximum_elapsed: MaximumElapsed


class EffectivePolicy(ImmutableModel):
    page: EffectivePage
    request: Request
    documents: Documents
    locators: Locators
    tuning: Tuning
    map: Map
    search: EffectiveSearch


class Policy(Model):
    page: Page = _field("page")
    request: Request = _field("request")
    documents: Documents = _field("documents")
    locators: Locators = _field("locators")
    tuning: Tuning = Field(default_factory=Tuning)
    map: Map = _field("map")
    search: Search = _field("search")

    @model_validator(mode="after")
    def _validate_in_rust(self) -> Self:
        try:
            self.check()
        except _native.PolicyError as error:
            raise ValueError(str(error)) from error
        return self

    def check(self) -> None:
        """Validate this declaration in Rust, including later edits."""
        _native.validate_policy(self.model_dump_json(exclude_none=True))

    def to_json(self) -> str:
        """Return a Rust-validated declaration, including edits to nested models."""
        return _native.validate_policy(self.model_dump_json(exclude_none=True))

    def identity(self) -> PolicyIdentity:
        return PolicyIdentity.model_validate_json(
            _native.policy_identity(self.to_json())
        )

    def effective_policy(self) -> EffectivePolicy:
        """Return Current selections resolved by the Rust policy registry."""
        return EffectivePolicy.model_validate_json(
            _native.effective_policy(self.to_json())
        )

    def snapshot(self) -> PolicySnapshot:
        """Return the immutable Rust-validated declaration and behavior."""
        return PolicySnapshot.from_policy(self)


class _SnapshotDocumentSelection(ImmutableModel):
    kind: Literal["current", "exact"]
    documents: (
        tuple[
            Literal[
                "response_document",
                "rendered_dom",
                "accessibility_tree",
                "network_tree",
            ],
            ...,
        ]
        | None
    ) = None


class _SnapshotAcquisition(ImmutableModel):
    kind: Literal["direct_http", "browser"]
    mode: Literal["headless", "headful"] | None = None
    documents: _SnapshotDocumentSelection


class _SnapshotPage(ImmutableModel):
    acquisitions: tuple[_SnapshotAcquisition, ...]


class _SnapshotSourceLimits(ImmutableModel):
    content_coded_bytes: AddressableByteLimit
    representation_bytes: AddressableByteLimit
    unicode_utf8_bytes: AddressableByteLimit


class _SnapshotBrowserLimits(ImmutableModel):
    dom_utf8_bytes: AddressableByteLimit
    ax_json_utf8_bytes: AddressableByteLimit
    max_events: EventLimit
    max_resources: ResourceLimit
    max_accessibility_nodes: AccessibilityNodeLimit


class _SnapshotRedirects(ImmutableModel):
    kind: Literal["disabled", "follow"]
    max_hops: RedirectHopLimit | None = None
    targets: Literal["allow_http_and_https", "same_origin"] | None = None


class _SnapshotRequest(ImmutableModel):
    maximum_elapsed: MaximumElapsed
    source: _SnapshotSourceLimits
    browser: _SnapshotBrowserLimits
    direct_http_redirects: _SnapshotRedirects


class _SnapshotDocuments(ImmutableModel):
    max_input_bytes: AddressableByteLimit
    max_nodes: CountLimit
    max_depth: StepLimit


class _SnapshotLocators(ImmutableModel):
    max_selector_visits: CountLimit
    max_query_bytes: AddressableByteLimit
    max_query_steps: StepLimit
    max_regions: StepLimit
    max_matches: CountLimit
    max_captures: CountLimit
    max_output_bytes: AddressableByteLimit


class _SnapshotDuration(ImmutableModel):
    seconds: U64
    nanoseconds: Annotated[int, Field(strict=True, ge=0, lt=1_000_000_000)]


class _SnapshotScope(ImmutableModel):
    hosts: Literal["seed_host", "registrable_domain"]
    paths: Literal["seed_subtree", "entire_origin"]


class _SnapshotMapLimits(ImmutableModel):
    max_link_depth: U16
    max_hosts: Budget
    max_urls: Budget
    max_relationships: Budget
    max_observations: Budget
    max_pending: Budget
    max_requests: Budget
    max_sitemaps: Budget
    max_sitemap_depth: U16
    max_response_bytes: Budget
    max_total_response_bytes: Budget
    max_retained_document_bytes: Budget
    max_concurrency: Budget
    maximum_elapsed: _SnapshotDuration
    max_url_bytes: Budget
    max_inventory_bytes: Budget
    max_parser_entries: Budget
    max_hostname_bytes: Budget


class _SnapshotFilters(ImmutableModel):
    excluded_query_keys: tuple[str, ...]
    excluded_path_prefixes: tuple[str, ...]


class _SnapshotMap(ImmutableModel):
    scope: _SnapshotScope
    pages: Literal["disabled", "explore"]
    robots: Literal["ignore", "respect"]
    subdomains: Literal["disabled", "passive"]
    limits: _SnapshotMapLimits
    documents: Literal["discard_after_inspection", "retain_within_budget"]
    filters: _SnapshotFilters


class _SnapshotTuning(ImmutableModel):
    mode: Literal["default"] = "default"


class _SnapshotProviderRequestProfile(ImmutableModel):
    page: _SnapshotPage
    request: _SnapshotRequest
    documents: _SnapshotDocuments


class _SnapshotProfileSelection(ImmutableModel):
    kind: Literal["current", "exact"]
    profile: _SnapshotProviderRequestProfile | None = None


class _SnapshotProviderSelection(ImmutableModel):
    provider: Literal["brave", "bing", "duck_duck_go"]
    profile: _SnapshotProfileSelection


class _SnapshotSearch(ImmutableModel):
    providers: tuple[_SnapshotProviderSelection, ...]
    max_in_flight: PositiveInt
    max_browser_in_flight: PositiveInt
    max_results_per_provider: PositiveU16
    max_total_results: PositiveU32
    max_retained_content_bytes: AddressableByteLimit
    maximum_elapsed: MaximumElapsed


class _SnapshotPolicy(ImmutableModel):
    page: _SnapshotPage
    request: _SnapshotRequest
    documents: _SnapshotDocuments
    locators: _SnapshotLocators
    tuning: _SnapshotTuning = Field(default_factory=_SnapshotTuning)
    map: _SnapshotMap
    search: _SnapshotSearch

    @model_serializer(mode="wrap")
    def _omit_default_tuning(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if self.tuning.mode == "default":
            data.pop("tuning", None)
        return data


class _SnapshotEffectiveAcquisition(ImmutableModel):
    acquisition: AcquisitionKind
    authored_selection: Literal["current", "exact"]
    documents: tuple[
        Literal[
            "response_document", "rendered_dom", "accessibility_tree", "network_tree"
        ],
        ...,
    ]


class _SnapshotEffectivePage(ImmutableModel):
    acquisitions: tuple[_SnapshotEffectiveAcquisition, ...]


class _SnapshotEffectiveProviderRoute(ImmutableModel):
    provider: Literal["brave", "bing", "duck_duck_go"]
    profile: _SnapshotProviderRequestProfile | None
    profile_selection_kind: Literal["current", "exact"]
    defaults_status: ProviderDefaultsStatus


class _SnapshotEffectiveSearch(ImmutableModel):
    providers: tuple[_SnapshotEffectiveProviderRoute, ...]
    max_in_flight: PositiveInt
    max_browser_in_flight: PositiveInt
    max_results_per_provider: PositiveU16
    max_total_results: PositiveU32
    max_retained_content_bytes: AddressableByteLimit
    maximum_elapsed: MaximumElapsed


class _SnapshotEffectivePolicy(ImmutableModel):
    page: _SnapshotEffectivePage
    request: _SnapshotRequest
    documents: _SnapshotDocuments
    locators: _SnapshotLocators
    tuning: _SnapshotTuning
    map: _SnapshotMap
    search: _SnapshotEffectiveSearch


class PolicySnapshot(ImmutableModel):
    """An immutable, deeply frozen Rust-validated declaration and resolution."""

    policy: _SnapshotPolicy
    effective_policy: _SnapshotEffectivePolicy
    identity: PolicyIdentity

    @classmethod
    def from_policy(cls, policy: Policy) -> Self:
        return cls.model_validate_json(_native.policy_snapshot(policy.to_json()))
