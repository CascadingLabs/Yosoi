---
title: "SkippedStep"
description: "yosoi.browser.SkippedStep Python API reference."
order: 0
---

`yosoi.browser.SkippedStep`

```python
class SkippedStep(ImmutableModel):
```

Retain a declared step that was not started after a stop decision.

Attributes:
    flow_path: Path of the skipped step.
    stopped_by: Path of the step or Flow that caused the stop.
    cause: Reason execution skipped this step.
    scope: Whether the stop applies to the current Flow or entire invocation.

[Source: python/yosoi/browser.py:1144](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1144-L1157)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
flow_path: tuple[U64, ...]
stopped_by: tuple[U64, ...]
cause: StopCause
scope: Literal['current_flow', 'invocation']
```
