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

[Source: python/yosoi/browser.py:1648](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L1648-L1657)
