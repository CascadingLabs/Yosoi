---
title: "wait_until"
description: "yosoi.browser.wait_until Python API reference."
order: 0
---

`yosoi.browser.wait_until`

```python
def wait_until(condition: Condition | ConditionExpectation, timeout_ms: int) -> WaitUntil:
```

Declare a bounded DOM-condition wait.

Args:
    condition: Raw DOM condition or ConditionExpectation wrapper.
    timeout_ms: Positive local deadline in milliseconds.

Returns:
    WaitUntil step; construction does not start the wait.

[Source: python/yosoi/browser.py:1703](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1703-L1720)
