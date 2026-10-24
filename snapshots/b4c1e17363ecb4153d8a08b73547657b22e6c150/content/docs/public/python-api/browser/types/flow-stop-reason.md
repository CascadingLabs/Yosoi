---
title: "FlowStopReason"
description: "yosoi.browser.FlowStopReason Python API reference."
order: 0
---

`yosoi.browser.FlowStopReason`

```python
class FlowStopReason(ImmutableModel):
```

Explain where execution stopped and which continuation applied.

Attributes:
    flow_path: Flow path where the stop decision occurred.
    cause: Failure, cancellation, unknown outcome, or unsafe state.
    continuation: Applied continuation decision when recorded.

[Source: python/yosoi/browser.py:1130](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L1130-L1141)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
flow_path: tuple[U64, ...]
cause: StopCause
continuation: Continuation | None = None
```
