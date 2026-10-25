import json
from typing import Any

import pytest
from pydantic import ValidationError

from yosoi.browser import (
    AllExpectation,
    Flow,
    JsonMatch,
    OperationReceipt,
    ResponseExpectation,
    SessionPolicy,
    UntilReport,
    UntilStep,
    all_of,
    ax,
    click,
    response,
    visible,
)


def valid_satisfied_until_report() -> dict[str, Any]:
    return {
        "version": 1,
        "termination": "satisfied",
        "scope": {
            "session_id": "session-1",
            "tab_id": "tab-1",
            "document_epoch": 5,
            "frame_id": "frame-1",
            "loader_id": "loader-1",
        },
        "trigger": {
            "id": "click-op-1",
            "kind": "click",
            "status": "observed",
            "result": {"value": None, "started_at_unix_us": 123_000},
            "observation": None,
            "error": None,
        },
        "evaluations": 1,
        "checks": [
            {
                "index": 0,
                "source": "dom",
                "state": "satisfied",
                "evidence": {"observation_id": "dom-1"},
                "error": None,
            }
        ],
        "error": None,
    }


def test_until_union_emits_schema_four_wire_shape() -> None:
    flow = Flow(
        steps=(
            click("button.place-order").until(
                all_of(
                    (
                        visible("#confirmation"),
                        response(
                            "https://shop.example/api/orders",
                            method="POST",
                            status=201,
                            json_matches=(
                                JsonMatch(pointer="/state", value="accepted"),
                            ),
                        ),
                        ax("Order placed", role="status"),
                    )
                )
            ),
        )
    )

    wire = json.loads(flow.to_json())
    step = wire["steps"][0]
    assert wire["schema_version"] == 4
    assert step["kind"] == "until"
    assert step["trigger"] == {
        "kind": "click",
        "selector": "button.place-order",
    }
    assert step["expectation"]["kind"] == "all"
    assert [item["kind"] for item in step["expectation"]["expectations"]] == [
        "condition",
        "response",
        "accessibility",
    ]
    response_wire = step["expectation"]["expectations"][1]
    assert response_wire["json"] == [{"pointer": "/state", "value": "accepted"}]
    assert "json_matches" not in response_wire


def test_until_flows_use_the_same_bounded_session_policy_fields() -> None:
    flow = Flow(steps=(visible("#ready").until(),))
    settings = SessionPolicy(
        execution_concurrency=3,
        maximum_queued_operations=9,
        yield_on_wait=False,
    )

    assert json.loads(flow.to_json())["schema_version"] == 4
    policy_wire = json.loads(settings.to_json())
    assert policy_wire["execution_concurrency"] == 3
    assert policy_wire["maximum_queued_operations"] == 9
    assert policy_wire["yield_on_wait"] is False


def test_standalone_until_waits_and_legacy_schema_rejects_until() -> None:
    flow = Flow(steps=(visible("#ready").until(),))
    assert flow.schema_version == 4

    legacy = {
        "schema_version": 3,
        "steps": [
            {
                "kind": "until",
                "expectation": {
                    "kind": "condition",
                    "condition": {"kind": "visible", "selector": "#ready"},
                },
            }
        ],
    }
    with pytest.raises(ValidationError, match="schema version 4"):
        Flow.model_validate(legacy)
    with pytest.raises(ValidationError, match="reserved for Until"):
        Flow(schema_version=4)


def test_until_rejects_navigation_and_bounds_expectation_tree() -> None:
    with pytest.raises(ValidationError, match="unsupported Until trigger"):
        UntilStep.model_validate(
            {
                "kind": "until",
                "trigger": {"kind": "navigate", "url": "https://shop.example/"},
                "expectation": {
                    "kind": "condition",
                    "condition": {"kind": "visible", "selector": "#ready"},
                },
            }
        )

    nested = visible("#ready")
    for _ in range(8):
        nested = AllExpectation(expectations=(nested,))
    with pytest.raises(ValidationError, match="nesting exceeds 8"):
        UntilStep(expectation=nested)


def test_response_expectation_fields_are_bounded_and_use_json_pointers() -> None:
    with pytest.raises(ValidationError, match="JSON Pointer"):
        JsonMatch(pointer="/bad/~2escape", value=True)
    with pytest.raises(ValidationError, match="JSON expectation value"):
        JsonMatch(pointer="/payload", value="x" * 16_385)
    with pytest.raises(ValidationError):
        response("https://shop.example/", status=600)
    with pytest.raises(ValidationError, match="response URL"):
        response("é" * 4_097)

    expectation = ResponseExpectation(
        url="https://shop.example/api/orders",
        json_matches=(JsonMatch(pointer="/state", value="accepted"),),
    )
    wire = json.loads(expectation.model_dump_json(exclude_none=True))
    assert wire["json"] == [{"pointer": "/state", "value": "accepted"}]
    assert "json_matches" not in wire
    restored = ResponseExpectation.model_validate(wire)
    assert restored.json_matches == expectation.json_matches


def test_until_receipt_exposes_a_validated_typed_report() -> None:
    receipt = OperationReceipt(
        id="until-op-1",
        kind="until",
        status="observed",
        result=valid_satisfied_until_report(),
    )

    report = receipt.until_report()
    assert isinstance(report, UntilReport)
    assert report.scope.document_epoch == 5
    assert report.scope.frame_id == "frame-1"
    assert report.scope.loader_id == "loader-1"
    assert report.trigger is not None
    assert report.trigger.id == "click-op-1"

    invalid = valid_satisfied_until_report()
    invalid["evaluations"] = 0
    with pytest.raises(ValidationError, match="satisfaction claim"):
        UntilReport.model_validate(invalid)


def test_until_report_requires_trigger_watermark_and_original_frame_scope() -> None:
    missing_result = valid_satisfied_until_report()
    missing_result["trigger"]["result"] = None
    with pytest.raises(ValidationError, match="command result"):
        UntilReport.model_validate(missing_result)

    missing_value = valid_satisfied_until_report()
    missing_value["trigger"]["result"] = {"started_at_unix_us": 123_000}
    with pytest.raises(ValidationError, match="command result"):
        UntilReport.model_validate(missing_value)

    error_trigger = valid_satisfied_until_report()
    error_trigger["trigger"]["error"] = "unexpected error"
    with pytest.raises(ValidationError, match="cannot have an error"):
        UntilReport.model_validate(error_trigger)

    zero_start = valid_satisfied_until_report()
    zero_start["trigger"]["result"]["started_at_unix_us"] = 0
    with pytest.raises(ValidationError, match="positive start watermark"):
        UntilReport.model_validate(zero_start)

    missing_frame = valid_satisfied_until_report()
    del missing_frame["scope"]["frame_id"]
    with pytest.raises(ValidationError, match="satisfaction claim"):
        UntilReport.model_validate(missing_frame)

    missing_loader = valid_satisfied_until_report()
    del missing_loader["scope"]["loader_id"]
    with pytest.raises(ValidationError, match="satisfaction claim"):
        UntilReport.model_validate(missing_loader)


def test_until_report_bounds_total_retained_evidence() -> None:
    with pytest.raises(ValidationError, match="Until report exceeds"):
        UntilReport(
            version=1,
            termination="satisfied",
            scope={
                "session_id": "session-1",
                "tab_id": "tab-1",
                "document_epoch": 5,
                "frame_id": "frame-1",
                "loader_id": "loader-1",
            },
            trigger=None,
            evaluations=1,
            checks=(
                {
                    "index": 0,
                    "source": "dom",
                    "state": "satisfied",
                    "evidence": "x" * 1_048_577,
                    "error": None,
                },
            ),
            error=None,
        )


def test_bidi_until_scope_requires_native_provenance_without_a_cdp_loader() -> None:
    value = valid_satisfied_until_report()
    value["scope"]["protocol"] = "bidi"
    del value["scope"]["loader_id"]
    identity = {"engine": "firefox", "protocol": "bidi", "process_owned": False}
    value["trigger"]["browser"] = identity
    report = UntilReport.model_validate(value)
    assert report.scope.protocol == "bidi"
    assert report.scope.loader_id is None
    receipt = {
        "id": "bidi-until",
        "kind": "until",
        "status": "observed",
        "browser": identity,
        "result": value,
        "observation": {
            "id": "dom-1",
            "session_id": "session-1",
            "tab_id": "tab-1",
            "document_epoch": 5,
            "html": None,
            "url": None,
            "screenshot": None,
            "browser": identity,
        },
    }
    assert OperationReceipt.model_validate(receipt).until_report() == report
    with pytest.raises(ValidationError, match="scope protocol"):
        OperationReceipt.model_validate({**receipt, "browser": None})
    with pytest.raises(ValidationError, match="observation provenance"):
        OperationReceipt.model_validate(
            {**receipt, "observation": {**receipt["observation"], "browser": None}}
        )
    value["scope"]["loader_id"] = "pretend-loader"
    with pytest.raises(ValidationError, match="cannot claim a CDP loader"):
        UntilReport.model_validate(value)
