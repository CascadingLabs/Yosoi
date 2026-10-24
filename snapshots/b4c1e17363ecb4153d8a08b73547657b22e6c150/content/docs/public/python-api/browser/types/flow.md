---
title: "Flow"
description: "yosoi.browser.Flow Python API reference."
order: 0
---

`yosoi.browser.Flow`

```python
class Flow(ImmutableModel):
```

Declare ordered browser steps without acquiring a Session.

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

[Source: python/yosoi/browser.py:707](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L707-L789)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
schema_version: Literal[1, 2, 3, 4] = 3
steps: tuple[Step, ...] = Field(default_factory=tuple, max_length=128)
timeout: Duration | None = None
timeout_us: PositiveU64 | None = None
on_failure: Continuation | None = None
on_cancellation: Continuation | None = None
capture_on_failure: Literal['disabled', 'screenshot'] = 'disabled'
```

## Methods

### to_json

```python
def to_json(self) -> str:
```

Return the Rust-validated, serde-compatible flow representation.

[Source: python/yosoi/browser.py:754](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L754-L756)

### allow_javascript

```python
def allow_javascript(self) -> Flow:
```

Return a Flow that explicitly permits JavaScript in managed invocation.

[Source: python/yosoi/browser.py:758](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L758-L762)

### with_timeout_ms

```python
def with_timeout_ms(self, timeout_ms: int) -> Flow:
```

Return a Flow with a total execution timeout expressed in milliseconds.

[Source: python/yosoi/browser.py:764](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L764-L773)

### bind

```python
def bind(self, policy: Policy) -> BoundFlow:
```

Bind a Rust-validated Policy to this immutable Flow.

[Source: python/yosoi/browser.py:775](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L775-L780)

### invoke

```python
async def invoke(self, lease: Work | None=None, *, cancellation: CancellationToken | None=None) -> FlowOutcome:
```

Run this Flow, optionally borrowing an already acquired Work lease.

[Source: python/yosoi/browser.py:782](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L782-L789)
