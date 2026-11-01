import json
from typing import Any, cast

import pytest
from pydantic import ValidationError

from yosoi import _native
from yosoi.errors import PolicyError, rust_error_details
from yosoi.policy import (
    MAX_RECORDING_DURATION_MS,
    Acquisition,
    DocumentSelection,
    MapLimits,
    ObserveLimits,
    ObservePolicy,
    Page,
    Policy,
    ProfileSelection,
    ProviderRequestProfile,
    ProviderSelection,
    RecordingRule,
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


def test_observation_defaults_are_disabled_and_omitted_from_policy_json() -> None:
    policy = Policy()

    assert policy.observe.is_default()
    assert policy.observe.limits.max_buffer_bytes == 16_000_000
    assert policy.observe.limits.max_retained_bytes == 64_000_000
    assert RecordingRule().mode == "browser_visible"
    assert "observe" not in json.loads(policy.to_json())
    assert json.loads(policy.to_json()) == json.loads(_native.default_policy())


def test_observation_recording_rules_are_additive_and_native_validated() -> None:
    policy = Policy(
        observe=ObservePolicy(
            native_tab_capture=True,
            recordings=[
                RecordingRule(mode="each_tab"),
                RecordingRule(mode="each_tab", include_audio=True),
            ],
        )
    )

    serialized = json.loads(policy.to_json())["observe"]
    assert serialized["native_tab_capture"] is True
    assert [rule["mode"] for rule in serialized["recordings"]] == [
        "each_tab",
        "each_tab",
    ]
    assert serialized["recordings"][1]["include_audio"] is True

    with pytest.raises(ValidationError):
        Policy(observe=ObservePolicy(recordings=[RecordingRule(mode="each_tab")]))


def test_observation_recording_limit_error_preserves_configured_counts() -> None:
    with pytest.raises(ValidationError) as rejected:
        Policy(
            observe=ObservePolicy(
                native_tab_capture=True,
                recordings=[
                    RecordingRule(mode="each_tab"),
                    RecordingRule(mode="each_tab"),
                ],
                limits=ObserveLimits(max_recordings=1),
            )
        )

    details = rust_error_details(rejected.value)
    assert details is not None
    assert details.variant == "ObservationRulesExceedRecordingLimit"
    assert details.details["configured"] == 2
    assert details.details["maximum"] == 1


def test_observe_limits_reject_zero_and_non_integer_values() -> None:
    with pytest.raises(ValidationError):
        ObserveLimits(max_sources=0)
    with pytest.raises(ValidationError):
        ObserveLimits(max_recordings=True)


def test_recording_duration_constant_matches_typed_24_hour_cap() -> None:
    assert MAX_RECORDING_DURATION_MS == 86_400_000
    assert RecordingRule(max_duration_ms=MAX_RECORDING_DURATION_MS).max_duration_ms == (
        MAX_RECORDING_DURATION_MS
    )
    with pytest.raises(ValidationError):
        RecordingRule(max_duration_ms=MAX_RECORDING_DURATION_MS + 1)


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
