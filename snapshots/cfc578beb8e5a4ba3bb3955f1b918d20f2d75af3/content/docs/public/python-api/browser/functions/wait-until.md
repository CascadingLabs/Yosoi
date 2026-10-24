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

[Source: python/yosoi/browser.py:1604](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1604-L1621)
