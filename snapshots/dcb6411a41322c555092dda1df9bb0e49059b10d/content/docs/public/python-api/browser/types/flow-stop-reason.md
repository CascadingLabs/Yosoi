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

[Source: python/yosoi/browser.py:1229](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1229-L1240)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
flow_path: tuple[U64, ...]
cause: StopCause
continuation: Continuation | None = None
```
