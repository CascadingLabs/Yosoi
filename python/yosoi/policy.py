"""Typed policy authoring with Rust-owned defaults and validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StrictBool,
    model_serializer,
    model_validator,
)

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
"""Strict integer from zero through the u16 maximum. Numeric strings, booleans, and
floats are not coerced.
"""
U64 = Annotated[int, Field(strict=True, ge=0, le=(1 << 64) - 1)]
"""Strict integer from zero through the u64 maximum; units depend on the consuming
field.
"""
PositiveU16 = Annotated[int, Field(strict=True, gt=0, le=(1 << 16) - 1)]
"""Strict positive u16 integer; zero and numeric coercions are rejected."""
PositiveU32 = Annotated[int, Field(strict=True, gt=0, le=(1 << 32) - 1)]
"""Strict positive u32 integer; zero and numeric coercions are rejected."""
PositiveU64 = Annotated[int, Field(strict=True, gt=0, le=(1 << 64) - 1)]
"""Strict positive u64 integer; zero and numeric coercions are rejected."""
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
"""Strict positive Python integer. Native policy validation applies
operation-specific width and plan constraints.
"""

DocumentRequest = Literal[
    "response_document", "rendered_dom", "accessibility_tree", "network_tree"
]
"""Requested output evidence families. Selection does not guarantee production;
inspect typed partial, unavailable, or unprojectable outcomes.
"""
DocumentSelectionKind = Literal["current", "exact"]
"""Current selection resolves package output defaults; exact selection preserves
authored outputs, including an intentionally empty selection.
"""
BrowserMode = Literal["headless", "headful"]
"""Headless or headful acquisition mode. Session settings and bound browser
acquisitions must agree before startup.
"""
BrowserEngine = Literal["chrome", "firefox", "moli"]
"""Browser implementation. Optional engines use native BiDi; Chrome retains CDP."""
MoliProfile = Literal["dom", "layout"]
"""Moli DOM-only or on-demand layout profile, independent of window mode."""
DirectHttpRedirectTargets = Literal["allow_http_and_https", "same_origin"]
"""Redirect admission allows supported HTTP(S) destinations or restricts transitions
to the seed origin. Hop and request budgets apply separately.
"""
DiscoveryDocuments = Literal["discard_after_inspection", "retain_within_budget"]
"""Map evidence retention either discards documents after inspection or retains them
within the configured payload budget.
"""
HostScope = Literal["seed_host", "registrable_domain"]
"""Map admission stays on the seed host or the supported registrable domain. Passive
discoveries do not prove HTTP reachability.
"""
PathScope = Literal["seed_subtree", "entire_origin"]
"""Map admission stays within the seed path subtree or admits the entire origin;
scheme, port, and host rules remain independent.
"""
PageDiscovery = Literal["disabled", "explore"]
"""Disable ordinary page-link exploration or explore admitted pages within depth and
resource budgets.
"""
Robots = Literal["ignore", "respect"]
"""Ignore or respect applicable robots rules during Map exploration. This does not
change URL scope admission.
"""
Subdomains = Literal["disabled", "passive"]
"""Disable name discovery or use passive historical provider evidence, without
guessing hosts or claiming current reachability.
"""
TuningMode = Literal["default"]
"""Current supported tuning vocabulary uses package defaults; no separate override
mode is implied.
"""
ProfileSelectionKind = Literal["current", "exact"]
"""Current provider profiles resolve registry metadata; exact profiles retain
complete authored child-request sections.
"""


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
"""Strict positive u64 policy count validated by Rust; zero never means unlimited."""
StepLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(StepLimit))
]
"""Strict positive u32 query/depth counter validated by Rust."""
AddressableByteLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(AddressableByteLimit))
]
"""Strict positive u64 byte limit checked by Rust to fit platform address size."""
EventLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(EventLimit))
]
"""Strict positive addressable browser event count validated by Rust."""
ResourceLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(ResourceLimit))
]
"""Strict positive addressable u32 resource-count bound validated by Rust."""
AccessibilityNodeLimitValue = Annotated[
    int,
    Field(strict=True),
    AfterValidator(_scalar_validator(AccessibilityNodeLimit)),
]
"""Strict positive addressable u32 accessibility-node bound validated by Rust."""
MaximumElapsedValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(MaximumElapsed))
]
"""Strict positive u64 elapsed budget in microseconds. Conversion to a platform
capture deadline is checked separately.
"""
RedirectHopLimitValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(RedirectHopLimit))
]
"""Strict positive u32 Direct HTTP redirect-transition bound validated by Rust."""
BudgetValue = Annotated[
    int, Field(strict=True), AfterValidator(_scalar_validator(Budget))
]
"""Strict positive u32 Map budget validated by Rust; zero is not an unlimited
setting.
"""


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
    """Current or explicit document outputs for one acquisition.

    Attributes:
        kind: current resolves package defaults; exact retains an authored output
            selection.
        documents: None for current selection; an explicit bounded tuple for exact
            selection, including an intentionally empty tuple.
    """

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
    """Authored acquisition mechanism with explicit document selection.

    Attributes:
        kind: direct_http or browser selects the acquisition adapter family.
        mode: Required headless/headful selection for browser, absent for direct HTTP.
        documents: Current defaults or exact authored output representations. Direct
            HTTP supports only a response document.
    """

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
        """Return Direct HTTP authoring with current document-selection defaults."""
        return cls()

    @classmethod
    def browser(cls, mode: Literal["headless", "headful"] = "headless") -> Self:
        """Declare browser acquisition without launching a browser.

        Args:
            mode: Headless or headful selection, defaulting to headless.

        Returns:
            Browser authoring with current document-selection defaults.
        """
        return cls(kind="browser", mode=mode)

    def with_documents(self, documents: list[str] | tuple[str, ...]) -> Self:
        """Return a new acquisition with exact authored document outputs.

        Args:
            documents: Supported representations, including an explicit empty selection.

        Returns:
            Revalidated acquisition without changing this declaration.

        Raises:
            PolicyError: The adapter kind or selected document outputs are unsupported.
        """
        value = _rust_component(
            "acquisition",
            self.model_dump_json(exclude_none=True),
            "with_documents",
            documents,
        )
        return type(self).model_validate(value)

    @property
    def exact_documents(self) -> tuple[str, ...] | None:
        """Return exact authored outputs, or None for a Current selection."""
        value = _rust_component(
            "acquisition",
            self.model_dump_json(exclude_none=True),
            "exact_documents",
        )
        return None if value is None else tuple(value)

    @property
    def selection_kind(self) -> Literal["current", "exact"]:
        """Return whether outputs were selected by Current defaults or explicitly."""
        return _rust_component(
            "acquisition",
            self.model_dump_json(exclude_none=True),
            "selection_kind",
        )


class Page(Model):
    """Ordered bounded acquisitions for one page request.

    Attributes:
        acquisitions: Authored acquisitions in execution/outcome order; at most three
            declarations are accepted.
    """

    acquisitions: Annotated[list[Acquisition], Field(max_length=3)] = _field(
        "page", "acquisitions"
    )


class SourceLimits(Model):
    """Separate retained byte budgets for the HTTP source stages.

    Attributes:
        content_coded_bytes: Maximum compressed/content-coded response-body bytes
            admitted.
        representation_bytes: Maximum decoded representation bytes after content
            decoding.
        unicode_utf8_bytes: Maximum UTF-8 bytes in a decoded Unicode text view.
    """

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
    """Browser evidence byte bounds and capture resource counts.

    Attributes:
        dom_utf8_bytes: Maximum retained rendered-DOM UTF-8 bytes.
        ax_json_utf8_bytes: Maximum retained accessibility-tree JSON UTF-8 bytes.
        max_events: Positive addressable browser-event count.
        max_resources: Positive addressable resource count admitted to one capture.
        max_accessibility_nodes: Positive addressable node count in an accessibility
            response.
    """

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
    """Direct HTTP redirect traversal configuration.

    Attributes:
        kind: disabled for no traversal; follow requires both hop and target settings.
        max_hops: Positive redirect-transition count when following, otherwise None.
        targets: HTTP(S) targets or same-origin restriction when following, otherwise
            None.
    """

    kind: Literal["disabled", "follow"]
    max_hops: RedirectHopLimitValue | None = None
    targets: DirectHttpRedirectTargets | None = None

    @classmethod
    def default(cls) -> Self:
        """Return redirect behavior selected by the current Rust package default."""
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
    """Acquisition deadlines and source/browser evidence budgets.

    Attributes:
        maximum_elapsed: Positive total acquisition elapsed budget in microseconds.
        source: Content-coded, representation, and Unicode retention byte bounds.
        browser: DOM/accessibility byte bounds and capture event/resource counts.
        direct_http_redirects: Explicit redirect traversal limits; adapter support is
            checked separately.
    """

    maximum_elapsed: MaximumElapsedValue = _field("request", "maximum_elapsed")
    source: SourceLimits = _field("request", "source")
    browser: BrowserLimits = _field("request", "browser")
    direct_http_redirects: Redirects = _field("request", "direct_http_redirects")


class Documents(Model):
    """Retained-payload parsing resource limits.

    Attributes:
        max_input_bytes: Positive addressable input payload bytes accepted for parsing.
        max_nodes: Positive maximum parsed node count.
        max_depth: Positive maximum parse/tree depth.
    """

    max_input_bytes: AddressableByteLimitValue = _field("documents", "max_input_bytes")
    max_nodes: CountLimitValue = _field("documents", "max_nodes")
    max_depth: StepLimitValue = _field("documents", "max_depth")


class Locators(Model):
    """Locator traversal, query, match, and output resource limits.

    Attributes:
        max_selector_visits: Positive maximum selector traversal visits.
        max_query_bytes: Positive addressable encoded query metadata bytes.
        max_query_steps: Positive maximum query evaluation steps.
        max_regions: Positive maximum retained repeated-region matches.
        max_matches: Positive maximum retained finding matches.
        max_captures: Positive maximum retained capture values.
        max_output_bytes: Positive addressable bytes retained in locator output.
    """

    max_selector_visits: CountLimitValue = _field("locators", "max_selector_visits")
    max_query_bytes: AddressableByteLimitValue = _field("locators", "max_query_bytes")
    max_query_steps: StepLimitValue = _field("locators", "max_query_steps")
    max_regions: StepLimitValue = _field("locators", "max_regions")
    max_matches: CountLimitValue = _field("locators", "max_matches")
    max_captures: CountLimitValue = _field("locators", "max_captures")
    max_output_bytes: AddressableByteLimitValue = _field("locators", "max_output_bytes")


class Duration(Model):
    """Portable elapsed duration with seconds and subsecond nanoseconds.

    Attributes:
        seconds: Unsigned u64 whole seconds, not an absolute timestamp.
        nanoseconds: Strict integer remainder below one billion; operation-specific
            positivity is checked separately.
    """

    seconds: U64
    nanoseconds: Annotated[int, Field(strict=True, ge=0, lt=1_000_000_000)] = 0


class Scope(Model):
    """Map URL admission boundaries relative to the authored seed.

    Attributes:
        hosts: seed_host or registrable_domain controls admitted hostname scope.
        paths: seed_subtree or entire_origin controls admitted URL paths. Scheme and
            port remain part of origin admission.
    """

    hosts: HostScope = _field("map", "scope", "hosts")
    paths: PathScope = _field("map", "scope", "paths")


class MapLimits(Model):
    """Map discovery counts, retention bounds, and execution budgets.

    Attributes:
        max_link_depth: Maximum rooted hyperlink depth; zero permits root-only
            exploration.
        max_hosts: Positive maximum retained hostnames.
        max_urls: Positive maximum retained normalized page URLs.
        max_relationships: Positive maximum directed relationships retained.
        max_observations: Positive maximum provenance observations retained.
        max_pending: Positive maximum pending frontier entries.
        max_requests: Positive charged acquisition request count, including support
            sources.
        max_sitemaps: Positive maximum sitemap sources processed.
        max_sitemap_depth: Maximum nested sitemap depth.
        max_response_bytes: Positive maximum bytes in one acquired response.
        max_total_response_bytes: Positive aggregate acquired-response byte budget.
        max_retained_document_bytes: Positive retained document payload budget, distinct
            from inventory metadata.
        max_concurrency: Positive maximum simultaneous acquisition work; this does not
            grant tab ownership.
        maximum_elapsed: Elapsed discovery budget expressed as seconds plus nanoseconds.
        max_url_bytes: Positive maximum normalized URL UTF-8 bytes.
        max_inventory_bytes: Positive byte budget for retained discovery inventory.
        max_parser_entries: Positive maximum source-parser entries examined.
        max_hostname_bytes: Positive maximum canonical hostname UTF-8 bytes.
    """

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
    """Explicit Map admission exclusions rather than discovery selectors.

    Attributes:
        excluded_query_keys: URL query key names to exclude during admission.
        excluded_path_prefixes: Literal URL path prefixes to exclude.
    """

    excluded_query_keys: list[str] = _field("map", "filters", "excluded_query_keys")
    excluded_path_prefixes: list[str] = _field(
        "map", "filters", "excluded_path_prefixes"
    )

    def check(self) -> None:
        """Validate admission exclusions in Rust without discovering URLs.

        Raises:
            PolicyError: Exclusion declarations exceed supported shape or bounds.
        """
        _rust_component("filters", self.model_dump_json(exclude_none=True), "validate")


class Map(Model):
    """Complete bounded discovery declaration resolved by the Rust SDK.

    Attributes:
        scope: Seed-relative host and path admission rules.
        pages: disabled or explore controls page link exploration.
        robots: ignore or respect selects applicable robots admission behavior.
        subdomains: disabled or passive selects historical name discovery.
        limits: Count, byte, concurrency, and elapsed discovery bounds.
        documents: Discard after inspection or retain within the configured document
            budget.
        filters: Explicit query-key and path-prefix exclusions.
    """

    scope: Scope = _field("map", "scope")
    pages: PageDiscovery = _field("map", "pages")
    robots: Robots = _field("map", "robots")
    subdomains: Subdomains = _field("map", "subdomains")
    limits: MapLimits = _field("map", "limits")
    documents: DiscoveryDocuments = _field("map", "documents")
    filters: Filters = _field("map", "filters")

    def check(self) -> None:
        """Validate scope, resource bounds, and exclusions without acquisition I/O.

        Raises:
            PolicyError: Discovery declaration violates supported scope or bounds.
        """
        _rust_component("map", self.model_dump_json(exclude_none=True), "validate")


class ProviderRequestProfile(Model):
    """Complete child-request policy sections for a search provider.

    Attributes:
        page: Provider-specific acquisitions and document selections.
        request: Provider acquisition deadlines, byte/resource limits, and redirect
            behavior.
        documents: Provider retained-document parsing limits.
    """

    page: Page = Field(default_factory=Page)
    request: Request = Field(default_factory=Request)
    documents: Documents = Field(default_factory=Documents)


class ProfileSelection(Model):
    """Current provider defaults or an explicit complete request profile.

    Attributes:
        kind: current resolves package registry metadata; exact retains an authored
            profile.
        profile: None for current selection, required complete profile for exact
            selection.
    """

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
    """Supported provider names with Rust registry default-status evidence.

    Attributes:
        brave: Brave public search route.
        bing: Bing public search route.
        duck_duck_go: DuckDuckGo public search route. Selection does not guarantee
            availability or certification.
        google: Google rendered web search route. Preview availability does not
            establish certification.
    """

    brave = "brave"
    bing = "bing"
    duck_duck_go = "duck_duck_go"
    google = "google"

    def defaults_status(self) -> ProviderDefaultsStatus:
        """Return registry availability/certification without executing a search."""
        value = _rust_component("provider", json.dumps(self.value), "defaults_status")
        return ProviderDefaultsStatus.model_validate(value)


class ProviderSelection(Model):
    """One provider and its current or explicit child-request profile.

    Attributes:
        provider: Provider occupying this authored search slot.
        profile: Current registry defaults or a complete exact request profile.
    """

    provider: Provider
    profile: ProfileSelection = Field(default_factory=ProfileSelection)

    @classmethod
    def current(cls, provider: Provider | str) -> Self:
        """Select one provider with registry-owned defaults to resolve later.

        Args:
            provider: Supported provider enum or serialized provider name.

        Returns:
            Current-profile declaration; selection does not certify availability.

        Raises:
            PolicyError: The provider name or declaration is unsupported.
        """
        value = _rust_component(
            "provider_selection",
            None,
            "current",
            {"provider": str(provider)},
        )
        return cls.model_validate(value)

    @classmethod
    def exact(cls, provider: Provider | str, profile: ProviderRequestProfile) -> Self:
        """Select one provider with an explicit complete request profile.

        Args:
            provider: Supported provider enum or serialized provider name.
            profile: Complete child-request policy sections to retain.

        Returns:
            An exact-profile selection without acquiring provider results.

        Raises:
            PolicyError: Provider or profile semantics are unsupported.
        """
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
    """Ordered provider selection with shared search resource budgets.

    Attributes:
        providers: Authored provider slots, at most four and without duplicates after
            validation.
        max_in_flight: Positive maximum simultaneous provider work.
        max_browser_in_flight: Positive maximum browser-backed provider work, separate
            from total concurrency.
        max_results_per_provider: Positive u16 retained organic-result limit for each
            provider.
        max_total_results: Positive u32 shared result capacity; validation checks the
            selected plan fits.
        max_retained_content_bytes: Positive addressable shared URL/text retention byte
            budget.
        maximum_elapsed: Positive shared search elapsed budget in microseconds.
    """

    providers: Annotated[list[ProviderSelection], Field(max_length=4)] = _field(
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
        """Return a validated search declaration selecting no provider routes."""
        return cls.model_validate(_rust_component("search", None, "disabled"))

    def is_enabled(self) -> bool:
        """Return whether at least one provider is selected, not whether it can run."""
        return _rust_component(
            "search", self.model_dump_json(exclude_none=True), "is_enabled"
        )

    def with_max_in_flight(self, value: int) -> Self:
        """Return revalidated search limits without changing this declaration.

        Args:
            value: Positive bound measured in simultaneous provider operations.

        Returns:
            A new declaration checked by the Rust policy implementation.

        Raises:
            PolicyError: Width, positivity, addressability, or plan consistency fails.
        """
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_max_in_flight",
                value,
            )
        )

    def with_max_browser_in_flight(self, value: int) -> Self:
        """Return revalidated search limits without changing this declaration.

        Args:
            value: Positive bound measured in simultaneous browser-backed provider
                operations.

        Returns:
            A new declaration checked by the Rust policy implementation.

        Raises:
            PolicyError: Width, positivity, addressability, or plan consistency fails.
        """
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_max_browser_in_flight",
                value,
            )
        )

    def per_provider_limit(self, value: int) -> Self:
        """Return revalidated search limits without changing this declaration.

        Args:
            value: Positive bound measured in retained organic hits per provider.

        Returns:
            A new declaration checked by the Rust policy implementation.

        Raises:
            PolicyError: Width, positivity, addressability, or plan consistency fails.
        """
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "per_provider_limit",
                value,
            )
        )

    def with_result_limits(self, per_provider: int, total: int) -> Self:
        """Return a search declaration with explicit per-provider and shared limits.

        Args:
            per_provider: Positive u16 retained-hit limit for each provider.
            total: Positive u32 shared retained-hit capacity.

        Returns:
            A revalidated copy; this declaration is not mutated.

        Raises:
            PolicyError: Width, positivity, or selected-plan capacity checks fail.
        """
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_result_limits",
                {"per_provider": per_provider, "total": total},
            )
        )

    def with_max_total_results(self, value: int) -> Self:
        """Return revalidated search limits without changing this declaration.

        Args:
            value: Positive bound measured in shared retained organic hits.

        Returns:
            A new declaration checked by the Rust policy implementation.

        Raises:
            PolicyError: Width, positivity, addressability, or plan consistency fails.
        """
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_max_total_results",
                value,
            )
        )

    def with_max_retained_content_bytes(self, value: int) -> Self:
        """Return revalidated search limits without changing this declaration.

        Args:
            value: Positive bound measured in shared retained URL/text bytes.

        Returns:
            A new declaration checked by the Rust policy implementation.

        Raises:
            PolicyError: Width, positivity, addressability, or plan consistency fails.
        """
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_max_retained_content_bytes",
                value,
            )
        )

    def with_maximum_elapsed(self, value: int) -> Self:
        """Return revalidated search limits without changing this declaration.

        Args:
            value: Positive bound measured in shared elapsed microseconds.

        Returns:
            A new declaration checked by the Rust policy implementation.

        Raises:
            PolicyError: Width, positivity, addressability, or plan consistency fails.
        """
        return type(self).model_validate(
            _rust_component(
                "search",
                self.model_dump_json(exclude_none=True),
                "with_maximum_elapsed",
                value,
            )
        )


class Tuning(Model):
    """Package-owned tuning mode without independent runtime overrides.

    Attributes:
        mode: Currently default is the supported tuning vocabulary.
    """

    mode: TuningMode = "default"

    def is_default(self) -> bool:
        """Return whether this declaration uses the supported default tuning mode."""
        return _rust_component("tuning", self.model_dump_json(), "is_default")


class PolicyIdentity(ImmutableModel):
    """Versioned Rust digest identifying effective policy behavior.

    Attributes:
        version: Positive identity-format version.
        sha256: Canonical 64-character lowercase hexadecimal digest of the resolved
            policy identity.
    """

    version: PositiveU16
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AcquisitionKind(ImmutableModel):
    """Resolved acquisition family and optional browser mode.

    Attributes:
        kind: direct_http or browser identifies the execution mechanism.
        mode: Headless/headful mode only for browser acquisitions.
    """

    kind: Literal["direct_http", "browser"]
    mode: Literal["headless", "headful"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def _validate_variant(self) -> Self:
        if (self.kind == "browser") != (self.mode is not None):
            raise ValueError("acquisition kind fields do not match its kind")
        return self


class EffectiveAcquisition(ImmutableModel):
    """Resolved acquisition output selection preserving authored intent.

    Attributes:
        acquisition: Resolved adapter family and browser mode when applicable.
        authored_selection: Whether output selection was current or exact when authored.
        documents: Concrete document representations selected after resolution.
    """

    acquisition: AcquisitionKind
    authored_selection: Literal["current", "exact"]
    documents: tuple[
        Literal[
            "response_document", "rendered_dom", "accessibility_tree", "network_tree"
        ],
        ...,
    ]


class EffectivePage(ImmutableModel):
    """Resolved acquisitions retained in authored page order.

    Attributes:
        acquisitions: Concrete acquisitions and output selections for execution.
    """

    acquisitions: tuple[EffectiveAcquisition, ...]


class ProviderDefaultsStatus(ImmutableModel):
    """Explicit registry certification or exact-profile provenance.

    Attributes:
        status: unavailable, preview, certified, or exact distinguishes default
            eligibility from authored profiles.
        registry_version: Registry version when defaults are unavailable, otherwise
            None.
        version: Positive defaults-profile version for preview/certified metadata,
            otherwise None.
    """

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
    """Resolved provider profile with its default-selection provenance.

    Attributes:
        provider: Provider occupying the authored search slot.
        profile: Resolved child profile, absent when unavailable.
        profile_selection_kind: Current defaults or an exact authored declaration.
        defaults_status: Certification/availability or exact-profile provenance.
    """

    provider: Provider
    profile: ProviderRequestProfile | None
    profile_selection_kind: Literal["current", "exact"]
    defaults_status: ProviderDefaultsStatus

    @property
    def page(self) -> Page | None:
        """Return acquisition/output settings, or None when unavailable."""
        value = _rust_component(
            "effective_provider_route",
            self.model_dump_json(exclude_none=True),
            "page",
        )
        return None if value is None else Page.model_validate(value)

    @property
    def request(self) -> Request | None:
        """Return timing/evidence settings, or None when unavailable."""
        value = _rust_component(
            "effective_provider_route",
            self.model_dump_json(exclude_none=True),
            "request",
        )
        return None if value is None else Request.model_validate(value)

    @property
    def documents(self) -> Documents | None:
        """Return a retained-document parsing profile copy, or None when unavailable."""
        value = _rust_component(
            "effective_provider_route",
            self.model_dump_json(exclude_none=True),
            "documents",
        )
        return None if value is None else Documents.model_validate(value)

    @property
    def defaults_version(self) -> ProviderDefaultsVersion | None:
        """Return the defaults version, absent for exact or unavailable profiles."""
        value = _rust_component(
            "effective_provider_route",
            self.model_dump_json(exclude_none=True),
            "defaults_version",
        )
        return None if value is None else ProviderDefaultsVersion(value)


class EffectiveSearch(ImmutableModel):
    """Resolved ordered provider routes and shared search budgets.

    Attributes:
        providers: Concrete provider slots in authored order, including unavailable
            routes.
        max_in_flight: Maximum simultaneous provider work.
        max_browser_in_flight: Maximum simultaneous browser-backed provider work.
        max_results_per_provider: Retained organic hits per provider.
        max_total_results: Shared retained-hit capacity.
        max_retained_content_bytes: Shared URL/text retention bytes.
        maximum_elapsed: Shared elapsed budget in microseconds.
    """

    providers: tuple[EffectiveProviderRoute, ...]
    max_in_flight: PositiveInt
    max_browser_in_flight: PositiveInt
    max_results_per_provider: PositiveU16
    max_total_results: PositiveU32
    max_retained_content_bytes: AddressableByteLimit
    maximum_elapsed: MaximumElapsed


class Continue(ImmutableModel):
    """Retain an unsuccessful result and attempt the next safe step.

    Attributes:
        kind: Discriminator fixed to continue. Unknown effects or unsafe state can still
            force a hard stop.
    """

    kind: Literal["continue"] = "continue"


StopScope = Literal["current_flow", "invocation"]
"""current_flow stops its remaining leaves; invocation stops all remaining invocation
work. Unknown effects can still force a hard safety stop.
"""


class Stop(ImmutableModel):
    """Stop a selected Flow scope after failure or cancellation.

    Attributes:
        kind: Discriminator fixed to stop.
        scope: current_flow omits its remaining leaves; invocation stops the entire
            invocation.
    """

    kind: Literal["stop"] = "stop"
    scope: StopScope


Continuation = Annotated[Continue | Stop, Field(discriminator="kind")]
"""Tagged Continue or Stop behavior for known failures and observed cancellations.
Retaining a result does not imply successful business effects.
"""


class FlowPolicy(Model):
    """Independent fallback continuation for failures and cancellations.

    Attributes:
        on_failure: Fallback for known step failures unless locally overridden.
        on_cancellation: Fallback for observed cancellation unless locally overridden.
            Unknown effects and unsafe state can force a hard stop.
    """

    on_failure: Continuation = Field(default_factory=Continue)
    on_cancellation: Continuation = Field(default_factory=Continue)

    def is_default(self) -> bool:
        """Return whether both fallbacks match Rust's default Continue behavior."""
        return isinstance(self.on_failure, Continue) and isinstance(
            self.on_cancellation, Continue
        )


class _SnapshotFlowPolicy(ImmutableModel):
    on_failure: Continuation = Field(default_factory=Continue)
    on_cancellation: Continuation = Field(default_factory=Continue)


def _network_is_default(value: Network | _SnapshotNetwork) -> bool:
    return (
        value.ip_family == "system_default"
        and value.source_address is None
        and value.proxy is None
    )


class BrowserConfig(Model):
    """Select a browser implementation without installing or launching it.

    Rust validates the complete declaration. Capability never grants arbitrary
    JavaScript permission, and an optional engine never silently falls back.

    Attributes:
        engine: Chrome/CDP by default, or optional Firefox/Moli native BiDi.
        executable: Absolute installed binary path; omitted paths use engine discovery.
        endpoint: Existing BiDi WebSocket service, mutually exclusive with executable.
            User information, queries and fragments are rejected. Debug repr omits it.
        moli_profile: DOM-only or on-demand layout. Layout is not native headful mode.
        moli_resources: Load optional Moli image/font/media resources deliberately.
        moli_allow_private_networks: Explicit exception to owned Moli's native private
            network blocking. A client cannot attest a shared service's egress policy.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    engine: BrowserEngine = "chrome"
    executable: Path | None = None
    endpoint: str | None = Field(default=None, repr=False, max_length=4096)
    moli_profile: MoliProfile = "dom"
    moli_resources: StrictBool = False
    moli_allow_private_networks: StrictBool = False

    def is_default(self) -> bool:
        """Return whether canonical policy serialization may omit this declaration."""
        return (
            self.engine == "chrome"
            and self.executable is None
            and self.endpoint is None
            and self.moli_profile == "dom"
            and not self.moli_resources
            and not self.moli_allow_private_networks
        )

    @model_validator(mode="after")
    def _validate_in_rust(self) -> Self:
        declaration = json.loads(_native.default_policy())
        declaration["browser"] = self.model_dump(mode="json", exclude_none=True)
        try:
            _native.validate_policy(json.dumps(declaration))
        except _native.PolicyError as error:
            raise ValueError(str(error)) from error
        return self


class _SnapshotBrowserConfig(BrowserConfig):
    model_config = ConfigDict(frozen=True)


class EffectivePolicy(ImmutableModel):
    """Rust-resolved behavior view, separate from caller authoring intent.

    Attributes:
        network: Opt-in IP family, local source binding, and upstream proxy.
        browser: Resolved browser engine/profile declaration, without a live handle.
        default_action_timeout_ms: Positive fallback action duration in milliseconds,
            distinct from request startup budgets.
        flow: Resolved independent failure/cancellation fallback policies.
        page: Resolved acquisitions and output representations.
        request: Acquisition deadlines and evidence limits.
        documents: Parsing byte/node/depth limits.
        locators: Query, traversal, match, capture, and output limits.
        tuning: Resolved package tuning mode.
        map: Resolved discovery scope and resource declaration.
        search: Resolved provider routes and shared budgets.
    """

    network: Network = Field(
        default_factory=lambda: Network(), exclude_if=_network_is_default
    )
    browser: _SnapshotBrowserConfig = Field(default_factory=_SnapshotBrowserConfig)
    default_action_timeout_ms: PositiveU64 = 10_000
    flow: _SnapshotFlowPolicy = Field(default_factory=_SnapshotFlowPolicy)
    page: EffectivePage
    request: Request
    documents: Documents
    locators: Locators
    tuning: Tuning
    map: Map
    search: EffectiveSearch

    @model_serializer(mode="wrap")
    def _omit_default_browser(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if self.browser.is_default():
            data.pop("browser", None)
        return data


IpFamily = Literal["system_default", "ipv4_only", "ipv6_only"]
"""Permitted outbound TCP family; an upstream proxy owns its destination family."""


def _source_address(value: str) -> str:
    declaration = json.loads(_native.default_policy())
    declaration["network"] = {"source_address": value}
    try:
        normalized = json.loads(_native.validate_policy(json.dumps(declaration)))
    except _native.PolicyError as error:
        raise ValueError(str(error)) from error
    return normalized["network"]["source_address"]


class Network(Model):
    """Opt-in TCP routing retained by Requests and owned browser Sessions.

    Attributes:
        ip_family: Permitted socket family, including the connection to a proxy.
        source_address: Already-assigned local IP; does not select a NAT public IP.
        proxy: HTTP(S) CONNECT or SOCKS5 URL. Credentials persist in serialized policy.
            The upstream proxy controls destination DNS and egress family.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    ip_family: IpFamily = "system_default"
    source_address: Annotated[str, AfterValidator(_source_address)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    proxy: str | None = Field(
        default=None, repr=False, exclude_if=lambda value: value is None
    )


class Policy(Model):
    """Editable complete declaration with Rust-owned defaults and validation.

    Attributes:
        network: Opt-in IP family, local source binding, and upstream proxy.
        browser: Browser engine and optional launch/profile configuration.
        default_action_timeout_ms: Positive fallback action duration in milliseconds;
            explicit action/Flow budgets can override it.
        flow: Independent failure/cancellation continuation defaults.
        page: Ordered acquisition declarations and output selections.
        request: Acquisition timing, evidence limits, and redirect behavior.
        documents: Retained-payload parsing limits.
        locators: Query/traversal/finding resource limits.
        tuning: Supported package tuning declaration.
        map: Bounded site discovery scope and budgets.
        search: Ordered search provider selection and shared limits. Later edits are
            rechecked by check, to_json, or snapshot.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    network: Network = Field(default_factory=Network, exclude_if=_network_is_default)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    default_action_timeout_ms: PositiveU64 = 10_000
    flow: FlowPolicy = Field(default_factory=FlowPolicy)
    page: Page = _field("page")
    request: Request = _field("request")
    documents: Documents = _field("documents")
    locators: Locators = _field("locators")
    tuning: Tuning = Field(default_factory=Tuning)
    map: Map = _field("map")
    search: Search = _field("search")

    @model_serializer(mode="wrap")
    def _omit_default_browser(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if self.browser.is_default():
            data.pop("browser", None)
        return data

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
        """Validate and return the Rust identity of resolved policy behavior.

        Returns:
            Versioned canonical digest, independent of subsequent caller edits.

        Raises:
            PolicyError: Complete policy validation or identity resolution fails.
        """
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
    provider: Literal["brave", "bing", "duck_duck_go", "google"]
    profile: _SnapshotProfileSelection


class _SnapshotSearch(ImmutableModel):
    providers: tuple[_SnapshotProviderSelection, ...]
    max_in_flight: PositiveInt
    max_browser_in_flight: PositiveInt
    max_results_per_provider: PositiveU16
    max_total_results: PositiveU32
    max_retained_content_bytes: AddressableByteLimit
    maximum_elapsed: MaximumElapsed


class _SnapshotNetwork(ImmutableModel):
    ip_family: IpFamily = "system_default"
    source_address: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    proxy: str | None = Field(
        default=None, repr=False, exclude_if=lambda value: value is None
    )


class _SnapshotPolicy(ImmutableModel):
    network: _SnapshotNetwork = Field(
        default_factory=_SnapshotNetwork, exclude_if=_network_is_default
    )
    browser: _SnapshotBrowserConfig = Field(default_factory=_SnapshotBrowserConfig)
    default_action_timeout_ms: PositiveU64 = 10_000
    flow: _SnapshotFlowPolicy = Field(default_factory=_SnapshotFlowPolicy)
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
        if self.browser.is_default():
            data.pop("browser", None)
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
    provider: Literal["brave", "bing", "duck_duck_go", "google"]
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
    network: _SnapshotNetwork = Field(
        default_factory=_SnapshotNetwork, exclude_if=_network_is_default
    )
    browser: _SnapshotBrowserConfig = Field(default_factory=_SnapshotBrowserConfig)
    default_action_timeout_ms: PositiveU64 = 10_000
    flow: _SnapshotFlowPolicy = Field(default_factory=_SnapshotFlowPolicy)
    page: _SnapshotEffectivePage
    request: _SnapshotRequest
    documents: _SnapshotDocuments
    locators: _SnapshotLocators
    tuning: _SnapshotTuning
    map: _SnapshotMap
    search: _SnapshotEffectiveSearch

    @model_serializer(mode="wrap")
    def _omit_default_browser(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if self.browser.is_default():
            data.pop("browser", None)
        return data


class PolicySnapshot(ImmutableModel):
    """Deeply frozen Rust-validated authoring and resolved behavior.

    Attributes:
        policy: Immutable authored declaration retained at preparation time.
        effective_policy: Immutable Current selections and concrete execution budgets
            resolved by Rust.
        identity: Versioned digest binding this snapshot to resolved behavior.
    """

    policy: _SnapshotPolicy
    effective_policy: _SnapshotEffectivePolicy
    identity: PolicyIdentity

    @classmethod
    def from_policy(cls, policy: Policy) -> Self:
        """Freeze a validated authored declaration and its resolved behavior.

        Args:
            policy: Editable complete declaration to validate and snapshot now.

        Returns:
            A deeply frozen snapshot unaffected by later authoring or registry edits.

        Raises:
            PolicyError: Complete declaration or Current selection resolution fails.
        """
        return cls.model_validate_json(_native.policy_snapshot(policy.to_json()))


EffectivePolicy.model_rebuild()
