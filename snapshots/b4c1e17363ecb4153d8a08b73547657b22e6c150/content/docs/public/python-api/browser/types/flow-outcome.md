---
title: "FlowOutcome"
description: "yosoi.browser.FlowOutcome Python API reference."
order: 0
---

`yosoi.browser.FlowOutcome`

```python
class FlowOutcome(ImmutableModel):
```

Retain executed, skipped, and cleanup facts for a Flow invocation.

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

[Source: python/yosoi/browser.py:1250](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L1250-L1308)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
version: Literal[1, 2, 3]
flow: Flow
steps: tuple[StepOutcome, ...]
terminal: FlowTermination
continuation_defaults: _SnapshotFlowPolicy = Field(default_factory=_SnapshotFlowPolicy)
stop_reason: FlowStopReason | None = None
skipped_steps: tuple[SkippedStep, ...] = ()
cleanup: tuple[OperationReceipt, ...] = ()
failure_capture: OperationReceipt | None = None
```

## Methods

### require_completed

```python
def require_completed(self) -> FlowOutcome:
```

Return this outcome or raise with the original noncompleted outcome.

[Source: python/yosoi/browser.py:1292](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L1292-L1308)
