---
title: "navigate"
description: "yosoi.browser.navigate Python API reference."
order: 0
---

`yosoi.browser.navigate`

```python
def navigate(url: str) -> Navigate:
```

Declare navigation without acquiring or changing a browser.

Args:
    url: Nonempty destination URL.

Returns:
    Immutable Navigate step.

[Source: python/yosoi/browser.py:1595](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1595-L1604)
