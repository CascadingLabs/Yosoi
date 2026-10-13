---
title: "click"
description: "yosoi.browser.click Python API reference."
order: 0
---

`yosoi.browser.click`

```python
def click(selector: str) -> Click:
```

Declare one click without dispatching it.

Args:
    selector: CSS selector for the current browser page.

Returns:
    Click trigger; use Until to observe its intended effect.

[Source: python/yosoi/browser.py:1535](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L1535-L1544)
