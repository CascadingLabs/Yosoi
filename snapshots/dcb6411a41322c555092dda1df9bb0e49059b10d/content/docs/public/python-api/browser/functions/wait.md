---
title: "wait"
description: "yosoi.browser.wait Python API reference."
order: 0
---

`yosoi.browser.wait`

```python
def wait(milliseconds: int) -> Wait:
```

Declare an explicit duration rather than a readiness condition.

Args:
    milliseconds: Unsigned elapsed-time duration; zero is permitted.

Returns:
    Immutable Wait step.

[Source: python/yosoi/browser.py:1659](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1659-L1668)
