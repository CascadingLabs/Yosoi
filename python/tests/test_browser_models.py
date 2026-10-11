import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi import _native
from yosoi.browser import (
    Assert,
    Click,
    CountAtLeast,
    EnterText,
    Evaluate,
    Exists,
    Flow,
    FlowOutcome,
    Navigate,
    Screenshot,
    SessionPolicy,
    Wait,
    WaitUntil,
)


def test_flow_uses_rust_tagged_step_and_condition_shapes() -> None:
    flow = Flow(
        steps=(
            Navigate(url="https://example.test/"),
            Click(selector="button.submit"),
            EnterText(selector="input[name=q]", text="rust"),
            Wait(milliseconds=100),
            Screenshot(),
            Assert(condition=Exists(selector="main")),
            WaitUntil(condition=CountAtLeast(selector="li", count=2), timeout_ms=500),
            Evaluate(source="document.title"),
        )
    )

    encoded = json.loads(flow.to_json())
    assert encoded == {
        "schema_version": 3,
        "steps": [
            {"kind": "navigate", "url": "https://example.test/"},
            {"kind": "click", "selector": "button.submit"},
            {"kind": "enter_text", "selector": "input[name=q]", "text": "rust"},
            {"kind": "wait", "milliseconds": 100},
            {"kind": "screenshot"},
            {"kind": "assert", "condition": {"kind": "exists", "selector": "main"}},
            {
                "kind": "wait_until",
                "condition": {"kind": "count_at_least", "selector": "li", "count": 2},
                "timeout_ms": 500,
            },
            {"kind": "evaluate", "source": "document.title"},
        ],
    }


def test_flow_models_reject_wrong_scalar_types_and_rust_invalid_bounds() -> None:
    with pytest.raises(ValidationError):
        Wait(milliseconds=True)
    with pytest.raises(ValidationError):
        Click(selector=cast(Any, 123))
    with pytest.raises(ValidationError):
        WaitUntil(condition=Exists(selector="main"), timeout_ms=0)
    with pytest.raises(ValidationError):
        Flow(steps=tuple(Wait(milliseconds=1) for _ in range(129)))


def test_session_policy_defaults_and_wire_enum_names_come_from_rust() -> None:
    settings = SessionPolicy()
    assert Path(_native.__file__).resolve().parent == Path(ys.__file__).resolve().parent
    assert json.loads(settings.to_json()) == json.loads(
        _native.default_session_policy()
    )
    assert settings.mode == "headless"
    assert not settings.allow_arbitrary_js
    assert "evaluate" not in settings.allowed_actions
    assert settings.execution_concurrency == 2
    assert settings.maximum_queued_operations == 64
    assert settings.yield_on_wait is True

    custom = SessionPolicy(
        allowed_actions=("navigate", "evaluate"),
        allow_arbitrary_js=True,
        execution_concurrency=4,
        maximum_queued_operations=12,
        yield_on_wait=False,
    )
    wire = json.loads(custom.to_json())
    assert wire["allowed_actions"] == ["Navigate", "Evaluate"]
    assert wire["allow_arbitrary_js"] is True
    assert wire["execution_concurrency"] == 4
    assert wire["maximum_queued_operations"] == 12
    assert wire["yield_on_wait"] is False

    with pytest.raises(ValidationError):
        SessionPolicy(execution_concurrency=33)
    with pytest.raises(ValidationError):
        SessionPolicy(maximum_queued_operations=1_025)
    with pytest.raises(ValidationError):
        SessionPolicy(yield_on_wait=cast(Any, 1))


def test_unsupported_remote_session_endpoint_is_reported_by_rust() -> None:
    with pytest.raises(ValidationError):
        SessionPolicy(remote_endpoint="wss://browser.example.test")


def test_flow_outcome_models_receipts_and_binary_screenshot_evidence() -> None:
    value = {
        "version": 1,
        "flow": {"steps": [{"kind": "screenshot"}]},
        "steps": [
            {
                "index": 0,
                "receipt": {
                    "id": "op-1",
                    "kind": "screenshot",
                    "status": "observed",
                    "result": None,
                    "error": None,
                    "observation": {
                        "id": "obs-1",
                        "session_id": "session-1",
                        "tab_id": "tab-1",
                        "document_epoch": 4,
                        "html": "<main/>",
                        "url": "https://example.test/",
                        "screenshot": [137, 80, 78, 71],
                    },
                },
            }
        ],
        "terminal": "completed",
    }
    outcome = FlowOutcome.model_validate(value)
    receipt = outcome.steps[0].receipt
    assert receipt.status == "observed"
    assert receipt.observation is not None
    assert receipt.observation.screenshot_bytes == bytes([137, 80, 78, 71])
    assert receipt.observation.document_epoch == 4


def test_failure_capture_policy_and_receipt_preserve_primary_terminal() -> None:
    flow = Flow(
        steps=(Assert(condition=Exists(selector="#missing")),),
        capture_on_failure="screenshot",
    )
    wire = json.loads(flow.to_json())
    assert wire["capture_on_failure"] == "screenshot"
    outcome = FlowOutcome.model_validate(
        {
            "version": 1,
            "flow": wire,
            "steps": [
                {
                    "index": 0,
                    "receipt": {
                        "id": "assert-failed",
                        "kind": "assert",
                        "status": "rejected",
                        "error": "condition was not satisfied",
                    },
                }
            ],
            "terminal": "failed",
            "failure_capture": {
                "id": "capture-unknown",
                "kind": "screenshot",
                "status": "unknown",
                "error": "capture unavailable after possible dispatch",
            },
        }
    )
    assert outcome.terminal == "failed"
    assert outcome.failure_capture is not None
    assert outcome.failure_capture.status == "unknown"
