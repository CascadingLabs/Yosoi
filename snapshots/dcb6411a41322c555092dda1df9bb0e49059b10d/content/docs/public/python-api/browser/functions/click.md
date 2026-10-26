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

[Source: python/yosoi/browser.py:1634](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1634-L1643)
