from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import yosoi as ys
from yosoi.errors import PolicyError


def test_auto_defaults_candidates_and_historical_identity():
    policy = ys.Policy()
    assert policy.search.routing == "auto"
    assert [str(candidate.provider) for candidate in policy.search.providers] == [
        "google",
        "duck_duck_go",
        "bing",
        "brave",
    ]
    assert policy.identity().version == 10
    assert (
        ys.Policy.model_validate_json(policy.to_json()).identity() == policy.identity()
    )
    fixture = (
        Path(__file__).parents[2]
        / "crates/yosoi/src/internal/policy/integration_tests/fixtures"
        / "policy-v7-explicit-search.json"
    )
    historical = ys.Policy.model_validate_json(fixture.read_text())
    assert historical.search.routing == "all"
    assert (
        ys.Policy.model_validate(json.loads(fixture.read_text())).search.routing
        == "all"
    )
    assert historical.identity().version == 7
    assert (
        historical.identity().sha256
        == "65f808531d392ce5ea96509219dfd62a3e0440c0c2c0a8e657bc420a89a6d7d2"
    )


def test_auto_and_explicit_constructors_agree_with_rust_validation():
    assert ys.policy.Search.auto(["bing"]).routing == "auto"
    partial = ys.policy.Search(
        providers=[ys.policy.ProviderSelection.current("bing")],
        max_in_flight=1,
        maximum_elapsed=1_000_000,
    )
    assert partial.routing == "auto"
    explicit = ys.policy.Search.new(["bing", "brave"])
    assert explicit.with_max_in_flight(1).routing == "all"
    assert ys.policy.Search.new(["bing", "brave"]).routing == "all"
    with pytest.raises(PolicyError) as empty:
        ys.policy.Search.auto([])
    assert empty.value.variant == "EmptyAutoSearch"
    with pytest.raises(PolicyError) as duplicate:
        ys.policy.Search.auto(["bing", "bing"])
    assert duplicate.value.variant == "DuplicateSearchProvider"


def test_protected_auto_skips_unsupported_and_blocked_candidates_without_dispatch(
    tmp_path,
):
    async def run():
        registry = ys.registry.Registry(tmp_path / "search.jsonl")
        policy = ys.Policy(
            respectfulness=ys.policy.Respectfulness(
                groups=[
                    ys.policy.RespectfulnessGroup(
                        id="all", patterns=["^https://"], blocked=True
                    )
                ]
            )
        )
        response = (
            await ys.search.new("no outbound work")
            .bind(policy)
            .with_registry(registry)
            .send()
        )
        assert response.routing == "auto"
        assert response.selected_provider is None
        assert len(response.providers) == 4
        for provider in response.providers:
            assert isinstance(provider.outcome, ys.search.NotStarted)
            assert not provider.attempts
            expected = (
                "respectfulness"
                if provider.provider == "bing"
                else "unsupported_capability"
            )
            assert provider.outcome.value == expected
        assert registry.snapshot().entries == {}
        value = json.loads(response.model_dump_json())
        assert value["routing"] == "auto" and value["selected_provider"] is None

    asyncio.run(run())
