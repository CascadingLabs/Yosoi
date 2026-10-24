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

[Source: python/yosoi/browser.py:1560](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L1560-L1569)
