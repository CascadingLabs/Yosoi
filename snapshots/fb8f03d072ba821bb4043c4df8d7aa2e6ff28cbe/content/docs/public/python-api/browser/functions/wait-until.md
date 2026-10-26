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

[Source: python/yosoi/browser.py:1703](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L1703-L1720)
