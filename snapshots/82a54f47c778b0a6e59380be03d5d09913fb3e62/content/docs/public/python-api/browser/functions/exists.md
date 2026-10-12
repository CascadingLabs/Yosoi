---
title: "exists"
description: "yosoi.browser.exists Python API reference."
order: 0
---

`yosoi.browser.exists`

```python
def exists(selector: str) -> ConditionExpectation:
```

Declare an element-existence expectation for Until.

Args:
    selector: CSS selector for the current browser page.

Returns:
    ConditionExpectation; existence does not imply visibility.

[Source: python/yosoi/browser.py:1636](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L1636-L1645)
