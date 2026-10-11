"""Typed flows and async access to the Rust browser Session and Action APIs."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

from pydantic import (
    ConfigDict,
    Field,
    PrivateAttr,
    StrictBool,
    StrictBytes,
    StrictStr,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_validator,
)

from . import _native
from ._models import ImmutableModel, Model
from .cancellation import CancellationToken
from .locators import LocateOutcome, Plan
from .policy import Continuation, Policy, _SnapshotFlowPolicy

if TYPE_CHECKING:
    from .request import BoundPageRequest, PageRequest, Response

BrowserError = _native.BrowserError

U64 = Annotated[int, Field(strict=True, ge=0, le=(1 << 64) - 1)]
PositiveU32 = Annotated[int, Field(strict=True, gt=0, le=(1 << 32) - 1)]
PositiveU64 = Annotated[int, Field(strict=True, gt=0, le=(1 << 64) - 1)]
PositiveMilliseconds = Annotated[
    int, Field(strict=True, gt=0, le=((1 << 64) - 1) // 1_000)
]
HttpStatus = Annotated[int, Field(strict=True, ge=100, le=599)]
ExecutionConcurrency = Annotated[int, Field(strict=True, ge=1, le=32)]
MaximumQueuedOperations = Annotated[int, Field(strict=True, ge=1, le=1_024)]
MAX_UNTIL_REPORT_BYTES = 1_048_576

BrowserMode = Literal["headless", "headful"]
ActionKind = Literal[
    "navigate", "click", "enter_text", "screenshot", "wait", "assert", "evaluate"
]
OperationStatus = Literal["observed", "rejected", "unknown"]
FlowTermination = Literal[
    "completed", "completed_with_issues", "failed", "unknown", "cancelled"
]


class Exists(ImmutableModel):
    kind: Literal["exists"] = "exists"
    selector: StrictStr = Field(min_length=1, max_length=4096)


class Visible(ImmutableModel):
    kind: Literal["visible"] = "visible"
    selector: StrictStr = Field(min_length=1, max_length=4096)


class CountAtLeast(ImmutableModel):
    kind: Literal["count_at_least"] = "count_at_least"
    selector: StrictStr = Field(min_length=1, max_length=4096)
    count: U64


Condition = Annotated[Exists | Visible | CountAtLeast, Field(discriminator="kind")]


class TriggerStep(ImmutableModel):
    """A one-shot action that can be followed by a bounded expectation wait."""

    def until(self, expectation: UntilExpectation | LocalRustAssertion) -> UntilStep:
        if isinstance(expectation, LocalRustAssertion):
            return UntilStep(
                trigger=cast(Step, self),
                expectation=expectation._as_expectation(),
            )
        return UntilStep(trigger=cast(Step, self), expectation=expectation)


class WaitExpectation(ImmutableModel):
    """An expectation that can wait on the current page without a trigger."""

    def until(self) -> UntilStep:
        return UntilStep(expectation=cast(UntilExpectation, self))


class Navigate(ImmutableModel):
    kind: Literal["navigate"] = "navigate"
    url: StrictStr = Field(min_length=1)


class Click(TriggerStep):
    kind: Literal["click"] = "click"
    selector: StrictStr = Field(min_length=1, max_length=4096)


class EnterText(TriggerStep):
    kind: Literal["enter_text"] = "enter_text"
    selector: StrictStr = Field(min_length=1, max_length=4096)
    text: StrictStr


class Wait(ImmutableModel):
    kind: Literal["wait"] = "wait"
    milliseconds: U64


class Screenshot(ImmutableModel):
    kind: Literal["screenshot"] = "screenshot"


class Assert(ImmutableModel):
    kind: Literal["assert"] = "assert"
    condition: Condition


class WaitUntil(ImmutableModel):
    kind: Literal["wait_until"] = "wait_until"
    condition: Condition
    timeout_ms: PositiveU64


class Evaluate(TriggerStep):
    kind: Literal["evaluate"] = "evaluate"
    source: StrictStr = Field(min_length=1, max_length=65_536)


class ConditionExpectation(WaitExpectation):
    kind: Literal["condition"] = "condition"
    condition: Condition

    @model_validator(mode="after")
    def _validate_selector_bytes(self) -> ConditionExpectation:
        selector = self.condition.selector
        _bounded_text(selector, "condition selector", 4_096)
        return self


class LocalContractExpectation(WaitExpectation):
    """Inspection descriptor; executing its Rust checks still requires rebinding."""

    kind: Literal["contract"] = "contract"
    assertion: dict[str, Any]
    _binding: Any = PrivateAttr(default=None)

    def _with_binding(self, binding: Any) -> LocalContractExpectation:
        value = self.model_copy()
        object.__setattr__(value, "_binding", binding)
        return value

    @field_validator("assertion")
    @classmethod
    def _bound_descriptor(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(_json_bytes(value, "Contract descriptor")) > 65_536:
            raise ValueError("Contract descriptor exceeds 65536 bytes")
        return value


class AccessibilityExpectation(WaitExpectation):
    kind: Literal["accessibility"] = "accessibility"
    name: StrictStr = Field(min_length=1, max_length=4_096)
    role: StrictStr | None = None

    @field_validator("name")
    @classmethod
    def _bound_name(cls, value: str) -> str:
        return _bounded_text(value, "accessible name", 4_096)

    @field_validator("role")
    @classmethod
    def _bound_role(cls, value: str | None) -> str | None:
        return (
            None if value is None else _bounded_text(value, "accessibility role", 128)
        )


class JsonMatch(ImmutableModel):
    pointer: StrictStr
    value: Any

    @field_validator("pointer")
    @classmethod
    def _validate_pointer(cls, value: str) -> str:
        _bounded_text(value, "JSON Pointer", 4_096, allow_empty=True)
        if value and not value.startswith("/"):
            raise ValueError("JSON match path must be an RFC 6901 JSON Pointer")
        index = 0
        while index < len(value):
            if value[index] == "~":
                escaped = value[index + 1] if index + 1 < len(value) else None
                if escaped not in ("0", "1"):
                    raise ValueError("JSON Pointer contains an invalid escape")
                index += 1
            index += 1
        return value

    @field_validator("value")
    @classmethod
    def _bound_value(cls, value: Any) -> Any:
        if len(_json_bytes(value, "JSON expectation value")) > 16_384:
            raise ValueError("JSON expectation value exceeds 16384 bytes")
        return value


class ResponseExpectation(WaitExpectation):
    kind: Literal["response"] = "response"
    url: StrictStr = Field(min_length=1, max_length=8_192)
    method: StrictStr | None = Field(default=None, max_length=32)
    status: HttpStatus | None = None
    json_matches: tuple[JsonMatch, ...] = Field(
        default_factory=tuple,
        max_length=32,
        validation_alias="json",
        serialization_alias="json",
    )

    @field_validator("url")
    @classmethod
    def _bound_url(cls, value: str) -> str:
        return _bounded_text(value, "response URL", 8_192)

    @field_validator("method")
    @classmethod
    def _bound_method(cls, value: str | None) -> str | None:
        return None if value is None else _bounded_text(value, "response method", 32)


class AllExpectation(WaitExpectation):
    kind: Literal["all"] = "all"
    expectations: tuple[UntilExpectation, ...] = Field(min_length=1, max_length=128)


UntilExpectation = Annotated[
    ConditionExpectation
    | LocalContractExpectation
    | AccessibilityExpectation
    | ResponseExpectation
    | AllExpectation,
    Field(discriminator="kind"),
]


class UntilStep(ImmutableModel):
    kind: Literal["until"] = "until"
    trigger: Step | None = None
    expectation: UntilExpectation

    @model_validator(mode="after")
    def _validate_until(self) -> UntilStep:
        if self.trigger is not None and not isinstance(
            self.trigger, (Click, EnterText, Evaluate, EvaluateFile, EvaluateModule)
        ):
            raise ValueError("unsupported Until trigger; use a one-shot action")
        _validate_expectation_tree(self.expectation)
        return self


class Duration(ImmutableModel):
    """Unit-bearing Rust duration in persisted Flow and action records."""

    secs: U64
    nanos: Annotated[int, Field(strict=True, ge=0, lt=1_000_000_000)]


class Timed(ImmutableModel):
    kind: Literal["timed"] = "timed"
    action: Step
    timeout: Duration | None = None
    timeout_us: PositiveU64 | None = None

    @model_validator(mode="after")
    def _require_one_unit(self) -> Timed:
        if (self.timeout is None) == (self.timeout_us is None):
            raise ValueError("timed action requires exactly one timeout field")
        return self


class Configured(ImmutableModel):
    kind: Literal["configured"] = "configured"
    action: Step
    on_failure: Continuation | None = None
    on_cancellation: Continuation | None = None
    cancellation_binding_required: StrictBool = False


class NestedFlow(ImmutableModel):
    kind: Literal["nested_flow"] = "nested_flow"
    flow: Flow


class LocalRustAssertion(ImmutableModel):
    """Inspection descriptor; executing it requires Rust predicate rebinding."""

    kind: Literal["assert_all"] = "assert_all"
    assertion: dict[str, Any]
    _binding: Any = PrivateAttr(default=None)

    def _as_expectation(self) -> LocalContractExpectation:
        expectation = LocalContractExpectation(assertion=self.assertion)
        if self._binding is not None:
            object.__setattr__(expectation, "_binding", self._binding)
        return expectation

    def until(self, *, trigger: Step | None = None) -> UntilStep:
        expectation = self._as_expectation()
        return UntilStep(trigger=trigger, expectation=expectation)


class EvaluateFile(TriggerStep):
    """Rust-validated construction-time source snapshot."""

    kind: Literal["evaluate_file"] = "evaluate_file"
    snapshot: dict[str, Any]

    @model_validator(mode="after")
    def _bound_snapshot(self) -> EvaluateFile:
        _bounded_json_size(self.snapshot, 1_048_576, "JavaScript file snapshot")
        return self


class EvaluateModule(TriggerStep):
    """Rust-validated module graph retained in an inspection record."""

    kind: Literal["evaluate_module"] = "evaluate_module"
    bundle: dict[str, Any]

    @model_validator(mode="after")
    def _bound_bundle(self) -> EvaluateModule:
        _bounded_json_size(self.bundle, 4_194_304, "JavaScript module bundle")
        return self


Step = Annotated[
    Navigate
    | Click
    | EnterText
    | Wait
    | Screenshot
    | Assert
    | WaitUntil
    | Evaluate
    | Timed
    | Configured
    | NestedFlow
    | LocalRustAssertion
    | EvaluateFile
    | EvaluateModule
    | UntilStep,
    Field(discriminator="kind"),
]


def _bounded_text(
    value: str, label: str, maximum_bytes: int, *, allow_empty: bool = False
) -> str:
    if not allow_empty and not value.strip():
        raise ValueError(f"{label} must not be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{label} exceeds {maximum_bytes} UTF-8 bytes")
    return value


def _json_bytes(value: Any, label: str) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be JSON serializable") from error


def _bounded_json_size(value: Any, maximum_bytes: int, label: str) -> int:
    size = 0
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    try:
        for chunk in encoder.iterencode(value):
            size += len(chunk.encode("utf-8"))
            if size > maximum_bytes:
                raise ValueError(f"{label} exceeds {maximum_bytes} encoded bytes")
    except (TypeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith(label):
            raise
        raise ValueError(f"{label} must be JSON serializable") from error
    return size


def _validate_expectation_tree(root: UntilExpectation) -> None:
    pending: list[tuple[UntilExpectation, int]] = [(root, 1)]
    nodes = 0
    while pending:
        expectation, depth = pending.pop()
        if depth > 8:
            raise ValueError("Until expectation nesting exceeds 8 levels")
        nodes += 1
        if nodes > 128:
            raise ValueError("Until contains more than 128 expectation nodes")
        if isinstance(expectation, AllExpectation):
            pending.extend((child, depth + 1) for child in expectation.expectations)


def _contains_until_wire(value: object) -> bool:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping):
            if current.get("kind") == "until":
                return True
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
        elif isinstance(current, Model):
            if getattr(current, "kind", None) == "until":
                return True
            pending.extend(
                current.model_dump(mode="python", exclude_none=True).values()
            )
    return False


class Flow(ImmutableModel):
    schema_version: Literal[1, 2, 3, 4] = 3
    steps: tuple[Step, ...] = Field(default_factory=tuple, max_length=128)
    timeout: Duration | None = None
    timeout_us: PositiveU64 | None = None
    on_failure: Continuation | None = None
    on_cancellation: Continuation | None = None
    capture_on_failure: Literal["disabled", "screenshot"] = "disabled"
    _javascript_allowed: bool = PrivateAttr(default=False)

    @model_validator(mode="before")
    @classmethod
    def _preserve_legacy_timeout_units(cls, value: object) -> object:
        if isinstance(value, Mapping) and "schema_version" not in value:
            if "timeout_us" in value:
                return {**value, "schema_version": 1}
            if _contains_until_wire(value.get("steps", ())):
                return {**value, "schema_version": 4}
        return value

    @model_validator(mode="after")
    def _require_schema_four_for_until(self) -> Flow:
        contains_until = _contains_until_wire(self.steps)
        if contains_until and self.schema_version != 4:
            raise ValueError("Until steps require Flow schema version 4")
        if not contains_until and self.schema_version == 4:
            raise ValueError("Flow schema version 4 is reserved for Until steps")
        return self

    def to_json(self) -> str:
        """Return the Rust-validated, serde-compatible flow representation."""
        return _native.validate_flow(self.model_dump_json(exclude_none=True))

    def allow_javascript(self) -> Flow:
        """Return a Flow that explicitly permits JavaScript in managed invocation."""
        value = self.model_copy()
        object.__setattr__(value, "_javascript_allowed", True)
        return value

    def with_timeout_ms(self, timeout_ms: int) -> Flow:
        """Return a Flow with a total execution timeout expressed in milliseconds."""
        bounded = TypeAdapter(PositiveMilliseconds).validate_python(timeout_ms)
        return self.model_copy(
            update={
                "schema_version": 4 if _contains_until_wire(self.steps) else 3,
                "timeout": _duration_from_milliseconds(bounded),
                "timeout_us": None,
            }
        )

    def bind(self, policy: Policy) -> BoundFlow:
        """Bind a Rust-validated Policy to this immutable Flow."""
        if not isinstance(policy, Policy):
            raise TypeError("policy must be a Yosoi Policy")
        policy.check()
        return BoundFlow(flow=self, policy=policy.model_copy(deep=True))

    async def invoke(
        self,
        lease: Work | None = None,
        *,
        cancellation: CancellationToken | None = None,
    ) -> FlowOutcome:
        """Run this Flow, optionally borrowing an already acquired Work lease."""
        return await _invoke_flow(self, None, lease=lease, cancellation=cancellation)


Timed.model_rebuild()
Configured.model_rebuild()
NestedFlow.model_rebuild()
UntilStep.model_rebuild()
AllExpectation.model_rebuild()
Flow.model_rebuild()


class BoundFlow(ImmutableModel):
    """A Flow invocation with its validated policy declaration attached."""

    flow: Flow
    policy: Policy
    _policy_json: str = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        del context
        object.__setattr__(self, "_policy_json", self.policy.to_json())

    def allow_javascript(self) -> BoundFlow:
        """Return a managed BoundFlow with JavaScript explicitly enabled."""
        return self.model_copy(update={"flow": self.flow.allow_javascript()})

    async def invoke(
        self,
        lease: Work | None = None,
        *,
        cancellation: CancellationToken | None = None,
    ) -> FlowOutcome:
        return await _invoke_flow(
            self.flow, self._policy_json, lease=lease, cancellation=cancellation
        )


class Observation(ImmutableModel):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    id: StrictStr
    session_id: StrictStr
    tab_id: StrictStr
    document_epoch: U64
    html: StrictStr | None = None
    url: StrictStr | None = None
    screenshot: StrictBytes | None = None

    @field_validator("screenshot", mode="before")
    @classmethod
    def _decode_rust_byte_vector(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            if any(type(byte) is not int or byte < 0 or byte > 255 for byte in value):
                raise ValueError(
                    "screenshot byte values must be integers from 0 to 255"
                )
            return bytes(value)
        return value

    @property
    def screenshot_bytes(self) -> bytes | None:
        return self.screenshot


class OperationReceipt(ImmutableModel):
    id: StrictStr
    kind: StrictStr
    status: OperationStatus
    result: Any | None = None
    observation: Observation | None = None
    error: StrictStr | None = None

    @model_validator(mode="after")
    def _validate_until_result(self) -> OperationReceipt:
        if self.kind == "until":
            if not isinstance(self.result, Mapping):
                raise ValueError("Until receipts require a typed result report")
            report = UntilReport.model_validate(self.result)
            if (self.status == "observed") != (report.termination == "satisfied"):
                raise ValueError("Until receipt status disagrees with its report")
        return self

    def until_report(self) -> UntilReport | None:
        """Parse this Until receipt's immutable result, if it is an Until step."""
        if self.kind != "until" or not isinstance(self.result, Mapping):
            return None
        return UntilReport.model_validate(self.result)


class UntilScope(ImmutableModel):
    session_id: StrictStr = Field(min_length=1, max_length=4_096)
    tab_id: StrictStr = Field(min_length=1, max_length=4_096)
    document_epoch: U64
    frame_id: StrictStr | None = Field(default=None, min_length=1, max_length=4_096)
    loader_id: StrictStr | None = Field(default=None, min_length=1, max_length=4_096)

    @field_validator("session_id", "tab_id", "frame_id", "loader_id")
    @classmethod
    def _bound_scope_id(cls, value: str | None) -> str | None:
        return (
            None
            if value is None
            else _bounded_text(value, "Until scope identity", 4_096)
        )


UntilTermination = Literal[
    "satisfied", "timed_out", "cancelled", "rejected", "unavailable", "trigger_failed"
]
UntilCheckSource = Literal["dom", "accessibility", "network"]
UntilCheckState = Literal["pending", "satisfied", "rejected", "unavailable"]


class UntilCheck(ImmutableModel):
    index: U64
    source: UntilCheckSource
    state: UntilCheckState
    evidence: Any | None = None
    error: StrictStr | None = None

    @field_validator("error")
    @classmethod
    def _bound_check_error(cls, value: str | None) -> str | None:
        return (
            None if value is None else _bounded_text(value, "Until check error", 16_384)
        )


class UntilReport(ImmutableModel):
    """Typed Until receipt result. The enclosing Flow remains authoritative."""

    version: Literal[1]
    termination: UntilTermination
    scope: UntilScope
    trigger: OperationReceipt | None = None
    evaluations: U64
    checks: tuple[UntilCheck, ...] = Field(min_length=1, max_length=128)
    error: StrictStr | None = None

    @field_validator("error")
    @classmethod
    def _bound_error(cls, value: str | None) -> str | None:
        return (
            None
            if value is None
            else _bounded_text(value, "Until report error", 16_384)
        )

    @model_validator(mode="after")
    def _validate_claims(self) -> UntilReport:
        for position, check in enumerate(self.checks):
            if check.index != position:
                raise ValueError("Until check indexes must be contiguous from zero")
            if check.state == "satisfied" and (
                check.evidence is None or check.error is not None
            ):
                raise ValueError("satisfied Until checks require evidence and no error")
        if self.trigger is not None:
            if (
                not self.trigger.id
                or len(self.trigger.id.encode("utf-8")) > 4_096
                or self.trigger.kind
                not in {
                    "click",
                    "enter_text",
                    "evaluate",
                    "evaluate_file",
                    "evaluate_module",
                }
                or self.trigger.observation is not None
            ):
                raise ValueError("invalid Until trigger receipt metadata")
            if self.trigger.status == "observed":
                trigger_result = self.trigger.result
                if (
                    not isinstance(trigger_result, Mapping)
                    or "value" not in trigger_result
                ):
                    raise ValueError(
                        "observed Until trigger requires its command result"
                    )
                started_at = trigger_result.get("started_at_unix_us")
                if type(started_at) is not int or not 0 < started_at <= (1 << 64) - 1:
                    raise ValueError(
                        "observed Until trigger requires a positive start watermark"
                    )
                if self.trigger.error is not None:
                    raise ValueError("observed Until trigger cannot have an error")
        if self.termination == "satisfied" and (
            self.evaluations == 0
            or self.error is not None
            or any(check.state != "satisfied" for check in self.checks)
            or (self.trigger is not None and self.trigger.status != "observed")
            or not self.scope.frame_id
            or not self.scope.loader_id
        ):
            raise ValueError(
                "Until satisfaction claim is inconsistent with its evidence"
            )
        if self.termination == "trigger_failed" and (
            self.trigger is None or self.trigger.status == "observed"
        ):
            raise ValueError(
                "trigger_failed requires a rejected or unknown trigger receipt"
            )
        if (
            self.termination == "rejected"
            and all(check.state != "rejected" for check in self.checks)
            and self.error is None
        ):
            raise ValueError("Until rejection requires a rejected check or diagnostic")
        wire = self.model_dump(mode="json")
        scope = wire.get("scope")
        if isinstance(scope, dict):
            if self.scope.frame_id is None:
                scope.pop("frame_id", None)
            if self.scope.loader_id is None:
                scope.pop("loader_id", None)
        _bounded_json_size(wire, MAX_UNTIL_REPORT_BYTES, "Until report")
        return self


class StepOutcome(ImmutableModel):
    index: U64
    flow_path: tuple[U64, ...] = ()
    receipt: OperationReceipt
    failure: Literal["rejected", "execution", "unknown_outcome"] | None = None
    cancellation: Literal["step", "invocation", "session"] | None = None
    cancelled_flow: tuple[U64, ...] | None = None


StopCause = Literal["failure", "cancellation", "unknown_outcome", "unsafe_state"]


class FlowStopReason(ImmutableModel):
    flow_path: tuple[U64, ...]
    cause: StopCause
    continuation: Continuation | None = None


class SkippedStep(ImmutableModel):
    flow_path: tuple[U64, ...]
    stopped_by: tuple[U64, ...]
    cause: StopCause
    scope: Literal["current_flow", "invocation"]


class FlowExecutionError(RuntimeError):
    """A noncompleted Flow outcome, retained intact for caller inspection."""

    def __init__(self, outcome: FlowOutcome) -> None:
        self.outcome = outcome
        super().__init__(f"browser Flow ended with terminal state {outcome.terminal!r}")


class FlowInvocationError(BrowserError):
    """Native invocation failure with any partial outcome and cleanup detail."""

    def __init__(
        self,
        native_error: BaseException,
        *,
        outcome: FlowOutcome | None,
        outcome_json: str | None,
        outcome_encoding_error: str | None,
        cleanup_error: str | None,
        rust_variant: str | None,
        outcome_parse_error: BaseException | None = None,
    ) -> None:
        self.native_error = native_error
        self.outcome = outcome
        self.outcome_json = outcome_json
        self.outcome_encoding_error = outcome_encoding_error
        self.cleanup_error = cleanup_error
        self.rust_variant = rust_variant
        self.outcome_parse_error = outcome_parse_error
        super().__init__(str(native_error))


class BrowserCleanupError(RuntimeError):
    """Context cleanup failed while preserving the operation's original error."""

    def __init__(
        self,
        original_error: BaseException,
        cleanup_errors: tuple[BaseException, ...],
    ) -> None:
        self.original_error = original_error
        self.cleanup_errors = cleanup_errors
        detail = "; ".join(str(error) for error in cleanup_errors)
        super().__init__(f"browser cleanup failed after {original_error!r}: {detail}")


class FlowOutcome(ImmutableModel):
    version: Literal[1, 2, 3]
    flow: Flow
    steps: tuple[StepOutcome, ...]
    terminal: FlowTermination
    continuation_defaults: _SnapshotFlowPolicy = Field(
        default_factory=_SnapshotFlowPolicy
    )
    stop_reason: FlowStopReason | None = None
    skipped_steps: tuple[SkippedStep, ...] = ()
    cleanup: tuple[OperationReceipt, ...] = ()
    failure_capture: OperationReceipt | None = None

    @model_validator(mode="before")
    @classmethod
    def _preserve_legacy_flow_schema(cls, value: object) -> object:
        if isinstance(value, Mapping) and value.get("version") in (1, 2):
            flow = value.get("flow")
            if isinstance(flow, Mapping) and "schema_version" not in flow:
                return {**value, "flow": {**flow, "schema_version": 1}}
        return value

    def require_completed(self) -> FlowOutcome:
        """Return this outcome or raise with the original noncompleted outcome."""
        completed = (
            self.terminal == "completed"
            and self.stop_reason is None
            and not self.skipped_steps
            and all(item.status == "observed" for item in self.cleanup)
            and all(
                step.receipt.status == "observed"
                and step.failure is None
                and step.cancellation is None
                for step in self.steps
            )
        )
        if completed:
            return self
        raise FlowExecutionError(self)


_SESSION_POLICY_DEFAULTS_ADAPTER: TypeAdapter[dict[str, object]] = TypeAdapter(
    dict[str, object]
)


def _native_session_defaults() -> dict[str, object]:
    return _SESSION_POLICY_DEFAULTS_ADAPTER.validate_json(
        _native.default_session_policy()
    )


def _native_session_default[T](name: str, adapter: TypeAdapter[T]) -> T:
    return adapter.validate_python(_native_session_defaults()[name])


def _native_session_allowed_actions() -> tuple[ActionKind, ...]:
    native_names = TypeAdapter(tuple[StrictStr, ...]).validate_python(
        _native_session_defaults()["allowed_actions"]
    )
    python_names = {
        "Navigate": "navigate",
        "Click": "click",
        "EnterText": "enter_text",
        "Screenshot": "screenshot",
        "Wait": "wait",
        "Assert": "assert",
        "Evaluate": "evaluate",
    }
    return TypeAdapter(tuple[ActionKind, ...]).validate_python(
        tuple(python_names.get(name, name) for name in native_names)
    )


class SessionPolicy(Model):
    """Rust-owned browser limits and capabilities for one retained Session."""

    mode: BrowserMode = Field(
        default_factory=lambda: _native_session_default(
            "mode", TypeAdapter(BrowserMode)
        )
    )
    maximum_tabs: PositiveU32 = Field(
        default_factory=lambda: _native_session_default(
            "maximum_tabs", TypeAdapter(PositiveU32)
        )
    )
    dom: StrictBool = Field(
        default_factory=lambda: _native_session_default("dom", TypeAdapter(StrictBool))
    )
    allow_arbitrary_js: StrictBool = Field(
        default_factory=lambda: _native_session_default(
            "allow_arbitrary_js", TypeAdapter(StrictBool)
        )
    )
    allowed_actions: tuple[ActionKind, ...] = Field(
        default_factory=_native_session_allowed_actions
    )
    execution_concurrency: ExecutionConcurrency = Field(
        default_factory=lambda: _native_session_default(
            "execution_concurrency", TypeAdapter(ExecutionConcurrency)
        )
    )
    maximum_queued_operations: MaximumQueuedOperations = Field(
        default_factory=lambda: _native_session_default(
            "maximum_queued_operations", TypeAdapter(MaximumQueuedOperations)
        )
    )
    yield_on_wait: StrictBool = Field(
        default_factory=lambda: _native_session_default(
            "yield_on_wait", TypeAdapter(StrictBool)
        )
    )
    operation_timeout_ms: PositiveU64 = Field(
        default_factory=lambda: _native_session_default(
            "operation_timeout_ms", TypeAdapter(PositiveU64)
        )
    )
    maximum_input_bytes: PositiveU64 = Field(
        default_factory=lambda: _native_session_default(
            "maximum_input_bytes", TypeAdapter(PositiveU64)
        )
    )
    maximum_result_bytes: PositiveU64 = Field(
        default_factory=lambda: _native_session_default(
            "maximum_result_bytes", TypeAdapter(PositiveU64)
        )
    )
    maximum_observation_bytes: PositiveU64 = Field(
        default_factory=lambda: _native_session_default(
            "maximum_observation_bytes", TypeAdapter(PositiveU64)
        )
    )
    watch_capacity: PositiveU32 = Field(
        default_factory=lambda: _native_session_default(
            "watch_capacity", TypeAdapter(PositiveU32)
        )
    )
    remote_endpoint: StrictStr | None = Field(
        default_factory=lambda: _native_session_default(
            "remote_endpoint", TypeAdapter(StrictStr | None)
        )
    )

    @model_validator(mode="before")
    @classmethod
    def _fill_rust_defaults(cls, value: object) -> object:
        defaults = json.loads(_native.default_session_policy())
        if value is None:
            value = {}
        if isinstance(value, Mapping):
            merged = {**defaults, **value}
            rust_names = {
                "Navigate": "navigate",
                "Click": "click",
                "EnterText": "enter_text",
                "Screenshot": "screenshot",
                "Wait": "wait",
                "Assert": "assert",
                "Evaluate": "evaluate",
            }
            actions = merged.get("allowed_actions")
            if isinstance(actions, (list, tuple)):
                merged["allowed_actions"] = tuple(
                    rust_names.get(action, action)
                    if isinstance(action, str)
                    else action
                    for action in actions
                )
            return merged
        return value

    @field_serializer("allowed_actions")
    def _serialize_rust_action_names(self, value: tuple[ActionKind, ...]) -> list[str]:
        rust_names = {
            "navigate": "Navigate",
            "click": "Click",
            "enter_text": "EnterText",
            "screenshot": "Screenshot",
            "wait": "Wait",
            "assert": "Assert",
            "evaluate": "Evaluate",
        }
        return [rust_names[action] for action in value]

    @model_validator(mode="after")
    def _validate_in_rust(self) -> SessionPolicy:
        try:
            _native.validate_session_policy(self.model_dump_json(exclude_none=True))
        except _native.BrowserError as error:
            raise ValueError(str(error)) from error
        return self

    def to_json(self) -> str:
        return _native.validate_session_policy(self.model_dump_json(exclude_none=True))


def navigate(url: str) -> Navigate:
    return Navigate(url=url)


def flow(
    steps: Iterable[Step],
    *,
    timeout_ms: int | None = None,
    on_failure: Continuation | None = None,
    on_cancellation: Continuation | None = None,
    capture_on_failure: Literal["disabled", "screenshot"] | None = None,
) -> Flow:
    """Build an immutable Flow, retaining Rust defaults unless configured."""
    value = Flow(
        steps=tuple(steps),
        on_failure=on_failure,
        on_cancellation=on_cancellation,
        capture_on_failure=(
            "disabled" if capture_on_failure is None else capture_on_failure
        ),
    )
    return value if timeout_ms is None else value.with_timeout_ms(timeout_ms)


def _duration_from_milliseconds(milliseconds: int) -> Duration:
    return Duration(
        secs=milliseconds // 1_000,
        nanos=(milliseconds % 1_000) * 1_000_000,
    )


def click(selector: str) -> Click:
    return Click(selector=selector)


def enter_text(selector: str, text: str) -> EnterText:
    return EnterText(selector=selector, text=text)


def wait(milliseconds: int) -> Wait:
    return Wait(milliseconds=milliseconds)


def timed(step: Step, timeout_ms: int) -> Timed:
    """Apply a positive, explicit millisecond timeout to one action."""
    bounded = TypeAdapter(PositiveMilliseconds).validate_python(timeout_ms)
    return Timed(action=step, timeout=_duration_from_milliseconds(bounded))


def screenshot() -> Screenshot:
    return Screenshot()


def assert_that(condition: Condition | ConditionExpectation) -> Assert:
    value = (
        condition.condition
        if isinstance(condition, ConditionExpectation)
        else condition
    )
    return Assert(condition=value)


def wait_until(
    condition: Condition | ConditionExpectation, timeout_ms: int
) -> WaitUntil:
    value = (
        condition.condition
        if isinstance(condition, ConditionExpectation)
        else condition
    )
    return WaitUntil(condition=value, timeout_ms=timeout_ms)


def evaluate(source: str) -> Evaluate:
    return Evaluate(source=source)


def exists(selector: str) -> ConditionExpectation:
    return ConditionExpectation(condition=Exists(selector=selector))


def visible(selector: str) -> ConditionExpectation:
    return ConditionExpectation(condition=Visible(selector=selector))


def count_at_least(selector: str, count: int) -> ConditionExpectation:
    return ConditionExpectation(condition=CountAtLeast(selector=selector, count=count))


def response(
    url: str,
    *,
    method: str | None = None,
    status: int | None = None,
    json_matches: Iterable[JsonMatch] = (),
) -> ResponseExpectation:
    return ResponseExpectation(
        url=url,
        method=method,
        status=status,
        json_matches=tuple(json_matches),
    )


def ax(name: str, *, role: str | None = None) -> AccessibilityExpectation:
    return AccessibilityExpectation(name=name, role=role)


def all_of(
    expectations: Iterable[UntilExpectation | LocalRustAssertion],
) -> AllExpectation:
    return AllExpectation(
        expectations=tuple(
            item._as_expectation() if isinstance(item, LocalRustAssertion) else item
            for item in expectations
        )
    )


def until(
    expectation: UntilExpectation | LocalRustAssertion,
    *,
    trigger: Step | None = None,
) -> UntilStep:
    if isinstance(expectation, LocalRustAssertion):
        return expectation.until(trigger=trigger)
    return UntilStep(trigger=trigger, expectation=expectation)


@dataclass(frozen=True, slots=True)
class Check:
    """A synchronous local predicate with a short diagnostic name."""

    name: str
    predicate: Callable[[Any], bool]


@dataclass(frozen=True, slots=True)
class _AssertionBinding:
    contract: type[Any]
    checks: tuple[Check, ...]

    def __call__(self, located_json: str, policy_json: str) -> str:
        del policy_json  # Rust has already applied the exact policy to location.
        from .scalars import RUST_DOMAIN_VALIDATED

        located = TypeAdapter(LocateOutcome).validate_json(
            located_json, context=RUST_DOMAIN_VALIDATED
        )
        result = self.contract.extract(located).validate()
        source_error: dict[str, Any] | None = None
        field_issues = [
            field.model_dump(mode="json", exclude_none=True)
            for issue in result.issues
            for field in issue.fields
        ]
        diagnostics = [
            item.model_dump(mode="json", exclude_none=True)
            for item in result.extraction_diagnostics
        ]
        check_results: list[dict[str, Any]] = []

        if result.status == "locate_failed":
            source_error = {"kind": "locate_failed"}
        elif result.status == "no_match":
            source_error = {"kind": "record_count", "actual": 0}
        elif result.status == "indeterminate":
            source_error = {"kind": "incomplete_evidence"}
        elif result.status == "extraction_rejected":
            source_error = {"kind": "extraction_rejected"}
        elif result.status == "validation_rejected":
            source_error = {"kind": "validation_rejected"}
        elif result.issues or field_issues or diagnostics:
            source_error = {"kind": "invalid_contract"}
        elif len(result.records) != 1:
            source_error = {"kind": "record_count", "actual": len(result.records)}
        else:
            record = result.records[0].value
            for index, item in enumerate(self.checks):
                try:
                    passed = item.predicate(record)
                except Exception as error:
                    message = str(error) or type(error).__name__
                    bounded_message = message.encode("utf-8", errors="replace")[:1_024]
                    message = bounded_message.decode("utf-8", errors="ignore")
                    check_results.append(
                        {
                            "index": index,
                            "name": item.name,
                            "passed": None,
                            "error": {"evaluation_failed": {"message": message}},
                        }
                    )
                    continue
                if inspect.isawaitable(passed):
                    close = getattr(passed, "close", None)
                    if callable(close):
                        close()
                    raise TypeError("assertion predicates must be synchronous")
                if type(passed) is not bool:
                    raise TypeError("assertion predicates must return bool")
                check_results.append(
                    {
                        "index": index,
                        "name": item.name,
                        "passed": passed,
                        "error": None,
                    }
                )

        if source_error is not None:
            check_results = [
                {
                    "index": index,
                    "name": item.name,
                    "passed": None,
                    "error": None,
                }
                for index, item in enumerate(self.checks)
            ]

        report = {
            "passed": source_error is None
            and all(item["passed"] is True for item in check_results),
            "checks": check_results,
            "source_error": source_error,
            "field_issues": field_issues,
            "extraction_diagnostics": diagnostics,
            "located": json.loads(located_json),
        }
        return json.dumps(
            report, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )


def check(name: str, predicate: Callable[[Any], bool]) -> Check:
    """Author one named synchronous Contract predicate."""
    if not isinstance(name, str):
        raise TypeError("check name must be a string")
    try:
        encoded_name = name.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("check name must be valid UTF-8") from error
    if not name.strip() or len(encoded_name) > 256:
        raise ValueError("check name must be nonempty and at most 256 UTF-8 bytes")
    if not callable(predicate):
        raise TypeError("check predicate must be callable")
    if inspect.iscoroutinefunction(predicate):
        raise TypeError("assertion predicates must be synchronous")
    return Check(name=name, predicate=predicate)


def assert_all(
    contract: type[Any],
    *,
    plan: Plan | None = None,
    checks: Iterable[Check],
) -> LocalRustAssertion:
    """Check one typed Contract observation using synchronous local predicates."""
    from .contracts import Contract as ContractType

    if not isinstance(contract, type) or not issubclass(contract, ContractType):
        raise TypeError("assert_all requires a Yosoi Contract type")
    selected_plan = contract.plan() if plan is None else plan
    if not isinstance(selected_plan, Plan):
        raise TypeError("assert_all plan must be a Yosoi Plan")
    authored_checks = tuple(checks)
    if not authored_checks:
        raise ValueError("assert_all requires at least one check")
    if len(authored_checks) > 128:
        raise ValueError("assert_all accepts at most 128 checks")
    if any(not isinstance(item, Check) for item in authored_checks):
        raise TypeError("checks must be created with yosoi.check(name, predicate)")

    contract.contract_schema()
    descriptor_json = _native.create_assertion(
        f"{contract.__module__}.{contract.__qualname__}",
        json.dumps(selected_plan.compiled(), ensure_ascii=False, separators=(",", ":")),
        [item.name for item in authored_checks],
    )
    step = TypeAdapter(Step).validate_json(descriptor_json)
    if not isinstance(step, LocalRustAssertion):
        raise BrowserError("native assertion factory returned an invalid Step")
    object.__setattr__(step, "_binding", _AssertionBinding(contract, authored_checks))
    return step


def evaluate_file(path: str | os.PathLike[str]) -> EvaluateFile:
    """Take a bounded, Rust-validated snapshot of one UTF-8 JavaScript file."""
    step = TypeAdapter(Step).validate_json(
        _native.snapshot_evaluate_file(os.fspath(path))
    )
    if not isinstance(step, EvaluateFile):
        raise BrowserError("native JavaScript file snapshot returned an invalid Step")
    return step


def run_module(path: str | os.PathLike[str]) -> EvaluateModule:
    """Snapshot a bounded relative JavaScript module graph from disk."""
    step = TypeAdapter(Step).validate_json(
        _native.snapshot_module(os.fspath(path), None)
    )
    if not isinstance(step, EvaluateModule):
        raise BrowserError("native JavaScript module snapshot returned an invalid Step")
    return step


def run_module_with_export(
    path: str | os.PathLike[str], export_name: str
) -> EvaluateModule:
    """Snapshot a JavaScript module graph and read one named export as JSON."""
    step = TypeAdapter(Step).validate_json(
        _native.snapshot_module(os.fspath(path), export_name)
    )
    if not isinstance(step, EvaluateModule):
        raise BrowserError("native JavaScript module snapshot returned an invalid Step")
    return step


def _assertion_callbacks(flow_value: Flow) -> dict[str, Callable[[str, str], str]]:
    callbacks: dict[str, Callable[[str, str], str]] = {}
    owners: dict[str, _AssertionBinding] = {}
    pending: list[Any] = [flow_value]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)

        if isinstance(current, (LocalRustAssertion, LocalContractExpectation)):
            descriptor = current.assertion
            descriptor_id = descriptor.get("id")
            binding = current._binding
            if not isinstance(descriptor_id, str) or not descriptor_id:
                raise BrowserError("local assertion descriptor has no native identity")
            if not isinstance(binding, _AssertionBinding):
                raise BrowserError(
                    "Flow contains a persisted local assertion without Python checks; "
                    "rebuild it with yosoi.assert_all before invocation"
                )
            existing = owners.get(descriptor_id)
            if existing is not None and existing is not binding:
                raise BrowserError(
                    "duplicate local assertion identity has conflicting bindings"
                )
            owners[descriptor_id] = binding
            callbacks[descriptor_id] = binding

        if isinstance(current, Model):
            pending.extend(
                getattr(current, name) for name in type(current).model_fields
            )
        elif isinstance(current, Mapping):
            pending.extend(current.values())
        elif isinstance(current, (tuple, list)):
            pending.extend(current)
    return callbacks


async def _invoke_flow(
    flow_value: Flow,
    policy: Policy | str | None,
    *,
    lease: Work | None,
    cancellation: CancellationToken | None,
) -> FlowOutcome:
    callbacks = _assertion_callbacks(flow_value)
    flow_json = flow_value.to_json()
    if lease is not None and not isinstance(lease, Work):
        raise TypeError("lease must be a Yosoi Work instance")
    selected_policy = (
        lease._session.policy if policy is None and lease is not None else policy
    )
    if selected_policy is None:
        policy_json = Policy().to_json()
    elif isinstance(selected_policy, str):
        policy_json = _native.validate_policy(selected_policy)
    else:
        policy_json = selected_policy.to_json()
    try:
        if lease is not None:
            result = await lease._invoke_native(
                flow_json,
                policy_json,
                cancellation,
                callbacks,
            )
        else:
            result = await _native.invoke_flow(
                flow_json,
                policy_json,
                _token(cancellation),
                flow_value._javascript_allowed,
                callbacks,
            )
    except BrowserError as error:
        outcome_json = getattr(error, "outcome_json", None)
        outcome_encoding_error = getattr(error, "outcome_encoding_error", None)
        cleanup_error = getattr(error, "cleanup_error", None)
        rust_variant = getattr(error, "rust_variant", None)
        if (
            not isinstance(outcome_json, str)
            and outcome_encoding_error is None
            and cleanup_error is None
        ):
            raise
        outcome = None
        outcome_parse_error = None
        if isinstance(outcome_json, str):
            try:
                outcome = FlowOutcome.model_validate_json(outcome_json)
            except Exception as parse_error:
                outcome_parse_error = parse_error
        raise FlowInvocationError(
            error,
            outcome=outcome,
            outcome_json=outcome_json if isinstance(outcome_json, str) else None,
            outcome_encoding_error=(
                outcome_encoding_error
                if isinstance(outcome_encoding_error, str)
                else None
            ),
            cleanup_error=(cleanup_error if isinstance(cleanup_error, str) else None),
            rust_variant=rust_variant if isinstance(rust_variant, str) else None,
            outcome_parse_error=outcome_parse_error,
        ) from error
    return FlowOutcome.model_validate_json(result)


async def action(
    url: str,
    flow: Flow,
    *,
    policy: Policy | None = None,
    cancellation: CancellationToken | None = None,
) -> FlowOutcome:
    """Navigate to ``url``, then run the flow with managed SDK cleanup.

    Caller cancellation stops subsequent steps and preserves partial/unknown
    execution facts. Cancellation is not rollback; managed cleanup still runs.
    """
    if len(flow.steps) >= 128:
        raise ValueError("managed Action requires room for its initial navigation step")
    recipe = flow.model_copy(update={"steps": (navigate(url), *flow.steps)})
    return await _invoke_flow(recipe, policy, lease=None, cancellation=cancellation)


async def _settle_cleanup_task(task: asyncio.Task[None]) -> BaseException | None:
    """Shield owner cleanup until settlement and return any caller cancellation."""
    try:
        await asyncio.shield(task)
        return None
    except asyncio.CancelledError as cancellation:
        if task.cancelled():
            raise
        try:
            await asyncio.shield(task)
        except BaseException as cleanup_error:
            raise BrowserCleanupError(cancellation, (cleanup_error,)) from cancellation
        return cancellation


def _native_request_binding(
    request: PageRequest | BoundPageRequest,
) -> tuple[_native.PageRequest, str | None]:
    from .request import BoundPageRequest as BoundRequest
    from .request import PageRequest as Request

    if isinstance(request, BoundRequest):
        return request.request._handle, request._policy_json
    if isinstance(request, Request):
        return request._handle, None
    raise TypeError("request must be a Yosoi PageRequest")


class Session:
    """An acquired Rust Session, released by async context exit.

    This Python bridge exposes one Work lease at a time. Rust watcher streams
    and explicit tab creation are not exposed through this first pass.
    Omitted settings inherit the bound policy's browser mode; explicit settings
    retain their configured mode and must agree with that policy.
    """

    def __init__(
        self,
        policy: Policy | None = None,
        settings: SessionPolicy | None = None,
        *,
        cancellation: CancellationToken | None = None,
    ) -> None:
        if policy is not None and not isinstance(policy, Policy):
            raise TypeError("session policy must be a Yosoi Policy")
        if settings is not None and not isinstance(settings, SessionPolicy):
            raise TypeError("session settings must be a Yosoi SessionPolicy")
        if cancellation is not None and not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be a Yosoi CancellationToken")
        self.policy = Policy() if policy is None else policy
        self.settings = settings
        self._cancellation = cancellation
        self._handle: Any | None = None
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Session:
        if self._handle is not None:
            raise BrowserError("browser Session is already acquired")
        self._handle = await _native.acquire_browser_session(
            self.policy.to_json(),
            None if self.settings is None else self.settings.to_json(),
            _token(self._cancellation),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        try:
            await self.close()
        except BaseException as cleanup_error:
            if exc is None:
                raise
            raise BrowserCleanupError(exc, (cleanup_error,)) from exc
        return False

    @property
    def closed(self) -> bool:
        return self._handle is None

    def work(self) -> Work:
        if self._handle is None:
            raise BrowserError("enter the browser Session before creating Work")
        return Work(self)

    async def run(
        self,
        flow: Flow,
        *,
        policy: Policy | None = None,
        cancellation: CancellationToken | None = None,
    ) -> FlowOutcome:
        """Run on an explicitly leased Work control, then release that lease."""
        async with self.work() as work:
            return await work.invoke(flow, policy=policy, cancellation=cancellation)

    async def invoke(
        self,
        flow: Flow,
        *,
        policy: Policy | None = None,
        cancellation: CancellationToken | None = None,
    ) -> FlowOutcome:
        return await self.run(flow, policy=policy, cancellation=cancellation)

    async def send(
        self,
        request: PageRequest | BoundPageRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> Response:
        """Send a PageRequest through this retained Session without closing it."""
        handle = self._handle
        if handle is None:
            raise BrowserError("enter the browser Session before sending a request")
        request_handle, policy_json = _native_request_binding(request)
        response = await handle.send_request(
            request_handle,
            policy_json,
            _token(self._cancellation if cancellation is None else cancellation),
        )
        from .request import Response as RequestResponse

        return RequestResponse._from_native(response)

    async def close(self) -> None:
        async with self._close_lock:
            handle = self._handle
            if handle is None:
                return
            task = self._close_task
            if task is None:

                async def settle() -> None:
                    await handle.close()

                task = asyncio.create_task(settle())
                self._close_task = task
        cancellation = await _settle_cleanup_task(task)
        async with self._close_lock:
            if self._close_task is task:
                self._handle = None
                self._close_task = None
        if cancellation is not None:
            raise cancellation


class Work:
    """An explicit browser control lease owned by one Session.

    Explicit cancellation bounds the current Flow scope. It does not undo a
    dispatched operation or close the caller-owned Session.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._handle: Any | None = None
        self._released = False
        self._acquire_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._release_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Work:
        async with self._operation_lock:
            await self._acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        try:
            await self.release()
        except BaseException as cleanup_error:
            if exc is None:
                raise
            raise BrowserCleanupError(exc, (cleanup_error,)) from exc
        return False

    @property
    def released(self) -> bool:
        return self._released

    async def run(
        self,
        flow: Flow,
        *,
        policy: Policy | None = None,
        cancellation: CancellationToken | None = None,
    ) -> FlowOutcome:
        return await self.invoke(flow, policy=policy, cancellation=cancellation)

    async def invoke(
        self,
        flow: Flow,
        *,
        policy: Policy | None = None,
        cancellation: CancellationToken | None = None,
    ) -> FlowOutcome:
        return await _invoke_flow(flow, policy, lease=self, cancellation=cancellation)

    async def send(
        self,
        request: PageRequest | BoundPageRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> Response:
        """Send a PageRequest on this borrowed Work without releasing the lease."""
        request_handle, policy_json = _native_request_binding(request)
        async with self._operation_lock:
            await self._acquire()
            handle = self._handle
            if handle is None:
                raise BrowserError("browser Work lease is unavailable")
            response = await handle.send_request(
                request_handle,
                policy_json,
                _token(
                    self._session._cancellation
                    if cancellation is None
                    else cancellation
                ),
            )
        from .request import Response as RequestResponse

        return RequestResponse._from_native(response)

    async def _invoke_native(
        self,
        flow_json: str,
        policy_json: str,
        cancellation: CancellationToken | None,
        assertions: dict[str, Callable[[str, str], str]],
    ) -> str:
        async with self._operation_lock:
            await self._acquire()
            handle = self._handle
            if handle is None:
                raise BrowserError("browser Work lease is unavailable")
            token = _token(
                self._session._cancellation if cancellation is None else cancellation
            )
            return await handle.invoke_flow(flow_json, policy_json, token, assertions)

    async def release(self) -> None:
        async with self._operation_lock:
            if self._released:
                return
            handle = self._handle
            if handle is None:
                self._released = True
                return
            task = self._release_task
            if task is None:

                async def settle() -> None:
                    await handle.release()

                task = asyncio.create_task(settle())
                self._release_task = task
            cancellation = await _settle_cleanup_task(task)
            if self._release_task is task:
                self._handle = None
                self._released = True
                self._release_task = None
        if cancellation is not None:
            raise cancellation

    async def _acquire(self) -> None:
        async with self._acquire_lock:
            if self._released:
                raise BrowserError("browser Work lease has been released")
            if self._handle is not None:
                return
            session_handle = self._session._handle
            if session_handle is None:
                raise BrowserError("browser Session is closed")
            self._handle = await session_handle.work(
                _token(self._session._cancellation)
            )


def session(
    policy: Policy | None = None,
    settings: SessionPolicy | None = None,
    *,
    cancellation: CancellationToken | None = None,
) -> Session:
    """Create an async context manager for an explicitly owned browser Session."""
    return Session(policy=policy, settings=settings, cancellation=cancellation)


def _token(value: CancellationToken | None) -> Any | None:
    if value is None:
        return None
    if not isinstance(value, CancellationToken):
        raise TypeError("cancellation must be a Yosoi CancellationToken")
    return value._handle


__all__ = [
    "AccessibilityExpectation",
    "AllExpectation",
    "ActionKind",
    "Assert",
    "BoundFlow",
    "BrowserCleanupError",
    "BrowserError",
    "BrowserMode",
    "Check",
    "Click",
    "Condition",
    "ConditionExpectation",
    "CountAtLeast",
    "EnterText",
    "Evaluate",
    "EvaluateFile",
    "EvaluateModule",
    "ExecutionConcurrency",
    "Exists",
    "Flow",
    "FlowExecutionError",
    "FlowInvocationError",
    "FlowOutcome",
    "FlowTermination",
    "HttpStatus",
    "JsonMatch",
    "LocalContractExpectation",
    "LocalRustAssertion",
    "MAX_UNTIL_REPORT_BYTES",
    "MaximumQueuedOperations",
    "Navigate",
    "NestedFlow",
    "Observation",
    "OperationReceipt",
    "OperationStatus",
    "ResponseExpectation",
    "Screenshot",
    "Session",
    "SessionPolicy",
    "Step",
    "StepOutcome",
    "TriggerStep",
    "UntilCheck",
    "UntilCheckSource",
    "UntilCheckState",
    "UntilReport",
    "UntilScope",
    "UntilStep",
    "UntilTermination",
    "UntilExpectation",
    "Visible",
    "Wait",
    "WaitExpectation",
    "WaitUntil",
    "Work",
    "all_of",
    "action",
    "assert_all",
    "ax",
    "assert_that",
    "check",
    "click",
    "count_at_least",
    "enter_text",
    "evaluate",
    "evaluate_file",
    "exists",
    "flow",
    "navigate",
    "response",
    "run_module",
    "run_module_with_export",
    "session",
    "screenshot",
    "timed",
    "until",
    "visible",
    "wait",
    "wait_until",
]
