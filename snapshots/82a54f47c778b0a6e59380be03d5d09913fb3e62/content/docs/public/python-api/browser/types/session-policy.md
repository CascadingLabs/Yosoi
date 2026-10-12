---
title: "SessionPolicy"
description: "yosoi.browser.SessionPolicy Python API reference."
order: 0
---

`yosoi.browser.SessionPolicy`

```python
class SessionPolicy(Model):
```

Configure Rust-owned limits and capabilities for a retained Session.

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

[Source: python/yosoi/browser.py:1344](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L1344-L1493)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
mode: BrowserMode = Field(default_factory=lambda: _native_session_default('mode', TypeAdapter(BrowserMode)))
maximum_tabs: PositiveU32 = Field(default_factory=lambda: _native_session_default('maximum_tabs', TypeAdapter(PositiveU32)))
dom: StrictBool = Field(default_factory=lambda: _native_session_default('dom', TypeAdapter(StrictBool)))
allow_arbitrary_js: StrictBool = Field(default_factory=lambda: _native_session_default('allow_arbitrary_js', TypeAdapter(StrictBool)))
allowed_actions: tuple[ActionKind, ...] = Field(default_factory=_native_session_allowed_actions)
execution_concurrency: ExecutionConcurrency = Field(default_factory=lambda: _native_session_default('execution_concurrency', TypeAdapter(ExecutionConcurrency)))
maximum_queued_operations: MaximumQueuedOperations = Field(default_factory=lambda: _native_session_default('maximum_queued_operations', TypeAdapter(MaximumQueuedOperations)))
yield_on_wait: StrictBool = Field(default_factory=lambda: _native_session_default('yield_on_wait', TypeAdapter(StrictBool)))
operation_timeout_ms: PositiveU64 = Field(default_factory=lambda: _native_session_default('operation_timeout_ms', TypeAdapter(PositiveU64)))
maximum_input_bytes: PositiveU64 = Field(default_factory=lambda: _native_session_default('maximum_input_bytes', TypeAdapter(PositiveU64)))
maximum_result_bytes: PositiveU64 = Field(default_factory=lambda: _native_session_default('maximum_result_bytes', TypeAdapter(PositiveU64)))
maximum_observation_bytes: PositiveU64 = Field(default_factory=lambda: _native_session_default('maximum_observation_bytes', TypeAdapter(PositiveU64)))
watch_capacity: PositiveU32 = Field(default_factory=lambda: _native_session_default('watch_capacity', TypeAdapter(PositiveU32)))
remote_endpoint: StrictStr | None = Field(default_factory=lambda: _native_session_default('remote_endpoint', TypeAdapter(StrictStr | None)))
```

## Methods

### to_json

```python
def to_json(self) -> str:
```

Validate these settings in Rust and return their canonical wire JSON.

Raises:
    BrowserError: Mutated settings no longer satisfy Rust policy requirements.

[Source: python/yosoi/browser.py:1487](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L1487-L1493)
