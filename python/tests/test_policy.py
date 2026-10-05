import json
from typing import Any, cast

import pytest
from pydantic import ValidationError

from yosoi import _native
from yosoi.errors import PolicyError
from yosoi.policy import (
    Acquisition,
    DocumentSelection,
    MapLimits,
    Page,
    Policy,
    ProfileSelection,
    ProviderRequestProfile,
    ProviderSelection,
    Search,
    SourceLimits,
)


def test_default_policy_and_identity_are_exactly_rust_owned() -> None:
    defaults = _native.default_policy()
    policy = Policy()
    assert json.loads(policy.to_json()) == json.loads(defaults)
    assert policy.identity().model_dump() == json.loads(
        _native.policy_identity(defaults)
    )


def test_policy_instances_have_independent_mutable_sections() -> None:
    first = Policy()
    second = Policy()
    first.documents.max_nodes = 42
    first.search.providers.clear()
    assert second.documents.max_nodes != 42
    assert len(second.search.providers) == 3


def test_mutating_nested_policy_is_checked_again_when_used() -> None:
    policy = Policy()
    policy.locators.max_matches = 0
    with pytest.raises(PolicyError):
        policy.to_json()
    with pytest.raises(PolicyError):
        policy.check()


def test_malformed_browser_or_duplicate_acquisition_is_rejected_by_rust() -> None:
    with pytest.raises(ValidationError):
        Policy(page=Page(acquisitions=[Acquisition(kind="browser")]))
    with pytest.raises(ValidationError):
        Policy(
            page=Page(
                acquisitions=[Acquisition.direct_http(), Acquisition.direct_http()]
            )
        )


def test_search_can_be_disabled_without_modifying_other_limits() -> None:
    policy = Policy(search=Search(providers=[]))
    assert json.loads(policy.to_json())["search"]["providers"] == []


def test_effective_policy_and_snapshot_resolve_current_and_exact_routes() -> None:
    policy = Policy()
    effective = policy.effective_policy()
    assert effective.page.acquisitions[0].authored_selection == "current"
    assert effective.page.acquisitions[0].documents == ("response_document",)
    assert all(route.profile is not None for route in effective.search.providers)
    assert all(
        route.defaults_status.status == "preview"
        for route in effective.search.providers
    )

    exact = Policy(
        page=Page(
            acquisitions=[
                Acquisition(
                    kind="browser",
                    mode="headless",
                    documents=DocumentSelection(
                        kind="exact", documents=("rendered_dom",)
                    ),
                )
            ]
        ),
        search=Search(
            providers=[
                ProviderSelection(
                    provider="bing",
                    profile=ProfileSelection(
                        kind="exact", profile=ProviderRequestProfile()
                    ),
                )
            ]
        ),
    )
    resolved = exact.effective_policy()
    assert resolved.page.acquisitions[0].authored_selection == "exact"
    assert resolved.page.acquisitions[0].documents == ("rendered_dom",)
    route = resolved.search.providers[0]
    assert route.profile_selection_kind == "exact"
    assert route.defaults_status.status == "exact"
    assert route.profile is not None

    snapshot = exact.snapshot()
    assert snapshot.identity == exact.identity()
    assert json.loads(snapshot.policy.model_dump_json(exclude_none=True)) == json.loads(
        exact.to_json()
    )
    assert json.loads(
        snapshot.effective_policy.model_dump_json(exclude_none=True)
    ) == json.loads(exact.effective_policy().model_dump_json(exclude_none=True))


def test_policy_snapshot_is_deeply_immutable_and_detached_from_authoring_value() -> (
    None
):
    policy = Policy()
    snapshot = policy.snapshot()
    original_identity = snapshot.identity
    original_limit = snapshot.policy.documents.max_nodes

    with pytest.raises(ValidationError):
        cast(Any, snapshot.policy.documents).max_nodes = 42
    with pytest.raises(AttributeError):
        cast(Any, snapshot.policy.search.providers).clear()
    with pytest.raises(ValidationError):
        cast(Any, snapshot.effective_policy.request).maximum_elapsed = 0

    policy.documents.max_nodes = 42
    assert snapshot.policy.documents.max_nodes == original_limit
    assert snapshot.identity == original_identity


def test_standalone_policy_values_enforce_rust_scalar_widths_and_positive_bounds() -> (
    None
):
    with pytest.raises(ValidationError):
        SourceLimits(content_coded_bytes=0)
    with pytest.raises(ValidationError):
        SourceLimits(content_coded_bytes=True)
    with pytest.raises(ValidationError):
        MapLimits(max_hosts=0)
    with pytest.raises(ValidationError):
        Search(max_results_per_provider=0)
