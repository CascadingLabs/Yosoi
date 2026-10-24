---
title: "FlowExecutionError"
description: "yosoi.browser.FlowExecutionError Python API reference."
order: 0
---

`yosoi.browser.FlowExecutionError`

```python
class FlowExecutionError(RuntimeError):
```

Raise strict completion failure while preserving the Flow outcome.

Attributes:
    outcome: Original outcome rejected by require_completed().

[Source: python/yosoi/browser.py:1160](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1160-L1175)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, outcome: FlowOutcome) -> None:
```

Retain the outcome that failed strict completion checking.

Args:
    outcome: Original Flow outcome, including partial steps and cleanup
        receipts.

[Source: python/yosoi/browser.py:1167](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1167-L1175)
