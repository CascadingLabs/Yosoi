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

[Source: python/yosoi/browser.py:1648](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1648-L1657)
