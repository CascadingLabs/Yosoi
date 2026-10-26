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

[Source: python/yosoi/browser.py:1636](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L1636-L1645)
