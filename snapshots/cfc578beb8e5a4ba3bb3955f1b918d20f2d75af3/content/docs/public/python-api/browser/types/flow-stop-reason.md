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

[Source: python/yosoi/browser.py:1130](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1130-L1141)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
flow_path: tuple[U64, ...]
cause: StopCause
continuation: Continuation | None = None
```
