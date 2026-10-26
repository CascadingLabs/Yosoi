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

[Source: python/yosoi/browser.py:1259](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1259-L1274)

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

[Source: python/yosoi/browser.py:1266](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1266-L1274)
