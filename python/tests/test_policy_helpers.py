import pytest

from yosoi.errors import PolicyError
from yosoi.policy import (
    Acquisition,
    Budget,
    CountLimit,
    Documents,
    Filters,
    Map,
    MapLimits,
    Policy,
    Provider,
    ProviderRequestProfile,
    ProviderSelection,
    Redirects,
    Scope,
    Search,
    Tuning,
)


def test_public_redirect_default_uses_rust_without_changing_variant_authoring() -> None:
    default = Redirects.default()
    assert default == Policy().request.direct_http_redirects
    assert Redirects(kind="disabled").kind == "disabled"


def test_search_disabled_and_builders_follow_rust_policy_methods() -> None:
    disabled = Search.disabled()
    assert disabled.providers == []
    assert not disabled.is_enabled()

    configured = (
        disabled.with_max_in_flight(3)
        .with_max_browser_in_flight(2)
        .per_provider_limit(4)
        .with_result_limits(3, 6)
        .with_max_total_results(9)
        .with_max_retained_content_bytes(4_096)
        .with_maximum_elapsed(5_000_000)
    )
    assert configured.max_in_flight == 3
    assert configured.max_browser_in_flight == 2
    assert configured.max_results_per_provider == 3
    assert configured.max_total_results == 9
    assert configured.max_retained_content_bytes == 4_096
    assert configured.maximum_elapsed == 5_000_000

    with pytest.raises(PolicyError):
        disabled.per_provider_limit(0)
    with pytest.raises(PolicyError):
        disabled.with_result_limits(0, 1)


def test_scalar_fields_keep_rust_values_and_accept_plain_int_assignment() -> None:
    documents = Documents(max_nodes=12)
    limits = MapLimits(max_requests=4)
    assert isinstance(documents.max_nodes, CountLimit)
    assert isinstance(limits.max_requests, Budget)

    policy = Policy()
    policy.documents.max_nodes = 42
    policy.map.limits.max_requests = 4
    policy.check()


def test_provider_factories_and_defaults_status_use_rust_registry() -> None:
    current = ProviderSelection.current(Provider.bing)
    assert current.provider is Provider.bing
    assert current.profile.kind == "current"

    profile = ProviderRequestProfile()
    exact = ProviderSelection.exact(Provider.bing, profile)
    assert exact.profile.kind == "exact"
    assert exact.profile.profile == profile

    rust_route = Policy().effective_policy().search.providers[1]
    assert Provider.bing.defaults_status() == rust_route.defaults_status


def test_acquisition_builders_keep_exact_documents_and_current_kind() -> None:
    current = Acquisition.browser()
    assert current.selection_kind == "current"
    assert current.exact_documents is None

    exact = current.with_documents(["accessibility_tree", "rendered_dom"])
    assert exact.selection_kind == "exact"
    assert exact.exact_documents == ("rendered_dom", "accessibility_tree")

    with pytest.raises(PolicyError):
        Acquisition.direct_http().with_documents(["rendered_dom"])


def test_effective_route_getters_match_resolved_profile() -> None:
    route = Policy().effective_policy().search.providers[1]
    assert route.profile is not None
    assert route.page == route.profile.page
    assert route.request == route.profile.request
    assert route.documents == route.profile.documents
    assert route.defaults_version == route.defaults_status.version


def test_filters_map_and_tuning_delegate_check_or_query_to_rust() -> None:
    Filters(excluded_query_keys=["utm_source"]).check()
    with pytest.raises(PolicyError):
        Filters(excluded_path_prefixes=[""]).check()

    Map().check()
    invalid_scope = Scope(hosts="seed_host", paths="seed_subtree")
    with pytest.raises(PolicyError):
        Map(scope=invalid_scope, subdomains="passive").check()

    assert Tuning().is_default()
