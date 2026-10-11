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
"""Native browser acquisition, execution, policy, or cleanup exception."""

U64 = Annotated[int, Field(strict=True, ge=0, le=(1 << 64) - 1)]
"""Strict integer from 0 through 2**64 - 1 for unsigned browser values.

Booleans, floating-point values, and numeric strings are rejected rather than
coerced. Units depend on the parameter using this alias.
"""

PositiveU32 = Annotated[int, Field(strict=True, gt=0, le=(1 << 32) - 1)]
"""Strict integer from 1 through 2**32 - 1 for positive browser values.

Zero, booleans, floating-point values, and numeric strings are rejected. This
alias checks numeric range, not whether a referenced object exists.
"""

PositiveU64 = Annotated[int, Field(strict=True, gt=0, le=(1 << 64) - 1)]
"""Strict integer from 1 through 2**64 - 1 for positive browser values.

Zero, booleans, floating-point values, and numeric strings are rejected rather
than coerced. Units belong to the consuming parameter; this alias alone does
not imply milliseconds, bytes, or an existing browser object.
"""

PositiveMilliseconds = Annotated[
    int, Field(strict=True, gt=0, le=((1 << 64) - 1) // 1_000)
]
"""Positive integer milliseconds whose microsecond conversion fits in u64.

Accepts 1 through (2**64 - 1) // 1_000 without numeric coercion. This validates
the representable duration range; operation-specific deadlines still apply.
"""
HttpStatus = Annotated[int, Field(strict=True, ge=100, le=599)]
"""Strict integer HTTP status from 100 through 599; booleans are rejected."""
ExecutionConcurrency = Annotated[int, Field(strict=True, ge=1, le=32)]
"""Strict admitted execution capacity from one through 32 permits."""
MaximumQueuedOperations = Annotated[int, Field(strict=True, ge=1, le=1_024)]
"""Strict queue capacity from one through 1,024 waiting operations."""
MAX_UNTIL_REPORT_BYTES = 1_048_576
"""Maximum encoded Until report size in bytes, currently 1 MiB."""

BrowserMode = Literal["headless", "headful"]
"""Native browser display mode: headless or headful."""
ActionKind = Literal[
    "navigate", "click", "enter_text", "screenshot", "wait", "assert", "evaluate"
]
"""Session policy action names used to allow or reject browser operations."""
OperationStatus = Literal["observed", "rejected", "unknown"]
"""Observed, rejected, or unknown operation state; unknown preserves uncertainty."""
FlowTermination = Literal[
    "completed", "completed_with_issues", "failed", "unknown", "cancelled"
]
"""Flow terminal states retaining issues, uncertainty, and cancellation."""


class Exists(ImmutableModel):
    """Declare that at least one matching DOM element must exist.

    Existence does not imply visibility, readiness, or business success.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        selector: CSS selector identifying elements on the current browser page.
    """
    kind: Literal["exists"] = "exists"
    selector: StrictStr = Field(min_length=1, max_length=4096)


class Visible(ImmutableModel):
    """Declare that a matching element must satisfy browser visibility checks.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        selector: CSS selector identifying elements on the current browser page.
    """
    kind: Literal["visible"] = "visible"
    selector: StrictStr = Field(min_length=1, max_length=4096)


class CountAtLeast(ImmutableModel):
    """Declare a minimum number of matching DOM elements.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        selector: CSS selector identifying elements on the current browser page.
        count: Unsigned minimum match count; zero is permitted.
    """
    kind: Literal["count_at_least"] = "count_at_least"
    selector: StrictStr = Field(min_length=1, max_length=4096)
    count: U64


Condition = Annotated[Exists | Visible | CountAtLeast, Field(discriminator="kind")]
"""DOM condition tagged as existence, visibility, or minimum match count."""


class TriggerStep(ImmutableModel):
    """A one-shot action that can be followed by a bounded expectation wait."""

    def until(self, expectation: UntilExpectation | LocalRustAssertion) -> UntilStep:
        """Observe an expectation around this one-shot action.

        Args:
            expectation: Typed expectation or locally bound Contract assertion.

        Returns:
            Until declaration that registers observers before dispatching this trigger.
        """
        if isinstance(expectation, LocalRustAssertion):
            return UntilStep(
                trigger=cast(Step, self),
                expectation=expectation._as_expectation(),
            )
        return UntilStep(trigger=cast(Step, self), expectation=expectation)


class WaitExpectation(ImmutableModel):
    """An expectation that can wait on the current page without a trigger."""

    def until(self) -> UntilStep:
        """Build an Until declaration that observes the page without a trigger."""
        return UntilStep(expectation=cast(UntilExpectation, self))


class Navigate(ImmutableModel):
    """Declare navigation to a URL on the leased browser tab.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        url: Nonempty destination URL; construction does not navigate or acquire a tab.
    """
    kind: Literal["navigate"] = "navigate"
    url: StrictStr = Field(min_length=1)


class Click(TriggerStep):
    """Declare a single click on the current browser page.

    Dispatching a click does not prove that its intended effect occurred. Use Until with
    an explicit domain expectation to observe that effect.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        selector: CSS selector identifying elements on the current browser page.
    """
    kind: Literal["click"] = "click"
    selector: StrictStr = Field(min_length=1, max_length=4096)


class EnterText(TriggerStep):
    """Declare text input on the current browser page.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        selector: CSS selector identifying elements on the current browser page.
        text: Text passed to the browser input action; an empty string is permitted.
    """
    kind: Literal["enter_text"] = "enter_text"
    selector: StrictStr = Field(min_length=1, max_length=4096)
    text: StrictStr


class Wait(ImmutableModel):
    """Declare an explicit elapsed-time wait.

    Elapsed time is not evidence that a page or operation is ready.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        milliseconds: Unsigned duration in milliseconds; zero is permitted.
    """
    kind: Literal["wait"] = "wait"
    milliseconds: U64


class Screenshot(ImmutableModel):
    """Declare screenshot capture from the current browser tab.

    Attributes:
        kind: Wire discriminator identifying this declaration.
    """
    kind: Literal["screenshot"] = "screenshot"


class Assert(ImmutableModel):
    """Declare an immediate DOM condition check.

    This checks one observation rather than waiting for the condition to become true.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        condition: Existence, visibility, or minimum-count condition to evaluate.
    """
    kind: Literal["assert"] = "assert"
    condition: Condition


class WaitUntil(ImmutableModel):
    """Declare a bounded wait for a DOM condition.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        condition: Existence, visibility, or minimum-count condition to observe.
        timeout_ms: Positive local deadline in milliseconds.
    """
    kind: Literal["wait_until"] = "wait_until"
    condition: Condition
    timeout_ms: PositiveU64


class Evaluate(TriggerStep):
    """Declare JavaScript evaluation in the browser page.

    Execution requires JavaScript permission in the owning Session or managed
    invocation. Construction does not execute the source.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        source: Nonempty JavaScript source bounded to 65,536 characters.
    """
    kind: Literal["evaluate"] = "evaluate"
    source: StrictStr = Field(min_length=1, max_length=65_536)


class ConditionExpectation(WaitExpectation):
    """Observe a DOM condition as part of an Until wait.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        condition: Existence, visibility, or minimum-count condition; selector is
            bounded to 4,096 UTF-8 bytes.
    """
    kind: Literal["condition"] = "condition"
    condition: Condition

    @model_validator(mode="after")
    def _validate_selector_bytes(self) -> ConditionExpectation:
        selector = self.condition.selector
        _bounded_text(selector, "condition selector", 4_096)
        return self


class LocalContractExpectation(WaitExpectation):
    """Retain an inspectable descriptor for local Contract checks.

    Executing checks requires the original local predicate binding. Deserializing the
    descriptor does not restore executable predicates.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        assertion: JSON descriptor bounded to 65,536 encoded bytes.
    """

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
    """Observe an accessible name and optional role during Until.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        name: Nonblank accessible name bounded to 4,096 UTF-8 bytes.
        role: Optional nonblank accessibility role bounded to 128 UTF-8 bytes.
    """
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
    """Compare a response JSON value at an RFC 6901 pointer.

    Attributes:
        pointer: JSON Pointer; empty selects the root, and ~0/~1 escape tilde/slash.
        value: JSON-serializable expected value bounded to 16,384 encoded bytes.
    """
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
    """Observe a matching network response during an Until wait.

    A matching response is evidence for this expectation, not a general guarantee that
    every page request succeeded.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        url: Exact full response URL bounded to 8,192 UTF-8 bytes.
        method: Optional HTTP method filter bounded to 32 UTF-8 bytes.
        status: Optional expected HTTP status from 100 through 599.
        json_matches: Up to 32 JSON comparisons; serialized under the key json.
    """
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
    """Require every child expectation within one Until wait.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        expectations: One through 128 expectations; complete trees allow at most 128
            nodes and eight nesting levels.
    """
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
"""Tagged DOM, Contract, accessibility, network, or combined Until expectation."""


class UntilStep(ImmutableModel):
    """Observe an expectation around an optional one-shot trigger.

    Observers start before dispatching the trigger. Trigger and observation share a
    bounded execution scope; cancellation does not undo the dispatched action.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        trigger: Optional Click, EnterText, Evaluate, EvaluateFile, or EvaluateModule
            action.
        expectation: DOM, accessibility, network, Contract, or combined expectation.
    """
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
    """Represent a persisted Rust duration with explicit units.

    Attributes:
        secs: Whole unsigned seconds.
        nanos: Subsecond nanoseconds from zero through 999,999,999.
    """

    secs: U64
    nanos: Annotated[int, Field(strict=True, ge=0, lt=1_000_000_000)]


class Timed(ImmutableModel):
    """Apply a local execution deadline to one action.

    Exactly one timeout field must be supplied.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        action: Action wrapped by this deadline.
        timeout: Unit-bearing duration; mutually exclusive with timeout_us.
        timeout_us: Legacy positive microsecond deadline; mutually exclusive with
            timeout.
    """
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
    """Override continuation decisions for one action.

    A persisted descriptor does not recreate live cancellation token authority.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        action: Action to execute with these overrides.
        on_failure: Failure continuation override; None inherits enclosing defaults.
        on_cancellation: Cancellation continuation override; None inherits enclosing
            defaults.
        cancellation_binding_required: Whether execution needs an external cancellation
            binding restored.
    """
    kind: Literal["configured"] = "configured"
    action: Step
    on_failure: Continuation | None = None
    on_cancellation: Continuation | None = None
    cancellation_binding_required: StrictBool = False


class NestedFlow(ImmutableModel):
    """Execute a nested Flow within its enclosing invocation.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        flow: Nested declaration retaining its own steps and continuation scope.
    """
    kind: Literal["nested_flow"] = "nested_flow"
    flow: Flow


class LocalRustAssertion(ImmutableModel):
    """Retain a local Contract assertion descriptor for inspection.

    Executing it requires the original local predicates. Deserialization retains
    inspection data but cannot restore executable callback bindings.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        assertion: Serialized schema, plan, and named-check declaration.
    """

    kind: Literal["assert_all"] = "assert_all"
    assertion: dict[str, Any]
    _binding: Any = PrivateAttr(default=None)

    def _as_expectation(self) -> LocalContractExpectation:
        expectation = LocalContractExpectation(assertion=self.assertion)
        if self._binding is not None:
            object.__setattr__(expectation, "_binding", self._binding)
        return expectation

    def until(self, *, trigger: Step | None = None) -> UntilStep:
        """Observe these locally bound Contract checks during an Until wait.

        Args:
            trigger: Optional supported one-shot action dispatched after registration.

        Returns:
            Until declaration retaining the original local predicate binding.
        """
        expectation = self._as_expectation()
        return UntilStep(trigger=trigger, expectation=expectation)


class EvaluateFile(TriggerStep):
    """Retain a construction-time JavaScript file snapshot.

    The factory reads source during construction. Later execution uses the retained
    snapshot rather than rereading the file, and requires JavaScript permission.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        snapshot: Rust-validated source snapshot bounded to 1 MiB of encoded JSON.
    """

    kind: Literal["evaluate_file"] = "evaluate_file"
    snapshot: dict[str, Any]

    @model_validator(mode="after")
    def _bound_snapshot(self) -> EvaluateFile:
        _bounded_json_size(self.snapshot, 1_048_576, "JavaScript file snapshot")
        return self


class EvaluateModule(TriggerStep):
    """Retain a construction-time local JavaScript module graph.

    Execution uses the retained local graph and requires JavaScript permission.
    Inspection records cannot authorize execution by themselves.

    Attributes:
        kind: Wire discriminator identifying this declaration.
        bundle: Rust-validated module bundle bounded to 4 MiB of encoded JSON.
    """

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
"""Tagged browser action, wrapper, nested Flow, or Until declaration."""


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
    """Declare ordered browser steps without acquiring a Session.

    Invocation either manages browser ownership or borrows an explicit Work lease.
    JavaScript permission must be explicitly enabled for managed execution; a
    borrowed Session retains its own permission policy.

    Attributes:
        schema_version: Wire schema version; Until requires version 4, and legacy
            timeout_us implies version 1 when omitted.
        steps: Ordered immutable tuple of at most 128 steps.
        timeout: Optional total execution duration with explicit seconds/nanoseconds.
        timeout_us: Optional legacy total timeout in positive microseconds.
        on_failure: Flow failure continuation override; None uses policy defaults.
        on_cancellation: Flow cancellation continuation override; None uses policy
            defaults.
        capture_on_failure: Whether to attempt a screenshot when execution fails.
    """
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
    """Retain an immutable Flow with a validated policy snapshot.

    The stored wire snapshot is used for invocation. Editing a separate Policy object
    does not change this binding.

    Attributes:
        flow: Flow declaration to invoke.
        policy: Policy declaration whose serialized snapshot is captured on
            construction.
    """

    flow: Flow
    policy: Policy
    _policy_json: str = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        """Capture the validated policy wire snapshot for later invocation.

        Args:
            context: Pydantic initialization context; unused by this bridge.
        """
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
        """Invoke this Flow with its captured policy and optional borrowed Work.

        Args:
            lease: Caller-owned Work, or None for managed acquisition and cleanup.
            cancellation: Optional token bounding execution without rolling back
                effects.

        Returns:
            Flow outcome retaining partial, unknown, skipped, and cleanup facts.

        Raises:
            BrowserError: Acquisition or execution fails at the native boundary.
            FlowInvocationError: Native failure includes partial or cleanup evidence.
        """
        return await _invoke_flow(
            self.flow, self._policy_json, lease=lease, cancellation=cancellation
        )


class Observation(ImmutableModel):
    """Retain browser evidence from a particular document epoch.

    Evidence describes an observation at capture time and does not grant live tab
    authority.

    Attributes:
        id: Observation identity.
        session_id: Identity of the Session that produced the observation.
        tab_id: Identity of the observed tab.
        document_epoch: Unsigned document generation used to fence stale observations.
        html: Captured HTML when this observation carries DOM evidence.
        url: Observed URL when present.
        screenshot: Optional screenshot bytes; JSON encoding uses base64.
    """
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
        """Return retained screenshot bytes, or None when no image was captured."""
        return self.screenshot


class OperationReceipt(ImmutableModel):
    """Retain observed, rejected, or unknown facts about an operation.

    Unknown does not imply that a dispatched operation had no effect. Inspect operation-
    specific evidence before claiming business success.

    Attributes:
        id: Operation receipt identity.
        kind: Operation kind; Until results carry a validated report.
        status: Whether the operation was observed, rejected, or left unknown.
        result: Operation-specific result payload, or None.
        observation: Optional browser evidence attached to the operation.
        error: Optional retained error detail.
    """
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
    """Fence an Until report to its Session, tab, and document.

    Attributes:
        session_id: Owning Session identity.
        tab_id: Observed tab identity.
        document_epoch: Document generation evaluated by the wait.
        frame_id: Optional frame identity; required for a satisfied report.
        loader_id: Optional document loader identity; required for a satisfied report.
    """
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
"""Wait terminal states preserving unsuccessful and uncertain observations."""
UntilCheckSource = Literal["dom", "accessibility", "network"]
"""Evidence source used by a DOM, accessibility, or network expectation check."""
UntilCheckState = Literal["pending", "satisfied", "rejected", "unavailable"]
"""Per-check pending, satisfied, rejected, or unavailable evaluation state."""


class UntilCheck(ImmutableModel):
    """Retain the state and evidence of one expectation check.

    Attributes:
        index: Zero-based check position in the report.
        source: DOM, accessibility, or network evidence source.
        state: Pending, satisfied, rejected, or unavailable evaluation state.
        evidence: Retained evidence; satisfied checks require it.
        error: Optional error bounded to 16,384 UTF-8 bytes.
    """
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
    """Retain a typed Until result within the authoritative Flow outcome.

    A satisfied report requires supporting check evidence and scope identities. The
    enclosing Flow outcome remains authoritative for continuation and cleanup.

    Attributes:
        version: Report wire version, currently 1.
        termination: Wait termination, including satisfaction or an explicit
            unsuccessful result.
        scope: Fenced Session, tab, document, frame, and loader identities.
        trigger: Optional receipt from the one-shot action dispatched by Until.
        evaluations: Unsigned count of expectation evaluations.
        checks: One through 128 checks with contiguous zero-based indexes.
        error: Optional report error bounded to 16,384 UTF-8 bytes.
    """

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
    """Retain one executed step with failure and cancellation facts.

    Attributes:
        index: Step position within its Flow.
        flow_path: Nested Flow path locating the step in the invocation.
        receipt: Operation receipt, including unknown outcomes when applicable.
        failure: Optional rejected, execution, or unknown-outcome classification.
        cancellation: Optional step, invocation, or Session cancellation scope.
        cancelled_flow: Optional Flow path affected by cancellation.
    """
    index: U64
    flow_path: tuple[U64, ...] = ()
    receipt: OperationReceipt
    failure: Literal["rejected", "execution", "unknown_outcome"] | None = None
    cancellation: Literal["step", "invocation", "session"] | None = None
    cancelled_flow: tuple[U64, ...] | None = None


StopCause = Literal["failure", "cancellation", "unknown_outcome", "unsafe_state"]
"""Explicit failure, cancellation, unknown-outcome, or unsafe-state stop cause."""


class FlowStopReason(ImmutableModel):
    """Explain where execution stopped and which continuation applied.

    Attributes:
        flow_path: Flow path where the stop decision occurred.
        cause: Failure, cancellation, unknown outcome, or unsafe state.
        continuation: Applied continuation decision when recorded.
    """
    flow_path: tuple[U64, ...]
    cause: StopCause
    continuation: Continuation | None = None


class SkippedStep(ImmutableModel):
    """Retain a declared step that was not started after a stop decision.

    Attributes:
        flow_path: Path of the skipped step.
        stopped_by: Path of the step or Flow that caused the stop.
        cause: Reason execution skipped this step.
        scope: Whether the stop applies to the current Flow or entire invocation.
    """
    flow_path: tuple[U64, ...]
    stopped_by: tuple[U64, ...]
    cause: StopCause
    scope: Literal["current_flow", "invocation"]


class FlowExecutionError(RuntimeError):
    """Raise strict completion failure while preserving the Flow outcome.

    Attributes:
        outcome: Original outcome rejected by require_completed().
    """

    def __init__(self, outcome: FlowOutcome) -> None:
        """Retain the outcome that failed strict completion checking.

        Args:
            outcome: Original Flow outcome, including partial steps and cleanup
                receipts.
        """
        self.outcome = outcome
        super().__init__(f"browser Flow ended with terminal state {outcome.terminal!r}")


class FlowInvocationError(BrowserError):
    """Retain native invocation failure and any partial execution evidence.

    Attributes:
        native_error: Original native exception.
        outcome: Parsed partial Flow outcome when available.
        outcome_json: Original partial outcome JSON when available.
        outcome_encoding_error: Native failure to encode partial outcome evidence, if
            any.
        cleanup_error: Native cleanup error detail, if any.
        rust_variant: Native failure variant name, if provided.
        outcome_parse_error: Exception encountered while parsing retained partial
            outcome JSON.
    """

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
        """Retain the original native failure and available partial evidence.

        Args:
            native_error: Exception from native invocation.
            outcome: Parsed partial outcome, or None when absent or unparseable.
            outcome_json: Original partial JSON, if emitted.
            outcome_encoding_error: Failure to encode an outcome, if reported.
            cleanup_error: Native cleanup failure detail, if reported.
            rust_variant: Rust failure variant name, if reported.
            outcome_parse_error: Error encountered while parsing retained outcome JSON.
        """
        self.native_error = native_error
        self.outcome = outcome
        self.outcome_json = outcome_json
        self.outcome_encoding_error = outcome_encoding_error
        self.cleanup_error = cleanup_error
        self.rust_variant = rust_variant
        self.outcome_parse_error = outcome_parse_error
        super().__init__(str(native_error))


class BrowserCleanupError(RuntimeError):
    """Retain cleanup failures alongside the original operation exception.

    Attributes:
        original_error: Exception raised before context cleanup failed.
        cleanup_errors: Cleanup exceptions retained in order.
    """

    def __init__(
        self,
        original_error: BaseException,
        cleanup_errors: tuple[BaseException, ...],
    ) -> None:
        """Preserve the operation exception alongside subsequent cleanup failures.

        Args:
            original_error: Exception raised by the operation or caller cancellation.
            cleanup_errors: Exceptions raised while settling cleanup.
        """
        self.original_error = original_error
        self.cleanup_errors = cleanup_errors
        detail = "; ".join(str(error) for error in cleanup_errors)
        super().__init__(f"browser cleanup failed after {original_error!r}: {detail}")


class FlowOutcome(ImmutableModel):
    """Retain executed, skipped, and cleanup facts for a Flow invocation.

    Cancellation preserves partial and unknown facts without rolling back effects.
    require_completed() checks receipts, skips, and cleanup as well as the terminal
    label.

    Attributes:
        version: Outcome wire version, independent of the embedded Flow schema version.
        flow: Original Flow declaration.
        steps: Executed steps with their receipts and cancellation facts.
        terminal: Invocation termination; inspect issues and cleanup rather than
            trusting the label alone.
        continuation_defaults: Policy continuation defaults recorded for this
            invocation.
        stop_reason: Optional explicit stop decision.
        skipped_steps: Declared steps not started after a stop decision.
        cleanup: Receipts from managed cleanup attempts.
        failure_capture: Optional screenshot or capture receipt produced after failure.
    """
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
    """Configure Rust-owned limits and capabilities for a retained Session.

    Omitted values use native Rust defaults. Construction and to_json() run Rust
    validation; numeric bounds alone do not authorize an operation.

    Attributes:
        mode: Headless or headful browser mode; must agree with the acquisition policy.
        maximum_tabs: Positive tab capacity; this Python bridge does not expose explicit
            tab creation.
        dom: Whether DOM operations are allowed.
        allow_arbitrary_js: Whether arbitrary JavaScript evaluation is permitted.
        allowed_actions: Action kinds allowed by the Session.
        execution_concurrency: Admitted execution permits from 1 through 32.
        maximum_queued_operations: Bounded queued operations from 1 through 1,024.
        yield_on_wait: Whether eligible waits yield execution capacity while retaining
            tab ownership.
        operation_timeout_ms: Positive default operation deadline in milliseconds.
        maximum_input_bytes: Positive maximum encoded operation input size.
        maximum_result_bytes: Positive maximum encoded operation result size.
        maximum_observation_bytes: Positive maximum retained observation size.
        watch_capacity: Positive Rust watcher capacity; watcher streams are not exposed
            by this bridge.
        remote_endpoint: Optional remote-browser declaration; current acquisition does
            not support it.
    """

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
        """Validate these settings in Rust and return their canonical wire JSON.

        Raises:
            BrowserError: Mutated settings no longer satisfy Rust policy requirements.
        """
        return _native.validate_session_policy(self.model_dump_json(exclude_none=True))


def navigate(url: str) -> Navigate:
    """Declare navigation without acquiring or changing a browser.

    Args:
        url: Nonempty destination URL.

    Returns:
        Immutable Navigate step.
    """
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
    """Declare one click without dispatching it.

    Args:
        selector: CSS selector for the current browser page.

    Returns:
        Click trigger; use Until to observe its intended effect.
    """
    return Click(selector=selector)


def enter_text(selector: str, text: str) -> EnterText:
    """Declare a text input action without executing it.

    Args:
        selector: CSS selector for the current browser page.
        text: Text to send, including an empty string.

    Returns:
        Immutable EnterText trigger.
    """
    return EnterText(selector=selector, text=text)


def wait(milliseconds: int) -> Wait:
    """Declare an explicit duration rather than a readiness condition.

    Args:
        milliseconds: Unsigned elapsed-time duration; zero is permitted.

    Returns:
        Immutable Wait step.
    """
    return Wait(milliseconds=milliseconds)


def timed(step: Step, timeout_ms: int) -> Timed:
    """Apply a positive, explicit millisecond timeout to one action."""
    bounded = TypeAdapter(PositiveMilliseconds).validate_python(timeout_ms)
    return Timed(action=step, timeout=_duration_from_milliseconds(bounded))


def screenshot() -> Screenshot:
    """Declare screenshot capture without executing it.

    Returns:
        Immutable Screenshot step; captured bytes appear in execution evidence.
    """
    return Screenshot()


def assert_that(condition: Condition | ConditionExpectation) -> Assert:
    """Declare an immediate check of a DOM condition.

    Args:
        condition: Raw DOM condition or ConditionExpectation wrapper.

    Returns:
        Assert step; it checks once instead of waiting for readiness.
    """
    value = (
        condition.condition
        if isinstance(condition, ConditionExpectation)
        else condition
    )
    return Assert(condition=value)


def wait_until(
    condition: Condition | ConditionExpectation, timeout_ms: int
) -> WaitUntil:
    """Declare a bounded DOM-condition wait.

    Args:
        condition: Raw DOM condition or ConditionExpectation wrapper.
        timeout_ms: Positive local deadline in milliseconds.

    Returns:
        WaitUntil step; construction does not start the wait.
    """
    value = (
        condition.condition
        if isinstance(condition, ConditionExpectation)
        else condition
    )
    return WaitUntil(condition=value, timeout_ms=timeout_ms)


def evaluate(source: str) -> Evaluate:
    """Declare JavaScript evaluation without executing the source.

    Args:
        source: Nonempty JavaScript source bounded to 65,536 characters.

    Returns:
        Evaluate trigger requiring explicit JavaScript execution permission.
    """
    return Evaluate(source=source)


def exists(selector: str) -> ConditionExpectation:
    """Declare an element-existence expectation for Until.

    Args:
        selector: CSS selector for the current browser page.

    Returns:
        ConditionExpectation; existence does not imply visibility.
    """
    return ConditionExpectation(condition=Exists(selector=selector))


def visible(selector: str) -> ConditionExpectation:
    """Declare a browser visibility expectation for Until.

    Args:
        selector: CSS selector for the current browser page.

    Returns:
        ConditionExpectation using browser visibility checks.
    """
    return ConditionExpectation(condition=Visible(selector=selector))


def count_at_least(selector: str, count: int) -> ConditionExpectation:
    """Declare a minimum DOM match count for Until.

    Args:
        selector: CSS selector for the current browser page.
        count: Unsigned minimum; zero is permitted.

    Returns:
        ConditionExpectation requiring at least the declared match count.
    """
    return ConditionExpectation(condition=CountAtLeast(selector=selector, count=count))


def response(
    url: str,
    *,
    method: str | None = None,
    status: int | None = None,
    json_matches: Iterable[JsonMatch] = (),
) -> ResponseExpectation:
    """Declare a matching network-response expectation for Until.

    Args:
        url: Exact full response URL.
        method: Optional HTTP method filter.
        status: Optional expected status from 100 through 599.
        json_matches: At most 32 pointer/value comparisons, copied into an immutable
            tuple.

    Returns:
        ResponseExpectation; this does not send an HTTP request.
    """
    return ResponseExpectation(
        url=url,
        method=method,
        status=status,
        json_matches=tuple(json_matches),
    )


def ax(name: str, *, role: str | None = None) -> AccessibilityExpectation:
    """Declare an accessibility expectation for Until.

    Args:
        name: Nonblank accessible name bounded to 4,096 UTF-8 bytes.
        role: Optional nonblank role bounded to 128 UTF-8 bytes.

    Returns:
        AccessibilityExpectation based on browser accessibility evidence.
    """
    return AccessibilityExpectation(name=name, role=role)


def all_of(
    expectations: Iterable[UntilExpectation | LocalRustAssertion],
) -> AllExpectation:
    """Combine expectations so every child must be satisfied.

    Args:
        expectations: Nonempty iterable copied into a tuple; local assertions retain
            bindings.

    Returns:
        AllExpectation; Until validates tree size and depth.
    """
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
    """Declare an expectation wait around an optional one-shot trigger.

    The trigger and wait share the execution deadline. Cancellation preserves execution
    facts and does not roll back effects.

    Args:
        expectation: Typed expectation or locally bound Contract assertion.
        trigger: Optional Click, EnterText, or JavaScript trigger.

    Returns:
        UntilStep; observation begins before trigger dispatch.
    """
    if isinstance(expectation, LocalRustAssertion):
        return expectation.until(trigger=trigger)
    return UntilStep(trigger=trigger, expectation=expectation)


@dataclass(frozen=True, slots=True)
class Check:
    """Name a synchronous local predicate for Contract assertions.

    Attributes:
        name: Short diagnostic name recorded when a check fails.
        predicate: Synchronous callable evaluating a validated record and returning a
            boolean.
    """

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

    Attributes:
        policy: Policy serialized when acquisition or operations require it.
        settings: Optional retained Session settings, or None to use native defaults.
    """

    def __init__(
        self,
        policy: Policy | None = None,
        settings: SessionPolicy | None = None,
        *,
        cancellation: CancellationToken | None = None,
    ) -> None:
        """Prepare a Session owner without acquiring a browser yet.

        Args:
            policy: Policy serialized on acquisition; None creates the default policy.
            settings: Optional Session settings, with mode agreeing with the policy.
            cancellation: Default cancellation token for acquisition and operations.

        Raises:
            TypeError: An argument has the wrong SDK type.
        """
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
        """Acquire the native browser Session and return this owner.

        Raises:
            BrowserError: This Session is already acquired or acquisition fails.
        """
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
        """Close the owned Session and preserve the context's original exception.

        Args:
            exc_type: Exception type supplied by async context management.
            exc: Original operation exception, if any.
            traceback: Original traceback supplied by async context management.

        Returns:
            False so successful cleanup does not suppress the original exception.

        Raises:
            BrowserCleanupError: Cleanup fails while an original exception is active.
        """
        try:
            await self.close()
        except BaseException as cleanup_error:
            if exc is None:
                raise
            raise BrowserCleanupError(exc, (cleanup_error,)) from exc
        return False

    @property
    def closed(self) -> bool:
        """Return whether no native handle is held, including before first entry."""
        return self._handle is None

    def work(self) -> Work:
        """Create a lazy Work wrapper for this acquired Session.

        Returns:
            Caller-owned wrapper; control is acquired on entry or its first operation.

        Raises:
            BrowserError: The Session has not been entered or is closed.
        """
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
        """Run a Flow with temporary Work ownership, retaining this Session.

        Args:
            flow: Declaration executed on this Session's leased tab.
            policy: Optional operation policy; None inherits the Session policy.
            cancellation: Explicit token, or the Session token when omitted.

        Returns:
            Flow outcome after the temporary Work lease is released.

        Raises:
            BrowserError: Work acquisition or native invocation fails.
            BrowserCleanupError: Lease cleanup fails after an operation exception.
        """
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
        """Await owned Session cleanup, then clear its native handle.

        Repeated calls on a closed Session are harmless. Cleanup settlement is shielded
        from caller task cancellation; cancellation is re-raised after settlement.
        Closing does not undo already dispatched browser operations.

        Raises:
            BrowserError: Native cleanup fails; retained state is not claimed closed.
            BrowserCleanupError: Cleanup fails while caller cancellation is pending.
        """
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
        """Prepare a lazy control lease tied to a caller-owned Session.

        Args:
            session: Session whose tab authority will be borrowed on acquisition.

        No control is acquired until context entry or the first operation.
        """
        self._session = session
        self._handle: Any | None = None
        self._released = False
        self._acquire_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._release_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Work:
        """Acquire serialized Work control and return this wrapper.

        Raises:
            BrowserError: Work was released, the Session is closed, or acquisition
                fails.
        """
        async with self._operation_lock:
            await self._acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Release control without closing the caller-owned Session.

        Args:
            exc_type: Exception type supplied by async context management.
            exc: Original operation exception, if any.
            traceback: Original traceback supplied by async context management.

        Returns:
            False so successful release does not suppress an original exception.

        Raises:
            BrowserCleanupError: Release fails while an original exception is active.
        """
        try:
            await self.release()
        except BaseException as cleanup_error:
            if exc is None:
                raise
            raise BrowserCleanupError(exc, (cleanup_error,)) from exc
        return False

    @property
    def released(self) -> bool:
        """Return whether release has settled; a released wrapper cannot reacquire."""
        return self._released

    async def run(
        self,
        flow: Flow,
        *,
        policy: Policy | None = None,
        cancellation: CancellationToken | None = None,
    ) -> FlowOutcome:
        """Invoke a Flow through this retained Work lease.

        Args:
            flow: Declaration executed on the borrowed tab.
            policy: Optional operation policy; None inherits the Session policy.
            cancellation: Explicit token, or the Session token when omitted.

        Returns:
            Flow outcome; this method retains the Work lease and owning Session.
        """
        return await self.invoke(flow, policy=policy, cancellation=cancellation)

    async def invoke(
        self,
        flow: Flow,
        *,
        policy: Policy | None = None,
        cancellation: CancellationToken | None = None,
    ) -> FlowOutcome:
        """Execute serialized Flow work without releasing caller-owned control.

        Args:
            flow: Declaration executed after lazy Work acquisition if needed.
            policy: Optional operation policy; None inherits the Session policy.
            cancellation: Explicit token, or the Session token when omitted.

        Returns:
            Outcome retaining partial and unknown facts. Cancellation does not roll
            back dispatched effects or close the owning Session.

        Raises:
            BrowserError: Work is unavailable or native invocation fails.
            FlowInvocationError: Native failure carries partial or cleanup evidence.
        """
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
        """Await native control release while retaining the owning Session.

        Repeated calls are harmless. The wrapper becomes permanently released after
        settlement. Caller task cancellation is shielded during release and re-raised
        afterward; release does not undo dispatched effects.

        Raises:
            BrowserError: Native release fails; settlement is not claimed successful.
            BrowserCleanupError: Release fails while caller cancellation is pending.
        """
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
