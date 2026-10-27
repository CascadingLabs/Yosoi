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

[Source: python/yosoi/browser.py:1659](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1659-L1668)
