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

[Source: python/yosoi/browser.py:1735](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1735-L1744)
