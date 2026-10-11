import json
from typing import Any, cast

import pytest
from pydantic import ValidationError

from yosoi.browser import (
    Configured,
    Duration,
    Flow,
    FlowOutcome,
    NestedFlow,
    Timed,
    Wait,
)
from yosoi.policy import Continue, FlowPolicy, Policy, Stop


def test_policy_continuation_matches_rust_identity_and_immutable_snapshot() -> None:
    policy = Policy(flow=FlowPolicy(on_failure=Stop(scope="invocation")))
    wire = json.loads(policy.to_json())
    assert wire["flow"]["on_failure"] == {"kind": "stop", "scope": "invocation"}
    assert wire["flow"]["on_cancellation"] == {"kind": "continue"}
    snapshot = policy.snapshot()
    assert snapshot.identity == policy.identity()
    assert snapshot.policy.flow.on_failure.kind == "stop"
    policy.flow.on_failure = Continue()
    assert policy.identity() != snapshot.identity
    assert snapshot.policy.flow.on_failure.kind == "stop"
    with pytest.raises(ValidationError):
        cast(Any, snapshot.policy.flow).on_failure = Continue()


def test_native_nested_flow_and_local_override_wire_are_consumable() -> None:
    flow = Flow(
        on_failure=Stop(scope="invocation"),
        steps=(
            NestedFlow(
                flow=Flow(
                    timeout=Duration(secs=30, nanos=0),
                    steps=(
                        Configured(action=Wait(milliseconds=0), on_failure=Continue()),
                    ),
                )
            ),
        ),
    )
    wire = json.loads(flow.to_json())
    assert wire["schema_version"] == 3
    assert wire["steps"][0]["flow"]["steps"][0]["on_failure"] == {"kind": "continue"}
    assert Flow.model_validate(wire).steps == flow.steps


def test_legacy_microsecond_fields_keep_their_schema_and_unit() -> None:
    legacy = Flow.model_validate({"steps": [], "timeout_us": 10_000})
    migrated = json.loads(legacy.to_json())
    assert migrated["timeout"] == {"secs": 0, "nanos": 10_000_000}
    with pytest.raises(ValidationError):
        Timed(
            action=Wait(milliseconds=0), timeout=Duration(secs=1, nanos=0), timeout_us=5
        )


def test_outcome_keeps_cancel_cause_unknown_effect_skip_and_cleanup() -> None:
    outcome = FlowOutcome.model_validate(
        {
            "version": 3,
            "flow": {
                "schema_version": 3,
                "steps": [
                    {"kind": "evaluate", "source": "new Promise(() => {})"},
                    {"kind": "click", "selector": "#after"},
                ],
            },
            "steps": [
                {
                    "index": 0,
                    "flow_path": [0],
                    "receipt": {
                        "id": "uncertain",
                        "kind": "evaluate",
                        "status": "unknown",
                    },
                    "cancellation": "step",
                    "failure": "unknown_outcome",
                }
            ],
            "terminal": "unknown",
            "stop_reason": {"flow_path": [0], "cause": "unknown_outcome"},
            "skipped_steps": [
                {
                    "flow_path": [1],
                    "stopped_by": [0],
                    "cause": "unknown_outcome",
                    "scope": "invocation",
                }
            ],
            "cleanup": [
                {
                    "id": "release",
                    "kind": "release",
                    "status": "rejected",
                    "error": "fenced",
                }
            ],
        }
    )
    assert outcome.steps[0].cancellation == "step"
    assert outcome.steps[0].receipt.status == "unknown"
    assert outcome.skipped_steps[0].stopped_by == (0,)
    assert outcome.cleanup[0].error == "fenced"


def test_old_outcomes_and_finished_with_issues_remain_readable() -> None:
    legacy = FlowOutcome.model_validate(
        {
            "version": 1,
            "flow": {"steps": [], "timeout_us": 10_000},
            "steps": [],
            "terminal": "completed",
        }
    )
    assert legacy.flow.schema_version == 1
    assert legacy.flow.timeout_us == 10_000
    assert legacy.skipped_steps == ()
    assert legacy.cleanup == ()
    current = FlowOutcome.model_validate(
        {
            "version": 3,
            "flow": {
                "schema_version": 3,
                "steps": [{"kind": "click", "selector": "#optional"}],
            },
            "steps": [
                {
                    "index": 0,
                    "flow_path": [0],
                    "failure": "rejected",
                    "receipt": {
                        "id": "missing",
                        "kind": "click",
                        "status": "rejected",
                        "error": "missing optional target",
                    },
                }
            ],
            "terminal": "completed_with_issues",
        }
    )
    assert current.terminal == "completed_with_issues"
