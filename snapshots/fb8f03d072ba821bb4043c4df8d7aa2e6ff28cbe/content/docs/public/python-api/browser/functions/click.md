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

[Source: python/yosoi/browser.py:1634](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L1634-L1643)
