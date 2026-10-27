---
title: "visible"
description: "yosoi.browser.visible Python API reference."
order: 0
---

`yosoi.browser.visible`

```python
def visible(selector: str) -> ConditionExpectation:
```

Declare a browser visibility expectation for Until.

Args:
    selector: CSS selector for the current browser page.

Returns:
    ConditionExpectation using browser visibility checks.

[Source: python/yosoi/browser.py:1747](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1747-L1756)
