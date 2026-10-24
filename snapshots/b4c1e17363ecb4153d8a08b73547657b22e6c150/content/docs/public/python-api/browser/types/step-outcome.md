---
title: "StepOutcome"
description: "yosoi.browser.StepOutcome Python API reference."
order: 0
---

`yosoi.browser.StepOutcome`

```python
class StepOutcome(ImmutableModel):
```

Retain one executed step with failure and cancellation facts.

Attributes:
    index: Step position within its Flow.
    flow_path: Nested Flow path locating the step in the invocation.
    receipt: Operation receipt, including unknown outcomes when applicable.
    failure: Optional rejected, execution, or unknown-outcome classification.
    cancellation: Optional step, invocation, or Session cancellation scope.
    cancelled_flow: Optional Flow path affected by cancellation.

[Source: python/yosoi/browser.py:1106](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L1106-L1123)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
index: U64
flow_path: tuple[U64, ...] = ()
receipt: OperationReceipt
failure: Literal['rejected', 'execution', 'unknown_outcome'] | None = None
cancellation: Literal['step', 'invocation', 'session'] | None = None
cancelled_flow: tuple[U64, ...] | None = None
```
