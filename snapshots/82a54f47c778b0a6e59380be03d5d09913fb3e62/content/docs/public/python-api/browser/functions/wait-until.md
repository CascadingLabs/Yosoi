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

[Source: python/yosoi/browser.py:1604](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L1604-L1621)
