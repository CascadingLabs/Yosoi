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

[Source: python/yosoi/browser.py:1535](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1535-L1544)
