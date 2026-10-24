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

[Source: python/yosoi/browser.py:1560](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1560-L1569)
